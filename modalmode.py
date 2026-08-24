import modal
from fastapi import FastAPI, WebSocket
import asyncio
import json
import base64
import traceback
from google import genai
from google.genai import types

try:
    app = modal.App("alphalive-proxy")
except AttributeError:
    app = modal.Stub("alphalive-proxy")
web_app = FastAPI()

image = modal.Image.debian_slim().pip_install(
    "google-genai>=0.5.0", "fastapi", "websockets"
)

@web_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        init_data = await websocket.receive_text()
        setup = json.loads(init_data)
        
        api_key = setup.get("api_key")
        config_dict = setup.get("config", {})
        
        # We process the configuration mapping directly rather than stripping keys
        try:
            config = types.LiveConnectConfig(**config_dict) if config_dict else None
        except Exception as cfg_err:
            print(f"[Proxy] Config parse error: {cfg_err}")
            config = types.LiveConnectConfig(response_modalities=["AUDIO"])
        
        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        
        try:
            async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
                
                async def receive_from_google():
                    try:
                        while True:
                            turn = session.receive()
                            async for response in turn:
                                sc = response.server_content
                                if sc and sc.model_turn:
                                    for part in sc.model_turn.parts:
                                        if part.inline_data and hasattr(part.inline_data, 'data'):
                                            b64_audio = base64.b64encode(part.inline_data.data).decode('utf-8')
                                            await websocket.send_json({"type": "audio", "data": b64_audio})
                                        if hasattr(part, "text") and part.text:
                                            await websocket.send_json({"type": "text", "data": part.text})
                                        if part.function_call:
                                            fc = part.function_call
                                            args_dict = {}
                                            try:
                                                if fc.args:
                                                    if isinstance(fc.args, dict):
                                                        args_dict = dict(fc.args)
                                                    elif hasattr(fc.args, 'items'):
                                                        args_dict = dict(fc.args.items())
                                                    else:
                                                        args_dict = fc.args
                                            except:
                                                pass
                                            await websocket.send_json({
                                                "type": "function_call", 
                                                "name": fc.name, 
                                                "id": fc.id,  
                                                "args": args_dict
                                            })
                                if getattr(sc, 'output_transcription', None):
                                    await websocket.send_json({"type": "output_transcription", "data": sc.output_transcription.text})
                                if getattr(sc, 'input_transcription', None):
                                    await websocket.send_json({"type": "input_transcription", "data": sc.input_transcription.text})
                            await websocket.send_json({"type": "turn_complete"})
                    except Exception as e:
                        print(f"Google disconnect: {e}")
                        try:
                            await websocket.send_json({"type": "error", "data": f"Gemini stream error: {e}"})
                        except: pass

                async def receive_from_client():
                    try:
                        while True:
                            msg = await websocket.receive_text()
                            data = json.loads(msg)
                            if data["type"] == "audio":
                                raw_audio = base64.b64decode(data["data"])
                                await session.send_realtime_input(audio=types.Blob(data=raw_audio, mime_type="audio/pcm"))
                            elif data["type"] == "video":
                                raw_video = base64.b64decode(data["data"])
                                await session.send_realtime_input(video=types.Blob(data=raw_video, mime_type="image/jpeg"))
                            elif data["type"] == "text":
                                await session.send_realtime_input(text=data["data"])
                            elif data["type"] == "tool_response":
                                resp = data["response"]
                                await session.send_tool_response(function_responses=[
                                    types.FunctionResponse(name=resp["name"], id=resp.get("id"), response=resp.get("response", {}))
                                ])
                    except Exception as e:
                        print(f"Client disconnect: {e}")

                await asyncio.gather(receive_from_google(), receive_from_client())
                
        except Exception as gemini_err:
            print(f"[Proxy] Connection failed: {gemini_err}")

    except Exception as e:
        print(f"[Proxy] Proxy failure: {e}")

@app.function(image=image, max_containers=1, scaledown_window=1800, timeout=3600)
@modal.asgi_app()
def fastapi_app():
    return web_app