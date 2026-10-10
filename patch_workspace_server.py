import re
import os

with open('ui/agent_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add WorkspaceServer init and closeEvent
search_init = """        self._proactive_triggered = False
        self.duplex_mode = "half\""""
replace_init = """        self._proactive_triggered = False
        self.duplex_mode = "half"

        # Workspace Server
        self.workspace_server = None
        self.workspace_timer = None

        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    wm = cfg.get("Global", {}).get("WorkspaceMode", False)
                    self.agent.workspace_mode = wm
            except Exception:
                pass"""
content = content.replace(search_init, replace_init)

search_close = """    def closeEvent(self, event):
        if hasattr(self, 'agent') and self.agent: self.agent.abort()
        if self.hud: self.hud.close()
        if self.overlay: self.overlay.close()
        if self.calib_overlay: self.calib_overlay.close()
        if self.overseer_panel: self.overseer_panel.close()
        if self.voice_listener: self.voice_listener.stop()
        event.accept()"""

replace_close = """    def closeEvent(self, event):
        if hasattr(self, 'agent') and self.agent: self.agent.abort()
        if self.hud: self.hud.close()
        if self.overlay: self.overlay.close()
        if self.calib_overlay: self.calib_overlay.close()
        if self.overseer_panel: self.overseer_panel.close()
        if self.voice_listener: self.voice_listener.stop()
        self._stop_workspace_server()
        event.accept()"""
content = content.replace(search_close, replace_close)

# Start workspace server if enabled in config
search_hud = """        self.hud = MiniStatusHUD()
        self.hud.show()
        self.hud.set_state("standby")"""

replace_hud = """        self.hud = MiniStatusHUD()
        self.hud.show()
        self.hud.set_state("standby")

        self._apply_workspace_mode()"""
content = content.replace(search_hud, replace_hud)

methods_to_add = """    def _toggle_quick_workspace(self):
        self.agent.workspace_mode = not getattr(self.agent, "workspace_mode", False)
        self._apply_workspace_mode()
        self._sync_toggles()
        if hasattr(self, 'chk_workspace_mode'):
            self.chk_workspace_mode.blockSignals(True)
            self.chk_workspace_mode.setChecked(self.agent.workspace_mode)
            self.chk_workspace_mode.blockSignals(False)

    def _apply_workspace_mode(self):
        if getattr(self.agent, "workspace_mode", False):
            self._start_workspace_server()
        else:
            self._stop_workspace_server()

    def _start_workspace_server(self):
        if self.workspace_server:
            return
        try:
            from core.workspace_bridge import WorkspaceServer
            self.workspace_server = WorkspaceServer(host="0.0.0.0", port=8766)
            self.workspace_server.on_command = self._on_workspace_command
            self.workspace_server.start()
            self._append_log("[WORKSPACE] Multi-Workspace Server started on 0.0.0.0:8766", C["neon_cyan"])
            self._update_status("WORKSPACE SERVER ON", C["neon_cyan"])

            if not self.workspace_timer:
                self.workspace_timer = QTimer(self)
                self.workspace_timer.timeout.connect(self._broadcast_telemetry)
                self.workspace_timer.start(500)
        except Exception as e:
            self._append_log(f"[WORKSPACE ERROR] Failed to start server: {e}", C["neon_red"])

    def _stop_workspace_server(self):
        if self.workspace_timer:
            self.workspace_timer.stop()
            self.workspace_timer = None
        if self.workspace_server:
            try:
                self.workspace_server.stop()
                self.workspace_server = None
                self._append_log("[WORKSPACE] Multi-Workspace Server stopped", C["text_dim"])
                self._update_status("WORKSPACE SERVER OFF", C["text_dim"])
            except Exception as e:
                self._append_log(f"[WORKSPACE ERROR] Failed to stop server: {e}", C["neon_red"])

    def _broadcast_telemetry(self):
        if not self.workspace_server:
            return
        state = self.hud.current_state if self.hud else "offline"
        mood = getattr(self.agent, "current_mood", "default")
        active_task = getattr(self.agent, "active_task", "") or ""

        # Determine monologue
        mono = ""
        # Check if speaking
        tts_engine = getattr(self.agent, "tts_engine", "gemini")
        tts_active = tts_engine != "off" and hasattr(self.agent, "voice") and self.agent.voice
        if tts_active and getattr(self.agent.voice, "is_speaking", False):
            # Try to get the latest spoken phrase
            phrases = self.agent.voice.get_recent_spoken_phrases()
            if phrases:
                mono = phrases[-1]

        # Try finding last spoken text in log box if not currently speaking or empty mono
        if not mono and hasattr(self, 'log_box'):
            text = self.log_box.toPlainText()
            lines = text.split('\\n')
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                if line.startswith('[') and ']' in line:
                    prefix_end = line.find(']')
                    prefix = line[1:prefix_end]
                    # Looking for persona name e.g. [Alpha]
                    persona = getattr(self.agent, "get_active_persona_name", lambda: "Alpha")()
                    if prefix.startswith(persona):
                         mono = line[prefix_end + 2:].strip()
                         break

        is_paused = getattr(self.agent.controller, "is_paused", False)

        telemetry_data = {
            "agent_state": state,
            "mood": mood,
            "is_paused": is_paused,
            "monologue": mono,
            "active_task": active_task
        }
        self.workspace_server.broadcast_telemetry(telemetry_data)

    def _on_workspace_command(self, action: str, data: dict):
        def _dispatch():
            if action == "inject_thought":
                text = data.get("text", "")
                if text:
                    self._on_overseer_thought_injected(text)
            elif action == "set_mood":
                mood = data.get("mood", "")
                if mood:
                    self._on_overseer_mood_selected(mood)
            elif action == "trigger_action":
                impulse = data.get("impulse", "")
                if impulse:
                    self._on_overseer_action_requested(impulse)
            elif action == "toggle_pause":
                paused = data.get("paused", False)
                self._on_overseer_pause_toggled(paused)
            elif action == "emergency_halt":
                self._on_overseer_emergency_halt()
            elif action == "voice_input":
                text = data.get("text", "")
                if text:
                    if getattr(self.agent, "identity_mode", False) and getattr(self.agent, "unobserved_mode", False):
                        if hasattr(self, "overseer_panel") and self.overseer_panel:
                            self.overseer_panel.on_voice_received(text)
                    else:
                        self.signals.voice_heard.emit(text)
        self.signals.run_on_gui.emit(_dispatch)

    def _launch_remote_cockpit(self):
        try:
            cmd = [sys.executable, "run_overseer_client.py"]
            subprocess.Popen(cmd, cwd=str(ROOT_DIR))
            self._append_log("[WORKSPACE] Launched Remote Overseer Cockpit", C["neon_cyan"])
        except Exception as e:
            self._append_log(f"[WORKSPACE ERROR] Failed to launch remote cockpit: {e}", C["neon_red"])

    def _sync_overseer_panel_visibility(self):"""

content = content.replace("    def _sync_overseer_panel_visibility(self):", methods_to_add)

with open('ui/agent_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
