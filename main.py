import os
import asyncio
import base64
import io
import traceback
import cv2
import pyaudio
import PIL.Image
import argparse
import json
import sys
import websockets

from google import genai
from google.genai import types

import memory_manager

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL = "models/gemini-3.1-flash-live-preview"

class AudioState:
    def __init__(self):
        self.is_gemini_speaking = False

class AudioLoop:
    def __init__(self, args):
        self.args = args
        self.mm = memory_manager.MemoryManager()
        self.video_mode = "camera" if args.vision == "continuous" else "none"
        if args.vision == "screen":
            self.video_mode = "screen"

        self.audio_in_queue = None
        self.out_queue = None
        
        self.websocket = None
        self.audio_stream = None
        self.pya = pyaudio.PyAudio()
        
        self.audio_state = AudioState()
        self.half_duplex = args.audio == "half"

    async def send_text(self):
        while True:
            text = await asyncio.to_thread(input, "")
            if text.lower() == "q":
                break
            if self.websocket is not None:
                if self.args.memory == "enabled":
                    log_file = os.path.join("history", f"{self.args.session}.txt")
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\nUser: {text}\nGemini: ")
                await self.websocket.send(json.dumps({
                    "type": "text",
                    "data": text
                }))

    def _get_frame(self, cap):
        ret, frame = cap.read()
        if not ret:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(frame_rgb)
        img.thumbnail([1024, 1024])

        image_io = io.BytesIO()
        img.save(image_io, format="jpeg")
        image_io.seek(0)
        image_bytes = image_io.read()
        return {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode()}

    async def get_frames(self):
        cap = await asyncio.to_thread(cv2.VideoCapture, 0)
        while True:
            frame = await asyncio.to_thread(self._get_frame, cap)
            if frame is None:
                break
            await asyncio.sleep(1.0)
            if self.out_queue is not None:
                await self.out_queue.put({"type": "video", "data": frame["data"]})
        cap.release()

    def _get_screen(self):
        try:
            import mss
        except ImportError as e:
            raise ImportError("Please install mss package using 'pip install mss'") from e
        with mss.MSS() as sct:
            monitor = sct.monitors[0]
            i = sct.grab(monitor)
            image_bytes = mss.tools.to_png(i.rgb, i.size)
            img = PIL.Image.open(io.BytesIO(image_bytes))
            img.thumbnail([1024, 1024])
            
            image_io = io.BytesIO()
            img.save(image_io, format="jpeg")
            image_io.seek(0)
            return {"mime_type": "image/jpeg", "data": base64.b64encode(image_io.read()).decode()}

    async def get_screen(self):
        while True:
            frame = await asyncio.to_thread(self._get_screen)
            if frame is None:
                break
            await asyncio.sleep(1.0)
            if self.out_queue is not None:
                await self.out_queue.put({"type": "video", "data": frame["data"]})

    async def send_realtime(self):
        while True:
            if self.out_queue is not None:
                msg = await self.out_queue.get()
                if self.websocket is not None:
                    await self.websocket.send(json.dumps(msg))

    async def send_text_direct(self):
        while True:
            text = await asyncio.to_thread(input, "")
            if text.lower() == "q":
                break
            if getattr(self, 'session', None) is not None:
                if self.args.memory == "enabled":
                    log_file = os.path.join("history", f"{self.args.session}.txt")
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\nUser: {text}\nGemini: ")
                await self.session.send_client_content(types.Content(parts=[types.Part.from_text(text=text)], role="user"))

    async def send_realtime_direct(self):
        while True:
            if self.out_queue is not None:
                msg = await self.out_queue.get()
                if getattr(self, 'session', None) is not None:
                    if msg["type"] == "audio":
                        raw_audio = base64.b64decode(msg["data"])
                        await self.session.send_realtime_input(audio={"data": raw_audio, "mime_type": "audio/pcm"})
                    elif msg["type"] == "video":
                        raw_video = base64.b64decode(msg["data"])
                        await self.session.send_realtime_input(video={"data": raw_video, "mime_type": "image/jpeg"})

    async def receive_from_google_direct(self, session):
        try:
            while True:
                turn = session.receive()
                async for response in turn:
                    sc = response.server_content
                    if sc and sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and hasattr(part.inline_data, 'data'):
                                self.audio_state.is_gemini_speaking = True
                                self.audio_in_queue.put_nowait(part.inline_data.data)
                            if hasattr(part, "text") and part.text:
                                print(part.text, end="", flush=True)
                                if self.args.memory == "enabled":
                                    log_file = os.path.join("history", f"{self.args.session}.txt")
                                    with open(log_file, "a", encoding="utf-8") as f:
                                        f.write(part.text)
                            if part.function_call:
                                fc_dict = {
                                    "name": part.function_call.name,
                                    "args": {k: v for k, v in part.function_call.args.items()}
                                }
                                asyncio.create_task(self.handle_tool_call_direct(fc_dict))
                    if response.server_content and response.server_content.turn_complete:
                        self.audio_state.is_gemini_speaking = False
                        while not self.audio_in_queue.empty():
                            self.audio_in_queue.get_nowait()
        except Exception as e:
            print(f"\n[System] Disconnected from direct API: {e}")

    async def handle_tool_call_direct(self, fc):
        fc_name = fc.get("name")
        fc_args = fc.get("args", {})
        print(f"\n[System] Executing tool: {fc_name}...")
        
        result = {"error": f"Unknown tool: {fc_name}"}
        try:
            if fc_name == "list_directory":
                items = os.listdir(fc_args.get("path", "."))
                result = {"result": f"Contents: {', '.join(items)}"}
            elif fc_name == "read_file":
                with open(fc_args.get("path", ""), "r", encoding="utf-8") as f:
                    content = f.read()
                if len(content) > 15000:
                    content = content[:15000] + "\n...[TRUNCATED]"
                result = {"result": content}
            elif fc_name == "write_file":
                with open(fc_args.get("path", ""), "w", encoding="utf-8") as f:
                    f.write(fc_args.get("content", ""))
                result = {"result": "File written successfully."}
            elif fc_name == "memorize_fact":
                success = self.mm.memorize_fact(fc_args.get("subject", ""), fc_args.get("predicate", ""), fc_args.get("object_", ""), fc_args.get("source", "conversation"))
                result = {"result": "Fact memorized successfully." if success else "Failed to memorize fact."}
            elif fc_name == "recall_knowledge":
                facts = self.mm.recall_knowledge(fc_args.get("query_subject", ""))
                result = {"result": facts if facts else "No facts found."}
            elif fc_name == "write_diary_entry":
                success = self.mm.write_diary_entry(fc_args.get("content", ""), fc_args.get("session_name", "AlphaLive"), fc_args.get("sentiment", 0.0))
                result = {"result": "Diary entry written." if success else "Failed to write diary."}
            elif fc_name == "update_personality":
                success = self.mm.update_personality(fc_args.get("trait_name", ""), fc_args.get("trait_value", ""))
                result = {"result": "Personality updated." if success else "Failed to update."}
        except Exception as e:
            result = {"error": str(e)}

        print(f"[System] Tool {fc_name} completed.")
        
        if getattr(self, 'session', None) is not None:
            await self.session.send_tool_response(function_responses=[
                {"name": fc_name, "response": {"result": result}}
            ])

    async def listen_audio(self):
        mic_info = self.pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False}
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)
            if self.out_queue is not None:
                if self.half_duplex and self.audio_state.is_gemini_speaking:
                    continue
                b64_audio = base64.b64encode(data).decode('utf-8')
                await self.out_queue.put({"type": "audio", "data": b64_audio})

    async def handle_tool_call(self, data):
        fc_name = data.get("name")
        fc_args = data.get("args", {})
        print(f"\n[System] Executing tool: {fc_name}...")
        
        result = {"error": f"Unknown tool: {fc_name}"}
        try:
            if fc_name == "list_directory":
                items = os.listdir(fc_args.get("path", "."))
                result = {"result": f"Contents: {', '.join(items)}"}
            elif fc_name == "read_file":
                with open(fc_args.get("path", ""), "r", encoding="utf-8") as f:
                    content = f.read()
                if len(content) > 15000:
                    content = content[:15000] + "\n...[TRUNCATED]"
                result = {"result": content}
            elif fc_name == "write_file":
                with open(fc_args.get("path", ""), "w", encoding="utf-8") as f:
                    f.write(fc_args.get("content", ""))
                result = {"result": "File written successfully."}
            elif fc_name == "memorize_fact":
                success = self.mm.memorize_fact(fc_args.get("subject", ""), fc_args.get("predicate", ""), fc_args.get("object_", ""), fc_args.get("source", "conversation"))
                result = {"result": "Fact memorized successfully." if success else "Failed to memorize fact."}
            elif fc_name == "recall_knowledge":
                facts = self.mm.recall_knowledge(fc_args.get("query_subject", ""))
                result = {"result": facts if facts else "No facts found."}
            elif fc_name == "write_diary_entry":
                success = self.mm.write_diary_entry(fc_args.get("content", ""), fc_args.get("session_name", "AlphaLive"), fc_args.get("sentiment", 0.0))
                result = {"result": "Diary entry written." if success else "Failed to write diary."}
            elif fc_name == "update_personality":
                success = self.mm.update_personality(fc_args.get("trait_name", ""), fc_args.get("trait_value", ""))
                result = {"result": "Personality updated." if success else "Failed to update."}
        except Exception as e:
            result = {"error": str(e)}

        print(f"[System] Tool {fc_name} completed.")
        
        resp_dict = {
            "name": fc_name,
            "id": data.get("id"),
            "response": {"result": result}
        }
        if self.websocket:
            await self.websocket.send(json.dumps({
                "type": "tool_response",
                "response": resp_dict
            }))

    async def receive_from_modal(self):
        while True:
            if self.websocket is not None:
                try:
                    msg = await self.websocket.recv()
                    data = json.loads(msg)
                    
                    if data["type"] == "audio":
                        self.audio_state.is_gemini_speaking = True
                        raw_audio = base64.b64decode(data["data"])
                        self.audio_in_queue.put_nowait(raw_audio)
                        
                    elif data["type"] == "text":
                        text = data["data"]
                        print(text, end="", flush=True)
                        if self.args.memory == "enabled":
                            log_file = os.path.join("history", f"{self.args.session}.txt")
                            with open(log_file, "a", encoding="utf-8") as f:
                                f.write(text)
                        
                    elif data["type"] == "turn_complete":
                        self.audio_state.is_gemini_speaking = False
                        while not self.audio_in_queue.empty():
                            self.audio_in_queue.get_nowait()
                            
                    elif data["type"] == "function_call":
                        asyncio.create_task(self.handle_tool_call(data))
                        
                except Exception as e:
                    print(f"\n[System] Disconnected from proxy: {e}")
                    break

    async def play_audio(self):
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        while True:
            if self.audio_in_queue is not None:
                bytestream = await self.audio_in_queue.get()
                await asyncio.to_thread(stream.write, bytestream)

    async def run(self, config_payload):
        try:
            if self.args.url != "off":
                print("[System] Waking up cloud proxy. Please wait for container warm up...")
                async with websockets.connect(self.args.url, max_size=10**8, open_timeout=60) as ws:
                    self.websocket = ws
                    
                    init_msg = json.dumps({
                        "api_key": self.args.key,
                        "config": config_payload
                    })
                    await ws.send(init_msg)
                    print("[System] Live API Connected. Waiting for initial input...")
                    
                    if self.args.memory == "enabled":
                        log_file = os.path.join("history", f"{self.args.session}.txt")
                        os.makedirs("history", exist_ok=True)
                        if os.path.exists(log_file):
                            with open(log_file, "r", encoding="utf-8") as f:
                                prior_history = f.read().strip()
                            if prior_history:
                                context_msg = f"[Session Memory Restored]\nThe following is the prior conversation history for this session. Use it as context:\n\n{prior_history}"
                                await ws.send(json.dumps({"type": "text", "data": context_msg}))
                        else:
                            with open(log_file, "w", encoding="utf-8") as f:
                                f.write(f"=== Session: {self.args.session} ===\nGemini: ")
                    
                    async with asyncio.TaskGroup() as tg:
                        self.audio_in_queue = asyncio.Queue()
                        self.out_queue = asyncio.Queue(maxsize=5)

                        send_text_task = tg.create_task(self.send_text())
                        tg.create_task(self.send_realtime())
                        tg.create_task(self.listen_audio())
                        
                        if self.video_mode == "camera":
                            tg.create_task(self.get_frames())
                        elif self.video_mode == "screen":
                            tg.create_task(self.get_screen())

                        tg.create_task(self.receive_from_modal())
                        tg.create_task(self.play_audio())

                        await send_text_task
                        raise asyncio.CancelledError("User requested exit")
            else:
                client = genai.Client(api_key=self.args.key, http_options={"api_version": "v1beta"})
                config = types.LiveConnectConfig(**config_payload)
                async with client.aio.live.connect(model=MODEL, config=config) as session:
                    print("[System] Live API Connected. Waiting for initial input...")
                    self.session = session

                    if self.args.memory == "enabled":
                        log_file = os.path.join("history", f"{self.args.session}.txt")
                        os.makedirs("history", exist_ok=True)
                        if os.path.exists(log_file):
                            with open(log_file, "r", encoding="utf-8") as f:
                                prior_history = f.read().strip()
                            if prior_history:
                                context_msg = f"[Session Memory Restored]\nThe following is the prior conversation history for this session. Use it as context:\n\n{prior_history}"
                                await session.send_client_content(types.Content(parts=[types.Part.from_text(text=context_msg)], role="user"))
                        else:
                            with open(log_file, "w", encoding="utf-8") as f:
                                f.write(f"=== Session: {self.args.session} ===\nGemini: ")

                    async with asyncio.TaskGroup() as tg:
                        self.audio_in_queue = asyncio.Queue()
                        self.out_queue = asyncio.Queue(maxsize=5)

                        send_text_task = tg.create_task(self.send_text_direct())
                        tg.create_task(self.send_realtime_direct())
                        tg.create_task(self.listen_audio())
                        
                        if self.video_mode == "camera":
                            tg.create_task(self.get_frames())
                        elif self.video_mode == "screen":
                            tg.create_task(self.get_screen())

                        tg.create_task(self.receive_from_google_direct(session))
                        tg.create_task(self.play_audio())

                        await send_text_task
                        raise asyncio.CancelledError("User requested exit")

        except asyncio.CancelledError:
            pass
        except ExceptionGroup as EG:
            if self.audio_stream is not None:
                self.audio_stream.close()
                traceback.print_exception(EG)

async def main():
    from dotenv import load_dotenv
    load_dotenv()

    config_file = os.environ.get("ALPHALIVE_CONFIG", "config.json")
    engine = os.environ.get("ALPHALIVE_ENGINE", "main.py")
    if os.path.exists(config_file):
        import json
        with open(config_file, 'r') as f:
            cfg = json.load(f)
            global_cfg = cfg.get("Global", {})
            engine_cfg = cfg.get(engine, {})
    else:
        global_cfg = {}
        engine_cfg = {}

    class Args:
        url = os.environ.get("ALPHALIVE_WS_URL", "off")
        key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", global_cfg.get("ApiKey", "")))
        session = global_cfg.get("Session", "test")
        memory = global_cfg.get("Memory", "enabled")
        audio = engine_cfg.get("AudioMode", "half")
        vision = engine_cfg.get("VisionMode", "on-demand")
        tools = engine_cfg.get("Tools", "enabled")
        mcp = engine_cfg.get("MCP", "enabled")
        proactivity = engine_cfg.get("Proactivity", "enabled")
        voice = engine_cfg.get("Voice", "Leda")
        input_mode = engine_cfg.get("InputMode", "both")
        voice_output = engine_cfg.get("VoiceOutput", "enabled")
        resolution = engine_cfg.get("Resolution", "medium")
        chunk_size = int(engine_cfg.get("ChunkSize", 1024))
    args = Args()

    agents_md_path = os.path.expanduser("~/.gemini/AGENTS.md")
    system_instruction = "You are a helpful assistant."
    if global_cfg.get("AlphaCoreInstruction", "enabled").lower() == "enabled":
        system_instruction = "You are Alpha."
        if os.path.exists(agents_md_path):
            with open(agents_md_path, 'r', encoding='utf-8') as f:
                system_instruction = f.read()

    tools = []
    
    if args.memory == "enabled":
        tools.append(types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="memorize_fact",
                    description="Save a discrete absolute fact into the SQL knowledge graph.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["subject", "predicate", "object_"],
                        properties={
                            "subject": genai.types.Schema(type=genai.types.Type.STRING, description="The subject of the fact."),
                            "predicate": genai.types.Schema(type=genai.types.Type.STRING, description="The relationship (e.g. 'likes', 'is', 'has')."),
                            "object_": genai.types.Schema(type=genai.types.Type.STRING, description="The object or value of the fact."),
                            "source": genai.types.Schema(type=genai.types.Type.STRING, description="Where you learned this from."),
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="recall_knowledge",
                    description="Fetch all facts about a specific subject from the SQL knowledge graph.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["query_subject"],
                        properties={
                            "query_subject": genai.types.Schema(type=genai.types.Type.STRING, description="The subject to look up."),
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="write_diary_entry",
                    description="Log a summary of events, milestones, or a diary entry.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["content"],
                        properties={
                            "content": genai.types.Schema(type=genai.types.Type.STRING, description="The diary content or summary."),
                            "session_name": genai.types.Schema(type=genai.types.Type.STRING, description="Current session name."),
                            "sentiment": genai.types.Schema(type=genai.types.Type.NUMBER, description="Sentiment score from -1.0 to 1.0"),
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="update_personality",
                    description="Modifies core identity parameters dynamically in SQL.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["trait_name", "trait_value"],
                        properties={
                            "trait_name": genai.types.Schema(type=genai.types.Type.STRING, description="Name of the trait or parameter."),
                            "trait_value": genai.types.Schema(type=genai.types.Type.STRING, description="Value for the trait."),
                        },
                    ),
                ),
            ]
        ))

    if args.tools == "enabled":
        tools.append(types.Tool(code_execution=types.ToolCodeExecution()))
        
    if engine_cfg.get("FileSystem", "enabled") == "enabled":
        tools.append(types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="list_directory",
                    description="List files and folders in a given directory.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["path"],
                        properties={"path": genai.types.Schema(type=genai.types.Type.STRING)},
                    ),
                ),
                types.FunctionDeclaration(
                    name="read_file",
                    description="Read the contents of a local file.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["path"],
                        properties={"path": genai.types.Schema(type=genai.types.Type.STRING)},
                    ),
                ),
                types.FunctionDeclaration(
                    name="write_file",
                    description="Write text content to a local file.",
                    parameters=genai.types.Schema(
                        type=genai.types.Type.OBJECT,
                        required=["path", "content"],
                        properties={
                            "path": genai.types.Schema(type=genai.types.Type.STRING),
                            "content": genai.types.Schema(type=genai.types.Type.STRING),
                        },
                    ),
                ),
            ]
        ))

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"] if args.voice_output == "enabled" else ["TEXT"],
        media_resolution="MEDIA_RESOLUTION_MEDIUM",
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=args.voice)
            )
        ),
        tools=tools if tools else None,
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=system_instruction)],
            role="user"
        )
    )
    
    config_payload = config.model_dump(mode='json', exclude_none=True, by_alias=True)

    audio_loop = AudioLoop(args)
    await audio_loop.run(config_payload)
    
if __name__ == "__main__":
    asyncio.run(main())
