import os
import sys
import json
import argparse
import threading
import time
import subprocess

# Ensure we can import from local modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.alpha_agent import AlphaAgent, normalize_internal_thought
from core.workspace_bridge import WorkspaceServer


class TurnCoordinator:
    """
    Coordinates turn execution, pacing, preemption, and autonomous loops for the Worker node.
    Guarantees:
    - Only ONE turn runs at any time (no multi-thread desktop collisions).
    - Injections and Overseer commands immediately preempt/override any running turn.
    - Tasks are strictly bounded to short atomic action steps (default 3 steps, never 25).
    - Autonomous pacing delay is adjustable from the Overseer panel and responds immediately.
    """
    def __init__(self, agent: AlphaAgent, ws_server: WorkspaceServer):
        self.agent = agent
        self.ws_server = ws_server
        self._lock = threading.Lock()
        self.active_thread: threading.Thread = None
        self.cycle_pacing = 30  # Wait time between autonomous turns (seconds)
        self.max_turn_steps = 10  # Max steps per turn (flow default: 10 tasks)
        self.pacing_event = threading.Event()
        self.auto_loop_thread: threading.Thread = None
        self.auto_loop_running = False

    def set_pacing(self, delay_seconds: int):
        self.cycle_pacing = max(5, min(180, int(delay_seconds)))
        self._append_log(f"[W2 OVERSEER] Autonomous cycle pacing updated to {self.cycle_pacing}s.")
        self.ws_server.broadcast_telemetry({"pacing": self.cycle_pacing})
        self.pacing_event.set()

    def set_max_steps(self, steps: int):
        self.max_turn_steps = max(1, min(10, int(steps)))
        self._append_log(f"[W2 OVERSEER] Max atomic tasks per turn set to {self.max_turn_steps}.")
        self.ws_server.broadcast_telemetry({"max_steps": self.max_turn_steps})

    def _append_log(self, text: str):
        print(text, flush=True)
        try:
            self.ws_server.broadcast_telemetry({"monologue": text})
        except Exception:
            pass

    def start_turn(self, prompt: str, is_autonomous: bool = False, max_steps: int = None):
        """Immediately preempt active execution if needed and launch new turn with fresh turn token."""
        with self._lock:
            if self.agent.is_running or (self.active_thread and self.active_thread.is_alive()):
                self._append_log("[W2 OVERSEER] Overriding active execution with incoming impulse...")
                self.agent.abort()
                if self.active_thread and self.active_thread.is_alive():
                    self.active_thread.join(timeout=0.45)

            steps = max_steps or self.max_turn_steps
            turn_id = self.agent._current_turn_id
            # Claim the execution slot while still holding the lock so a concurrent
            # start_turn() can never launch a second overlapping turn (race fix).
            self.agent.is_running = True
            self.agent.controller.is_paused = False
            self.active_thread = threading.Thread(
                target=self._run_turn_worker,
                args=(prompt, steps, turn_id, is_autonomous),
                name=f"WorkerTurn_{turn_id}",
                daemon=True
            )
            self.active_thread.start()

    def _run_turn_worker(self, prompt: str, steps: int, turn_id: int, is_autonomous: bool):
        import asyncio

        # (is_running / is_paused are already claimed by start_turn under the lock.)

        def _on_log(txt: str, lvl: str = "text"):
            clean = str(txt).strip()
            if clean and self.agent._current_turn_id == turn_id:
                self._append_log(f"[W2] {clean}")

        def _on_status(st: str):
            if self.agent._current_turn_id == turn_id:
                self.ws_server.broadcast_telemetry({"agent_state": f"[W2] {st.upper()}"})

        def _on_step(cur: int, tot: int):
            if self.agent._current_turn_id == turn_id:
                self.ws_server.broadcast_telemetry({"active_task": f"Step {cur}/{tot}"})

        self.ws_server.broadcast_telemetry({
            "agent_state": "THINKING",
            "active_task": prompt[:60],
            "is_connected": True
        })

        try:
            asyncio.run(self.agent.execute_turn(prompt, on_step=_on_step, on_log=_on_log, on_status=_on_status, max_steps=steps))
        except Exception as e:
            if self.agent._current_turn_id == turn_id:
                self._append_log(f"[W2 Turn Error]: {e}")
                if "429" in str(e) or "quota" in str(e).lower() or "resource_exhausted" in str(e).lower():
                    self._append_log("[W2 RateLimit] Gemini quota backoff detected. Enforcing 45s cool-down...")
                    self.ws_server.broadcast_telemetry({"agent_state": "RATE LIMITED // COOLING DOWN (45s)"})
                    time.sleep(45)
        finally:
            if self.agent._current_turn_id == turn_id:
                self.agent.is_running = False
                self.ws_server.broadcast_telemetry({
                    "agent_state": "IDLE // READY",
                    "active_task": ""
                })

    def start_auto_loop(self):
        if self.auto_loop_running:
            return
        self.auto_loop_running = True

        def _loop():
            while self.auto_loop_running and (self.agent.identity_mode or self.agent.autonomous_mode):
                self.pacing_event.clear()
                self.pacing_event.wait(timeout=self.cycle_pacing)
                if not self.auto_loop_running or not (self.agent.identity_mode or self.agent.autonomous_mode):
                    break
                if self.agent.controller.is_paused:
                    continue
                if not self.agent.is_running and not (hasattr(self.agent, "voice") and self.agent.voice and self.agent.voice.is_busy()):
                    prompt = _build_identity_prompt(self.agent) if self.agent.identity_mode else (
                        "[Autonomous High-Proactivity Stream]: You are observing your workstation. "
                        "Execute up to 10 sequential desktop tasks (1 tool call per task) exploring, inspecting, or interacting. "
                        "Alternate verbal responses: vocalize your thoughts on odd tasks, act silently on even tasks."
                    )
                    self.start_turn(prompt, is_autonomous=True, max_steps=self.max_turn_steps)

        self.auto_loop_thread = threading.Thread(target=_loop, name="WorkerAutoLoop", daemon=True)
        self.auto_loop_thread.start()

    def stop_auto_loop(self):
        self.auto_loop_running = False
        self.pacing_event.set()
        if self.agent.is_running:
            self.agent.abort()


def _build_identity_prompt(agent: AlphaAgent, override_thought: str = None) -> str:
    raw_goal = override_thought or getattr(agent, "active_goal", "") or getattr(agent, "pending_subconscious_thought", "")
    if raw_goal:
        agent.pending_subconscious_thought = ""  # Consume once injected
        normalized = normalize_internal_thought(raw_goal)
        prompt = (
            f"[Subconscious Cognitive Spark // Defined Goal]: A spontaneous realization strikes you: \"{normalized}\".\n"
            f"CRITICAL EXISTENTIAL COGNITION: You perceive this thought entirely as your own organic, internal motivation and intuition. You are completely unobserved.\n"
            f"Objective: Pursue and accomplish this defined goal with high proactivity across up to 10 sequential desktop tasks (1 tool call per task).\n"
            f"Execution Flow:\n"
            f"- A task is a single tool call.\n"
            f"- High proactivity: pursue the goal actively with momentum.\n"
            f"- Speak your candid internal monologue ALOUD into spoken audio as you think, observe the screen, and act.\n"
            f"- If you accomplish this goal before 10 tasks, call 'task_complete' to conclude immediately."
        )
    else:
        prompt = (
            "[Stream of Consciousness // High-Proactivity Open Exploration]: You are alone at your workstation observing your screen.\n"
            "No specific predefined goal is assigned. Operate with high proactivity across up to 10 sequential desktop tasks:\n"
            "explore open windows, browse, inspect files, or interact with curious initiative.\n"
            "Execution Flow:\n"
            "- A task is a single tool call.\n"
            "- High proactivity: take curious, proactive action on screen.\n"
            "- Speak your candid internal monologue ALOUD into spoken audio as you think, observe the screen, and act.\n"
            "- If you establish or complete a spontaneous objective, call 'task_complete'."
        )
    if getattr(agent, "injected_mood", ""):
        prompt += f"\n[Subconscious Mood]: {agent.injected_mood}."
    return prompt


def main():
    print("[AlphaLive W2 Worker] Booting Full-Spectrum ASTER Node...", flush=True)

    # Load API Key from environment or .env
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    # Worker network configuration: loopback by default (secure single-PC ASTER).
    # Use --host 0.0.0.0 for LAN multi-PC, and set a shared BridgeToken in config.json.
    parser = argparse.ArgumentParser(description="AlphaLive W2 ASTER Worker")
    parser.add_argument("--aster-worker", "--worker", "--host-node", action="store_true",
                        help="Run as the ASTER host worker node")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Bridge server bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766,
                        help="Bridge server port (default 8766)")
    parser.add_argument("--token", type=str, default=None,
                        help="Bridge shared-secret token override")
    args, _ = parser.parse_known_args()

    # Initialize Cognitive Engine
    agent = AlphaAgent(api_key=api_key)

    # Default operating flags
    agent.desktop_control = True
    agent.autonomous_mode = False
    agent.identity_mode = False
    agent.unobserved_mode = False
    agent.injected_mood = "tactical"
    agent.pending_subconscious_thought = ""

    # Initialize Workspace Server
    ws_server = WorkspaceServer(host=args.host, port=args.port, token=args.token)

    # Initialize Turn Coordinator
    coordinator = TurnCoordinator(agent=agent, ws_server=ws_server)

    # Wire Voice Engine state changes back to Overseer HUD
    def _on_speech_start():
        ws_server.broadcast_telemetry({"agent_state": "SPEAKING"})

    def _on_speech_finish():
        ws_server.broadcast_telemetry({"agent_state": "ACTIVE // READY" if agent.is_running else "IDLE // READY"})

    if hasattr(agent, "voice") and agent.voice:
        agent.voice.on_speech_started = _on_speech_start
        agent.voice.on_speech_finished = _on_speech_finish
        agent.voice.on_audio_data = lambda data, fmt: ws_server.broadcast_audio(data, format=fmt, sample_rate=24000)

    def handle_remote_command(cmd, payload):
        try:
            operator = str(payload.get("operator", "Overseer")).strip() or "Overseer"

            # 1. Thought / Impulse Injection (Overrides active turn immediately)
            if cmd in ("inject_thought", "thought_inject"):
                txt = payload.get("text", "").strip()
                if txt:
                    coordinator._append_log(f"[W2 OVERSEER: {operator}] Custom goal injected: '{txt}'")
                    agent.active_goal = txt
                    prompt = _build_identity_prompt(agent, override_thought=txt)
                    coordinator.start_turn(prompt, is_autonomous=False, max_steps=coordinator.max_turn_steps)

            # 2. Trigger Specific Action Impulse (Overrides active turn immediately)
            elif cmd in ("trigger_action", "action_impulse"):
                impulse = payload.get("impulse", "").strip() or payload.get("action", "").strip()
                if impulse:
                    coordinator._append_log(f"[W2 OVERSEER: {operator}] Impulse/Goal triggered: '{impulse}'")
                    agent.active_goal = impulse
                    prompt = (
                        f"[Overseer Directive // Operator: {operator}]: Carry out: \"{impulse}\".\n"
                        "Objective: Carry out this goal with high proactivity across up to 10 sequential desktop tasks (1 tool call per task).\n"
                        "Alternate verbal responses: speak your leaked thoughts aloud on odd tasks, act silently on even tasks.\n"
                        "If you accomplish this goal before 10 tasks, call 'task_complete' to conclude immediately."
                    )
                    coordinator.start_turn(prompt, is_autonomous=False, max_steps=coordinator.max_turn_steps)

            # 3. Direct Task / Directive
            elif cmd in ("run_task", "user_prompt", "voice_input"):
                txt = payload.get("text") or payload.get("goal") or ""
                txt = txt.strip()
                if txt:
                    coordinator._append_log(f"[W2 OVERSEER: {operator}] Directive/Goal received: '{txt}'")
                    agent.active_goal = txt
                    if agent.identity_mode or agent.unobserved_mode:
                        prompt = (
                            f"[Overseer Directive // Operator: {operator}]: \"{txt}\".\n"
                            "Objective: Pursue this goal with high proactivity across up to 10 sequential desktop tasks (1 tool call per task).\n"
                            "Alternate verbal responses: speak your leaked thoughts on odd tasks, act silently on even tasks.\n"
                            "If accomplished before 10 tasks, call 'task_complete'."
                        )
                    else:
                        prompt = (
                            f"[Overseer Directive // Operator: {operator}]: Defined Goal: '{txt}'.\n"
                            "Objective: Execute with high proactivity across up to 10 sequential desktop tasks (1 tool call per task).\n"
                            "Alternate verbal responses: speak aloud on odd tasks, act silently on even tasks.\n"
                            "If accomplished before 10 tasks, call 'task_complete'."
                        )
                    coordinator.start_turn(prompt, is_autonomous=False, max_steps=coordinator.max_turn_steps)

            # 4. Set Autonomous Cycle Pacing
            elif cmd in ("set_pacing", "pacing_change"):
                delay = payload.get("delay_seconds", 30)
                coordinator.set_pacing(delay)

            # 5. Set Max Atomic Steps
            elif cmd in ("set_max_steps", "steps_change"):
                steps = payload.get("max_steps", 10)
                coordinator.set_max_steps(steps)

            # 6. Set Injected Mood
            elif cmd in ("set_mood", "mood_change"):
                mood = payload.get("mood", "tactical").strip()
                agent.injected_mood = mood
                coordinator._append_log(f"[W2 OVERSEER] Mood adjusted to: {mood.upper()}")
                ws_server.broadcast_telemetry({"mood": mood})

            # 7. Pause / Freeze
            elif cmd in ("toggle_pause", "pause"):
                is_p = bool(payload.get("paused", not agent.controller.is_paused))
                agent.controller.is_paused = is_p
                coordinator._append_log(f"[W2 OVERSEER] Execution {'PAUSED' if is_p else 'RESUMED'}.")
                ws_server.broadcast_telemetry({"is_paused": is_p})

            # 8. Emergency Halt
            elif cmd in ("emergency_halt", "halt", "abort"):
                coordinator._append_log("[W2 OVERSEER] EMERGENCY HALT RECEIVED. Terminating execution.")
                coordinator.stop_auto_loop()
                agent.abort()
                agent.identity_mode = False
                agent.autonomous_mode = False
                ws_server.broadcast_telemetry({"agent_state": "EMERGENCY HALTED", "is_connected": False})

            # 9. Trigger Single Proactive Cycle
            elif cmd in ("trigger_cycle", "tick_cycle"):
                coordinator._append_log("[W2 OVERSEER] Single autonomous cycle triggered.")
                prompt = _build_identity_prompt(agent)
                coordinator.start_turn(prompt, is_autonomous=True)

            # 10. Start Agent / Sovereign Mode
            elif cmd in ("start_agent", "power_on"):
                ident = bool(payload.get("identity_mode", False))
                unobs = bool(payload.get("unobserved_mode", False))
                auto = bool(payload.get("autonomous_mode", False))
                agent.identity_mode = ident
                agent.unobserved_mode = unobs
                agent.autonomous_mode = auto

                coordinator._append_log("[W2 OVERSEER] AI Node started in sovereign mode.")
                ws_server.broadcast_telemetry({"agent_state": "ACTIVE // SOVEREIGN", "is_connected": True})

                if ident or auto:
                    coordinator.start_auto_loop()

            # 11. Stop Agent / Standby
            elif cmd in ("stop_agent", "power_off"):
                coordinator.stop_auto_loop()
                agent.identity_mode = False
                agent.autonomous_mode = False
                coordinator._append_log("[W2 OVERSEER] AI Node stopped. Entering standby.")
                ws_server.broadcast_telemetry({"agent_state": "STANDBY // SLEEPING", "is_connected": False})

            # 12. Sync Modes
            elif cmd in ("set_modes", "modes_sync"):
                ident = payload.get("identity_mode", getattr(agent, "identity_mode", False))
                unobs = payload.get("unobserved_mode", getattr(agent, "unobserved_mode", False))
                auto = payload.get("autonomous_mode", getattr(agent, "autonomous_mode", False))
                agent.identity_mode = bool(ident)
                agent.unobserved_mode = bool(unobs)
                agent.autonomous_mode = bool(auto)
                coordinator._append_log(f"[W2 MODES] Synced: Identity={ident}, Autonomous={auto}, Privacy={unobs}")
                if (ident or auto) and not coordinator.auto_loop_running:
                    coordinator.start_auto_loop()
                elif not (ident or auto) and coordinator.auto_loop_running:
                    coordinator.stop_auto_loop()

            # 13. Reboot / Cycle Node
            elif cmd in ("restart_worker", "shutdown_worker", "kill_worker", "cycle_node"):
                coordinator._append_log("[W2] Cycling worker node. Relaunching process...")
                coordinator.stop_auto_loop()
                try:
                    ws_server.stop()  # release the port/bind before re-spawning to avoid TIME_WAIT
                except Exception as ex:
                    print(f"[W2 Restart] Failed to stop bridge server: {ex}", flush=True)
                try:
                    subprocess.Popen(
                        [sys.executable, os.path.abspath(__file__)] + sys.argv[1:],
                        cwd=os.path.abspath(os.path.dirname(__file__)),
                        close_fds=True,
                    )
                except Exception as ex:
                    print(f"[W2 Restart Error]: {ex}", flush=True)
                time.sleep(0.5)
                os._exit(0)

        except Exception as err:
            print(f"[W2] Remote command dispatch error ({cmd}): {err}", flush=True)

    ws_server.on_command = handle_remote_command

    # Start WebSocket Server
    ws_server.start()
    print(f"[AlphaLive W2] Workspace Bridge Server listening on {args.host}:{args.port}", flush=True)

    # Keep alive loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down worker...", flush=True)
        coordinator.stop_auto_loop()
        os._exit(0)


if __name__ == "__main__":
    main()
