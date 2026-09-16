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
        model_name = setup.get("model", "gemini-3.1-flash-live-preview")
        if model_name.startswith("models/"):
            model_name = model_name[len("models/"):]
        config_dict = setup.get("config", {})
        
        # Properly deserialize the nested LiveConnectConfig using Pydantic
        try:
            if config_dict:
                if hasattr(types.LiveConnectConfig, "model_validate"):
                    config = types.LiveConnectConfig.model_validate(config_dict)
                else:
                    config = types.LiveConnectConfig(**config_dict)
            else:
                config = types.LiveConnectConfig(response_modalities=["AUDIO"])
        except Exception as cfg_err:
            print(f"[Proxy] Config parse error: {cfg_err}")
            traceback.print_exc()
            config = types.LiveConnectConfig(response_modalities=["AUDIO"])
        
        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        
        try:
            async with client.aio.live.connect(model=model_name, config=config) as session:
                
                async def receive_from_google():
                    try:
                        while True:
                            turn = session.receive()
                            async for response in turn:
                                # ── Audio (primary path: response.data) ──────
                                if response.data:
                                    b64_audio = base64.b64encode(response.data).decode("utf-8")
                                    await send_json({"type": "audio", "data": b64_audio})
                                    continue

                                sc = getattr(response, "server_content", None)
                                if sc:
                                    # ── model_turn parts (text + function_call + inline audio) ──
                                    if getattr(sc, "model_turn", None):
                                        for part in sc.model_turn.parts:
                                            # Inline audio blob (fallback)
                                            inline_data = getattr(part, "inline_data", None)
                                            if inline_data and hasattr(inline_data, "data"):
                                                b64_audio = base64.b64encode(inline_data.data).decode("utf-8")
                                                await send_json({"type": "audio", "data": b64_audio})
                                            # Text
                                            if getattr(part, "text", None):
                                                await send_json({"type": "text", "data": part.text})
                                            # Function call
                                            fc = getattr(part, "function_call", None)
                                            if fc:
                                                args_dict = {}
                                                try:
                                                    if fc.args:
                                                        if isinstance(fc.args, dict):
                                                            args_dict = dict(fc.args)
                                                        elif hasattr(fc.args, "items"):
                                                            args_dict = dict(fc.args.items())
                                                        else:
                                                            args_dict = fc.args
                                                except Exception:
                                                    pass
                                                await send_json({
                                                    "type": "function_call",
                                                    "name": fc.name,
                                                    "id": getattr(fc, "id", None),
                                                    "args": args_dict,
                                                })

                                    # ── tool_call attribute (alternative SDK path) ──
                                    tool_call = getattr(response, "tool_call", None)
                                    if tool_call:
                                        for fc in tool_call.function_calls:
                                            args_dict = {}
                                            try:
                                                if fc.args:
                                                    args_dict = dict(fc.args) if isinstance(fc.args, dict) else dict(fc.args.items())
                                            except Exception:
                                                pass
                                            await send_json({
                                                "type": "function_call",
                                                "name": fc.name,
                                                "id": getattr(fc, "id", None),
                                                "args": args_dict,
                                            })

                                    # ── Transcriptions ────────────────────────
                                    out_tr = getattr(sc, "output_transcription", None)
                                    in_tr  = getattr(sc, "input_transcription", None)
                                    if out_tr and getattr(out_tr, "text", None):
                                        await send_json({"type": "output_transcription", "data": out_tr.text})
                                    if in_tr and getattr(in_tr, "text", None):
                                        await send_json({"type": "input_transcription", "data": in_tr.text})

                            await send_json({"type": "turn_complete"})
                    except WebSocketDisconnect:
                        raise
                    except Exception as e:
                        print(f"Google disconnect: {e}")
                        try:
                            await send_json({"type": "error", "data": f"Gemini stream error: {e}"})
                        except Exception:
                            pass
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
                                ret_resp = resp.get("response", {})
                                if not isinstance(ret_resp, dict):
                                    ret_resp = {"result": str(ret_resp)}
                                await session.send_tool_response(function_responses=[
                                    types.FunctionResponse(name=resp["name"], id=resp.get("id"), response=ret_resp)
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
            try:
                await send_json({"type": "error", "data": f"Proxy Gemini connection failed: {gemini_err}"})
            except Exception:
                pass

    except Exception as e:
        print(f"[Proxy] Proxy failure: {e}")

@app.function(image=image, cpu=2.0, memory=1024, max_containers=1, scaledown_window=1800, timeout=3600)
@modal.asgi_app()
def fastapi_app():
    return web_app
