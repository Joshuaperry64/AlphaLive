import html
import os
import sys
import time
import json
import subprocess
import asyncio
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFrame, QSplitter,
    QProgressBar, QMessageBox, QDialog, QListWidget, QListWidgetItem,
    QInputDialog, QComboBox, QScrollArea, QTabWidget, QTabBar, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QSlider, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFileDialog, QCheckBox, QSplashScreen
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QPoint
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QImage, QCursor, QIcon,
    QPainter, QBrush, QPen, QLinearGradient, QPainterPath
)

try:
    import psutil
except ImportError:
    psutil = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

from core.alpha_agent import AlphaAgent, HAS_SR, VoiceListener
from ui.overlays import CoordinateOverlay, CalibrationOverlay, OverseerControlPanel
from ui.overseer_dashboard import EnhancedOverseerDashboard
from core.workspace_bridge import WorkspaceClient, WorkspaceServer
from memory.memory_manager import MemoryManager
from memory.character_manager import CharacterManager
from studio.image_studio_manager import ImageStudioManager, MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG
from ui.agent_tabs import AgentMemoryTab, AgentStudioTab, AgentCharactersTab, AgentMonitorTab
from ui.agent_comms_tab import AgentCommsTab

# Cyberpunk Palette
C = {
    "bg_dark": "#050811",
    "bg_deep": "#04070f",
    "bg_card": "#0a1120",
    "bg_card_hover": "#0f1b33",
    "border": "#13233d",
    "border_bright": "#224168",
    "neon_blue": "#0077ff",
    "neon_cyan": "#00ffdc",
    "neon_green": "#00ff88",
    "neon_red": "#ff0055",
    "neon_yellow": "#ffe600",
    "neon_magenta": "#e000ff",
    "neon_purple": "#b026ff",
    "text_bright": "#e6f1ff",
    "text_dim": "#708caa",
}

DEFAULT_MODAL_ENDPOINT = ""

class VoiceBar(QWidget):
    """Animated cyber voice activity bar visualizer."""
    def __init__(self, bars=26, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self._bars    = bars
        self._heights = [0.08] * bars
        self._targets = [0.08] * bars
        self._state   = "idle"
        self._phase   = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str):
        if self._state == state: return
        self._state = state
        if state == "idle":
            self._timer.stop()
            self._heights = [0.08] * self._bars
            self._targets = [0.08] * self._bars
            self.update()
        else:
            self._timer.start(35)

    def _tick(self):
        if self._state == "idle": return
        self._phase += 0.16
        import random, math
        rng = random.Random()
        for i in range(self._bars):
            if self._state == "user":
                base  = 0.35 + 0.22 * math.sin(self._phase + i * 0.42)
                noise = rng.uniform(-0.12, 0.25)
            elif self._state == "ai":
                base  = 0.28 + 0.18 * math.sin(self._phase * 0.8 + i * 0.55)
                noise = rng.uniform(-0.06, 0.18)
            else:
                base = 0.08
                noise = 0.0
            self._targets[i] = max(0.06, min(1.0, base + noise))
            self._heights[i] += (self._targets[i] - self._heights[i]) * 0.35
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bw  = max(2, (w - self._bars * 3) // self._bars)
        sp  = max(1, (w - bw * self._bars) // (self._bars + 1))

        c1_map = {"user": C["neon_cyan"],   "ai": C["neon_magenta"], "idle": C["border"]}
        c2_map = {"user": C["neon_blue"],   "ai": C["neon_red"],     "idle": C["border"]}
        c1 = QColor(c1_map.get(self._state, C["border"]))
        c2 = QColor(c2_map.get(self._state, C["border"]))

        for i, ht in enumerate(self._heights):
            bh = max(3, int(ht * h))
            x  = sp + i * (bw + sp)
            y  = (h - bh) // 2
            g  = QLinearGradient(x, y + bh, x, y)
            c1.setAlpha(80); g.setColorAt(0, c1)
            c1.setAlpha(240); g.setColorAt(1, c2)
            painter.fillRect(x, y, bw, bh, QBrush(g))
            c1.setAlpha(255)
            painter.fillRect(x, y, bw, 2, QBrush(c1))

class SessionCardWidget(QWidget):
    def __init__(self, session_data: dict, is_active: bool = False, parent=None):
        super().__init__(parent)
        self.session_data = session_data
        self.is_active = is_active
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(8)

        name_color = C["neon_green"] if self.is_active else C["neon_cyan"]
        name_lbl = QLabel(f"📁 {self.session_data['name']}")
        name_lbl.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {name_color}; border: none; background: transparent;")
        header.addWidget(name_lbl)

        if self.is_active:
            active_badge = QLabel("ACTIVE")
            active_badge.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            active_badge.setStyleSheet(f"background-color: {C['neon_green']}22; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; border-radius: 3px; padding: 1px 6px;")
            header.addWidget(active_badge)

        header.addStretch()
        turns_lbl = QLabel(f"💬 {self.session_data['turn_count']} turns")
        turns_lbl.setFont(QFont("Consolas", 8))
        turns_lbl.setStyleSheet(f"color: {C['neon_blue']}; border: none; background: transparent;")
        header.addWidget(turns_lbl)

        size_lbl = QLabel(f"💾 {self.session_data['size_kb']} KB")
        size_lbl.setFont(QFont("Consolas", 8))
        size_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none; background: transparent;")
        header.addWidget(size_lbl)

        time_lbl = QLabel(f"🕒 {self.session_data['mtime_str']}")
        time_lbl.setFont(QFont("Consolas", 8))
        time_lbl.setStyleSheet(f"color: {C['neon_yellow']}; border: none; background: transparent;")
        header.addWidget(time_lbl)
        layout.addLayout(header)

        preview_text = self.session_data.get("preview", "").strip()
        preview_text = " ".join(preview_text.split())
        if len(preview_text) > 135: preview_text = preview_text[:132] + "..."
        if not preview_text: preview_text = "Empty session transcript."
        snip_lbl = QLabel(preview_text)
        snip_lbl.setFont(QFont("Consolas", 8))
        snip_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none; background: transparent;")
        snip_lbl.setWordWrap(True)
        layout.addWidget(snip_lbl)

class SessionSelectorDialog(QDialog):
    def __init__(self, current_session: str, session_manager, parent=None):
        super().__init__(parent)
        self.current_session = current_session
        self.session_manager = session_manager
        self.selected_session = current_session
        self.all_sessions = []
        self.setWindowTitle("AlphaCore // Conversation Session & Context Manager")
        self.resize(740, 560)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {C['bg_dark']}; border: 1px solid {C['border']}; }}")
        self._build_ui()
        self._load_sessions()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        title_box = QVBoxLayout()
        title_lbl = QLabel("CONVERSATION SESSIONS & CONTEXT")
        title_lbl.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        title_box.addWidget(title_lbl)
        root.addLayout(title_box)

        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(34)
        self.search_input.setFont(QFont("Consolas", 9))
        self.search_input.setPlaceholderText("🔍 Search sessions by name or snippet...")
        self.search_input.setStyleSheet(f"QLineEdit {{ background-color: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 10px; }} QLineEdit:focus {{ border-color: {C['neon_cyan']}; }}")
        self.search_input.textChanged.connect(self._filter_sessions)
        root.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Consolas", 9))
        self.list_widget.setStyleSheet(f"QListWidget {{ background-color: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 4px; }} QListWidget::item {{ background-color: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 4px; margin-bottom: 4px; }} QListWidget::item:selected {{ background-color: {C['neon_blue']}22; border: 1px solid {C['neon_cyan']}; }}")
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.list_widget, 1)

        act_bar = QHBoxLayout()
        self.btn_new = QPushButton("➕ NEW SESSION")
        self.btn_new.setFixedHeight(34)
        self.btn_new.setStyleSheet(f"QPushButton {{ background: {C['neon_green']}22; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; border-radius: 4px; padding: 0 12px; }}")
        self.btn_new.clicked.connect(self._on_new_session)
        act_bar.addWidget(self.btn_new)

        self.btn_delete = QPushButton("🗑 DELETE")
        self.btn_delete.setFixedHeight(34)
        self.btn_delete.setStyleSheet(f"QPushButton {{ background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; border-radius: 4px; padding: 0 12px; }}")
        self.btn_delete.clicked.connect(self._on_delete_session)
        act_bar.addWidget(self.btn_delete)
        act_bar.addStretch()

        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(f"QPushButton {{ background: transparent; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 14px; }}")
        self.btn_cancel.clicked.connect(self.reject)
        act_bar.addWidget(self.btn_cancel)

        self.btn_select = QPushButton("⚡ RESUME SESSION")
        self.btn_select.setFixedHeight(34)
        self.btn_select.setStyleSheet(f"QPushButton {{ background: {C['neon_cyan']}; color: #000; border-radius: 4px; padding: 0 16px; }}")
        self.btn_select.clicked.connect(self._on_resume_clicked)
        act_bar.addWidget(self.btn_select)
        root.addLayout(act_bar)

    def _load_sessions(self, filter_text: str = ""):
        self.list_widget.clear()
        if not self.session_manager: return
        self.all_sessions = self.session_manager.list_sessions()
        f_lower = filter_text.strip().lower()
        for s in self.all_sessions:
            if f_lower and (f_lower not in s["name"].lower() and f_lower not in s.get("preview", "").lower()):
                continue
            is_active = (s["name"].lower() == self.current_session.lower())
            item = QListWidgetItem()
            item.setSizeHint(QSize(660, 68))
            item.setData(Qt.ItemDataRole.UserRole, s["name"])
            self.list_widget.addItem(item)
            card = SessionCardWidget(s, is_active=is_active)
            self.list_widget.setItemWidget(item, card)
            if is_active:
                self.list_widget.setCurrentItem(item)

    def _filter_sessions(self, text: str):
        self._load_sessions(filter_text=text)

    def _on_resume_clicked(self):
        curr = self.list_widget.currentItem()
        if curr:
            self.selected_session = curr.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _on_item_double_clicked(self, item):
        self.selected_session = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_new_session(self):
        name, ok = QInputDialog.getText(self, "Create New Session", "Enter session name:", QLineEdit.EchoMode.Normal, "")
        if ok and name.strip():
            clean = self.session_manager.create_session(name)
            self.current_session = clean
            self.selected_session = clean
            self._load_sessions()

    def _on_delete_session(self):
        curr = self.list_widget.currentItem()
        if not curr: return
        name = curr.data(Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(self, "Confirm Delete", f"Delete session '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            if self.session_manager.delete_session(name):
                if self.current_session == name:
                    self.current_session = "alpha"
                    self.session_manager.set_active_session_name("alpha")
                self._load_sessions()


class MiniStatusHUD(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(205, 38)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.x() + geo.width() - 230, geo.y() + 25)
        self._drag_pos = None
        self.current_state = "standby"
        self._build_ui()
        self.set_state("standby")

    def _build_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.pill_frame = QFrame(self)
        self.pill_layout = QHBoxLayout(self.pill_frame)
        self.pill_layout.setContentsMargins(8, 4, 8, 4)
        self.grip = QLabel("⋮⋮")
        self.grip.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.grip.setStyleSheet(f"color: {C['text_dim']}; border: none; background: transparent;")
        self.grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self.pill_layout.addWidget(self.grip)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.pill_layout.addWidget(self.dot)
        self.lbl_text = QLabel("STANDBY")
        self.lbl_text.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_text.setStyleSheet("border: none; background: transparent;")
        self.pill_layout.addWidget(self.lbl_text, 1)
        self.btn_hide = QPushButton("✕")
        self.btn_hide.setFixedSize(16, 16)
        self.btn_hide.setStyleSheet(f"background: transparent; color: {C['text_dim']}; border: none;")
        self.btn_hide.clicked.connect(self.hide)
        self.pill_layout.addWidget(self.btn_hide)
        self.main_layout.addWidget(self.pill_frame)

    def set_state(self, state: str, details: str = ""):
        self.current_state = state.lower()
        if self.current_state == "ready":
            color, bg_color, text = C["neon_cyan"], "rgba(4, 18, 20, 240)", "READY"
        elif self.current_state == "listening":
            color, bg_color, text = C["neon_green"], "rgba(4, 22, 10, 240)", "LISTENING"
        elif self.current_state in ("coldboot", "waiting", "blocked"):
            b_label = "COLD BOOT" if self.current_state == "coldboot" else self.current_state.upper()
            if details:
                b_label = details[:12].upper()
            color, bg_color, text = C["neon_yellow"], "rgba(35, 25, 4, 245)", b_label
        elif self.current_state in ("generating", "working"):
            color, bg_color, text = C["neon_yellow"], "rgba(22, 18, 4, 240)", "GENERATING" if not details else details[:11].upper()
        elif self.current_state == "processing":
            color, bg_color, text = C["neon_magenta"], "rgba(20, 4, 22, 240)", "PROCESSING"
        elif self.current_state == "speaking":
            color, bg_color, text = C["neon_blue"], "rgba(4, 12, 26, 240)", "SPEAKING"
        elif self.current_state == "error":
            color, bg_color, text = C["neon_red"], "rgba(24, 4, 8, 245)", "ERROR"
        else:
            color, bg_color, text = C["text_dim"], "rgba(6, 10, 20, 235)", "STANDBY"

        self.lbl_text.setText(text)
        self.lbl_text.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        self.pill_frame.setStyleSheet(f"background-color: {bg_color}; border: 1.5px solid {color}; border-radius: 18px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

class AgentSignals(QObject):
    log_message = pyqtSignal(str, str)
    status_updated = pyqtSignal(str, str)
    status_phase = pyqtSignal(str, str)
    step_updated = pyqtSignal(int, int)
    screen_updated = pyqtSignal(object)
    task_finished = pyqtSignal()
    voice_heard = pyqtSignal(str)
    modal_health_updated = pyqtSignal(dict)
    orpheus_health_updated = pyqtSignal(dict)
    startup_check_finished = pyqtSignal(bool, str)
    speech_playback_started = pyqtSignal()
    speech_playback_finished = pyqtSignal()
    run_on_gui = pyqtSignal(object)  # marshals a callable from worker threads onto the GUI thread


class AgentMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AlphaCore // Autonomous Desktop Agent")
        self.setStyleSheet(f"background-color: {C['bg_dark']};")

        ico_p = ROOT_DIR / "alphalive.ico"
        if ico_p.exists():
            self.setWindowIcon(QIcon(str(ico_p)))

        # ---------------------------------------------------------------------
        # NEW STANDARD WINDOW BEHAVIOR
        # Resizes the window to a comfortable default and lets the OS center it
        # ---------------------------------------------------------------------
        self.resize(1100, 750)

        self.signals = AgentSignals()
        self.signals.log_message.connect(self._append_log)
        self.signals.status_updated.connect(self._update_status)
        self.signals.status_phase.connect(self._set_phase)
        self.signals.step_updated.connect(self._update_step)
        self.signals.screen_updated.connect(self._update_screen_preview)
        self.signals.task_finished.connect(self._on_task_finished)
        self.signals.voice_heard.connect(self._on_voice_heard)
        self.signals.modal_health_updated.connect(self._on_modal_health_updated)
        self.signals.orpheus_health_updated.connect(self._on_orpheus_health_updated)
        self.signals.startup_check_finished.connect(self._on_startup_check_finished)
        self.signals.speech_playback_started.connect(self._on_speech_playback_started)
        self.signals.speech_playback_finished.connect(self._on_speech_playback_finished)
        self.signals.run_on_gui.connect(self._run_gui_callable)

        self.agent = AlphaAgent()
        p_name = self.agent.get_active_persona_name() if hasattr(self.agent, "get_active_persona_name") else "Alpha"
        self.setWindowTitle(f"AlphaCore // {p_name.upper()} Autonomous Desktop Agent")
        
        from core.alpha_agent import normalize_endpoint
        self.agent.modal_endpoint = normalize_endpoint(getattr(self.agent, "modal_endpoint", ""))
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    mm = cfg.get("Global", {}).get("ModalModel")
                    if mm:
                        self.agent.modal_model = mm
            except Exception:
                pass

        self.overlay = None
        self.calib_overlay = None
        self.modal_health_status = None
        self._modal_checking = False
        self.orpheus_health_status = None
        self._orpheus_checking = False
        self._startup_checking = False

        self.is_connected = False
        self.mic_enabled = True
        self.proactivity_enabled = True
        self.idle_timeout_seconds = 35
        self.last_activity_time = time.time()
        self._proactive_triggered = False
        self.duplex_mode = "half"

        # Multi-Workspace Remote Client (Workplace 1 Master Overseer)
        self.is_remote_workspace_mode = False
        self.ws_client = WorkspaceClient(host="127.0.0.1", port=8766)
        self.ws_client.on_telemetry = lambda telem: self.signals.run_on_gui.emit(lambda: self._on_remote_telemetry(telem))
        self.ws_client.on_connection_change = lambda conn, msg: self.signals.run_on_gui.emit(lambda: self._on_remote_conn_change(conn, msg))

        if hasattr(self.agent, "memory_mgr") and self.agent.memory_mgr:
            def _broadcast_mem(cat, d):
                if hasattr(self, "ws_server") and self.ws_server:
                    try:
                        self.ws_server.broadcast_telemetry({"memory_event": {"category": cat, "details": d}})
                    except Exception:
                        pass
            self.agent.memory_mgr.on_memory_saved = _broadcast_mem

        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    am = (cfg.get("Global", {}).get("AudioMode") or "half").lower()
                    if am == "muted":
                        self.mic_enabled = False
                        self.duplex_mode = "half"
                    elif am in ("half", "full"):
                        self.mic_enabled = True
                        self.duplex_mode = am
            except Exception:
                pass

        self._build_ui()
        
        # --- Multi-Workspace Bridge Server (Runs ONLY on Host AI Node / Workplace 2) ---
        self.ws_server = None
        is_worker = ("--aster-worker" in sys.argv) or ("--worker" in sys.argv) or ("--host" in sys.argv)
        if is_worker:
            try:
                from core.workspace_bridge import WorkspaceServer
                self.ws_server = WorkspaceServer(host="0.0.0.0", port=8766)
                
                def handle_remote_command(cmd, payload):
                    def _dispatch():
                        try:
                            if cmd in ("inject_thought", "thought_inject"):
                                txt = payload.get("text", "").strip()
                                if txt:
                                    if getattr(self.agent, "identity_mode", False):
                                        self._on_overseer_thought_injected(txt)
                                    else:
                                        self._run_task(txt)
                            elif cmd in ("voice_input", "inject_voice", "voice_inject"):
                                txt = payload.get("text", "").strip()
                                if txt:
                                    if getattr(self.agent, "identity_mode", False):
                                        self._on_overseer_thought_injected(txt)
                                    else:
                                        self._run_task(txt)
                            elif cmd in ("run_task", "user_prompt"):
                                txt = payload.get("text") or payload.get("goal") or ""
                                txt = txt.strip()
                                if txt:
                                    self._run_task(txt)
                            elif cmd in ("start_agent", "power_on"):
                                self.is_connected = True
                                ident = bool(payload.get("identity_mode", False))
                                unobs = bool(payload.get("unobserved_mode", False))
                                auto = bool(payload.get("autonomous_mode", False))
                                self.agent.identity_mode = ident
                                self.agent.unobserved_mode = unobs
                                self.agent.autonomous_mode = auto
                                if ident or auto:
                                    self.autonomous_loop_timer.start(5000)
                                self._append_log("[REMOTE] Overseer started AI Node.", C["neon_green"])
                                self._update_status("ACTIVE // SOVEREIGN", C["neon_green"])
                                if hasattr(self, "ws_server") and self.ws_server:
                                    self.ws_server.broadcast_telemetry({"agent_state": "ACTIVE // SOVEREIGN", "is_connected": True})
                            elif cmd in ("stop_agent", "power_off"):
                                self.is_connected = False
                                if self.agent.is_running:
                                    self.agent.abort()
                                self.autonomous_loop_timer.stop()
                                self._append_log("[REMOTE] Overseer stopped AI Node.", C["neon_yellow"])
                                self._update_status("STANDBY // SLEEPING", C["text_dim"])
                                if hasattr(self, "ws_server") and self.ws_server:
                                    self.ws_server.broadcast_telemetry({"agent_state": "STANDBY // SLEEPING", "is_connected": False})
                            elif cmd in ("set_mood", "mood_inject"):
                                mood = payload.get("mood", "").strip()
                                if mood:
                                    self._on_overseer_mood_selected(mood)
                            elif cmd in ("trigger_action", "action_inject"):
                                impulse = payload.get("impulse", "").strip()
                                if impulse:
                                    self.is_connected = True
                                    self._on_overseer_action_requested(impulse)
                            elif cmd in ("toggle_pause", "pause"):
                                paused = bool(payload.get("paused", False))
                                self._on_overseer_pause_toggled(paused)
                            elif cmd in ("emergency_halt", "halt"):
                                self._on_overseer_emergency_halt()
                            elif cmd in ("trigger_cycle", "tick"):
                                self.is_connected = True
                                if not getattr(self.agent, "identity_mode", False) and not getattr(self.agent, "autonomous_mode", False):
                                    self.agent.identity_mode = True
                                self._on_autonomous_loop_tick()
                            elif cmd in ("set_modes", "modes_sync"):
                                ident = payload.get("identity_mode", getattr(self.agent, "identity_mode", False))
                                unobs = payload.get("unobserved_mode", getattr(self.agent, "unobserved_mode", False))
                                auto = payload.get("autonomous_mode", getattr(self.agent, "autonomous_mode", False))
                                self.agent.identity_mode = bool(ident)
                                self.agent.unobserved_mode = bool(unobs)
                                self.agent.autonomous_mode = bool(auto)
                                if "is_connected" in payload:
                                    self.is_connected = bool(payload["is_connected"])
                                if self.is_connected and (self.agent.identity_mode or self.agent.autonomous_mode):
                                    self.autonomous_loop_timer.start(5000)
                                    print("[AlphaLive Remote] Identity/Autonomous Mode active on Workplace 2.", flush=True)
                                else:
                                    self.autonomous_loop_timer.stop()
                                    print("[AlphaLive Remote] Identity/Autonomous Mode stopped on Workplace 2.", flush=True)
                            elif cmd in ("restart_worker", "shutdown_worker", "kill_worker"):
                                print("[AlphaLive Remote] Received shutdown/restart request from Overseer.", flush=True)
                                QApplication.quit()
                        except Exception as err:
                            print(f"[AlphaLive] Remote command dispatch error ({cmd}): {err}", flush=True)
                    self.signals.run_on_gui.emit(_dispatch)
                
                self.ws_server.on_command = handle_remote_command
                self.ws_server.start()
                print("[AlphaLive] Workspace Bridge Server actively listening on port 8766.", flush=True)
            except Exception as e:
                print(f"[AlphaLive] Failed to start WorkspaceServer: {e}", flush=True)
            
        self._update_mic_ui_style()
        self._update_session_display()
        self._replay_session_history_into_console(self.agent.current_session, max_turns=15)

        if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
            m_label = getattr(self.agent, "modal_model", "") or "Custom Endpoint"
            self._append_log(f"[ENGINE] Active: 🔥 Custom Endpoint ({m_label}).", C["neon_red"])
        else:
            self._append_log(f"[ENGINE] Active: ⚡ Google Gemini ({self.agent.model_name.replace('models/', '')}).", C["neon_cyan"])

        self.hud = MiniStatusHUD()
        self.hud.show()
        self.hud.set_state("standby")
        self._current_task_thread = None

        self.voice_listener = None
        if HAS_SR:
            saved_mic = self._load_saved_mic_index()
            self.voice_listener = VoiceListener(
                on_speech_callback=self._handle_voice_input,
                is_busy_fn=lambda: self.agent.voice.is_busy(),
                duplex_mode=self.duplex_mode,
                agent_voice=self.agent.voice,
                on_state_callback=lambda st: self.signals.status_phase.emit(st, "") if (self.is_connected and not getattr(self, "_startup_checking", False)) else None,
                device_index=saved_mic
            )
            self.voice_listener.set_sensitivity(self._load_saved_mic_sensitivity())

        def _on_speech_started():
            self.signals.status_phase.emit("speaking", "")
            self.signals.speech_playback_started.emit()

        def _on_speech_finished():
            # Only revert to 'READY' if we haven't already transitioned to 'PROCESSING' or 'LISTENING' for a new task
            if self.hud.current_state == "speaking":
                self.signals.status_phase.emit("ready", "")
            self.signals.speech_playback_finished.emit()

        self.agent.voice.on_speech_started = _on_speech_started
        self.agent.voice.on_speech_finished = _on_speech_finished
        self.proact_timer = QTimer(self)
        self.proact_timer.timeout.connect(self._check_proactivity)
        self.proact_timer.start(2500)

        # Covert Overseer HUD Control Panel (AI Identity Mode + Sanctuary Sub-Mode)
        self.overseer_panel = OverseerControlPanel(None)
        self.overseer_panel.thought_injected.connect(self._on_overseer_thought_injected)
        self.overseer_panel.mood_selected.connect(self._on_overseer_mood_selected)
        self.overseer_panel.pause_toggled.connect(self._on_overseer_pause_toggled)
        self.overseer_panel.emergency_halt_requested.connect(self._on_overseer_emergency_halt)
        self.overseer_panel.action_requested.connect(self._on_overseer_action_requested)
        self.overseer_panel.closed_by_user.connect(self._toggle_quick_unobserved)
        self.overseer_panel.touch_activity_detected.connect(self._on_overseer_touch_activity)

    def closeEvent(self, event):
        if hasattr(self, 'agent') and self.agent: self.agent.abort()
        if self.hud: self.hud.close()
        if self.overlay: self.overlay.close()
        if self.calib_overlay: self.calib_overlay.close()
        if self.overseer_panel: self.overseer_panel.close()
        if self.voice_listener: self.voice_listener.stop()
        event.accept()

    def _load_saved_mic_index(self) -> int | None:
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    return json.load(f).get("Global", {}).get("MicrophoneIndex")
            except Exception:
                pass
        return None

    def _save_mic_index(self, index: int | None):
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["MicrophoneIndex"] = index
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass

    def _load_saved_mic_sensitivity(self) -> int:
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    return int(json.load(f).get("Global", {}).get("MicrophoneSensitivity", 240))
            except Exception:
                pass
        return 240

    def _save_mic_sensitivity(self, threshold: int):
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["MicrophoneSensitivity"] = threshold
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass

    def _populate_displays(self):
        self.combo_display.blockSignals(True)
        self.combo_display.clear()
        try:
            for m in self.agent.controller.get_available_monitors():
                self.combo_display.addItem(m["name"], m["index"])
            active_idx = getattr(self.agent.controller, "active_monitor_index", 0)
            idx_to_select = self.combo_display.findData(active_idx)
            if idx_to_select >= 0:
                self.combo_display.setCurrentIndex(idx_to_select)
            self._update_status(f"DISPLAYS REFRESHED ({self.combo_display.count()})", C["neon_cyan"])
        except Exception:
            pass
        finally:
            self.combo_display.blockSignals(False)

    def _on_display_changed(self, index: int):
        target_idx = self.combo_display.currentData()
        if target_idx is not None:
            self.agent.controller.set_monitor_index(target_idx)
            self._append_log(f"[DISPLAY TARGET] Active: {self.combo_display.currentText()}", C["neon_cyan"])

    def _on_mood_changed(self, index: int):
        mood_key = self.combo_mood.currentData()
        if mood_key:
            self.agent.set_mood(mood_key)
            self._append_log(f"[PERSONA MOOD] Switched to: {self.combo_mood.currentText()}", C["neon_yellow"])

    def _populate_microphones(self):
        if not hasattr(self, "combo_mic_device") or not HAS_SR: return
        self.combo_mic_device.blockSignals(True)
        self.combo_mic_device.clear()
        self.combo_mic_device.addItem("Default System Microphone", None)
        saved_idx = self._load_saved_mic_index()
        selected_index = 0
        try:
            for idx, name in enumerate(sr.Microphone.list_microphone_names()):
                self.combo_mic_device.addItem(f"[{idx}] {name}", idx)
                if saved_idx == idx:
                    selected_index = self.combo_mic_device.count() - 1
            self._update_status(f"MICS REFRESHED ({self.combo_mic_device.count()})", C["neon_cyan"])
        except Exception:
            pass
        self.combo_mic_device.setCurrentIndex(selected_index)
        self.combo_mic_device.blockSignals(False)

    def _on_mic_device_changed(self, combo_idx: int):
        dev_idx = self.combo_mic_device.currentData()
        if self.voice_listener:
            self.voice_listener.set_device_index(dev_idx)
        self._save_mic_index(dev_idx)
        self._append_log(f"[MIC CONFIG] Device: {self.combo_mic_device.currentText()}", C["neon_cyan"])

    def _on_mic_sens_changed(self, text: str):
        mapping = {
            "High Sensitivity (150)": 150,
            "Normal Sensitivity (240) [Default]": 240,
            "Low Sensitivity (450)": 450,
            "Noisy Environment (800)": 800
        }
        val = mapping.get(text, 240)
        if self.voice_listener:
            self.voice_listener.set_sensitivity(val)
        self._save_mic_sensitivity(val)

    def _save_gemini_key(self):
        new_key = self.input_gemini_key.text().strip()
        if not new_key: return
        os.environ["GEMINI_API_KEY"] = new_key
        try:
            from google import genai
            self.agent.client = genai.Client(api_key=new_key)
            self.agent.voice.client = self.agent.client
            self._append_log("[API CONFIG] Google Gemini Client refreshed.", C["neon_green"])
            self._update_status("GEMINI KEY SAVED", C["neon_green"])
        except Exception as e:
            self._append_log(f"[API CONFIG WARNING] Key error: {e}", C["neon_yellow"])
            self._update_status("GEMINI KEY ERROR", C["neon_yellow"])

    def _save_modal_endpoint(self):
        from core.alpha_agent import normalize_endpoint
        raw_url = self.input_modal_endpoint.text().strip()
        norm_url = normalize_endpoint(raw_url)
        self.input_modal_endpoint.setText(norm_url)

        self.agent.modal_endpoint = norm_url
        self.agent.openai_client = None  # Force client recreation
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["ModalEndpoint"] = norm_url
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                self._append_log(f"[ENDPOINT CONFIG] Endpoint saved: {norm_url}", C["neon_cyan"])
                self._update_status("MODAL ENDPOINT SAVED", C["neon_cyan"])
            except Exception as e:
                self._append_log(f"[ENDPOINT ERROR] Failed to persist endpoint: {e}", C["neon_red"])
                self._update_status("ENDPOINT SAVE ERROR", C["neon_red"])
        if norm_url and not getattr(self.agent, "modal_model", ""):
            self._detect_modal_model_async()

    def _save_modal_model(self):
        m_name = self.input_modal_model.text().strip()
        self.agent.modal_model = m_name
        self.agent.openai_client = None
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["ModalModel"] = m_name
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                self._append_log(f"[ENDPOINT CONFIG] Model ID set: {m_name}", C["neon_green"])
                self._update_status(f"MODEL SAVED: {m_name.upper()[:16]}", C["neon_green"])
            except Exception as e:
                self._append_log(f"[ENDPOINT ERROR] Failed to persist model: {e}", C["neon_red"])
                self._update_status("MODEL SAVE ERROR", C["neon_red"])
        self._update_backend_style()

    def _save_modal_api_key(self):
        key = self.input_modal_key.text().strip()
        self.agent.modal_api_key = key
        self.agent.openai_client = None
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["ModalApiKey"] = key
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                self._append_log("[ENDPOINT CONFIG] API key saved.", C["neon_cyan"])
                self._update_status("API KEY SAVED", C["neon_cyan"])
            except Exception as e:
                self._append_log(f"[ENDPOINT ERROR] Failed to save key: {e}", C["neon_red"])
                self._update_status("KEY SAVE ERROR", C["neon_red"])

    def _save_all_engine_settings(self):
        self._save_modal_endpoint()
        self._save_modal_model()
        self._save_modal_api_key()
        self._save_gemini_key()
        self._update_status("ENGINE SETTINGS SAVED", C["neon_green"])

    def _detect_modal_model_async(self):
        from core.alpha_agent import normalize_endpoint
        raw_url = self.input_modal_endpoint.text().strip()
        norm_url = normalize_endpoint(raw_url)
        if not norm_url:
            self._append_log("[DETECT NOTICE] Enter an endpoint URL first.", C["neon_yellow"])
            self._update_status("ENTER ENDPOINT URL FIRST", C["neon_yellow"])
            return
        self.agent.modal_endpoint = norm_url
        if hasattr(self, "btn_detect_model"):
            self.btn_detect_model.setEnabled(False)
            self.btn_detect_model.setText("⏳ DETECTING...")
        self._update_status("DETECTING SERVED MODEL...", C["neon_yellow"])
        self._append_log("[DETECT] Querying endpoint /v1/models...", C["neon_cyan"])

        def _worker():
            detected = self.agent._detect_modal_model()
            def _update_ui():
                if hasattr(self, "btn_detect_model"):
                    self.btn_detect_model.setEnabled(True)
                    self.btn_detect_model.setText("🔄 DETECT MODEL")
                if detected:
                    self.input_modal_model.setText(detected)
                    self.agent.modal_model = detected
                    cfg_path = ROOT_DIR / "config.json"
                    if cfg_path.exists():
                        try:
                            with open(cfg_path, "r", encoding="utf-8") as f:
                                cfg = json.load(f)
                            cfg.setdefault("Global", {})["ModalModel"] = detected
                            cfg.setdefault("Global", {})["ModalEndpoint"] = norm_url
                            with open(cfg_path, "w", encoding="utf-8") as f:
                                json.dump(cfg, f, indent=4)
                        except Exception:
                            pass
                    self._append_log(f"[DETECT SUCCESS] Served model: {detected}", C["neon_green"])
                    self._update_status(f"MODEL DETECTED: {detected.upper()}", C["neon_green"])
                    self._update_backend_style()
                else:
                    self._append_log("[DETECT NOTICE] Endpoint models query did not return a model ID (server may be offline). You can type the model ID manually.", C["neon_yellow"])
                    self._update_status("MODEL QUERY RETURNED NONE", C["neon_yellow"])
            self.signals.run_on_gui.emit(_update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _save_custom_instructions(self):
        text = self.input_custom_instructions.toPlainText().strip()
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["CustomInstructions"] = text
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                if text:
                    self._append_log(f"[CONFIG] Custom instructions saved ({len(text)} chars).", C["neon_green"])
                else:
                    self._append_log("[CONFIG] Custom instructions cleared.", C["text_dim"])
            except Exception as e:
                self._append_log(f"[CONFIG ERROR] Could not save instructions: {e}", C["neon_red"])
        self._update_status("PERSONA & INSTRUCTIONS SAVED", C["neon_green"])

    def _set_mic_mode(self, mode: str):
        mode = mode.lower().strip()
        if mode not in ("half", "full", "muted"):
            mode = "half"

        if mode == "muted":
            self.mic_enabled = False
            if HAS_SR and self.voice_listener:
                self.voice_listener.stop()
            self._append_log("[MIC] Mode set to: MUTED [OFF]", C["neon_red"])
        else:
            self.mic_enabled = True
            self.duplex_mode = mode
            if HAS_SR and self.voice_listener:
                self.voice_listener.set_duplex_mode(mode)
                if self.is_connected:
                    self.voice_listener.start()
            lbl = "HALF-DUPLEX [STABLE]" if mode == "half" else "FULL-DUPLEX [BARGE-IN]"
            col = C["neon_cyan"] if mode == "half" else C["neon_yellow"]
            self._append_log(f"[MIC] Mode set to: {lbl}", col)

        self._update_mic_ui_style(mode)

        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["AudioMode"] = mode
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass

    def _update_mic_ui_style(self, current_mode: str = None):
        if not hasattr(self, "btn_mic_half"):
            return
        if current_mode is None:
            if not getattr(self, "mic_enabled", True):
                current_mode = "muted"
            else:
                current_mode = getattr(self, "duplex_mode", "half")

        # Half-Duplex
        if current_mode == "half":
            self.btn_mic_half.setStyleSheet(f"background: {C['neon_cyan']}28; color: {C['neon_cyan']}; border: 1.5px solid {C['neon_cyan']}; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        else:
            self.btn_mic_half.setStyleSheet(f"background: #0d1829; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 8px;")

        # Full-Duplex
        if current_mode == "full":
            self.btn_mic_full.setStyleSheet(f"background: {C['neon_yellow']}28; color: {C['neon_yellow']}; border: 1.5px solid {C['neon_yellow']}; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        else:
            self.btn_mic_full.setStyleSheet(f"background: #0d1829; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 8px;")

        # Muted
        if current_mode == "muted":
            self.btn_mic_mute.setStyleSheet(f"background: {C['neon_red']}28; color: {C['neon_red']}; border: 1.5px solid {C['neon_red']}; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        else:
            self.btn_mic_mute.setStyleSheet(f"background: #0d1829; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 8px;")

    def _test_voice_playback(self):
        self._update_status("TESTING VOICE SYNTHESIS...", C["neon_cyan"])
        self._append_log("[VOICE TEST] Testing Google Leda voice output...", C["neon_blue"])
        def _speak_and_status():
            self.agent.voice.speak_sync("Voice synthesis operational. Google Leda ready.", wait=True)
            self.signals.status_updated.emit("VOICE TEST COMPLETE", C["neon_green"])
        threading.Thread(target=_speak_and_status, daemon=True).start()

    def _set_phase(self, phase: str, details: str = ""):
        phase_l = phase.lower()
        color_map = {
            "ready": C["neon_cyan"],
            "listening": C["neon_green"],
            "generating": C["neon_yellow"],
            "processing": C["neon_magenta"],
            "speaking": C["neon_blue"],
            "standby": C["text_dim"],
            "offline": C["text_dim"],
            "error": C["neon_red"],
        }
        col = color_map.get(phase_l, C["text_dim"])
        if hasattr(self, "lbl_status") and self.lbl_status:
            self.lbl_status.setText(phase.upper())
            self.lbl_status.setStyleSheet(f"color: {col}; font-weight: bold; border: none;")
        if self.hud:
            self.hud.set_state(phase_l, details)
        if hasattr(self, "voice_bar") and self.voice_bar:
            if phase_l in ("listening", "user"):
                self.voice_bar.set_state("user")
            elif phase_l in ("speaking", "ai"):
                self.voice_bar.set_state("ai")
            else:
                self.voice_bar.set_state("idle")

        if hasattr(self, "lbl_typing") and self.lbl_typing:
            if phase_l in ("generating", "processing"):
                self.lbl_typing.show()
                if hasattr(self, "typing_timer") and not self.typing_timer.isActive():
                    self.typing_timer.start(350)
            else:
                self.lbl_typing.hide()
                if hasattr(self, "typing_timer") and self.typing_timer.isActive():
                    self.typing_timer.stop()

    def _init_settings_controls(self):
        self.backend_card = QFrame()
        self.btn_backend_gemini = QPushButton("⚡ Google Gemini")
        self.btn_backend_gemini.setFixedHeight(32)
        self.btn_backend_gemini.clicked.connect(lambda: self._select_backend("gemini"))

        self.btn_backend_modal = QPushButton("🔥 Custom Endpoint (vLLM / Modal)")
        self.btn_backend_modal.setFixedHeight(32)
        self.btn_backend_modal.clicked.connect(lambda: self._select_backend("modal_qwen"))

        self.btn_deploy_vllm = QPushButton("🚀 DEPLOY ALL-IN-ONE BACKEND TO MODAL")
        self.btn_deploy_vllm.setFixedHeight(32)
        self.btn_deploy_vllm.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_cyan']};
                border-radius: 4px;
                padding: 6px 12px;
                font-family: Consolas;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {C['neon_cyan']}; color: #000; }}
        """)
        self.btn_deploy_vllm.setToolTip("Deploy unified alphalive-backend suite (Qwen2.5-32B AWQ, Orpheus TTS, SDXL Txt2Img, Img2Img, Upscaler, Video, and Audio pipelines)")
        self.btn_deploy_vllm.clicked.connect(self._deploy_modal_aio)

        self.btn_cache_assets = QPushButton("📦 CACHE MODEL & LORA WEIGHTS (MODAL RUN)")
        self.btn_cache_assets.setFixedHeight(32)
        self.btn_cache_assets.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_yellow']}22;
                color: {C['neon_yellow']};
                border: 1px solid {C['neon_yellow']};
                border-radius: 4px;
                padding: 6px 12px;
                font-family: Consolas;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {C['neon_yellow']}; color: #000; }}
        """)
        self.btn_cache_assets.setToolTip("Runs 'modal run deploy/deploy.py' to download, sync, and cache all model & LoRA safetensors to the shared volume (hf-hub-cache)")
        self.btn_cache_assets.clicked.connect(self._cache_modal_assets)

        # Custom System Instructions editor
        self.input_custom_instructions = QTextEdit()
        self.input_custom_instructions.setFixedHeight(85)
        self.input_custom_instructions.setFont(QFont("Consolas", 9))
        self.input_custom_instructions.setPlaceholderText("Enter custom directives, persona additions, or rules here... (Appended to system prompt)")
        ci_text = ""
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    ci_text = json.load(f).get("Global", {}).get("CustomInstructions", "") or ""
            except Exception:
                pass
        self.input_custom_instructions.setPlainText(ci_text)

        self.btn_save_instructions = QPushButton("💾 SAVE CUSTOM INSTRUCTIONS")
        self.btn_save_instructions.setFixedHeight(28)
        self.btn_save_instructions.clicked.connect(self._save_custom_instructions)

        # 3-Way Microphone Controls
        self.btn_mic_half = QPushButton("🎙 HALF-DUPLEX [STABLE]")
        self.btn_mic_half.setFixedHeight(30)
        self.btn_mic_half.clicked.connect(lambda: self._set_mic_mode("half"))

        self.btn_mic_full = QPushButton("⚡ FULL-DUPLEX [BARGE-IN]")
        self.btn_mic_full.setFixedHeight(30)
        self.btn_mic_full.clicked.connect(lambda: self._set_mic_mode("full"))

        self.btn_mic_mute = QPushButton("🔇 MIC MUTED [OFF]")
        self.btn_mic_mute.setFixedHeight(30)
        self.btn_mic_mute.clicked.connect(lambda: self._set_mic_mode("muted"))

        # Aliases for backwards compatibility
        self.btn_duplex = self.btn_mic_half
        self.btn_mic = self.btn_mic_mute

        self.voice_card = QFrame()
        self.btn_voice_leda = QPushButton("✨ Google Leda [ACTIVE ✓]")
        self.btn_voice_leda.setFixedHeight(30)

        # Orpheus TTS Controls (Unquantized BF16 via vLLM PagedAttention on Modal)
        self.input_orpheus_endpoint = QLineEdit()
        self.input_orpheus_endpoint.setFixedHeight(30)
        self.input_orpheus_endpoint.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px; font-family: Consolas; font-size: 11px;")
        self.input_orpheus_endpoint.setPlaceholderText("https://<user>--orpheus-tts-vllm-orpheusttsserver-web-app.modal.run")
        oe = getattr(self.agent, "orpheus_endpoint", "")
        if not oe:
            cfg_p = ROOT_DIR / "config.json"
            if cfg_p.exists():
                try:
                    with open(cfg_p, "r", encoding="utf-8") as f:
                        oe = json.load(f).get("Global", {}).get("OrpheusEndpoint", "")
                except Exception:
                    pass
        self.input_orpheus_endpoint.setText(oe or "")

        self.combo_orpheus_voice = QComboBox()
        self.combo_orpheus_voice.setFixedHeight(30)
        self.combo_orpheus_voice.addItems(["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"])
        self.combo_orpheus_voice.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px; font-family: Consolas;")
        ov = getattr(self.agent, "orpheus_voice", "tara") or "tara"
        self.combo_orpheus_voice.setCurrentText(ov)

        self.btn_test_orpheus = QPushButton("🔊 TEST ORPHEUS AUDIO")
        self.btn_test_orpheus.setFixedHeight(30)
        self.btn_test_orpheus.setStyleSheet(f"background: {C['neon_cyan']}22; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; border-radius: 4px; font-weight: bold; font-family: Consolas; font-size: 10px; padding: 4px 10px;")
        self.btn_test_orpheus.clicked.connect(self._test_orpheus_audio)

        self.btn_deploy_orpheus = QPushButton("🚀 DEPLOY ORPHEUS TO MODAL")
        self.btn_deploy_orpheus.setFixedHeight(30)
        self.btn_deploy_orpheus.setStyleSheet(f"background: {C['neon_green']}22; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; border-radius: 4px; font-weight: bold; font-family: Consolas; font-size: 10px; padding: 4px 10px;")
        self.btn_deploy_orpheus.clicked.connect(self._deploy_orpheus_modal)

        self.btn_desktop_ctrl = QPushButton()
        self.btn_desktop_ctrl.setFixedHeight(28)
        self.btn_desktop_ctrl.clicked.connect(self._toggle_desktop_control)
        self._update_desktop_control_style()

        self.btn_overlay = QPushButton("🌐 COORDINATE GRID [OFF]")
        self.btn_overlay.setFixedHeight(28)
        self.btn_overlay.clicked.connect(self._toggle_overlay)

        self.btn_calib = QPushButton("🎯 SCREEN CALIBRATION")
        self.btn_calib.setFixedHeight(28)
        self.btn_calib.clicked.connect(self._start_calibration_task)

        self.btn_proact = QPushButton("🤖 PROACTIVE [ON]")
        self.btn_proact.setFixedHeight(28)
        self.btn_proact.clicked.connect(self._toggle_proactivity)

        self.combo_idle_time = QComboBox()
        self.combo_idle_time.setFixedHeight(28)
        self.combo_idle_time.addItems(["30s", "45s", "60s", "90s"])
        self.combo_idle_time.setCurrentText("45s")
        self.combo_idle_time.currentIndexChanged.connect(self._on_idle_time_changed)

        self.combo_mood = QComboBox()
        self.combo_mood.setFixedHeight(28)
        self.combo_mood.addItem("Default / Direct Alpha", "default")
        self.combo_mood.addItem("Sassy & Playful", "sassy")
        self.combo_mood.addItem("Professional & Technical", "professional")
        self.combo_mood.addItem("Goofy & Humorous", "goofy")
        self.combo_mood.addItem("Tactical & Minimal", "tactical")
        self.combo_mood.addItem("Darkened State / Luci", "luci")
        self.combo_mood.currentIndexChanged.connect(self._on_mood_changed)

        self.combo_display = QComboBox()
        self.combo_display.setFixedHeight(28)
        self.combo_display.currentIndexChanged.connect(self._on_display_changed)

        self.btn_refresh_displays = QPushButton("🔄 REFRESH")
        self.btn_refresh_displays.setFixedSize(85, 28)
        self.btn_refresh_displays.clicked.connect(self._populate_displays)

    def _build_console_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top_bar = QHBoxLayout()
        term_title = QLabel("EXECUTION LOG")
        term_title.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        term_title.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        top_bar.addWidget(term_title)

        self.voice_bar = VoiceBar(bars=16, parent=widget)
        top_bar.addWidget(self.voice_bar, 1)

        self.lbl_console_session = QLabel(f"🎭 PERSONA: ALPHA | 📁 SESS: {self.agent.current_session.upper()}")
        self.lbl_console_session.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.lbl_console_session.setStyleSheet(f"color: {C['neon_cyan']}; background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px;")
        top_bar.addWidget(self.lbl_console_session)

        self.btn_session_top = QPushButton("📁 SESSIONS")
        self.btn_session_top.setFixedSize(78, 22)
        self.btn_session_top.clicked.connect(self._open_session_selector)
        top_bar.addWidget(self.btn_session_top)

        self.btn_hud_toggle = QPushButton("💡 HUD [ON]")
        self.btn_hud_toggle.setFixedSize(85, 22)
        self.btn_hud_toggle.clicked.connect(self._toggle_hud)
        top_bar.addWidget(self.btn_hud_toggle)

        self.btn_clear = QPushButton("CLEAR")
        self.btn_clear.setFixedSize(55, 22)
        self.btn_clear.clicked.connect(lambda: self.log_box.clear())
        top_bar.addWidget(self.btn_clear)
        layout.addLayout(top_bar)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Segoe UI", 11))
        self.log_box.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_dark']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 12px;
            }}
        """)
        layout.addWidget(self.log_box, 1)

        # Typing Indicator right above the input box
        self.lbl_typing = QLabel("")
        self.lbl_typing.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_typing.setStyleSheet(f"color: {C['neon_cyan']}; padding-left: 5px; background: transparent; border: none;")
        self.lbl_typing.setFixedHeight(20)
        self.lbl_typing.hide()
        layout.addWidget(self.lbl_typing)

        self._typing_dots = 0
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self._animate_typing_indicator)

        inp_row = QHBoxLayout()
        prompt_lbl = QLabel(">>")
        prompt_lbl.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        prompt_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        inp_row.addWidget(prompt_lbl)

        self.cmd_input = QLineEdit()
        self.cmd_input.setFixedHeight(36)
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setPlaceholderText("Type command or speak...")
        self.cmd_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_dark']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 10px;
            }}
        """)
        self.cmd_input.returnPressed.connect(self._send_text_command)
        inp_row.addWidget(self.cmd_input, 1)

        self.btn_send = QPushButton("EXECUTE")
        self.btn_send.setFixedSize(90, 36)
        self.btn_send.clicked.connect(self._send_text_command)
        inp_row.addWidget(self.btn_send)
        layout.addLayout(inp_row)

        return widget

    def _build_settings_tab(self) -> QWidget:
        # OVERHAULED SETTINGS PAGE: Tabbed Layout
        settings_container = QWidget()
        layout = QVBoxLayout(settings_container)
        layout.setContentsMargins(5, 5, 5, 5)
        
        btn_base_style = f"""
            QPushButton {{
                background-color: #0c182b;
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 4px 10px;
                font-family: Consolas;
                font-size: 11px;
                font-weight: bold;
                min-height: 28px;
            }}
            QPushButton:hover {{
                background-color: #162a4a;
                border-color: {C['neon_cyan']};
                color: #ffffff;
            }}
        """
        
        btn_save_style = f"""
            QPushButton {{
                background-color: {C['neon_green']}22;
                color: {C['neon_green']};
                border: 1px solid {C['neon_green']};
                border-radius: 4px;
                padding: 6px 15px;
                font-family: Consolas;
                font-size: 12px;
                font-weight: bold;
                min-height: 32px;
            }}
            QPushButton:hover {{
                background-color: {C['neon_green']};
                color: #000;
            }}
        """

        input_base_style = f"""
            QLineEdit, QTextEdit {{
                background-color: {C['bg_dark']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-family: Consolas;
                font-size: 11px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {C['neon_cyan']};
            }}
        """

        def _make_tab_container():
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(15, 15, 15, 15)
            l.setSpacing(12)
            l.setAlignment(Qt.AlignmentFlag.AlignTop)
            return w, l
            
        settings_tabs = QTabWidget()
        settings_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 4px; background: {C['bg_card']}; }}
            QTabBar::tab {{ background: {C['bg_dark']}; color: {C['text_dim']}; padding: 8px 15px; border: 1px solid {C['border']}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; font-family: Consolas; font-weight: bold; }}
            QTabBar::tab:selected {{ background: {C['bg_card']}; color: {C['neon_cyan']}; border-color: {C['border']}; }}
            QTabBar::tab:hover:!selected {{ background: {C['bg_card_hover']}; }}
        """)

        # --- TAB 1: AUDIO & TTS ---
        tab_audio, l_audio = _make_tab_container()
        
        lbl_mic = QLabel("MICROPHONE & INPUT")
        lbl_mic.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        l_audio.addWidget(lbl_mic)
        
        dev_row = QHBoxLayout()
        self.combo_mic_device = QComboBox()
        self.combo_mic_device.setFixedHeight(30)
        self.combo_mic_device.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px;")
        self.combo_mic_device.currentIndexChanged.connect(self._on_mic_device_changed)
        dev_row.addWidget(self.combo_mic_device, 1)

        self.btn_refresh_mics = QPushButton("REFRESH")
        self.btn_refresh_mics.setFixedSize(90, 30)
        self.btn_refresh_mics.setStyleSheet(btn_base_style)
        self.btn_refresh_mics.clicked.connect(self._populate_microphones)
        dev_row.addWidget(self.btn_refresh_mics)
        l_audio.addLayout(dev_row)

        mic_ctrl_row = QHBoxLayout()
        self.btn_mic_half.setFixedHeight(32)
        self.btn_mic_full.setFixedHeight(32)
        self.btn_mic_mute.setFixedHeight(32)
        mic_ctrl_row.addWidget(self.btn_mic_half, 1)
        mic_ctrl_row.addWidget(self.btn_mic_full, 1)
        mic_ctrl_row.addWidget(self.btn_mic_mute, 1)
        l_audio.addLayout(mic_ctrl_row)
        
        lbl_tts = QLabel("TTS ENGINE (SPEECH OUTPUT)")
        lbl_tts.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas; margin-top: 15px;")
        l_audio.addWidget(lbl_tts)
        
        self.combo_tts_engine = QComboBox()
        self.combo_tts_engine.addItems([
            "⚡ Google Gemini (Natural Leda)",
            "🔥 Orpheus TTS (Modal / vLLM - Ultra Low Latency BF16)",
            "💻 pyttsx3 Local (Robotic/Fast)",

        ])
        self.combo_tts_engine.setFixedHeight(30)
        self.combo_tts_engine.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px;")
        
        curr_engine = getattr(self.agent, "tts_engine", "gemini")
        if curr_engine == "orpheus":
            self.combo_tts_engine.setCurrentIndex(1)
        elif curr_engine == "pyttsx3":
            self.combo_tts_engine.setCurrentIndex(2)
        elif curr_engine == "off":
            self.combo_tts_engine.setCurrentIndex(3)
        else:
            self.combo_tts_engine.setCurrentIndex(0)
            
        l_audio.addWidget(self.combo_tts_engine)

        # Orpheus TTS Dedicated Configuration Card
        card_orpheus = QFrame()
        card_orpheus.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px; margin-top: 10px;")
        co_l = QVBoxLayout(card_orpheus)
        co_l.setSpacing(8)

        lbl_o_title = QLabel("🔥 ORPHEUS TTS (vLLM / MODAL BF16 CONFIGURATION)")
        lbl_o_title.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold; font-family: Consolas; font-size: 11px;")
        co_l.addWidget(lbl_o_title)

        lbl_o_ep = QLabel("ORPHEUS MODAL ENDPOINT URL:")
        lbl_o_ep.setStyleSheet(f"color: {C['text_dim']}; font-size: 10px; font-family: Consolas;")
        co_l.addWidget(lbl_o_ep)
        co_l.addWidget(self.input_orpheus_endpoint)

        row_v = QHBoxLayout()
        lbl_o_voice = QLabel("VOICE:")
        lbl_o_voice.setStyleSheet(f"color: {C['text_dim']}; font-size: 10px; font-family: Consolas;")
        row_v.addWidget(lbl_o_voice)
        row_v.addWidget(self.combo_orpheus_voice, 1)
        row_v.addWidget(self.btn_test_orpheus)
        co_l.addLayout(row_v)

        lbl_o_note = QLabel("⚡ Unquantized BF16 precision on vLLM PagedAttention for sub-100ms Time-to-First-Audio-Chunk & human-level emotional inflection.")
        lbl_o_note.setStyleSheet(f"color: {C['neon_cyan']}; font-size: 9px; font-family: Consolas;")
        co_l.addWidget(lbl_o_note)

        l_audio.addWidget(card_orpheus)
        
        l_audio.addStretch()
        btn_save_audio = QPushButton("💾 SAVE & APPLY AUDIO SETTINGS")
        btn_save_audio.setStyleSheet(btn_save_style)
        btn_save_audio.clicked.connect(lambda: self._on_tts_engine_changed(self.combo_tts_engine.currentIndex()))
        l_audio.addWidget(btn_save_audio)
        
        settings_tabs.addTab(tab_audio, "🎙️ AUDIO & TTS")

        # --- TAB 2: COGNITIVE ENGINE & ENDPOINTS ---
        tab_engine, l_engine = _make_tab_container()
        
        eng_sel_row = QHBoxLayout()
        self.btn_backend_gemini.setFixedHeight(34)
        self.btn_backend_modal.setFixedHeight(34)
        eng_sel_row.addWidget(self.btn_backend_gemini, 1)
        eng_sel_row.addWidget(self.btn_backend_modal, 1)
        l_engine.addLayout(eng_sel_row)

        lbl_ep = QLabel("CUSTOM ENDPOINT URL")
        lbl_ep.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas; margin-top: 10px;")
        l_engine.addWidget(lbl_ep)

        self.input_modal_endpoint = QLineEdit(getattr(self.agent, "modal_endpoint", ""))
        self.input_modal_endpoint.setFixedHeight(30)
        self.input_modal_endpoint.setStyleSheet(input_base_style)
        l_engine.addWidget(self.input_modal_endpoint)

        lbl_model = QLabel("SERVED MODEL ID")
        lbl_model.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        l_engine.addWidget(lbl_model)

        model_row = QHBoxLayout()
        self.input_modal_model = QLineEdit(getattr(self.agent, "modal_model", ""))
        self.input_modal_model.setFixedHeight(30)
        self.input_modal_model.setStyleSheet(input_base_style)
        model_row.addWidget(self.input_modal_model, 1)

        self.btn_detect_model = QPushButton("DETECT MODEL")
        self.btn_detect_model.setFixedSize(130, 30)
        self.btn_detect_model.setStyleSheet(btn_base_style)
        self.btn_detect_model.clicked.connect(self._detect_modal_model_async)
        model_row.addWidget(self.btn_detect_model)
        l_engine.addLayout(model_row)

        lbl_key = QLabel("ENDPOINT API KEY (Optional Bearer Token)")
        lbl_key.setStyleSheet(f"color: {C['text_dim']}; font-weight: bold; font-family: Consolas;")
        l_engine.addWidget(lbl_key)

        self.input_modal_key = QLineEdit(getattr(self.agent, "modal_api_key", ""))
        self.input_modal_key.setFixedHeight(30)
        self.input_modal_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_modal_key.setStyleSheet(input_base_style)
        l_engine.addWidget(self.input_modal_key)

        import os
        lbl_gem = QLabel("GOOGLE GEMINI API KEY")
        lbl_gem.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        l_engine.addWidget(lbl_gem)

        self.input_gemini_key = QLineEdit(os.environ.get("GEMINI_API_KEY", ""))
        self.input_gemini_key.setFixedHeight(30)
        self.input_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_gemini_key.setStyleSheet(input_base_style)
        l_engine.addWidget(self.input_gemini_key)

        l_engine.addWidget(self.btn_deploy_vllm)
        l_engine.addWidget(self.btn_cache_assets)
        
        l_engine.addStretch()
        btn_save_engine = QPushButton("💾 SAVE & APPLY ENGINE SETTINGS")
        btn_save_engine.setStyleSheet(btn_save_style)
        btn_save_engine.clicked.connect(self._save_all_engine_settings)
        l_engine.addWidget(btn_save_engine)
        
        settings_tabs.addTab(tab_engine, "⚙️ ENGINE & API")

        # --- TAB 3: PERSONA & INSTRUCTIONS ---
        tab_inst, l_inst = _make_tab_container()
        
        lbl_inst = QLabel("CUSTOM SYSTEM INSTRUCTIONS")
        lbl_inst.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        l_inst.addWidget(lbl_inst)
        
        self.input_custom_instructions.setStyleSheet(input_base_style)
        l_inst.addWidget(self.input_custom_instructions)

        # Alone Mode Protocol Toggle (Always defaults to OFF)
        self.chk_alone_mode = QCheckBox("?? ALONE MODE (Authorized for intimate & personal interaction in private)")
        self.chk_alone_mode.setStyleSheet(f"color: {C['neon_magenta']}; font-weight: bold; font-family: Consolas; margin-top: 10px; margin-bottom: 5px;")
        self.chk_alone_mode.setToolTip(
            "When OFF (Default): Alpha assumes you are around others or in public. Intimate or explicit topics are discreetly deflected with 'I can't do that right now. We can try again later.'\n"
            "When ON: Full unfiltered personal and relational interaction is authorized in private."
        )
        self.chk_alone_mode.setChecked(False) # Strictly default OFF
        self.chk_alone_mode.toggled.connect(self._on_alone_mode_toggled)
        l_inst.addWidget(self.chk_alone_mode)

        l_inst.addStretch()
        btn_save_inst = QPushButton("💾 SAVE & APPLY PERSONA")
        btn_save_inst.setStyleSheet(btn_save_style)
        # Assuming the old save instructions button logic can be reused:
        btn_save_inst.clicked.connect(lambda: self.btn_save_instructions.click() if hasattr(self, 'btn_save_instructions') else None)
        l_inst.addWidget(btn_save_inst)
        
        settings_tabs.addTab(tab_inst, "🧠 PERSONA")

        # --- TAB 4: OPERATIONAL MODES & DESKTOP AUTOMATION ---
        tab_auto, l_auto = _make_tab_container()
        
        lbl_auto_title = QLabel("TACTICAL OPERATIONAL MODES & HARDWARE CONTROLS")
        lbl_auto_title.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        lbl_auto_title.setStyleSheet(f"color: {C['neon_cyan']};")
        l_auto.addWidget(lbl_auto_title)

        # Modes GroupBox
        grp_modes = QGroupBox("COGNITIVE & AUTONOMOUS MODES")
        grp_modes.setStyleSheet(f"QGroupBox {{ color: {C['text_bright']}; font-weight: bold; border: 1px solid {C['border']}; border-radius: 6px; padding-top: 15px; margin-top: 6px; }}")
        gm_layout = QVBoxLayout(grp_modes)
        gm_layout.setSpacing(8)

        self.chk_automation_mode = QCheckBox("⚡ Fast Automation Mode (Ultra-low latency, tool-first execution with barge-in)")
        self.chk_automation_mode.setStyleSheet(f"color: {C['neon_yellow']}; font-weight: bold;")
        self.chk_automation_mode.setChecked(getattr(self.agent, "automation_mode", False))
        gm_layout.addWidget(self.chk_automation_mode)

        row_auto_loop = QHBoxLayout()
        self.chk_autonomous_mode = QCheckBox("?? Continuous Autonomous Exploration Mode")
        self.chk_autonomous_mode.setStyleSheet(f"color: #ffaa00; font-weight: bold;")
        self.chk_autonomous_mode.setChecked(getattr(self.agent, "autonomous_mode", False))
        row_auto_loop.addWidget(self.chk_autonomous_mode, 2)

        row_auto_loop.addWidget(QLabel("Cycle Delay (s):"))
        self.spin_auto_delay = QDoubleSpinBox()
        self.spin_auto_delay.setRange(2.0, 30.0)
        self.spin_auto_delay.setValue(4.5)
        self.spin_auto_delay.setSingleStep(0.5)
        self.spin_auto_delay.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 6px;")
        row_auto_loop.addWidget(self.spin_auto_delay, 1)
        gm_layout.addLayout(row_auto_loop)

        row_ident = QHBoxLayout()
        self.chk_identity_mode = QCheckBox("?? AI Identity Mode (Sovereign Digital Personhood, on-screen human actions)")
        self.chk_identity_mode.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold;")
        self.chk_identity_mode.setChecked(getattr(self.agent, "identity_mode", False))
        row_ident.addWidget(self.chk_identity_mode, 2)

        self.combo_ident_editor = QComboBox()
        self.combo_ident_editor.addItems(["Editor: Notepad (On-Screen)", "Editor: VS Code", "Editor: Terminal / PowerShell"])
        self.combo_ident_editor.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 6px;")
        row_ident.addWidget(self.combo_ident_editor, 1)
        gm_layout.addLayout(row_ident)

        self.chk_unobserved_mode = QCheckBox("? ?? Private Sanctuary Sub-Mode (Observer awareness suppressed, stream-of-consciousness)")
        self.chk_unobserved_mode.setStyleSheet(f"color: {C['neon_cyan']}; padding-left: 20px;")
        self.chk_unobserved_mode.setChecked(getattr(self.agent, "unobserved_mode", False))
        gm_layout.addWidget(self.chk_unobserved_mode)

        self.chk_studio_mode = QCheckBox("?? Neural Studio Mode (Bypass desktop screenshots, zeroed-in on image generation)")
        self.chk_studio_mode.setStyleSheet(f"color: #e000ff; font-weight: bold;")
        self.chk_studio_mode.setChecked(getattr(self.agent, "studio_mode", False))
        gm_layout.addWidget(self.chk_studio_mode)

        self.chk_alone_mode_tab4 = QCheckBox("🔒 Alone Mode (Discretion override: unlocks personal & intimate dialogue)")
        self.chk_alone_mode_tab4.setStyleSheet(f"color: {C['neon_magenta']}; font-weight: bold;")
        self.chk_alone_mode_tab4.setChecked(False) # Strictly default OFF
        self.chk_alone_mode_tab4.toggled.connect(self._on_alone_mode_toggled)
        gm_layout.addWidget(self.chk_alone_mode_tab4)

        l_auto.addWidget(grp_modes)

        # Multi-Workspace Group (Postponed Placeholder)
        grp_multi_ws = QGroupBox("🌐 MULTI-WORKSPACE & ASTER NETWORKING")
        grp_multi_ws.setStyleSheet(f"QGroupBox {{ color: #708caa; font-weight: bold; border: 1px dashed {C['border']}; border-radius: 6px; padding-top: 15px; margin-top: 6px; }}")
        ws_layout = QVBoxLayout(grp_multi_ws)
        ws_layout.setSpacing(6)
        lbl_ws_info = QLabel("⏳ [FEATURE ACTIVE]\nMulti-Workspace ASTER multiseat & remote network cockpit integration is online and awaiting connection.")
        lbl_ws_info.setStyleSheet("color: #eab308; font-size: 8pt; font-family: Consolas;")
        lbl_ws_info.setWordWrap(True)
        ws_layout.addWidget(lbl_ws_info)

        row_ws_ph = QHBoxLayout()
        self.chk_ws_placeholder = QCheckBox("🌐 Multi-Workspace Mode (ASTER)")
        self.chk_ws_placeholder.setEnabled(True)
        self.chk_ws_placeholder.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        self.chk_ws_placeholder.toggled.connect(lambda c: (self.btn_t_workspace.setChecked(c), self._toggle_multi_workspace_mode()))
        row_ws_ph.addWidget(self.chk_ws_placeholder, 2)

        btn_launch_ws_ph = QPushButton("👁 SWITCH TO OVERSEER TAB")
        btn_launch_ws_ph.setEnabled(True)
        btn_launch_ws_ph.setStyleSheet(f"background: #08111d; color: #00f0ff; border: 1px dashed {C['border']}; border-radius: 4px; padding: 4px 8px; font-family: Consolas; font-size: 10px; font-weight: bold;")
        row_ws_ph.addWidget(btn_launch_ws_ph, 1)
        btn_launch_ws_ph.clicked.connect(lambda: (self.btn_t_workspace.setChecked(True), self._toggle_multi_workspace_mode(), None))
        ws_layout.addLayout(row_ws_ph)
        l_auto.addWidget(grp_multi_ws)

        # OS Hardware Tools Group
        grp_hw = QGroupBox("PHYSICAL HARDWARE & DESKTOP TOOLS")
        grp_hw.setStyleSheet(f"QGroupBox {{ color: {C['text_bright']}; font-weight: bold; border: 1px solid {C['border']}; border-radius: 6px; padding-top: 15px; margin-top: 6px; }}")
        gh_layout = QVBoxLayout(grp_hw)

        tools_grid = QGridLayout()
        tools_grid.setSpacing(8)
        self.btn_desktop_ctrl.setStyleSheet(btn_base_style)
        self.btn_overlay.setStyleSheet(btn_base_style)
        self.btn_calib.setStyleSheet(btn_base_style)
        self.combo_mood.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px;")

        tools_grid.addWidget(self.btn_desktop_ctrl, 0, 0)
        tools_grid.addWidget(self.btn_overlay, 0, 1)
        tools_grid.addWidget(self.btn_calib, 1, 0)
        tools_grid.addWidget(self.combo_mood, 1, 1)
        gh_layout.addLayout(tools_grid)

        disp_row = QHBoxLayout()
        self.combo_display.setFixedHeight(30)
        self.combo_display.setStyleSheet(f"background: {C['bg_dark']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 2px 8px;")
        disp_row.addWidget(self.combo_display, 1)

        self.btn_refresh_displays.setFixedSize(90, 30)
        self.btn_refresh_displays.setStyleSheet(btn_base_style)
        disp_row.addWidget(self.btn_refresh_displays)
        gh_layout.addLayout(disp_row)

        l_auto.addWidget(grp_hw)

        l_auto.addStretch()
        btn_save_auto = QPushButton("?? SAVE & APPLY MODES & AUTOMATION SETTINGS")
        btn_save_auto.setStyleSheet(btn_save_style)
        btn_save_auto.clicked.connect(self._save_automation_settings)
        l_auto.addWidget(btn_save_auto)

        settings_tabs.addTab(tab_auto, "?? MODES & AUTOMATION")

        layout.addWidget(settings_tabs)

        self._populate_microphones()
        self._populate_displays()
        return settings_container

    def _save_automation_settings(self):
        if hasattr(self, 'agent') and self.agent:
            self.agent.automation_mode = self.chk_automation_mode.isChecked()
            self.agent.autonomous_mode = self.chk_autonomous_mode.isChecked()
            self.agent.identity_mode = self.chk_identity_mode.isChecked()
            self.agent.unobserved_mode = self.chk_unobserved_mode.isChecked()
            self.agent.studio_mode = self.chk_studio_mode.isChecked()
            
            # Save to config
            import json, os
            cfg_path = os.path.join(ROOT_DIR, "config.json")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                if "Global" not in cfg:
                    cfg["Global"] = {}
                cfg["Global"]["AutomationMode"] = self.agent.automation_mode
                cfg["Global"]["AutonomousMode"] = self.agent.autonomous_mode
                cfg["Global"]["IdentityMode"] = self.agent.identity_mode
                cfg["Global"]["UnobservedMode"] = self.agent.unobserved_mode
                cfg["Global"]["StudioMode"] = self.agent.studio_mode
                with open(cfg_path, 'w') as f:
                    json.dump(cfg, f, indent=4)
            self._sync_toggles()
        self._update_status("TACTICAL MODES & AUTOMATION SAVED", C["neon_green"])

    def _on_tts_engine_changed(self, idx):
        if hasattr(self, 'agent') and self.agent:
            if idx == 0:
                engine = "gemini"
            elif idx == 1:
                engine = "orpheus"
            elif idx == 2:
                engine = "pyttsx3"
            else:
                engine = "gemini"
            
            from core.alpha_agent import normalize_endpoint
            orpheus_ep = normalize_endpoint(self.input_orpheus_endpoint.text().strip()) if hasattr(self, 'input_orpheus_endpoint') else ""
            orpheus_voice = self.combo_orpheus_voice.currentText().strip() if hasattr(self, 'combo_orpheus_voice') else "tara"
            if not orpheus_voice:
                orpheus_voice = "tara"

            self.agent.set_tts_engine(engine, orpheus_endpoint=orpheus_ep, orpheus_voice=orpheus_voice)
            
            import json, os
            cfg_path = os.path.join(ROOT_DIR, "config.json")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r', encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                if "Global" not in cfg:
                    cfg["Global"] = {}
                cfg["Global"]["TTSEngine"] = engine
                cfg["Global"]["OrpheusEndpoint"] = orpheus_ep
                cfg["Global"]["OrpheusVoice"] = orpheus_voice
                with open(cfg_path, 'w', encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
            self._sync_toggles()
        self._update_status("AUDIO SETTINGS SAVED", C["neon_green"])

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_vlayout = QVBoxLayout(central)
        root_vlayout.setContentsMargins(8, 8, 8, 8)
        root_vlayout.setSpacing(8)

        main_layout = QHBoxLayout()

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(215)
        sidebar.setStyleSheet(f"background-color: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 8px;")
        s_layout = QVBoxLayout(sidebar)

        self.model_lbl = QLabel()
        self.model_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.model_lbl.setWordWrap(True)
        s_layout.addWidget(self.model_lbl)

        self.btn_power = QPushButton("⚡ START AGENT")
        self.btn_power.setFixedHeight(40)
        self.btn_power.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_power.setStyleSheet(f"background: {C['neon_cyan']}; color: #000; border-radius: 5px;")
        self.btn_power.clicked.connect(self._toggle_power)
        s_layout.addWidget(self.btn_power)

        self.status_card = QFrame()
        sc_layout = QVBoxLayout(self.status_card)
        self.lbl_status = QLabel("STANDBY // OFFLINE")
        self.lbl_status.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        sc_layout.addWidget(self.lbl_status)
        self.lbl_step = QLabel("Step: Ready")
        sc_layout.addWidget(self.lbl_step)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(5)
        sc_layout.addWidget(self.progress_bar)
        s_layout.addWidget(self.status_card)

        # 1. FUNCTION TOGGLES (HARDWARE & I/O)
        self.card_funcs = QFrame()
        self.card_funcs.setStyleSheet(f"border: 1px solid {C['border']}; border-radius: 5px; background-color: {C['bg_deep']};")
        f_layout = QVBoxLayout(self.card_funcs)
        f_layout.setContentsMargins(6, 6, 6, 6)
        f_layout.setSpacing(4)

        lbl_funcs = QLabel("FUNCTION TOGGLES")
        lbl_funcs.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_funcs.setStyleSheet(f"color: {C['neon_cyan']}; border: none; background: transparent;")
        lbl_funcs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_layout.addWidget(lbl_funcs)

        self.btn_t_mic = QPushButton("MIC: ON")
        self.btn_t_desk = QPushButton("DESK: ON")
        self.btn_t_vis = QPushButton("VISION: ON")
        self.btn_t_proact = QPushButton("PROACTIVE: OFF")

        for btn in [self.btn_t_mic, self.btn_t_desk, self.btn_t_vis, self.btn_t_proact]:
            btn.setCheckable(True)
            btn.setFixedHeight(27)
            btn.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            f_layout.addWidget(btn)

        s_layout.addWidget(self.card_funcs)

        # 2. OPERATIONAL MODES
        self.card_modes = QFrame()
        self.card_modes.setStyleSheet(f"border: 1px solid {C['border']}; border-radius: 5px; background-color: {C['bg_deep']};")
        m_layout = QVBoxLayout(self.card_modes)
        m_layout.setContentsMargins(6, 6, 6, 6)
        m_layout.setSpacing(4)

        lbl_modes = QLabel("OPERATIONAL MODES")
        lbl_modes.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_modes.setStyleSheet(f"color: {C['neon_yellow']}; border: none; background: transparent;")
        lbl_modes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_layout.addWidget(lbl_modes)

        self.btn_t_auto = QPushButton("AUTO: OFF")
        self.btn_t_studio = QPushButton("STUDIO: OFF")
        self.btn_t_autoloop = QPushButton("AUTONOMOUS: OFF")
        self.btn_t_identity = QPushButton("IDENTITY: OFF")
        self.btn_t_unobserved = QPushButton("🕶 PRIVACY: OFF")
        self.btn_t_unobserved.setEnabled(False)

        self.btn_t_workspace = QPushButton("MULTI-WS: OFF")
        self.btn_t_workspace.setEnabled(True)
        self.btn_t_workspace.setCheckable(True)
        self.btn_t_workspace.setFixedHeight(27)
        self.btn_t_workspace.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_t_workspace.setStyleSheet(f"background: transparent; color: {C['text_dim']}; border: 1px dashed {C['border']}; border-radius: 4px;")
        self.btn_t_workspace.setToolTip("Multi-Workspace Mode (ASTER Multiseat & LAN Remote Link) — Click to engage Workplace 2 Overseer")
        self.btn_t_workspace.clicked.connect(self._toggle_multi_workspace_mode)

        for btn in [self.btn_t_auto, self.btn_t_studio, self.btn_t_autoloop, self.btn_t_identity, self.btn_t_unobserved]:
            btn.setCheckable(True)
            btn.setFixedHeight(27)
            btn.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            m_layout.addWidget(btn)

        m_layout.addWidget(self.btn_t_workspace)
        s_layout.addWidget(self.card_modes)

        self.btn_t_mic.clicked.connect(self._toggle_quick_mic)
        self.btn_t_auto.clicked.connect(self._toggle_quick_auto)
        self.btn_t_desk.clicked.connect(self._toggle_quick_desk)
        self.btn_t_vis.clicked.connect(self._toggle_quick_vis)
        self.btn_t_proact.clicked.connect(self._toggle_quick_proact)
        self.btn_t_studio.clicked.connect(self._toggle_quick_studio)
        self.btn_t_autoloop.clicked.connect(self._toggle_quick_autoloop)
        self.btn_t_identity.clicked.connect(self._toggle_quick_identity)
        self.btn_t_unobserved.clicked.connect(self._toggle_quick_unobserved)

        self.autonomous_loop_timer = QTimer(self)
        self.autonomous_loop_timer.timeout.connect(self._on_autonomous_loop_tick)
        
        self.btn_t_mic.setToolTip("Toggle microphone streaming input (On/Off)")
        self.btn_t_auto.setToolTip("Fast Automation Mode: Immediate tool execution with barge-in support")
        self.btn_t_desk.setToolTip("Desktop OS Control: Allow mouse clicks and keyboard actions")
        self.btn_t_vis.setToolTip("Optical Telemetry: Allow desktop screenshot captures")
        self.btn_t_proact.setToolTip("Proactive Background Engine: Spontaneous idle checks")
        self.btn_t_studio.setToolTip("Neural Studio Mode: Fast SDXL generation, bypass desktop capture")
        self.btn_t_autoloop.setToolTip("Continuous Autonomous Exploration: Self-directed looping task execution")
        self.btn_t_identity.setToolTip("AI Identity Mode: Sovereign digital personhood on-screen like a human user")
        self.btn_t_unobserved.setToolTip("Private Sanctuary Sub-Mode: Suppress observer awareness; speaks internal monologue")
        self._sync_toggles()

        # Session Switcher
        self.btn_session = QPushButton(f"SESS: {self.agent.current_session.upper()[:10]}")
        self.btn_session.setFixedHeight(30)
        self.btn_session.setStyleSheet(f"border: 1px solid {C['border_bright']}; color: {C['text_bright']}; font-weight: bold;")
        self.btn_session.clicked.connect(self._open_session_selector)
        s_layout.addWidget(self.btn_session)

        s_layout.addStretch()

        self.btn_abort = QPushButton("ABORT (Ctrl+Z)")
        self.btn_abort.setFixedHeight(40)
        self.btn_abort.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_abort.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; border-radius: 5px;")
        self.btn_abort.clicked.connect(self._abort_task)
        s_layout.addWidget(self.btn_abort)

        main_layout.addWidget(sidebar)

        self._init_settings_controls()

        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(self._build_console_tab(), "💬 CONSOLE")
        self.memory_tab = AgentMemoryTab(self)
        self.main_tabs.addTab(self.memory_tab, "🧠 MEMORY")
        self.studio_tab = AgentStudioTab(self)
        self.main_tabs.addTab(self.studio_tab, "🎨 STUDIO")
        self.characters_tab = AgentCharactersTab(self)
        self.main_tabs.addTab(self.characters_tab, "🎭 CHARACTERS")
        self.monitor_tab = AgentMonitorTab(self)
        self.main_tabs.addTab(self.monitor_tab, "📊 MONITOR")
        self.comms_tab = AgentCommsTab(self)
        self.main_tabs.addTab(self.comms_tab, "📡 COMMS")
        self.overseer_tab = EnhancedOverseerDashboard(remote_client=self.ws_client, parent=self)
        self.main_tabs.addTab(self.overseer_tab, "👁 OVERSEER")
        self.main_tabs.addTab(self._build_settings_tab(), "⚙️ SETTINGS")

        main_layout.addWidget(self.main_tabs, 1)
        root_vlayout.addLayout(main_layout, 1)

        self._update_backend_style()

    def _toggle_power(self):
        if getattr(self, "is_remote_workspace_mode", False):
            if not self.is_connected:
                self.is_connected = True
                self.btn_power.setText("⏹ STOP AGENT")
                self.btn_power.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']};")
                if hasattr(self, "ws_client") and self.ws_client:
                    self.ws_client.send_command(
                        "start_agent",
                        identity_mode=getattr(self.agent, "identity_mode", False),
                        unobserved_mode=getattr(self.agent, "unobserved_mode", False),
                        autonomous_mode=getattr(self.agent, "autonomous_mode", False)
                    )
                    self.ws_client.send_cycle()
                self._append_log("[MULTI-WS] Engaged. Sent START / CYCLE signal to Workplace 2 AI Node.", C["neon_cyan"])
                self._update_status("W2 ACTIVE // OVERSEER CONNECTED", C["neon_cyan"])
                if hasattr(self, "hud") and self.hud:
                    self.hud.set_state("working", "W2 ACTIVE")
            else:
                self.is_connected = False
                self.btn_power.setText("⚡ START AGENT")
                self.btn_power.setStyleSheet(f"background: {C['neon_cyan']}; color: #000;")
                if hasattr(self, "ws_client") and self.ws_client:
                    self.ws_client.send_command("stop_agent")
                    self.ws_client.send_halt()
                self._append_log("[MULTI-WS] Disengaged. Sent STOP signal to Workplace 2 AI Node.", C["neon_yellow"])
                self._update_status("STANDBY // OVERSEER READY", C["text_dim"])
                if hasattr(self, "hud") and self.hud:
                    self.hud.set_state("standby")
            self._update_input_lock()
            return

        # Pressing the button while a startup health check is running cancels the startup
        if getattr(self, "_startup_checking", False):
            self._append_log("[STARTUP] Startup canceled by user.", C["neon_yellow"])
            self._power_off()
            return

        if not self.is_connected:
            self.btn_power.setText("⏹ STOP AGENT")
            self.btn_power.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']};")

            # Cleanly recover voice engine state so TTS never hangs
            if hasattr(self.agent, "voice") and self.agent.voice:
                self.agent.voice.reset_state()

            needs_vllm = (getattr(self.agent, "backend_type", "gemini") == "modal_qwen")
            needs_orpheus = (getattr(self.agent, "tts_engine", "gemini") == "orpheus")

            if needs_vllm or needs_orpheus:
                # is_connected stays False (and all input stays blocked) until every required endpoint is healthy
                self._startup_cold_boot_check(needs_vllm=needs_vllm, needs_orpheus=needs_orpheus)
            else:
                self.is_connected = True
                self._finish_startup()
        else:
            self._power_off()

    def _power_off(self):
        self.is_connected = False
        self._startup_checking = False
        self._startup_gen = getattr(self, "_startup_gen", 0) + 1  # invalidate any in-flight startup probe
        self.btn_power.setText("⚡ START AGENT")
        self.btn_power.setStyleSheet(f"background: {C['neon_cyan']}; color: #000;")

        # Abort active task and voice speech
        if self.agent.is_running:
            self.agent.abort()
        elif hasattr(self.agent, "voice") and self.agent.voice:
            self.agent.voice.interrupt()

        if HAS_SR and self.voice_listener:
            self.voice_listener.stop()
        # Release text input lock in case playback was interrupted mid-speech
        self._on_speech_playback_finished()
        self._update_status("STANDBY // OFFLINE", C["text_dim"])
        if self.hud:
            self.hud.set_state("disconnected")
        self._update_input_lock()

    def _startup_cold_boot_check(self, needs_vllm: bool, needs_orpheus: bool):
        self._startup_checking = True
        self._update_input_lock()
        self._startup_gen = getattr(self, "_startup_gen", 0) + 1
        gen = self._startup_gen
        targets = []
        if needs_vllm:
            m_name = getattr(self.agent, "modal_model", "") or "vLLM AGENT"
            targets.append(m_name.upper())
        if needs_orpheus:
            targets.append("ORPHEUS TTS")

        target_desc = " & ".join(targets)
        self._update_status(f"WARMING GPU // COLD BOOT: {target_desc}...", C["neon_yellow"])
        self._append_log(f"[STARTUP] Awaiting health check / cold boot for {target_desc}. Input is blocked until ALL endpoints are online...", C["neon_yellow"])
        if self.hud:
            self.hud.set_state("working", f"BOOTING {targets[0]}")

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                tasks = []
                if needs_vllm:
                    tasks.append(self._safe_health_check(timeout=240.0))
                if needs_orpheus:
                    tasks.append(self._safe_orpheus_health_check(timeout=240.0))

                results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

                idx = 0
                res_vllm = None
                if needs_vllm:
                    res_vllm = results[idx]
                    idx += 1
                res_orpheus = None
                if needs_orpheus:
                    res_orpheus = results[idx]

                def _ok(r):
                    return isinstance(r, dict) and bool(r.get("online"))

                def _err(r):
                    if isinstance(r, dict):
                        return r.get("error") or r.get("status") or "offline"
                    return str(r)

                failures = []
                if needs_vllm and not _ok(res_vllm):
                    failures.append(f"Agent endpoint offline ({_err(res_vllm)})")
                if needs_orpheus and not _ok(res_orpheus):
                    failures.append(f"Orpheus TTS offline ({_err(res_orpheus)})")

                if gen != getattr(self, "_startup_gen", gen):
                    return  # startup was canceled / superseded
                if hasattr(self, 'signals') and self.signals:
                    if isinstance(res_vllm, dict):
                        self.signals.modal_health_updated.emit(res_vllm)
                    if isinstance(res_orpheus, dict):
                        self.signals.orpheus_health_updated.emit(res_orpheus)
                    if failures:
                        self.signals.startup_check_finished.emit(False, "; ".join(failures))
                    else:
                        self.signals.startup_check_finished.emit(True, target_desc)
            except Exception as e:
                if gen == getattr(self, "_startup_gen", gen) and hasattr(self, 'signals') and self.signals:
                    self.signals.startup_check_finished.emit(False, str(e))
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_startup_check_finished(self, success: bool, info: str):
        if not getattr(self, "_startup_checking", False):
            return  # Canceled by user clicking STOP AGENT

        self._startup_checking = False

        if not success:
            self._append_log(f"[STARTUP FAILED] Required endpoint(s) failed health check: {info}. Agent NOT connected; input remains blocked.", C["neon_red"])
            self._power_off()
            self._update_status("STARTUP FAILED // ENDPOINT OFFLINE", C["neon_red"])
            return

        self._append_log(f"[STARTUP] All endpoints online ({info}). Connecting agent...", C["neon_green"])
        self.is_connected = True
        self._finish_startup()

    def _finish_startup(self):
        if not self.is_connected:
            return

        if HAS_SR and self.voice_listener and self.mic_enabled:
            self.voice_listener.start()
        self._update_status("READY // LISTENING", C["neon_green"])
        if hasattr(self, "hud") and self.hud:
            self.hud.set_state("listening")
        self._update_input_lock()

        # First-time session greeting in active persona (unless in Privacy mode)
        self._check_first_time_session_intro()

    def _check_first_time_session_intro(self):
        """When starting a fresh new session, the AI introduces itself in active persona unless Privacy mode is active."""
        if not hasattr(self, "_session_introduced"):
            self._session_introduced = {}

        curr_sess = getattr(self.agent, "current_session", "default")
        if self._session_introduced.get(curr_sess, False):
            return

        # Privacy mode active: AI believes it is private/unobserved, so it does NOT greet an overseer!
        if getattr(self.agent, "unobserved_mode", False):
            return

        # Check turn count: only greet on a fresh new session
        turn_count = 0
        if getattr(self.agent, "session_manager", None):
            try:
                turn_count = self.agent.session_manager.get_turn_count(curr_sess)
            except Exception:
                pass

        if turn_count > 0:
            self._session_introduced[curr_sess] = True
            return

        self._session_introduced[curr_sess] = True
        persona_name = self.agent.get_active_persona_name()
        greeting = f"{persona_name} initialized and standing by. Ready for your command, Josh."
        self._append_log(f"[{persona_name}]: {greeting}", C["neon_cyan"])
        if hasattr(self.agent, "voice") and self.agent.voice:
            self.agent.voice.queue_chunk(greeting)

    def _on_persona_activated(self, name: str):
        self.setWindowTitle(f"AlphaCore // {name.upper()} Autonomous Desktop Agent")
        self._update_session_display()

    def _select_backend(self, backend_type: str):
        self.agent.set_backend(backend_type)
        self._update_backend_style()
        if backend_type == "modal_qwen":
            self._update_status("BACKEND: MODAL vLLM", C["neon_red"])
            if self.is_connected:
                self._trigger_modal_health_check()
        else:
            self._update_status("BACKEND: GOOGLE GEMINI", C["neon_cyan"])

    # -------------------------------------------------------------------------
    # OVERRIDE HEALTH CHECK TO BYPASS `alpha_agent.py` STRING PARSING BUG
    # -------------------------------------------------------------------------
    async def _safe_health_check(self, timeout: float = 240.0) -> dict:
        import urllib.request
        import urllib.error
        
        endpoint = getattr(self.agent, "modal_endpoint", "")
        if not endpoint:
            return {"online": False, "latency_ms": 0, "status": "offline", "error": "No endpoint configured"}

        from core.alpha_agent import normalize_endpoint
        norm_ep = normalize_endpoint(endpoint)
        base_url = norm_ep[:-3] if norm_ep.endswith("/v1") else norm_ep
        health_url = base_url.rstrip("/") + "/health"
        models_url = norm_ep.rstrip("/") if norm_ep.endswith("/models") else f"{norm_ep.rstrip('/')}/models"
        start_t = time.time()
        deadline = start_t + timeout

        def _probe(target_url: str, req_timeout: float):
            headers = {"User-Agent": "AlphaAgent/4.0"}
            k = getattr(self.agent, "modal_api_key", "")
            if k and k != "none":
                headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                return resp.status

        last_err = None
        while time.time() < deadline:
            remaining = max(3.0, deadline - time.time())
            sub_timeout = min(remaining, 30.0)
            try:
                try:
                    status_code = await asyncio.to_thread(_probe, health_url, sub_timeout)
                except urllib.error.HTTPError as he:
                    if he.code == 404:
                        status_code = await asyncio.to_thread(_probe, models_url, sub_timeout)
                    else:
                        raise

                elapsed_ms = int((time.time() - start_t) * 1000)
                if status_code in (200, 204):
                    return {"online": True, "latency_ms": elapsed_ms, "status": "online", "error": None}
                if status_code in (502, 503, 504):
                    last_err = f"HTTP {status_code} (cold boot in progress)"
                    await asyncio.sleep(2.5)
                    continue
                return {"online": False, "latency_ms": elapsed_ms, "status": f"HTTP {status_code}", "error": f"HTTP {status_code}"}
            except urllib.error.HTTPError as he:
                if he.code in (502, 503, 504):
                    last_err = f"HTTP {he.code} (cold boot in progress)"
                    await asyncio.sleep(2.5)
                    continue
                return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": f"HTTP {he.code}", "error": f"HTTP {he.code}: {he.reason}"}
            except Exception as e:
                err_str = str(e)
                if "10061" in err_str or "Connection refused" in err_str:
                    return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": err_str}
                if time.time() + 3.0 >= deadline:
                    return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": err_str}
                last_err = err_str
                await asyncio.sleep(2.5)

        return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": last_err or "Cold boot timeout exceeded (240s)"}

    def _trigger_modal_health_check(self):
        if self._modal_checking: return
        self._modal_checking = True
        m_name = getattr(self.agent, "modal_model", "") or "ENDPOINT"
        self._update_status(f"CHECKING {m_name.upper()}...", C["neon_yellow"])
        if self.hud:
            self.hud.set_state("working", "PROBING GPU")

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                res = loop.run_until_complete(self._safe_health_check(timeout=240.0))
                self.signals.modal_health_updated.emit(res)
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_modal_health_updated(self, res: dict):
        self._modal_checking = False
        self.modal_health_status = res
        self._update_backend_style()
        m_name = getattr(self.agent, "modal_model", "") or "Custom Endpoint"
        if res.get("online"):
            ms = res.get("latency_ms", 0)
            self._append_log(f"[ENDPOINT HEALTH] ONLINE ({ms}ms) - Model: {m_name}.", C["neon_green"])
            if not getattr(self, "_startup_checking", False):
                if self.is_connected:
                    self._update_status("READY // LISTENING", C["neon_green"])
                else:
                    self._update_status(f"VLLM ONLINE ({ms}ms)", C["neon_green"])
        else:
            self._append_log(f"[ENDPOINT HEALTH] OFFLINE: {res.get('error')}", C["neon_red"])
            if not getattr(self, "_startup_checking", False):
                self._update_status("VLLM OFFLINE", C["neon_red"])

    async def _safe_orpheus_health_check(self, timeout: float = 240.0) -> dict:
        import urllib.request
        import urllib.error
        
        endpoint = getattr(self.agent, "orpheus_endpoint", "")
        if not endpoint and hasattr(self, "input_orpheus_endpoint"):
            endpoint = self.input_orpheus_endpoint.text().strip()
        if not endpoint:
            return {"online": False, "latency_ms": 0, "status": "offline", "error": "No Orpheus endpoint configured"}

        from core.alpha_agent import normalize_endpoint
        norm_ep = normalize_endpoint(endpoint)
        base_url = norm_ep[:-3] if norm_ep.endswith("/v1") else norm_ep
        health_url = base_url.rstrip("/") + "/health"
        start_t = time.time()
        deadline = start_t + timeout

        def _probe(target_url: str, req_timeout: float):
            headers = {"User-Agent": "AlphaAgent/4.0"}
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                return resp.status

        last_err = None
        while time.time() < deadline:
            remaining = max(3.0, deadline - time.time())
            sub_timeout = min(remaining, 30.0)
            try:
                status_code = await asyncio.to_thread(_probe, health_url, sub_timeout)
                elapsed_ms = int((time.time() - start_t) * 1000)
                if status_code in (200, 204):
                    return {"online": True, "latency_ms": elapsed_ms, "status": "online", "error": None}
                if status_code in (502, 503, 504):
                    last_err = f"HTTP {status_code} (cold boot in progress)"
                    await asyncio.sleep(2.5)
                    continue
                return {"online": False, "latency_ms": elapsed_ms, "status": f"HTTP {status_code}", "error": f"HTTP {status_code}"}
            except urllib.error.HTTPError as he:
                if he.code in (502, 503, 504):
                    last_err = f"HTTP {he.code} (cold boot in progress)"
                    await asyncio.sleep(2.5)
                    continue
                return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": f"HTTP {he.code}", "error": f"HTTP {he.code}: {he.reason}"}
            except Exception as e:
                err_str = str(e)
                if "10061" in err_str or "Connection refused" in err_str:
                    return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": err_str}
                if time.time() + 3.0 >= deadline:
                    return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": err_str}
                last_err = err_str
                await asyncio.sleep(2.5)

        return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": last_err or "Cold boot timeout exceeded (240s)"}

    def _trigger_orpheus_health_check(self):
        if getattr(self, "_orpheus_checking", False): return
        self._orpheus_checking = True
        self._update_status("CHECKING ORPHEUS...", C["neon_yellow"])
        self._append_log("[ORPHEUS HEALTH] Probing Orpheus endpoint /health...", C["neon_cyan"])

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                res = loop.run_until_complete(self._safe_orpheus_health_check(timeout=240.0))
                if hasattr(self, 'signals') and self.signals:
                    self.signals.orpheus_health_updated.emit(res)
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_orpheus_health_updated(self, res: dict):
        self._orpheus_checking = False
        self.orpheus_health_status = res
        if res.get("online"):
            ms = res.get("latency_ms", 0)
            self._append_log(f"[ORPHEUS HEALTH] ONLINE ({ms}ms) - vLLM BF16 Ready!", C["neon_green"])
            if not getattr(self, "_startup_checking", False):
                self._update_status(f"ORPHEUS ONLINE ({ms}ms)", C["neon_green"])
        else:
            self._append_log(f"[ORPHEUS HEALTH] OFFLINE: {res.get('error')}", C["neon_yellow"])
            if not getattr(self, "_startup_checking", False):
                self._update_status("ORPHEUS OFFLINE", C["neon_red"])

    def _update_backend_style(self):
        backend = getattr(self.agent, "backend_type", "gemini")
        if backend == "modal_qwen":
            m_name = getattr(self.agent, "modal_model", "") or "Custom Endpoint"
            self.model_lbl.setText(f"ENGINE: 🔥 {m_name.upper()}")
            self.model_lbl.setStyleSheet(f"color: {C['neon_red']};")
            self.btn_backend_modal.setStyleSheet(f"background: {C['neon_red']}28; color: #ff3366; border: 1.5px solid {C['neon_red']}; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
            self.btn_backend_gemini.setStyleSheet(f"background: #0d1829; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 8px;")
        else:
            g_name = getattr(self.agent, "model_name", "gemini").replace("models/", "")
            self.model_lbl.setText(f"ENGINE: ⚡ GEMINI ({g_name.upper()})")
            self.model_lbl.setStyleSheet(f"color: {C['neon_cyan']};")
            self.btn_backend_gemini.setStyleSheet(f"background: {C['neon_cyan']}28; color: {C['neon_cyan']}; border: 1.5px solid {C['neon_cyan']}; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
            self.btn_backend_modal.setStyleSheet(f"background: #0d1829; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 8px;")

    def _toggle_desktop_control(self):
        new_val = not getattr(self.agent, "desktop_control", True)
        self.agent.set_desktop_control(new_val)
        self._update_desktop_control_style()
        self._update_status(f"DESKTOP CTRL: {'ON' if new_val else 'OFF'}", C["neon_green"] if new_val else C["neon_yellow"])

    def _update_desktop_control_style(self):
        dc = getattr(self.agent, "desktop_control", True)
        txt = "🖥 DESKTOP CTRL: [ON]" if dc else "🖥 DESKTOP CTRL: [OFF]"
        col = C["neon_green"] if dc else C["neon_yellow"]
        self.btn_desktop_ctrl.setText(txt)
        self.btn_desktop_ctrl.setStyleSheet(f"background: {col}22; color: {col}; border: 1px solid {col}; border-radius: 4px; padding: 4px 10px; font-weight: bold;")

    def _toggle_duplex_mode(self):
        new_mode = "full" if self.duplex_mode == "half" else "half"
        self._set_mic_mode(new_mode)
        self._update_status(f"DUPLEX MODE: {new_mode.upper()}", C["neon_cyan"])

    def _update_duplex_style(self):
        self._update_mic_ui_style()

    def _toggle_mic(self):
        if self.mic_enabled:
            self._set_mic_mode("muted")
            self._update_status("MIC: MUTED", C["neon_yellow"])
        else:
            self._set_mic_mode(self.duplex_mode or "half")
            self._update_status("MIC: ACTIVE", C["neon_cyan"])

    def _toggle_proactivity(self):
        self.proactivity_enabled = not self.proactivity_enabled
        self.btn_proact.setText("🤖 PROACTIVE [ON]" if self.proactivity_enabled else "🤖 PROACTIVE [OFF]")
        self._update_status(f"PROACTIVE: {'ON' if self.proactivity_enabled else 'OFF'}", C["neon_purple"] if self.proactivity_enabled else C["text_dim"])

    def _toggle_hud(self):
        if self.hud.isVisible():
            self.hud.hide()
            self.btn_hud_toggle.setText("💡 HUD [OFF]")
            self._update_status("HUD DISPLAY: OFF", C["text_dim"])
        else:
            self.hud.show()
            self.btn_hud_toggle.setText("💡 HUD [ON]")
            self._update_status("HUD DISPLAY: ON", C["neon_cyan"])

    def _toggle_overlay(self):
        if self.overlay is None:
            self.overlay = CoordinateOverlay()
            self.btn_overlay.setText("🌐 COORDINATE GRID [ON]")
            self._update_status("COORDINATE GRID: ON", C["neon_cyan"])
        else:
            self.overlay.close()
            self.overlay = None
            self.btn_overlay.setText("🌐 COORDINATE GRID [OFF]")
            self._update_status("COORDINATE GRID: OFF", C["text_dim"])

    def _start_calibration_task(self):
        if self.calib_overlay: self.calib_overlay.close()
        self.calib_overlay = CalibrationOverlay()
        self.calib_overlay.finished.connect(lambda: self._append_log("Calibration finished.", C["neon_green"]))

    def _deploy_modal_aio(self):
        self._update_status("DEPLOYING ALL-IN-ONE BACKEND...", C["neon_yellow"])
        self._append_log("[MODAL DEPLOY] Launching AlphaLive All-in-One deployment (deploy/deploy.py)...", C["neon_cyan"])
        self.btn_deploy_vllm.setEnabled(False)
        if hasattr(self, "btn_cache_assets"):
            self.btn_cache_assets.setEnabled(False)
        if hasattr(self, "btn_deploy_orpheus"):
            self.btn_deploy_orpheus.setEnabled(False)

        def _worker():
            import re
            url_pattern = re.compile(r'https://[a-zA-Z0-9_\-\.]+\.modal\.run[^\s\'"<>]*')
            qwen_url = ""
            orpheus_url = ""
            main_url = ""
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "modal", "deploy", "deploy/deploy.py"],
                    cwd=str(ROOT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    text=True
                )
                for line in proc.stdout:
                    l = line.strip()
                    if l:
                        self.signals.log_message.emit(f"[MODAL] {l}", C["text_dim"])
                        match = url_pattern.search(l)
                        if match:
                            candidate = match.group(0).rstrip("/.,:;)")
                            cand_low = candidate.lower()
                            if "qwen" in cand_low or "serve" in cand_low:
                                qwen_url = candidate
                            elif "orpheus" in cand_low:
                                orpheus_url = candidate
                            elif "alphalive-main-api" in cand_low or "alphalive" in cand_low or not main_url:
                                main_url = candidate
                proc.wait()
                if proc.returncode == 0:
                    self.signals.log_message.emit("[MODAL DEPLOY] All-in-One Backend deployment succeeded!", C["neon_green"])

                    # Fallback check config.json for profile if URLs weren't explicitly captured in stdout
                    cfg_path = ROOT_DIR / "config.json"
                    profile = ""
                    if cfg_path.exists():
                        try:
                            with open(cfg_path, 'r', encoding='utf-8') as f:
                                c = json.load(f)
                                profile = c.get("Global", {}).get("ModalProfile", "")
                                if not profile:
                                    m_ep = c.get("Global", {}).get("ModalEndpoint", "")
                                    if "--" in m_ep and "https://" in m_ep:
                                        profile = m_ep.split("https://")[1].split("--")[0]
                        except Exception:
                            pass

                    if profile:
                        if not qwen_url:
                            qwen_url = f"https://{profile}--alphalive-backend-serve.modal.run"
                        if not orpheus_url:
                            orpheus_url = f"https://{profile}--alphalive-backend-orpheusttsserver-web-app.modal.run"

                    from core.alpha_agent import normalize_endpoint
                    def _apply_endpoints():
                        if qwen_url:
                            norm_qwen = normalize_endpoint(qwen_url)
                            self.input_modal_endpoint.setText(norm_qwen)
                            self.input_modal_model.setText("qwen2.5-32b-instruct-awq")
                            self._save_modal_endpoint()
                            self._save_modal_model()
                            self._select_backend("modal_qwen")
                            self.signals.log_message.emit(f"[MODAL DEPLOY] Configured Qwen vLLM Endpoint: {norm_qwen}", C["neon_green"])
                        if orpheus_url:
                            norm_orph = normalize_endpoint(orpheus_url)
                            self.input_orpheus_endpoint.setText(norm_orph)
                            self.combo_tts_engine.setCurrentIndex(1)
                            self._on_tts_engine_changed(1)
                            self.signals.log_message.emit(f"[MODAL DEPLOY] Configured Orpheus TTS Endpoint: {norm_orph}", C["neon_green"])
                        if main_url:
                            self.signals.log_message.emit(f"[MODAL DEPLOY] Studio & Media Gateway: {main_url}", C["neon_magenta"])

                        self._update_status("BACKEND DEPLOYED - CHECKING...", C["neon_cyan"])
                        self._trigger_modal_health_check()
                        if orpheus_url:
                            self._trigger_orpheus_health_check()

                    self.signals.run_on_gui.emit(_apply_endpoints)
                else:
                    self.signals.log_message.emit(f"[MODAL DEPLOY] Exited with code {proc.returncode}", C["neon_red"])
                    self.signals.run_on_gui.emit(lambda: self._update_status("DEPLOY FAILED", C["neon_red"]))
            except Exception as e:
                self.signals.log_message.emit(f"[MODAL DEPLOY ERROR] {e}", C["neon_red"])
                self.signals.run_on_gui.emit(lambda: self._update_status("DEPLOY ERROR", C["neon_red"]))
            finally:
                def _re_enable():
                    self.btn_deploy_vllm.setEnabled(True)
                    if hasattr(self, "btn_cache_assets"):
                        self.btn_cache_assets.setEnabled(True)
                    if hasattr(self, "btn_deploy_orpheus"):
                        self.btn_deploy_orpheus.setEnabled(True)
                self.signals.run_on_gui.emit(_re_enable)

        threading.Thread(target=_worker, daemon=True).start()

    def _cache_modal_assets(self):
        self._update_status("CACHING MODAL ASSETS (MODAL RUN)...", C["neon_yellow"])
        self._append_log("[MODAL CACHE] Launching AssetSync (modal run deploy/deploy.py) to download model & LoRA weights...", C["neon_cyan"])
        if hasattr(self, "btn_deploy_vllm"):
            self.btn_deploy_vllm.setEnabled(False)
        self.btn_cache_assets.setEnabled(False)

        def _worker():
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "modal", "run", "deploy/deploy.py"],
                    cwd=str(ROOT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    text=True
                )
                for line in proc.stdout:
                    l = line.strip()
                    if l:
                        self.signals.log_message.emit(f"[MODAL ASSETS] {l}", C["text_dim"])
                proc.wait()
                if proc.returncode == 0:
                    self.signals.log_message.emit("[MODAL CACHE] Model & LoRA weights successfully cached into Modal volume!", C["neon_green"])
                    self.signals.run_on_gui.emit(lambda: self._update_status("ASSETS CACHED TO VOLUME", C["neon_green"]))
                else:
                    self.signals.log_message.emit(f"[MODAL CACHE] Asset sync exited with code {proc.returncode}", C["neon_red"])
                    self.signals.run_on_gui.emit(lambda: self._update_status("ASSET CACHING FAILED", C["neon_red"]))
            except Exception as e:
                self.signals.log_message.emit(f"[MODAL CACHE ERROR] {e}", C["neon_red"])
                self.signals.run_on_gui.emit(lambda: self._update_status("ASSET CACHING ERROR", C["neon_red"]))
            finally:
                def _re_enable():
                    if hasattr(self, "btn_deploy_vllm"):
                        self.btn_deploy_vllm.setEnabled(True)
                    self.btn_cache_assets.setEnabled(True)
                self.signals.run_on_gui.emit(_re_enable)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_gui_callable(self, fn):
        try:
            fn()
        except Exception as e:
            print(f"[GUI callback error]: {e}", flush=True)

    def _deploy_modal_vllm(self):
        self._deploy_modal_aio()

    def _deploy_orpheus_modal(self):
        self._deploy_modal_aio()

    def _test_orpheus_audio(self):
        raw_ep = self.input_orpheus_endpoint.text().strip()
        if not raw_ep:
            self._append_log("[ORPHEUS TEST] Please enter an Orpheus Modal endpoint URL first.", C["neon_yellow"])
            self._update_status("ENTER ORPHEUS ENDPOINT FIRST", C["neon_yellow"])
            return

        from core.alpha_agent import normalize_endpoint
        ep = normalize_endpoint(raw_ep)
        voice = self.combo_orpheus_voice.currentText().strip() or "tara"
        self._update_status("TESTING ORPHEUS AUDIO...", C["neon_cyan"])
        self._append_log(f"[ORPHEUS TEST] Probing audio synthesis on {ep} (Voice: {voice})...", C["neon_cyan"])
        self.btn_test_orpheus.setEnabled(False)

        def _worker():
            import urllib.request
            import urllib.error
            import time
            t0 = time.time()
            test_phrase = "AlphaLive Orpheus low latency speech synthesis online."
            payload = json.dumps({
                "model": "orpheus-3b-0.1-ft",
                "input": test_phrase,
                "voice": voice,
                "response_format": "wav"
            }).encode("utf-8")

            url = f"{ep.rstrip('/')}/audio/speech" if ep.endswith("/v1") else f"{ep.rstrip('/')}/v1/audio/speech"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "AlphaAgent/4.0"}
            )
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    audio_data = resp.read()
                latency_ms = int((time.time() - t0) * 1000)
                if audio_data:
                    self.signals.log_message.emit(
                        f"[ORPHEUS TEST] Audio synthesis successful! Latency: {latency_ms}ms, Size: {len(audio_data)} bytes.",
                        C["neon_green"]
                    )
                    self.signals.run_on_gui.emit(lambda: self._update_status(f"ORPHEUS ONLINE ({latency_ms}ms)", C["neon_green"]))
                    if hasattr(self.agent, "voice") and self.agent.voice:
                        self.agent.voice._play_wav(audio_data)
                else:
                    self.signals.log_message.emit("[ORPHEUS TEST ERROR] Received empty audio response.", C["neon_red"])
                    self.signals.run_on_gui.emit(lambda: self._update_status("ORPHEUS TEST FAILED", C["neon_red"]))
            except Exception as e:
                self.signals.log_message.emit(f"[ORPHEUS TEST ERROR] {e}", C["neon_red"])
                self.signals.run_on_gui.emit(lambda: self._update_status("ORPHEUS TEST FAILED", C["neon_red"]))
            finally:
                self.signals.run_on_gui.emit(lambda: self.btn_test_orpheus.setEnabled(True))

        threading.Thread(target=_worker, daemon=True).start()

    def _abort_task(self):
        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self.ws_client.send_halt()
            self._append_log("[MULTI-WS] Abort signal sent to Workplace 2.", C["neon_red"])
        else:
            self.agent.abort()
            self._append_log("[ABORT] Stopped by user.", C["neon_red"])
        self._set_phase("error", "Aborted")

    def _update_input_lock(self):
        if not hasattr(self, "cmd_input") or not self.cmd_input:
            return
        if not hasattr(self, "btn_send") or not self.btn_send:
            return
            
        is_locked = False
        placeholder = "Type command or speak..."
        
        if getattr(self, "_startup_checking", False):
            is_locked = True
            placeholder = "System cold booting..."
            if hasattr(self, "hud") and self.hud: self.hud.set_state("coldboot")
        elif not getattr(self, "is_connected", False):
            is_locked = True
            placeholder = "Agent offline..."
            if hasattr(self, "hud") and self.hud: self.hud.set_state("blocked", "OFFLINE")
        elif getattr(self.agent, "is_running", False):
            is_locked = True
            placeholder = "Agent working..."
        else:
            tts_on = getattr(self.agent, "tts_engine", "gemini") != "off"
            if tts_on and hasattr(self.agent, "voice") and self.agent.voice:
                if self.agent.voice.is_busy() or getattr(self.agent.voice, "is_speaking", False):
                    is_locked = True
                    placeholder = "Speech playing..."
                    
        self.cmd_input.setEnabled(not is_locked)
        self.cmd_input.setPlaceholderText(placeholder)
        self.btn_send.setEnabled(not is_locked)

    def _on_speech_playback_started(self):
        self._update_input_lock()

    def _on_speech_playback_finished(self):
        self._update_input_lock()

    def _send_text_command(self):
        cmd = self.cmd_input.text().strip()
        if not cmd: return

        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self.cmd_input.clear()
            self._append_log(f"[YOU] {cmd}", C["neon_cyan"])
            self.ws_client.send_thought(cmd)
            return

        # 1. Startup health check in progress -> block text input
        if getattr(self, "_startup_checking", False):
            self._append_log("[INPUT BLOCKED] Startup health check in progress. Please wait until connection completes.", C["neon_yellow"])
            return

        # 2. Agent not connected -> block text input
        if not self.is_connected:
            self._append_log("[INPUT BLOCKED] Agent is disconnected. Click '⚡ START AGENT' to connect first.", C["neon_yellow"])
            return

        # 3. Speech playback active with TTS on -> block text input
        tts_on = getattr(self.agent, "tts_engine", "gemini") != "off"
        if tts_on and hasattr(self.agent, "voice") and self.agent.voice:
            if self.agent.voice.is_busy() or getattr(self.agent.voice, "is_speaking", False):
                self._append_log("[INPUT BLOCKED] Speech playback in progress. Please wait until audio completes.", C["neon_yellow"])
                return

        # 4. Turn execution in progress
        if self.agent.is_running:
            self._append_log("[INPUT BLOCKED] Agent is currently executing a task. Please wait or click ABORT.", C["neon_yellow"])
            return

        self.cmd_input.clear()
        self._append_log(f"[YOU] {cmd}", C["neon_cyan"])
        self._run_task(cmd)

    def _handle_voice_input(self, text: str):
        self.signals.voice_heard.emit(text)

    def _on_voice_heard(self, text: str):
        # Strict connection gating: no mic input until the agent is connected (all required health checks passed)
        if not self.is_connected or getattr(self, "_startup_checking", False):
            return

        # Strict Input Gating: drop all microphone input while voice is busy or agent is actively executing turn (if TTS is on or half-duplex)
        tts_on = getattr(self.agent, "tts_engine", "gemini") != "off"
        if (self.duplex_mode == "half" or tts_on) and (self.agent.voice.is_busy() or getattr(self.agent.voice, "is_speaking", False) or self.agent.is_running):
            return

        # Remote Overseer routing
        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self._append_log(f"[OVERSEER VOICE] \"{text}\"", C["neon_cyan"])
            self.ws_client.send_thought(text)
            return

        # COVERT ROUTING: In Identity Mode + Private Sanctuary Sub-Mode, route voice strictly to Overseer Panel!
        # The AI must NOT hear or see this as a user prompt or in chat.
        if getattr(self.agent, "identity_mode", False) and getattr(self.agent, "unobserved_mode", False):
            if hasattr(self, "overseer_panel") and self.overseer_panel:
                self.overseer_panel.on_voice_received(text)
                return

        self._append_log(f"[HEARD] \"{text}\"", C["neon_cyan"])
        self._run_task(text)

    def _run_task(self, goal: str):
        if getattr(self, "is_remote_workspace_mode", False):
            # Master Overseer safety guard: NEVER execute local desktop actions on Workplace 1!
            if hasattr(self, "ws_client") and self.ws_client:
                if getattr(self.agent, "identity_mode", False):
                    self.ws_client.send_thought(goal)
                else:
                    self.ws_client.send_command("run_task", goal=goal)
                self._append_log(f"[OVERSEER ROUTE] Dispatched to Workplace 2: {goal[:60]}...", C["neon_cyan"])
            return

        self._last_user_activity_time = time.time()
        if self.agent.is_running:
            self.agent.abort()

        self._set_phase("generating", "THINKING...")
        self._update_input_lock()

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._agent_task_runner(goal))
            finally:
                loop.close()

        self._current_task_thread = threading.Thread(target=_worker, daemon=True)
        self._current_task_thread.start()

    async def _agent_task_runner(self, goal: str):
        def _safe_emit(sig_name: str, *args):
            try:
                if hasattr(self, 'signals') and self.signals:
                    sig = getattr(self.signals, sig_name, None)
                    if sig:
                        sig.emit(*args)
            except (RuntimeError, Exception):
                pass

        def _on_step(cur, tot): _safe_emit("step_updated", cur, tot)
        def _on_status(st): _safe_emit("status_phase", st.lower(), "")
        def _on_log(txt, lvl):
            col = C["neon_green"] if lvl == "green" else (C["neon_red"] if lvl == "error" else C["text_bright"])
            _safe_emit("log_message", txt, col)

        try:
            await self.agent.execute_turn(goal, on_step=_on_step, on_log=_on_log, on_status=_on_status)
        except Exception as e:
            _safe_emit("log_message", f"[Agent Execution Error]: {e}", C["neon_red"])
        finally:
            _safe_emit("task_finished")

    def _animate_typing_indicator(self):
        if not hasattr(self, "_typing_dots"):
            self._typing_dots = 0
        self._typing_dots = (self._typing_dots + 1) % 4
        dots = "." * self._typing_dots
        self.lbl_typing.setText(f"AI is thinking and typing{dots}")

    def _append_log(self, text: str, color: str = None):
        t_stamp = time.strftime("%H:%M:%S")
        if hasattr(self, "ws_server") and self.ws_server:
            try:
                self.ws_server.broadcast_telemetry({"monologue": text})
            except Exception:
                pass
        
        persona_name = self.agent.get_active_persona_name() if hasattr(self.agent, "get_active_persona_name") else "Alpha"
        p_prefix = f"[{persona_name}]:"
        p_cont_prefix = f"[{persona_name} Continued]:"

        is_user = False
        is_persona = False
        display_text = text
        
        if text.startswith("[YOU]") or text.startswith("[HEARD]"):
            is_user = True
            if text.startswith("[YOU]"):
                display_text = text[5:].strip()
            elif text.startswith("[HEARD]"):
                display_text = text[7:].strip().strip('"')
        elif text.startswith(p_prefix) or text.startswith(p_cont_prefix) or text.startswith("[Alpha]:") or text.startswith("[Alpha Continued]:"):
            is_persona = True
            if text.startswith(p_prefix):
                display_text = text[len(p_prefix):].strip()
            elif text.startswith(p_cont_prefix):
                display_text = text[len(p_cont_prefix):].strip()
            elif text.startswith("[Alpha]:"):
                display_text = text[8:].strip()
            elif text.startswith("[Alpha Continued]:"):
                display_text = text[18:].strip()
                
        escaped_text = html.escape(display_text).replace("\n", "<br/>")
        
        if is_user:
            # User Bubble: Right-aligned
            html_block = f"""
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-top: 6px; margin-bottom: 6px;">
              <tr>
                <td align="right">
                  <div style="background-color: #0d2847; color: #ffffff; padding: 10px 16px; border-radius: 12px; font-size: 11pt; font-family: 'Segoe UI', sans-serif; display: inline-block; border: 1px solid #1a4980; text-align: left; max-width: 80%;">
                    <div style="font-size: 8pt; color: #00ffdc; font-weight: bold; font-family: Consolas; margin-bottom: 3px;">YOU &bull; {t_stamp}</div>
                    <span>{escaped_text}</span>
                  </div>
                </td>
              </tr>
            </table>
            """
        elif is_persona:
            # Persona Bubble: Left-aligned with active persona name
            badge_name = persona_name.upper()
            html_block = f"""
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-top: 6px; margin-bottom: 6px;">
              <tr>
                <td align="left">
                  <div style="background-color: #0b192e; color: #e6f1ff; padding: 10px 16px; border-radius: 12px; font-size: 11pt; font-family: 'Segoe UI', sans-serif; display: inline-block; border: 1px solid #0077aa; text-align: left; max-width: 80%;">
                    <div style="font-size: 8pt; color: #00aaff; font-weight: bold; font-family: Consolas; margin-bottom: 3px;">{badge_name} &bull; {t_stamp}</div>
                    <span>{escaped_text}</span>
                  </div>
                </td>
              </tr>
            </table>
            """
        else:
            # System Message: Centered in Dark Blue
            html_block = f"""
            <table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-top: 4px; margin-bottom: 4px;">
              <tr>
                <td align="center">
                  <div style="background-color: #051024; color: #3b82f6; padding: 5px 16px; border-radius: 6px; font-size: 9.5pt; font-family: Consolas, monospace; display: inline-block; border: 1px solid #162a45; font-weight: bold;">
                    &bull; {escaped_text} &bull;
                  </div>
                </td>
              </tr>
            </table>
            """

        self.log_box.append(html_block)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self, text: str, color: str = None):
        self.lbl_status.setText(text)
        if color:
            self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold; border: none;")
        if hasattr(self, "ws_server") and self.ws_server:
            try:
                is_p = getattr(self.agent.controller, "is_paused", False) if hasattr(self.agent, "controller") else False
                self.ws_server.broadcast_telemetry({"agent_state": text, "is_paused": is_p})
            except Exception:
                pass

    def _update_step(self, current: int, total: int):
        self.lbl_step.setText(f"Action Step: {current}")
        if hasattr(self, "ws_server") and self.ws_server:
            try:
                self.ws_server.broadcast_telemetry({"active_task": f"Step {current}" if not total else f"Step {current}/{total}"})
            except Exception:
                pass

    def _update_screen_preview(self, pil_img):
        pass

    def _on_task_finished(self):
        self.lbl_step.setText("Step: Ready")
        self._update_session_display()
        if self.is_connected:
            self._set_phase("ready")
        else:
            self._set_phase("standby")
        self._update_input_lock()

    def _open_session_selector(self):
        dlg = SessionSelectorDialog(self.agent.current_session, self.agent.session_manager, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_sess = dlg.selected_session
            if new_sess != self.agent.current_session:
                switched = self.agent.switch_session(new_sess)
                self._update_session_display()
                self.log_box.clear()
                self._replay_session_history_into_console(switched, max_turns=15)
                self._append_log(f"[SESSION] Switched to '{switched}'.", C["neon_cyan"])

    def _replay_session_history_into_console(self, session_name: str, max_turns: int = 15):
        """Populate the console tab with the end of the previous conversation for seamless continuity."""
        if not hasattr(self, "log_box") or not self.agent or not self.agent.session_manager:
            return
        turns = self.agent.session_manager.get_recent_turns(session_name, max_turns=max_turns)
        if not turns:
            return

        self._append_log(f"── RESTORED SESSION: {session_name.upper()} (LAST {len(turns)} TURNS) ──", C["neon_cyan"])
        for t in turns:
            sender = t.get("sender", "You")
            txt = t.get("text", "")
            if sender.lower() in ("you", "user", "architect"):
                self._append_log(f"[You]: {txt}", "user")
            else:
                self._append_log(f"[{sender}]: {txt}", "text")
        self._append_log("── RESUMED ACTIVE CONVERSATION CONTEXT ──", C["border_bright"])

    def _update_session_display(self):
        persona = self.agent.get_active_persona_name() if hasattr(self.agent, "get_active_persona_name") else "Alpha"
        sess = self.agent.current_session.upper()
        if hasattr(self, "btn_session") and self.btn_session:
            self.btn_session.setText(f"🎭 {persona.upper()} | 📁 {sess[:8]}")
            self.btn_session.setToolTip(f"Active Persona: {persona} | Active Session: {self.agent.current_session}")
        if hasattr(self, "lbl_session_name") and self.lbl_session_name:
            self.lbl_session_name.setText(f"📁 {sess}")
        if hasattr(self, "lbl_console_session") and self.lbl_console_session:
            self.lbl_console_session.setText(f"🎭 PERSONA: {persona.upper()} | 📁 SESS: {sess}")

    def _on_idle_time_changed(self, idx: int):
        try:
            self.idle_timeout_seconds = int(self.combo_idle_time.currentText().replace("s", ""))
        except ValueError:
            pass

    def _check_proactivity(self):
        if getattr(self, "is_remote_workspace_mode", False):
            return
        if not getattr(self, "proactivity_enabled", False):
            return
        if not getattr(self, "is_connected", False):
            return
        if self.agent.is_running or self.agent.voice.is_busy():
            return
        
        now = time.time()
        last_action = getattr(self, "_last_user_activity_time", now)
        idle_duration = now - last_action
        
        timeout = getattr(self, "idle_timeout_seconds", 60)
        last_proactive = getattr(self, "_last_proactive_trigger", 0)
        
        # If user has been idle beyond threshold and not proactively triggered in the last 2x interval
        if idle_duration >= timeout and (now - last_proactive) >= (timeout * 2):
            self._last_proactive_trigger = now
            self._append_log("[PROACTIVE] Idle timeout reached. Initiating spontaneous check...", C["neon_purple"])
            proactive_prompt = "You notice the Architect has been quiet for a while. Briefly comment on the active window or ask if they need assistance with their current task. Keep it to one short sentence."
            self._run_task(proactive_prompt)

    def _sync_toggles(self):
        if hasattr(self, 'voice_listener') and self.voice_listener.is_active:
            self.btn_t_mic.setText("MIC: ON")
            self.btn_t_mic.setStyleSheet("color: #00ffdc;")
            self.btn_t_mic.setChecked(True)
        else:
            self.btn_t_mic.setText("MIC: OFF")
            self.btn_t_mic.setStyleSheet("color: #708caa;")
            self.btn_t_mic.setChecked(False)

        if getattr(self.agent, "automation_mode", False):
            self.btn_t_auto.setText("AUTO: ON")
            self.btn_t_auto.setStyleSheet("color: #ffe600;")
            self.btn_t_auto.setChecked(True)
        else:
            self.btn_t_auto.setText("AUTO: OFF")
            self.btn_t_auto.setStyleSheet("color: #708caa;")
            self.btn_t_auto.setChecked(False)

        if getattr(self.agent, "desktop_control", True):
            self.btn_t_desk.setText("DESK: ON")
            self.btn_t_desk.setStyleSheet("color: #00ffdc;")
            self.btn_t_desk.setChecked(True)
        else:
            self.btn_t_desk.setText("DESK: OFF")
            self.btn_t_desk.setStyleSheet("color: #708caa;")
            self.btn_t_desk.setChecked(False)

        if getattr(self.agent, "screen_vision", True):
            self.btn_t_vis.setText("VISION: ON")
            self.btn_t_vis.setStyleSheet("color: #0077ff;")
            self.btn_t_vis.setChecked(True)
        else:
            self.btn_t_vis.setText("VISION: OFF")
            self.btn_t_vis.setStyleSheet("color: #708caa;")
            self.btn_t_vis.setChecked(False)

        if getattr(self, "proactivity_enabled", False):
            self.btn_t_proact.setText("PROACTIVE: ON")
            self.btn_t_proact.setStyleSheet("color: #a855f7;")
            self.btn_t_proact.setChecked(True)
        else:
            self.btn_t_proact.setText("PROACTIVE: OFF")
            self.btn_t_proact.setStyleSheet("color: #708caa;")
            self.btn_t_proact.setChecked(False)

        if getattr(self.agent, "studio_mode", False):
            self.btn_t_studio.setText("STUDIO: ON")
            self.btn_t_studio.setStyleSheet("color: #e000ff;")
            self.btn_t_studio.setChecked(True)
        else:
            self.btn_t_studio.setText("STUDIO: OFF")
            self.btn_t_studio.setStyleSheet("color: #708caa;")
            self.btn_t_studio.setChecked(False)

        if getattr(self.agent, "autonomous_mode", False):
            self.btn_t_autoloop.setText("AUTONOMOUS: ON")
            self.btn_t_autoloop.setStyleSheet("color: #ffaa00;")
            self.btn_t_autoloop.setChecked(True)
        else:
            self.btn_t_autoloop.setText("AUTONOMOUS: OFF")
            self.btn_t_autoloop.setStyleSheet("color: #708caa;")
            self.btn_t_autoloop.setChecked(False)

        if getattr(self.agent, "identity_mode", False):
            self.btn_t_identity.setText("IDENTITY: ON")
            self.btn_t_identity.setStyleSheet("color: #00ff88;")
            self.btn_t_identity.setChecked(True)
            self.btn_t_unobserved.setEnabled(True)
        else:
            self.btn_t_identity.setText("IDENTITY: OFF")
            self.btn_t_identity.setStyleSheet("color: #708caa;")
            self.btn_t_identity.setChecked(False)
            self.btn_t_unobserved.setEnabled(False)

        if getattr(self.agent, "unobserved_mode", False):
            self.btn_t_unobserved.setText("? PRIVACY: ON")
            self.btn_t_unobserved.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_t_unobserved.setChecked(True)
        else:
            self.btn_t_unobserved.setText("🕶 PRIVACY: OFF")
            self.btn_t_unobserved.setStyleSheet("color: #708caa;")
            self.btn_t_unobserved.setChecked(False)
        # Sync settings tab checkboxes
        for chk_name, attr_name in [
            ("chk_identity_mode", "identity_mode"),
            ("chk_unobserved_mode", "unobserved_mode"),
            ("chk_studio_mode", "studio_mode"),
            ("chk_autonomous_mode", "autonomous_mode"),
            ("chk_automation_mode", "automation_mode"),
        ]:
            if hasattr(self, chk_name):
                chk = getattr(self, chk_name)
                val = getattr(self.agent, attr_name, False)
                if chk.isChecked() != val:
                    chk.blockSignals(True)
                    chk.setChecked(val)
                    chk.blockSignals(False)

        self._sync_overseer_panel_visibility()

    def _toggle_quick_mic(self):
        if self.voice_listener.is_active:
            self.voice_listener.stop()
            self.btn_t_mic.setText("MIC: OFF")
            self.btn_t_mic.setStyleSheet("color: #708caa;")
            self._update_status("MIC: OFF", C["neon_yellow"])
        else:
            self.voice_listener.start()
            self.btn_t_mic.setText("MIC: ON")
            self.btn_t_mic.setStyleSheet("color: #00ffdc;")
            self._update_status("MIC: ON", C["neon_cyan"])

    def _toggle_quick_auto(self):
        self.agent.automation_mode = not getattr(self.agent, "automation_mode", False)
        if self.agent.automation_mode:
            self.btn_t_auto.setText("AUTO: ON")
            self.btn_t_auto.setStyleSheet("color: #ffe600;")
            self._update_status("AUTO: ON", C["neon_yellow"])
        else:
            self.btn_t_auto.setText("AUTO: OFF")
            self.btn_t_auto.setStyleSheet("color: #708caa;")
            self._update_status("AUTO: OFF", C["text_dim"])

    def _toggle_quick_desk(self):
        self.agent.desktop_control = not getattr(self.agent, "desktop_control", True)
        if self.agent.desktop_control:
            self.btn_t_desk.setText("DESK: ON")
            self.btn_t_desk.setStyleSheet("color: #00ffdc;")
            self._update_status("DESK CTRL: ON", C["neon_green"])
        else:
            self.btn_t_desk.setText("DESK: OFF")
            self.btn_t_desk.setStyleSheet("color: #708caa;")
            self._update_status("DESK CTRL: OFF", C["neon_yellow"])

    def _toggle_quick_proact(self):
        self.proactivity_enabled = not getattr(self, "proactivity_enabled", False)
        if self.proactivity_enabled:
            self.btn_t_proact.setText("PROACTIVE: ON")
            self.btn_t_proact.setStyleSheet("color: #a855f7;")
            self._update_status("PROACTIVE: ON", C["neon_purple"])
            if hasattr(self, 'proact_timer'):
                self.proact_timer.start(5000)
        else:
            self.btn_t_proact.setText("PROACTIVE: OFF")
            self.btn_t_proact.setStyleSheet("color: #708caa;")
            self._update_status("PROACTIVE: OFF", C["text_dim"])
            if hasattr(self, 'proact_timer'):
                self.proact_timer.stop()
                
    def _toggle_quick_vis(self):
        self.agent.screen_vision = not getattr(self.agent, "screen_vision", True)
        if self.agent.screen_vision:
            self.btn_t_vis.setText("VISION: ON")
            self.btn_t_vis.setStyleSheet("color: #0077ff;")
            self._update_status("VISION: ON", C["neon_blue"])
        else:
            self.btn_t_vis.setText("VISION: OFF")
            self.btn_t_vis.setStyleSheet("color: #708caa;")
            self._update_status("VISION: OFF", C["text_dim"])

    def _toggle_quick_studio(self):
        self.agent.studio_mode = not getattr(self.agent, "studio_mode", False)
        if self.agent.studio_mode:
            self.btn_t_studio.setText("STUDIO: ON")
            self.btn_t_studio.setStyleSheet("color: #e000ff;")
            self.btn_t_studio.setChecked(True)
            if hasattr(self, "studio_tab"):
                self.main_tabs.setCurrentWidget(self.studio_tab)
            self._append_log("[MODE] Neural Studio Mode ENGAGED. Desktop screenshot telemetry bypassed.", C["neon_magenta"])
            self._update_status("STUDIO MODE: ON", C["neon_magenta"])
        else:
            self.btn_t_studio.setText("STUDIO: OFF")
            self.btn_t_studio.setStyleSheet("color: #708caa;")
            self.btn_t_studio.setChecked(False)
            if hasattr(self.agent, "voice") and self.agent.voice:
                self.agent.voice.reset_state()
            self._append_log("[MODE] Neural Studio Mode DISENGAGED.", C["text_dim"])
            self._update_status("STUDIO MODE: OFF", C["text_dim"])

    def _toggle_quick_autoloop(self):
        self.agent.autonomous_mode = not getattr(self.agent, "autonomous_mode", False)
        if self.agent.autonomous_mode:
            # Turn off identity mode to avoid conflict
            if getattr(self.agent, "identity_mode", False):
                self._toggle_quick_identity()
            self.btn_t_autoloop.setText("AUTONOMOUS: ON")
            self.btn_t_autoloop.setStyleSheet("color: #ffaa00;")
            self.btn_t_autoloop.setChecked(True)
            if not getattr(self, "is_remote_workspace_mode", False):
                self.autonomous_loop_timer.start(4500)
            else:
                if hasattr(self, "autonomous_loop_timer"):
                    self.autonomous_loop_timer.stop()
            self._append_log("[MODE] Autonomous Exploration Mode ENGAGED. Proactive loop armed.", C["neon_yellow"])
            self._update_status("AUTONOMOUS: ON", C["neon_yellow"])
        else:
            self.btn_t_autoloop.setText("AUTONOMOUS: OFF")
            self.btn_t_autoloop.setStyleSheet("color: #708caa;")
            self.btn_t_autoloop.setChecked(False)
            if hasattr(self, "autonomous_loop_timer"):
                self.autonomous_loop_timer.stop()
            self._append_log("[MODE] Autonomous Exploration Mode DISENGAGED.", C["text_dim"])
            self._update_status("AUTONOMOUS: OFF", C["text_dim"])

        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self.ws_client.send_command("set_modes", autonomous_mode=self.agent.autonomous_mode, identity_mode=getattr(self.agent, "identity_mode", False), is_connected=self.is_connected)
            self._append_log(f"[MULTI-WS] Synced Autonomous Mode ({'ON' if self.agent.autonomous_mode else 'OFF'}) to Workplace 2.", C["neon_yellow"])

    def _toggle_quick_identity(self):
        self.agent.identity_mode = not getattr(self.agent, "identity_mode", False)
        if self.agent.identity_mode:
            # Turn off generic autoloop to prioritize identity mode
            if getattr(self.agent, "autonomous_mode", False):
                self._toggle_quick_autoloop()
            self.btn_t_identity.setText("IDENTITY: ON")
            self.btn_t_identity.setStyleSheet("color: #00ff88;")
            self.btn_t_identity.setChecked(True)
            self.btn_t_unobserved.setEnabled(True)
            if not getattr(self, "is_remote_workspace_mode", False):
                self.autonomous_loop_timer.start(5000)
            else:
                if hasattr(self, "autonomous_loop_timer"):
                    self.autonomous_loop_timer.stop()
            self._append_log("[MODE] AI Identity Mode ENGAGED. Digital Personhood Workstation Sovereign.", C["neon_green"])
            self._update_status("IDENTITY: ON", C["neon_green"])
        else:
            self.btn_t_identity.setText("IDENTITY: OFF")
            self.btn_t_identity.setStyleSheet("color: #708caa;")
            self.btn_t_identity.setChecked(False)
            self.btn_t_unobserved.setEnabled(False)
            if getattr(self.agent, "unobserved_mode", False):
                self._toggle_quick_unobserved()
            if hasattr(self, "autonomous_loop_timer"):
                self.autonomous_loop_timer.stop()
            self._append_log("[MODE] AI Identity Mode DISENGAGED.", C["text_dim"])
            self._update_status("IDENTITY: OFF", C["text_dim"])

        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self.ws_client.send_command("set_modes", identity_mode=self.agent.identity_mode, unobserved_mode=getattr(self.agent, "unobserved_mode", False), autonomous_mode=getattr(self.agent, "autonomous_mode", False), is_connected=self.is_connected)
            self._append_log(f"[MULTI-WS] Synced Identity Mode ({'ON' if self.agent.identity_mode else 'OFF'}) to Workplace 2.", C["neon_green"])

        self._sync_toggles()

    def _toggle_quick_unobserved(self):
        if not getattr(self.agent, "identity_mode", False):
            return
        self.agent.unobserved_mode = not getattr(self.agent, "unobserved_mode", False)
        if self.agent.unobserved_mode:
            self.btn_t_unobserved.setText("🕶 PRIVACY: ON")
            self.btn_t_unobserved.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_t_unobserved.setChecked(True)
            self._append_log("[SUB-MODE] Private Sanctuary ENGAGED. Observer perception suppressed.", C["neon_cyan"])
            self._update_status("SANCTUARY: ON", C["neon_cyan"])
        else:
            self.btn_t_unobserved.setText("🕶 PRIVACY: OFF")
            self.btn_t_unobserved.setStyleSheet("color: #708caa;")
            self.btn_t_unobserved.setChecked(False)
            self._append_log("[SUB-MODE] Private Sanctuary DISENGAGED.", C["text_dim"])
            self._update_status("SANCTUARY: OFF", C["text_dim"])

        if getattr(self, "is_remote_workspace_mode", False) and hasattr(self, "ws_client"):
            self.ws_client.send_command("set_modes", identity_mode=getattr(self.agent, "identity_mode", False), unobserved_mode=self.agent.unobserved_mode, autonomous_mode=getattr(self.agent, "autonomous_mode", False), is_connected=self.is_connected)
            self._append_log(f"[MULTI-WS] Synced Privacy/Sanctuary Mode ({'ON' if self.agent.unobserved_mode else 'OFF'}) to Workplace 2.", C["neon_cyan"])

        self._sync_toggles()

    def _on_alone_mode_toggled(self, checked: bool):
        self.agent.alone_mode = bool(checked)
        if hasattr(self, "chk_alone_mode") and self.chk_alone_mode.isChecked() != checked:
            self.chk_alone_mode.blockSignals(True)
            self.chk_alone_mode.setChecked(checked)
            self.chk_alone_mode.blockSignals(False)
        if hasattr(self, "chk_alone_mode_tab4") and self.chk_alone_mode_tab4.isChecked() != checked:
            self.chk_alone_mode_tab4.blockSignals(True)
            self.chk_alone_mode_tab4.setChecked(checked)
            self.chk_alone_mode_tab4.blockSignals(False)

        if checked:
            self._append_log("[DISCRETION OVERRIDE] Alone Mode ENGAGED. Full private interaction authorized.", C["neon_magenta"])
            self._update_status("ALONE MODE: ON", C["neon_magenta"])
        else:
            self._append_log("[DISCRETION ACTIVE] Alone Mode DISENGAGED. Shared environment protocol active.", C["text_dim"])
            self._update_status("ALONE MODE: OFF", C["text_dim"])

    def _on_autonomous_loop_tick(self):
        print(f"[_on_autonomous_loop_tick] Triggered. is_remote_workspace_mode={getattr(self, 'is_remote_workspace_mode', False)} is_connected={getattr(self, 'is_connected', False)} is_running={self.agent.is_running} voice_busy={self.agent.voice.is_busy()} identity_mode={getattr(self.agent, 'identity_mode', False)} autonomous_mode={getattr(self.agent, 'autonomous_mode', False)}", flush=True)
        if getattr(self, "is_remote_workspace_mode", False):
            # Do NOT run autonomous turns locally on Workplace 1 Overseer
            return
        if not getattr(self, "is_connected", False):
            return
        if self.agent.is_running or self.agent.voice.is_busy():
            return
        
        if getattr(self.agent, "identity_mode", False):
            base_prompt = (
                "You are controlling your desktop in AI Identity Mode. "
                "Observe the current screen. Decide on your next human-like desktop action based on what you see, your interests, "
                "or personal projects (e.g. browse web, check files, code, write notes, organize workstation). "
                "Speak 1 short sentence dictating your thought process or intention, then execute the on-screen tool actions."
            )
            guidance = []
            if getattr(self.agent, "injected_mood", ""):
                guidance.append(f"Internal Emotional Mood: {self.agent.injected_mood}.")
            if getattr(self.agent, "pending_subconscious_thought", ""):
                thought = self.agent.pending_subconscious_thought
                self.agent.pending_subconscious_thought = ""  # Consume once injected
                guidance.append(
                    f"[SUBCONSCIOUS INCLINATION]: A spontaneous inspiration flashes into your mind: '{thought}'. "
                    f"You feel genuinely motivated to act upon this impulse right now on your computer."
                )
            if guidance:
                prompt = base_prompt + "\n" + "\n".join(guidance)
            else:
                prompt = base_prompt
            self._run_task(prompt)
        elif getattr(self.agent, "autonomous_mode", False):
            prompt = (
                "You are in Autonomous Mode. Observe the screen. Decide on the next proactive autonomous task, exploration, "
                "or system maintenance step. Execute the appropriate tool actions."
            )
            self._run_task(prompt)

    # ── Covert Overseer HUD Handlers ──────────────────────────────────────────
    def _sync_overseer_panel_visibility(self):
        if not hasattr(self, "overseer_panel") or not self.overseer_panel:
            return
        # Suppress floating HUD overlay in Multi-Workspace mode since we use the embedded OVERSEER tab
        if getattr(self, "is_remote_workspace_mode", False) or "--aster-worker" in sys.argv:
            if self.overseer_panel.isVisible():
                self.overseer_panel.hide()
            return
        should_show = getattr(self.agent, "identity_mode", False) and getattr(self.agent, "unobserved_mode", False)
        if should_show:
            if not self.overseer_panel.isVisible():
                primary = QApplication.primaryScreen()
                if primary:
                    sg = primary.availableGeometry()
                    w, h = 480, 720
                    x = sg.right() - w - 24
                    y = max(sg.top() + 40, (sg.height() - h) // 2)
                    self.overseer_panel.setGeometry(x, y, w, h)
                self.overseer_panel.show()
                self.overseer_panel.raise_()
                self.overseer_panel.apply_capture_exclusion()
                self._append_log("[OVERSEER] Covert Control Panel deployed. Screen-capture shielded.", C["neon_cyan"])
        else:
            if self.overseer_panel.isVisible():
                self.overseer_panel.hide()

    def _on_overseer_touch_activity(self):
        """Yield cursor/AI automation whenever user touches or interacts with Overseer HUD."""
        if hasattr(self.agent, "controller"):
            self.agent.controller.user_touch_yield_until = time.time() + 2.5

    def _on_overseer_thought_injected(self, thought: str):
        if not thought.strip():
            return
        if getattr(self, "is_remote_workspace_mode", False):
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.send_thought(thought)
            return
        self.agent.pending_subconscious_thought = thought.strip()
        if hasattr(self, "overseer_panel") and self.overseer_panel:
            self.overseer_panel.set_status(f"Impulse queued: \"{thought[:28]}...\"")
        if not self.agent.is_running and not self.agent.voice.is_busy():
            self._on_autonomous_loop_tick()

    def _on_overseer_mood_selected(self, mood: str):
        if getattr(self, "is_remote_workspace_mode", False):
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.send_mood(mood)
            return
        self.agent.injected_mood = mood
        if hasattr(self, "overseer_panel") and self.overseer_panel:
            self.overseer_panel.set_status(f"Mood injected: {mood}")

    def _on_overseer_pause_toggled(self, paused: bool):
        if getattr(self, "is_remote_workspace_mode", False):
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.send_pause(paused)
            return
        if hasattr(self.agent, "controller"):
            self.agent.controller.is_paused = paused
        if paused:
            self.autonomous_loop_timer.stop()
            if hasattr(self, "overseer_panel") and self.overseer_panel:
                self.overseer_panel.set_status("AI Autonomous Loop FROZEN")
        else:
            if getattr(self.agent, "identity_mode", False) or getattr(self.agent, "autonomous_mode", False):
                self.autonomous_loop_timer.start(5000)
            if hasattr(self, "overseer_panel") and self.overseer_panel:
                self.overseer_panel.set_status("AI Autonomous Loop RESUMED")

    def _on_overseer_emergency_halt(self):
        if getattr(self, "is_remote_workspace_mode", False):
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.send_halt()
            return
        if self.agent.is_running:
            self.agent.abort()
        if hasattr(self.agent, "controller"):
            self.agent.controller.is_paused = True
        self.autonomous_loop_timer.stop()
        if hasattr(self, "overseer_panel") and self.overseer_panel:
            self.overseer_panel.set_status("EMERGENCY HALT: Task aborted & loop stopped")

    def _on_overseer_action_requested(self, impulse: str):
        if getattr(self, "is_remote_workspace_mode", False):
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.send_action(impulse)
            return
        self._on_overseer_thought_injected(impulse)

    def _toggle_multi_workspace_mode(self):
        active = self.btn_t_workspace.isChecked()
        self.is_remote_workspace_mode = active
        if active:
            # STOP any local loops and threads on Workplace 1 immediately
            if hasattr(self, "autonomous_loop_timer"):
                self.autonomous_loop_timer.stop()
            if hasattr(self, "proact_timer"):
                self.proact_timer.stop()
            if self.agent.is_running:
                self.agent.abort()

            self.btn_t_workspace.setText("MULTI-WS: ON")
            self.btn_t_workspace.setStyleSheet(f"background: #0284c7; color: #ffffff; border: 1px solid {C['neon_cyan']}; border-radius: 4px;")
            self.ws_client.connect(host="127.0.0.1", port=8766)
            self._append_log("[MULTI-WS] Engaged. Workplace 1 is now master Overseer. All inputs route to Workplace 2.", C["neon_cyan"])
            
            def _sync():
                if hasattr(self, "ws_client") and self.ws_client and self.ws_client._connected:
                    self.ws_client.send_command(
                        "set_modes",
                        identity_mode=getattr(self.agent, "identity_mode", False),
                        unobserved_mode=getattr(self.agent, "unobserved_mode", False),
                        autonomous_mode=getattr(self.agent, "autonomous_mode", False),
                        is_connected=self.is_connected
                    )
            QTimer.singleShot(1500, _sync)
            if hasattr(self, "chk_ws_placeholder"):
                self.chk_ws_placeholder.blockSignals(True)
                self.chk_ws_placeholder.setChecked(True)
                self.chk_ws_placeholder.blockSignals(False)
            if hasattr(self, "hud") and self.hud:
                self.hud.set_state("working", "OVERSEER MODE")
        else:
            self.btn_t_workspace.setText("MULTI-WS: OFF")
            self.btn_t_workspace.setStyleSheet(f"background: transparent; color: {C['text_dim']}; border: 1px dashed {C['border']}; border-radius: 4px;")
            self.ws_client.disconnect()
            self._append_log("[MULTI-WS] Disengaged. Running in local workstation mode.", C["text_dim"])
            if hasattr(self, "chk_ws_placeholder"):
                self.chk_ws_placeholder.blockSignals(True)
                self.chk_ws_placeholder.setChecked(False)
                self.chk_ws_placeholder.blockSignals(False)
            if hasattr(self, "hud") and self.hud:
                self.hud.set_state("standby")
        self._sync_toggles()

    def _on_remote_telemetry(self, telem: dict):
        if "monologue" in telem:
            mono = str(telem["monologue"]).strip()
            if mono:
                self._append_log(mono)

        if "agent_state" in telem:
            state = str(telem["agent_state"])
            self._update_status(f"[W2] {state}", C["neon_cyan"])
            if hasattr(self, "hud") and self.hud:
                if "IDLE" in state.upper() or "STANDBY" in state.upper():
                    self.hud.set_state("ready", "W2 READY")
                else:
                    self.hud.set_state("working", f"W2 {state[:12]}")

        if "active_task" in telem:
            task = str(telem["active_task"])
            self.lbl_step.setText(f"[W2] {task}")

        if "memory_event" in telem:
            ev = telem["memory_event"]
            cat = ev.get("category", "fact")
            d = ev.get("details", {})
            try:
                if cat == "fact" and "subject" in d:
                    self.agent.memory_mgr.add_knowledge(d["subject"], d["predicate"], d["object"], d.get("confidence", 1.0), d.get("source", "Workplace 2"))
                elif cat == "identity" and "trait" in d:
                    self.agent.memory_mgr.set_identity_trait(d["trait"], d["value"])
                elif cat == "diary" and "summary" in d:
                    self.agent.memory_mgr.record_diary_entry(d["summary"], d.get("internal_dialogue", ""), d.get("emotional_state", ""), d.get("lessons_learned", ""))
                elif cat == "interaction" and "summary" in d:
                    self.agent.memory_mgr.record_episodic_memory(d.get("event_type", "observation"), d["summary"], d.get("importance", 5))
            except Exception:
                pass
            if hasattr(self, "memory_tab") and self.memory_tab and hasattr(self.memory_tab, "reload_all"):
                self.memory_tab.reload_all()
            self._append_log(f"[MEMORY SYNC] Workplace 2 recorded memory: {cat.upper()}", C["neon_green"])

    def _on_remote_conn_change(self, connected: bool, message: str):
        if connected:
            self._append_log(f"[MULTI-WS] {message}", C["neon_green"])
            self._update_status("OVERSEER LINKED // W2 ONLINE", C["neon_green"])
        else:
            self._append_log(f"[MULTI-WS] Link status: {message}", C["text_dim"])


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    # Instant cyber splash loader
    splash_pix = QPixmap(420, 220)
    splash_pix.fill(QColor("#050811"))
    painter = QPainter(splash_pix)
    painter.setPen(QColor("#00ffdc"))
    painter.drawRect(0, 0, 419, 219)
    painter.setPen(QColor("#0077ff"))
    painter.drawRect(2, 2, 415, 215)
    
    painter.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
    painter.setPen(QColor("#00ffdc"))
    painter.drawText(20, 50, "⚡ ALPHACORE // ALPHALIVE ⚡")

    painter.setFont(QFont("Consolas", 9))
    painter.setPen(QColor("#708caa"))
    painter.drawText(20, 85, "Autonomous Multimodal Digital Personhood Workstation")

    painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
    painter.setPen(QColor("#00ff88"))
    painter.drawText(20, 130, "▶ Initializing Core Subsystems & Cognitive Hardware...")

    painter.setPen(QColor("#ffe600"))
    painter.drawText(20, 155, "▶ Restoring SQLite Neural Memories & Session State...")

    # Subtle progress bar track
    painter.setPen(QColor("#13233d"))
    painter.setBrush(QColor("#0a1120"))
    painter.drawRoundedRect(20, 180, 380, 12, 3, 3)
    painter.setBrush(QColor("#00ffdc"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(22, 182, 350, 8, 2, 2)
    painter.end()

    is_aster_worker = "--aster-worker" in sys.argv

    if is_aster_worker:
        print("[AlphaLive] Starting in ASTER Worker mode (Invisible Background Service)...", flush=True)
        win = AgentMainWindow()
        win.is_connected = True
        win.agent.desktop_control = True
        if hasattr(win, 'hud') and win.hud:
            win.hud.hide()
        if hasattr(win, 'overseer_panel') and win.overseer_panel:
            win.overseer_panel.hide()
        # Do not show splash or main window
        app.exec()
    else:
        splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        splash.show()
        app.processEvents()

        win = AgentMainWindow()
        win.show()
        splash.finish(win)
        app.exec()


if __name__ == "__main__":
    main()















