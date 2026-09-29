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
    "google-genai>=2.0.0", "fastapi", "websockets"
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
        
        # Properly deserialize the config dict into LiveConnectConfig
        config = None
        if config_dict:
            try:
                config = types.LiveConnectConfig.model_validate(config_dict)
            except Exception as e:
                print(f"[Warning] Failed to deserialize config: {e}\n{traceback.format_exc()}", flush=True)
                try:
                    tools_raw = config_dict.get("tools") or config_dict.get("functionDeclarations")
                    sys_inst = config_dict.get("system_instruction") or config_dict.get("systemInstruction")
                    config = types.LiveConnectConfig(
                        response_modalities=[types.LiveConnectConfig.Modality.AUDIO],
                        tools=tools_raw,
                        system_instruction=sys_inst,
                    )
                    print("[Proxy] Reconstructed fallback config with tools and system instruction preserved.", flush=True)
                except Exception as fb_err:
                    print(f"[Warning] Fallback config reconstruction failed: {fb_err}. Defaulting to basic Audio.", flush=True)
                    config = types.LiveConnectConfig(
                        response_modalities=[types.LiveConnectConfig.Modality.AUDIO]
                    )
        
        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        
        try:
            async with client.aio.live.connect(model=model_name, config=config) as session:
                google_send_lock = asyncio.Lock()
                
                async def receive_from_google():
                    try:
                        while True:
                            turn = session.receive()
                            async for response in turn:
                                # ── Audio (primary path: response.data) ──────
                                if response.data:
                                    b64_audio = base64.b64encode(response.data).decode("utf-8")
                                    await send_json({"type": "audio", "data": b64_audio})

                                # ── Tool calls (LiveServerToolCall - primary Google GenAI Live path) ──
                                tc = getattr(response, "tool_call", None)
                                seen_fc_keys = set()
                                if tc and getattr(tc, "function_calls", None):
                                    fcs = []
                                    for fc in tc.function_calls:
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
                                        fc_id = getattr(fc, "id", None)
                                        key = (fc.name, fc_id)
                                        seen_fc_keys.add(key)
                                        fcs.append({
                                            "name": fc.name,
                                            "id": fc_id,
                                            "args": args_dict,
                                        })
                                    if len(fcs) > 1:
                                        await send_json({
                                            "type": "tool_call",
                                            "function_calls": fcs,
                                        })
                                    elif len(fcs) == 1:
                                        await send_json({
                                            "type": "function_call",
                                            "name": fcs[0]["name"],
                                            "id": fcs[0]["id"],
                                            "args": fcs[0]["args"],
                                        })

                                # ── Tool call cancellation ──
                                tcc = getattr(response, "tool_call_cancellation", None)
                                if tcc and getattr(tcc, "ids", None):
                                    await send_json({
                                        "type": "tool_call_cancellation",
                                        "ids": list(tcc.ids),
                                    })

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
                                            # Function call fallback (if not already handled via response.tool_call)
                                            fc = getattr(part, "function_call", None)
                                            if fc:
                                                fc_id = getattr(fc, "id", None)
                                                key = (fc.name, fc_id)
                                                if key not in seen_fc_keys:
                                                    seen_fc_keys.add(key)
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
                                                        "id": fc_id,
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
                                async with google_send_lock:
                                    await session.send_realtime_input(audio=types.Blob(data=raw_audio, mime_type="audio/pcm"))
                            elif message_type == "video":
                                raw_video = base64.b64decode(data["data"])
                                async with google_send_lock:
                                    await session.send_realtime_input(video=types.Blob(data=raw_video, mime_type="image/jpeg"))
                            elif message_type == "text":
                                async with google_send_lock:
                                    await session.send_realtime_input(text=data["data"])
                            elif message_type == "tool_response":
                                resp = data["response"]
                                ret_resp = resp.get("response", {})
                                if not isinstance(ret_resp, dict):
                                    ret_resp = {"result": str(ret_resp)}
                                id_val = resp.get("id") or None
                                async with google_send_lock:
                                    await session.send_tool_response(function_responses=[
                                        types.FunctionResponse(name=resp["name"], id=id_val, response=ret_resp)
                                    ])
                            elif message_type == "tool_responses":
                                f_resps = []
                                for r in data.get("responses", []):
                                    ret_resp = r.get("response", {})
                                    if not isinstance(ret_resp, dict):
                                        ret_resp = {"result": str(ret_resp)}
                                    id_val = r.get("id") or None
                                    f_resps.append(
                                        types.FunctionResponse(name=r["name"], id=id_val, response=ret_resp)
                                    )
                                if f_resps:
                                    async with google_send_lock:
                                        await session.send_tool_response(function_responses=f_resps)
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
