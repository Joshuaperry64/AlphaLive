import os
import sys
import json
import threading
import time

# Ensure we can import from local modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.alpha_agent import AlphaAgent
from core.workspace_bridge import WorkspaceServer

def main():
    print("[AlphaLive W2 Worker] Booting lightweight ASTER Worker...", flush=True)

    # Load API Key from environment or .env
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    # Initialize Cognitive Engine
    agent = AlphaAgent(api_key=api_key)
    
    # Allow desktop control
    agent.desktop_control = True
    agent.autonomous_mode = False
    agent.identity_mode = False

    # Initialize Workspace Server
    ws_server = WorkspaceServer(host="0.0.0.0", port=8766)

    def _append_log(text):
        print(text, flush=True)
        try:
            ws_server.broadcast_telemetry({"monologue": text})
        except:
            pass

    def handle_remote_command(cmd, payload):
        try:
            if cmd in ("inject_thought", "thought_inject"):
                txt = payload.get("text", "").strip()
                if txt:
                    if getattr(agent, "identity_mode", False):
                        agent.pending_subconscious_thought = txt
                        _append_log(f"[W2 SUBCONSCIOUS] Injected: {txt}")
                        if not agent.is_running:
                            threading.Thread(target=agent.run_autonomous_turn, daemon=True).start()
                    else:
                        _append_log(f"[W2 REMOTE] Task received: {txt}")
                        agent.pending_instructions.append(txt)
                        agent.is_running = True
                        agent.controller.is_paused = False
                        threading.Thread(target=agent.run_task, args=(txt,), daemon=True).start()

            elif cmd in ("run_task", "user_prompt"):
                txt = payload.get("text") or payload.get("goal") or ""
                txt = txt.strip()
                if txt:
                    _append_log(f"[W2 REMOTE] Task received: {txt}")
                    agent.pending_instructions.append(txt)
                    agent.is_running = True
                    agent.controller.is_paused = False
                    threading.Thread(target=agent.run_task, args=(txt,), daemon=True).start()

            elif cmd in ("start_agent", "power_on"):
                ident = bool(payload.get("identity_mode", False))
                unobs = bool(payload.get("unobserved_mode", False))
                auto = bool(payload.get("autonomous_mode", False))
                agent.identity_mode = ident
                agent.unobserved_mode = unobs
                agent.autonomous_mode = auto
                
                _append_log("[REMOTE] Overseer started AI Node.")
                ws_server.broadcast_telemetry({"agent_state": "ACTIVE // SOVEREIGN", "is_connected": True})
                
                # Start autonomous loop if needed
                if ident or auto:
                    def _auto_loop():
                        while agent.identity_mode or agent.autonomous_mode:
                            if not agent.is_running:
                                agent.run_autonomous_turn()
                            time.sleep(5)
                    threading.Thread(target=_auto_loop, daemon=True).start()

            elif cmd in ("stop_agent", "power_off"):
                agent.identity_mode = False
                agent.autonomous_mode = False
                if agent.is_running:
                    agent.abort()
                _append_log("[REMOTE] Overseer stopped AI Node.")
                ws_server.broadcast_telemetry({"agent_state": "STANDBY // SLEEPING", "is_connected": False})

            elif cmd in ("set_modes", "modes_sync"):
                ident = payload.get("identity_mode", getattr(agent, "identity_mode", False))
                unobs = payload.get("unobserved_mode", getattr(agent, "unobserved_mode", False))
                auto = payload.get("autonomous_mode", getattr(agent, "autonomous_mode", False))
                agent.identity_mode = bool(ident)
                agent.unobserved_mode = bool(unobs)
                agent.autonomous_mode = bool(auto)
                
            elif cmd in ("restart_worker", "shutdown_worker", "kill_worker"):
                _append_log("[AlphaLive Remote] Received shutdown/restart request from Overseer.")
                os._exit(0)

        except Exception as err:
            print(f"[W2] Remote command dispatch error ({cmd}): {err}", flush=True)

    ws_server.on_command = handle_remote_command

    # Route telemetry from agent back to ws_server
    def _telemetry_bridge(text: str, source: str = "W2"):
        ws_server.broadcast_telemetry({"monologue": text})
    agent.on_monologue = _telemetry_bridge

    # Start Server
    ws_server.start()
    print("[AlphaLive W2] Workspace Bridge Server listening on 0.0.0.0:8766", flush=True)

    # Keep alive loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down worker...", flush=True)
        os._exit(0)

if __name__ == "__main__":
    main()
