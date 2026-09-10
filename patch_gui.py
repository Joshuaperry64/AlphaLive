import re

with open('gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

overlay_code = """
class StatusOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(160, 115)
        
        # Position in top-right corner
        screen_geo = QApplication.primaryScreen().availableGeometry()
        self.move(screen_geo.width() - self.width() - 20, 20)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        
        self.bg = QFrame(self)
        self.bg.setStyleSheet(f\"\"\"
            QFrame {{
                background-color: rgba(4, 8, 16, 210);
                border: 1px solid {C['border']};
                border-radius: 6px;
            }}
        \"\"\")
        bg_layout = QVBoxLayout(self.bg)
        bg_layout.setContentsMargins(8, 8, 8, 8)
        bg_layout.setSpacing(2)
        
        layout.addWidget(self.bg)

        # Title
        title = QLabel("ALPHA STATUS")
        title.setStyleSheet(f"color: {C['text_dim']}; font-weight: bold; font-family: {FONT_MONO}; font-size: 10px;")
        bg_layout.addWidget(title)
        
        bg_layout.addSpacing(4)

        self.lbl_conn   = self._make_lbl("CONN :", "DISCONNECTED", C['text_dim'])
        self.lbl_load   = self._make_lbl("LOAD :", "IDLE", C['text_dim'])
        self.lbl_exec   = self._make_lbl("EXEC :", "NONE", C['text_dim'])
        self.lbl_listen = self._make_lbl("MIC  :", "MUTED", C['text_dim'])
        self.lbl_err    = self._make_lbl("ERR  :", "NONE", C['text_dim'])

        bg_layout.addWidget(self.lbl_conn)
        bg_layout.addWidget(self.lbl_load)
        bg_layout.addWidget(self.lbl_exec)
        bg_layout.addWidget(self.lbl_listen)
        bg_layout.addWidget(self.lbl_err)
        
        bg_layout.addStretch()

        self._err_timer = QTimer(self)
        self._err_timer.setSingleShot(True)
        self._err_timer.timeout.connect(self._clear_err)

    def _make_lbl(self, prefix, val, color):
        lbl = QLabel()
        lbl.setText(f"<span style='color:{C['text_dim']}'>{prefix}</span> <span style='color:{color}'>{val}</span>")
        lbl.setStyleSheet(f"font-family: {FONT_MONO}; font-size: 9px; background: transparent; border: none;")
        return lbl

    def update_status(self, key, val, color):
        prefix = {
            "conn": "CONN :",
            "load": "LOAD :",
            "exec": "EXEC :",
            "listen": "MIC  :",
            "err": "ERR  :"
        }.get(key, key)
        
        lbl = getattr(self, f"lbl_{key}")
        lbl.setText(f"<span style='color:{C['text_dim']}'>{prefix}</span> <span style='color:{color}'>{val}</span>")

        if key == "err" and val != "NONE":
            self._err_timer.start(5000)

    def _clear_err(self):
        self.update_status("err", "NONE", C["text_dim"])

"""

if "class StatusOverlay" not in content:
    content = content.replace("class CoordinateOverlay(QWidget):", overlay_code + "class CoordinateOverlay(QWidget):")

if "self._status_overlay =" not in content:
    init_hook = """
        # Status overlay
        self._status_overlay = StatusOverlay()
        self._status_overlay.show()
"""
    content = re.sub(r'(self\._boot\.raise_\(\))', r'\1' + init_hook, content)

if "self._status_overlay.close()" not in content:
    close_hook = """
        if hasattr(self, '_status_overlay'):
            self._status_overlay.close()"""
    content = re.sub(r'(def closeEvent\(self, e\):)', r'\1' + close_hook, content)

on_line_hook = """
        if hasattr(self, '_status_overlay'):
            if "Modal proxy connected" in line or "Connected successfully" in line:
                self._status_overlay.update_status("conn", "CONNECTED", C["neon_green"])
            elif "Waking up" in line or "Connecting directly" in line:
                self._status_overlay.update_status("conn", "CONNECTING", C["neon_yellow"])
            elif "connection dropped" in lo or "disconnected from" in lo:
                self._status_overlay.update_status("conn", "DROPPED", C["neon_red"])
                self._status_overlay.update_status("err", "DROPPED", C["neon_red"])
            
            if "[Processing...]" in line:
                self._status_overlay.update_status("load", "PROCESSING", C["neon_blue"])
                self._status_overlay.update_status("listen", "MUTED", C["text_dim"])
            elif "message >" in line:
                self._status_overlay.update_status("load", "IDLE", C["text_dim"])
                self._status_overlay.update_status("listen", "LISTENING", C["neon_green"])

            if "[Tool Executing]" in line:
                self._status_overlay.update_status("exec", "EXECUTING", C["neon_purple"])
            elif "[Tool Finished]" in line:
                self._status_overlay.update_status("exec", "NONE", C["text_dim"])
                
            if "error" in lo and not "engine error" in lo:
                self._status_overlay.update_status("err", "ERROR", C["neon_red"])
"""
if on_line_hook.strip().split('\n')[0] not in content:
    content = re.sub(r'(def _on_line\(self, line: str\):\n        self\._terminal\.append\(line\)\n        lo = line\.lower\(\))', r'\1' + on_line_hook, content)

on_status_hook = """
            if hasattr(self, '_status_overlay'):
                self._status_overlay.update_status("conn", "DISCONNECTED", C["text_dim"])
                self._status_overlay.update_status("load", "IDLE", C["text_dim"])
                self._status_overlay.update_status("exec", "NONE", C["text_dim"])
                self._status_overlay.update_status("listen", "MUTED", C["text_dim"])
                if status == "error":
                    self._status_overlay.update_status("err", "CRITICAL", C["neon_red"])
"""
if "self._status_overlay.update_status(\"conn\", \"DISCONNECTED" not in content:
    content = re.sub(r'(self\._monitor\.session_stop\(\))', r'\1' + on_status_hook, content)

on_transcript_hook = """
            if role == "user" and hasattr(self, '_status_overlay'):
                self._status_overlay.update_status("listen", "HEARD", C["neon_cyan"])
"""
if "self._status_overlay.update_status(\"listen\", \"HEARD" not in content:
    content = re.sub(r'(self\._monitor\.inc_messages\(\))', r'\1' + on_transcript_hook, content)

with open('gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
