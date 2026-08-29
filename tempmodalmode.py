"""Temporary GPU-backed Gemini Live WebSocket proxy for main4.py."""

import asyncio
import base64
import json

import modal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

APP_NAME = "alphalive-temp-proxy"
app = modal.App(APP_NAME)
web_app = FastAPI()

image = modal.Image.debian_slim().pip_install(
    "google-genai>=2.3.0", "fastapi", "websockets"
)


@web_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send_json(payload):
        async with send_lock:
            await websocket.send_json(payload)

    try:
        setup = json.loads(await websocket.receive_text())
        api_key = setup.get("api_key")
        if not api_key:
            await send_json({"type": "error", "data": "Missing API key"})
            return

        try:
            config = types.LiveConnectConfig(**setup.get("config", {}))
        except Exception as exc:
            await send_json({"type": "error", "data": f"Invalid Live config: {exc}"})
            return

        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        async with client.aio.live.connect(
            model="gemini-3.1-flash-live-preview", config=config
        ) as session:

            async def from_google():
                try:
                    while True:
                        async for response in session.receive():
                            content = getattr(response, "server_content", None)
                            model_turn = getattr(content, "model_turn", None) if content else None
                            if model_turn:
                                for part in model_turn.parts:
                                    inline = getattr(part, "inline_data", None)
                                    if inline and getattr(inline, "data", None):
                                        await send_json({
                                            "type": "audio",
                                            "data": base64.b64encode(inline.data).decode("ascii"),
                                        })
                                    text = getattr(part, "text", None)
                                    if text:
                                        await send_json({"type": "text", "data": text})
                                    function_call = getattr(part, "function_call", None)
                                    if function_call:
                                        args = getattr(function_call, "args", {}) or {}
                                        if hasattr(args, "items"):
                                            args = dict(args.items())
                                        await send_json({
                                            "type": "function_call",
                                            "name": function_call.name,
                                            "id": getattr(function_call, "id", None),
                                            "args": args,
                                        })
                            output = getattr(content, "output_transcription", None) if content else None
                            input_ = getattr(content, "input_transcription", None) if content else None
                            if output and getattr(output, "text", None):
                                await send_json({"type": "output_transcription", "data": output.text})
                            if input_ and getattr(input_, "text", None):
                                await send_json({"type": "input_transcription", "data": input_.text})
                        await send_json({"type": "turn_complete"})
                except WebSocketDisconnect:
                    raise
                except Exception as exc:
                    try:
                        await send_json({"type": "error", "data": f"Gemini stream error: {exc}"})
                    finally:
                        raise

            async def from_client():
                try:
                    while True:
                        data = json.loads(await websocket.receive_text())
                        message_type = data.get("type")
                        if message_type == "heartbeat":
                            await send_json({
                                "type": "heartbeat_ack",
                                "id": data.get("id"),
                                "timestamp": data.get("timestamp"),
                            })
                        elif message_type == "audio":
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=base64.b64decode(data["data"]), mime_type="audio/pcm"
                                )
                            )
                        elif message_type == "video":
                            await session.send_realtime_input(
                                video=types.Blob(
                                    data=base64.b64decode(data["data"]), mime_type="image/jpeg"
                                )
                            )
                        elif message_type == "text":
                            await session.send_realtime_input(text=data.get("data", "."))
                        elif message_type == "tool_response":
                            response = data["response"]
                            await session.send_tool_response(function_responses=[
                                types.FunctionResponse(
                                    name=response["name"],
                                    id=response.get("id"),
                                    response=response.get("response", {}),
                                )
                            ])
                except WebSocketDisconnect:
                    raise
                except Exception:
                    raise

            google_task = asyncio.create_task(from_google())
            client_task = asyncio.create_task(from_client())
            done, pending = await asyncio.wait(
                {google_task, client_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[Temporary proxy] session ended: {type(exc).__name__}: {exc}")


@app.function(
    image=image,
    gpu="T4",
    max_containers=1,
    scaledown_window=120,
    timeout=3600,
)
@modal.asgi_app()
def fastapi_app():
    return web_app