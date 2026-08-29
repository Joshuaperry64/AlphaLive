import modal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
    send_lock = asyncio.Lock()

    async def send_json(payload):
        # Starlette/WebSocket sends must not race across proxy tasks.
        async with send_lock:
            await websocket.send_json(payload)
    
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
                                sc = getattr(response, "server_content", None)
                                if sc and getattr(sc, "model_turn", None):
                                    for part in sc.model_turn.parts:
                                        inline_data = getattr(part, "inline_data", None)
                                        if inline_data and hasattr(inline_data, 'data'):
                                            b64_audio = base64.b64encode(inline_data.data).decode('utf-8')
                                            await send_json({"type": "audio", "data": b64_audio})
                                        if hasattr(part, "text") and part.text:
                                            await send_json({"type": "text", "data": part.text})
                                        fc = getattr(part, "function_call", None)
                                        if fc:
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
                                            await send_json({
                                                "type": "function_call", 
                                                "name": fc.name, 
                                                "id": getattr(fc, "id", None),
                                                "args": args_dict
                                            })
                                output_transcription = getattr(sc, 'output_transcription', None) if sc else None
                                input_transcription = getattr(sc, 'input_transcription', None) if sc else None
                                if output_transcription and getattr(output_transcription, "text", None):
                                    await send_json({"type": "output_transcription", "data": output_transcription.text})
                                if input_transcription and getattr(input_transcription, "text", None):
                                    await send_json({"type": "input_transcription", "data": input_transcription.text})
                            await send_json({"type": "turn_complete"})
                    except WebSocketDisconnect:
                        raise
                    except Exception as e:
                        print(f"Google disconnect: {e}")
                        try:
                            await send_json({"type": "error", "data": f"Gemini stream error: {e}"})
                        except: pass
                        raise

                async def receive_from_client():
                    try:
                        while True:
                            msg = await websocket.receive_text()
                            data = json.loads(msg)
                            message_type = data.get("type")
                            if message_type == "heartbeat":
                                await send_json({
                                    "type": "heartbeat_ack",
                                    "id": data.get("id"),
                                    "timestamp": data.get("timestamp"),
                                })
                            elif message_type == "audio":
                                raw_audio = base64.b64decode(data["data"])
                                await session.send_realtime_input(audio=types.Blob(data=raw_audio, mime_type="audio/pcm"))
                            elif message_type == "video":
                                raw_video = base64.b64decode(data["data"])
                                await session.send_realtime_input(video=types.Blob(data=raw_video, mime_type="image/jpeg"))
                            elif message_type == "text":
                                await session.send_realtime_input(text=data["data"])
                            elif message_type == "tool_response":
                                resp = data["response"]
                                await session.send_tool_response(function_responses=[
                                    types.FunctionResponse(name=resp["name"], id=resp.get("id"), response=resp.get("response", {}))
                                ])
                    except WebSocketDisconnect:
                        raise
                    except Exception as e:
                        print(f"Client disconnect: {e}")
                        raise

                google_task = asyncio.create_task(receive_from_google())
                client_task = asyncio.create_task(receive_from_client())
                done, pending = await asyncio.wait(
                    {google_task, client_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
                
        except Exception as gemini_err:
            print(f"[Proxy] Connection failed: {gemini_err}")

    except Exception as e:
        print(f"[Proxy] Proxy failure: {e}")

@app.function(image=image, cpu=2.0, memory=1024, max_containers=1, scaledown_window=1800, timeout=3600)
@modal.asgi_app()
def fastapi_app():
    return web_app