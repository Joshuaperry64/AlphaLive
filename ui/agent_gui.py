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
    QDoubleSpinBox, QGroupBox, QFileDialog
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
from ui.overlays import CoordinateOverlay, CalibrationOverlay
from memory.memory_manager import MemoryManager
from memory.character_manager import CharacterManager
from studio.image_studio_manager import ImageStudioManager, MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG
from ui.agent_tabs import AgentMemoryTab, AgentStudioTab, AgentCharactersTab, AgentMonitorTab

# Cyberpunk Palette
C = {
    "bg_dark": "#050811",
    "bg_card": "#0a1120",
    "bg_card_hover": "#0f1b33",
    "border": "#13233d",
    "neon_blue": "#0077ff",
    "neon_cyan": "#00ffdc",
    "neon_green": "#00ff88",
    "neon_red": "#ff0055",
    "neon_yellow": "#ffe600",
    "neon_magenta": "#e000ff",
    "text_bright": "#e6f1ff",
    "text_dim": "#708caa",
}

DEFAULT_MODAL_ENDPOINT = "https://alphacoreprogramming--qwen2-5-32b-instruct-awq-serve.modal.run"

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

        self.agent = AlphaAgent()
        
        self.agent.modal_model = "qwen2.5-32b-instruct-awq"
        if not getattr(self.agent, "modal_endpoint", ""):
            self.agent.modal_endpoint = f"{DEFAULT_MODAL_ENDPOINT}/v1"
        elif not self.agent.modal_endpoint.endswith("/v1"):
            self.agent.modal_endpoint = f"{self.agent.modal_endpoint.rstrip('/')}/v1"

        self.overlay = None
        self.calib_overlay = None
        self.modal_health_status = None
        self._modal_checking = False

        self.is_connected = False
        self.mic_enabled = True
        self.proactivity_enabled = True
        self.idle_timeout_seconds = 35
        self.last_activity_time = time.time()
        self._proactive_triggered = False
        self.duplex_mode = "half"

        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                    am = cfg.get("Global", {}).get("AudioMode")
                    if am in ("half", "full"):
                        self.duplex_mode = am
            except Exception:
                pass

        self._build_ui()
        self._update_session_display()

        if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
            self._append_log("[ENGINE] Active: 🔥 Modal Qwen2.5-32B Instruct (AWQ Uncensored).", C["neon_red"])
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
                on_state_callback=lambda st: self.signals.status_phase.emit(st, ""),
                device_index=saved_mic
            )
            self.voice_listener.set_sensitivity(self._load_saved_mic_sensitivity())

        self.agent.voice.on_speech_started = lambda: self.signals.status_phase.emit("speaking", "")
        
        def _on_speech_finished():
            # Only revert to 'READY' if we haven't already transitioned to 'PROCESSING' or 'LISTENING' for a new task
            if self.hud.current_state == "speaking":
                self.signals.status_phase.emit("ready", "")
                
        self.agent.voice.on_speech_finished = _on_speech_finished
        self.proact_timer = QTimer(self)
        self.proact_timer.timeout.connect(self._check_proactivity)
        self.proact_timer.start(2500)

    def closeEvent(self, event):
        if self.hud: self.hud.close()
        if self.overlay: self.overlay.close()
        if self.calib_overlay: self.calib_overlay.close()
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
        except Exception as e:
            self._append_log(f"[API CONFIG WARNING] Key error: {e}", C["neon_yellow"])

    def _save_modal_endpoint(self):
        new_url = self.input_modal_endpoint.text().strip()
        if not new_url.endswith("/v1"):
            new_url = f"{new_url.rstrip('/')}/v1"
            self.input_modal_endpoint.setText(new_url)

        self.agent.modal_endpoint = new_url
        self.agent.openai_client = None  # Force client recreation
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["ModalEndpoint"] = new_url
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
                self._append_log(f"[MODAL CONFIG] Endpoint saved: {new_url}", C["neon_cyan"])
            except Exception:
                pass

    def _test_voice_playback(self):
        self._append_log("[VOICE TEST] Testing Google Leda voice output...", C["neon_blue"])
        threading.Thread(target=lambda: self.agent.voice.speak_sync("Voice synthesis operational. Google Leda ready.", wait=True), daemon=True).start()

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

    def _init_settings_controls(self):
        self.backend_card = QFrame()
        self.btn_backend_gemini = QPushButton("⚡ Google Gemini")
        self.btn_backend_gemini.setFixedHeight(32)
        self.btn_backend_gemini.clicked.connect(lambda: self._select_backend("gemini"))

        self.btn_backend_modal = QPushButton("🔥 Modal Qwen2.5-32B (A100 AWQ)")
        self.btn_backend_modal.setFixedHeight(32)
        self.btn_backend_modal.clicked.connect(lambda: self._select_backend("modal_qwen"))

        self.btn_deploy_vllm = QPushButton("🚀 DEPLOY / REDEPLOY MODAL vLLM")
        self.btn_deploy_vllm.setFixedHeight(28)
        self.btn_deploy_vllm.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: #ff5577;
                border: 1px solid {C['neon_red']};
                border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C['neon_red']}; color: #fff; }}
        """)
        self.btn_deploy_vllm.clicked.connect(self._deploy_modal_vllm)

        self.voice_card = QFrame()
        self.btn_voice_leda = QPushButton("✨ Google Leda [ACTIVE ✓]")
        self.btn_voice_leda.setFixedHeight(30)

        self.btn_desktop_ctrl = QPushButton()
        self.btn_desktop_ctrl.setFixedHeight(28)
        self.btn_desktop_ctrl.clicked.connect(self._toggle_desktop_control)
        self._update_desktop_control_style()

        self.btn_duplex = QPushButton()
        self.btn_duplex.setFixedHeight(28)
        self.btn_duplex.clicked.connect(self._toggle_duplex_mode)
        self._update_duplex_style()

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

        self.btn_mic = QPushButton("🎙 MIC: MUTED [STANDBY]")
        self.btn_mic.setFixedHeight(28)
        self.btn_mic.clicked.connect(self._toggle_mic)

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
        self.log_box.setFont(QFont("Consolas", 10))
        self.log_box.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_dark']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        layout.addWidget(self.log_box, 1)

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Audio Section
        card_audio = QFrame()
        card_audio.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ca_layout = QVBoxLayout(card_audio)
        ca_layout.addWidget(QLabel("🎙 AUDIO HARDWARE"))
        
        dev_row = QHBoxLayout()
        self.combo_mic_device = QComboBox()
        self.combo_mic_device.currentIndexChanged.connect(self._on_mic_device_changed)
        dev_row.addWidget(self.combo_mic_device, 1)
        self.btn_refresh_mics = QPushButton("🔄 REFRESH")
        self.btn_refresh_mics.clicked.connect(self._populate_microphones)
        dev_row.addWidget(self.btn_refresh_mics)
        ca_layout.addLayout(dev_row)

        mic_ctrl_row = QHBoxLayout()
        mic_ctrl_row.addWidget(self.btn_duplex, 1)
        mic_ctrl_row.addWidget(self.btn_mic, 1)
        ca_layout.addLayout(mic_ctrl_row)
        layout.addWidget(card_audio)

        # API Credentials Section
        card_api = QFrame()
        card_api.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        api_layout = QVBoxLayout(card_api)
        api_layout.addWidget(QLabel("🔑 BACKEND ENDPOINTS & KEYS"))

        self.input_gemini_key = QLineEdit(os.environ.get("GEMINI_API_KEY", ""))
        self.input_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        gem_row = QHBoxLayout()
        gem_row.addWidget(self.input_gemini_key, 1)
        btn_save_gem = QPushButton("💾 SAVE GEMINI")
        btn_save_gem.clicked.connect(self._save_gemini_key)
        gem_row.addWidget(btn_save_gem)
        api_layout.addLayout(gem_row)

        self.input_modal_endpoint = QLineEdit(getattr(self.agent, "modal_endpoint", f"{DEFAULT_MODAL_ENDPOINT}/v1"))
        mod_row = QHBoxLayout()
        mod_row.addWidget(self.input_modal_endpoint, 1)
        btn_save_mod = QPushButton("💾 SAVE MODAL")
        btn_save_mod.clicked.connect(self._save_modal_endpoint)
        mod_row.addWidget(btn_save_mod)
        api_layout.addLayout(mod_row)

        layout.addWidget(card_api)

        # Engine Section
        self.backend_card.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        be_layout = QVBoxLayout(self.backend_card)
        be_layout.addWidget(QLabel("🧠 COGNITIVE ENGINE SELECTION"))
        be_row = QHBoxLayout()
        be_row.addWidget(self.btn_backend_gemini, 1)
        be_row.addWidget(self.btn_backend_modal, 1)
        be_layout.addLayout(be_row)
        be_layout.addWidget(self.btn_deploy_vllm)
        layout.addWidget(self.backend_card)

        # Desktop Tools Section
        card_tools = QFrame()
        card_tools.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ct_layout = QVBoxLayout(card_tools)
        ct_layout.addWidget(QLabel("🖥 DESKTOP AUTOMATION"))
        tools_grid = QGridLayout()
        tools_grid.addWidget(self.btn_desktop_ctrl, 0, 0)
        tools_grid.addWidget(self.btn_overlay, 0, 1)
        tools_grid.addWidget(self.btn_calib, 1, 0)
        tools_grid.addWidget(self.combo_mood, 1, 1)
        ct_layout.addLayout(tools_grid)
        layout.addWidget(card_tools)

        layout.addStretch()
        scroll.setWidget(container)

        self._populate_microphones()
        self._populate_displays()
        return scroll

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

        self.session_card = QFrame()
        sess_layout = QVBoxLayout(self.session_card)
        self.lbl_session_name = QLabel(f"📁 {self.agent.current_session.upper()}")
        sess_layout.addWidget(self.lbl_session_name)
        self.lbl_session_stats = QLabel("Turns: ...")
        sess_layout.addWidget(self.lbl_session_stats)
        self.btn_session = QPushButton("🔄 SWITCH SESSION")
        self.btn_session.clicked.connect(self._open_session_selector)
        sess_layout.addWidget(self.btn_session)
        s_layout.addWidget(self.session_card)

        s_layout.addStretch()

        self.btn_abort = QPushButton("⛔ ABORT TASK (Ctrl+Z)")
        self.btn_abort.setFixedHeight(34)
        self.btn_abort.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']};")
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
        self.main_tabs.addTab(self._build_settings_tab(), "⚙️ SETTINGS")

        main_layout.addWidget(self.main_tabs, 1)
        root_vlayout.addLayout(main_layout, 1)

        self._update_backend_style()

    def _toggle_power(self):
        if not self.is_connected:
            self.is_connected = True
            self.btn_power.setText("⏹ STOP AGENT")
            self.btn_power.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']};")
            if HAS_SR and self.voice_listener and self.mic_enabled:
                self.voice_listener.start()
            self._update_status("READY // LISTENING", C["neon_green"])
            if self.hud:
                self.hud.set_state("listening")
            if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
                self._trigger_modal_health_check()
        else:
            self.is_connected = False
            self.btn_power.setText("⚡ START AGENT")
            self.btn_power.setStyleSheet(f"background: {C['neon_cyan']}; color: #000;")
            if HAS_SR and self.voice_listener:
                self.voice_listener.stop()
            self._update_status("STANDBY // OFFLINE", C["text_dim"])
            if self.hud:
                self.hud.set_state("disconnected")

    def _select_backend(self, backend_type: str):
        self.agent.set_backend(backend_type)
        self._update_backend_style()
        if backend_type == "modal_qwen" and self.is_connected:
            self._trigger_modal_health_check()

    # -------------------------------------------------------------------------
    # OVERRIDE HEALTH CHECK TO BYPASS `alpha_agent.py` STRING PARSING BUG
    # -------------------------------------------------------------------------
    async def _safe_health_check(self, timeout: float = 240.0) -> dict:
        import urllib.request
        import urllib.error
        
        # Safely remove exactly "/v1" from the end instead of using rstrip
        base_url = getattr(self.agent, "modal_endpoint", DEFAULT_MODAL_ENDPOINT)
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        
        health_url = base_url.rstrip("/") + "/health"
        start_t = time.time()
        
        try:
            def _probe():
                req = urllib.request.Request(health_url, headers={"User-Agent": "AlphaAgent/4.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status
            status_code = await asyncio.to_thread(_probe)
            elapsed_ms = int((time.time() - start_t) * 1000)
            if status_code == 200:
                return {"online": True, "latency_ms": elapsed_ms, "status": "online", "error": None}
            return {"online": False, "latency_ms": elapsed_ms, "status": f"HTTP {status_code}", "error": f"HTTP {status_code}"}
        except urllib.error.HTTPError as he:
            return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": f"HTTP {he.code}", "error": f"HTTP {he.code}: {he.reason}"}
        except Exception as e:
            return {"online": False, "latency_ms": int((time.time() - start_t)*1000), "status": "offline", "error": str(e)}

    def _trigger_modal_health_check(self):
        if self._modal_checking: return
        self._modal_checking = True
        self._update_status("WAKING MODAL A100...", C["neon_yellow"])
        if self.hud:
            self.hud.set_state("working", "WAKING GPU")

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
        if res.get("online"):
            ms = res.get("latency_ms", 0)
            self._append_log(f"[MODAL HEALTH] Endpoint ONLINE ({ms}ms) - Qwen2.5-32B AWQ operational.", C["neon_green"])
            self._update_status("READY // LISTENING", C["neon_green"])
        else:
            self._append_log(f"[MODAL HEALTH] OFFLINE: {res.get('error')}", C["neon_red"])
            self._update_status("MODAL TIMEOUT", C["neon_red"])

    def _update_backend_style(self):
        backend = getattr(self.agent, "backend_type", "gemini")
        if backend == "modal_qwen":
            self.model_lbl.setText("ENGINE: QWEN 2.5 32B (A100 AWQ // UNCENSORED)")
            self.model_lbl.setStyleSheet(f"color: {C['neon_red']};")
            self.btn_backend_modal.setStyleSheet(f"background: {C['neon_red']}28; color: #ff3366; border: 1.5px solid {C['neon_red']};")
            self.btn_backend_gemini.setStyleSheet("background: transparent; color: #708caa;")
        else:
            self.model_lbl.setText("ENGINE: GOOGLE GEMINI")
            self.model_lbl.setStyleSheet(f"color: {C['neon_cyan']};")
            self.btn_backend_gemini.setStyleSheet(f"background: {C['neon_cyan']}28; color: {C['neon_cyan']}; border: 1.5px solid {C['neon_cyan']};")
            self.btn_backend_modal.setStyleSheet("background: transparent; color: #708caa;")

    def _toggle_desktop_control(self):
        new_val = not getattr(self.agent, "desktop_control", True)
        self.agent.set_desktop_control(new_val)
        self._update_desktop_control_style()

    def _update_desktop_control_style(self):
        dc = getattr(self.agent, "desktop_control", True)
        txt = "🖥 DESKTOP CTRL: [ON]" if dc else "🖥 DESKTOP CTRL: [OFF]"
        col = C["neon_green"] if dc else C["neon_yellow"]
        self.btn_desktop_ctrl.setText(txt)
        self.btn_desktop_ctrl.setStyleSheet(f"background: {col}22; color: {col}; border: 1px solid {col};")

    def _toggle_duplex_mode(self):
        self.duplex_mode = "full" if self.duplex_mode == "half" else "half"
        if self.voice_listener:
            self.voice_listener.set_duplex_mode(self.duplex_mode)
        self._update_duplex_style()

    def _update_duplex_style(self):
        txt = "🎙 MIC: HALF-DUPLEX [STABLE]" if self.duplex_mode == "half" else "🎙 MIC: FULL-DUPLEX [BARGE-IN]"
        col = C["neon_cyan"] if self.duplex_mode == "half" else C["neon_yellow"]
        self.btn_duplex.setText(txt)
        self.btn_duplex.setStyleSheet(f"background: {col}22; color: {col}; border: 1px solid {col};")

    def _toggle_mic(self):
        if not HAS_SR or not self.voice_listener: return
        self.mic_enabled = not self.mic_enabled
        if not self.mic_enabled:
            self.voice_listener.stop()
            self.btn_mic.setText("🎙 MIC: MUTED [OFF]")
        else:
            if self.is_connected:
                self.voice_listener.start()
                self.btn_mic.setText("🎙 MIC: LISTENING [ON]")

    def _toggle_proactivity(self):
        self.proactivity_enabled = not self.proactivity_enabled
        self.btn_proact.setText("🤖 PROACTIVE [ON]" if self.proactivity_enabled else "🤖 PROACTIVE [OFF]")

    def _toggle_hud(self):
        if self.hud.isVisible():
            self.hud.hide()
            self.btn_hud_toggle.setText("💡 HUD [OFF]")
        else:
            self.hud.show()
            self.btn_hud_toggle.setText("💡 HUD [ON]")

    def _toggle_overlay(self):
        if self.overlay is None:
            self.overlay = CoordinateOverlay()
            self.btn_overlay.setText("🌐 COORDINATE GRID [ON]")
        else:
            self.overlay.close()
            self.overlay = None
            self.btn_overlay.setText("🌐 COORDINATE GRID [OFF]")

    def _start_calibration_task(self):
        if self.calib_overlay: self.calib_overlay.close()
        self.calib_overlay = CalibrationOverlay()
        self.calib_overlay.finished.connect(lambda: self._append_log("Calibration finished.", C["neon_green"]))

    def _deploy_modal_vllm(self):
        reply = QMessageBox.question(
            self,
            "Deploy Modal vLLM",
            "Deploy SamCrowdwave/Qwen2.5-32B-Instruct-abliterated-AWQ to Modal A100?\nExecutes 'modal deploy Vllm_3.py'.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes: return

        self._append_log("[MODAL DEPLOY] Launching deployment...", C["neon_red"])
        self.btn_deploy_vllm.setEnabled(False)

        def _worker():
            try:
                # FIX: Set Windows encoding explicitly to handle Modal's UTF-8 emojis without crashing
                proc = subprocess.Popen(
                    [sys.executable, "-m", "modal", "deploy", "Vllm_3.py"],
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
                proc.wait()
                if proc.returncode == 0:
                    self.signals.log_message.emit("[MODAL DEPLOY] Success!", C["neon_green"])
                    QTimer.singleShot(500, self._trigger_modal_health_check)
            except Exception as e:
                self.signals.log_message.emit(f"[MODAL DEPLOY ERROR] {e}", C["neon_red"])
            finally:
                QTimer.singleShot(0, lambda: self.btn_deploy_vllm.setEnabled(True))

        threading.Thread(target=_worker, daemon=True).start()

    def _abort_task(self):
        self.agent.abort()
        self._append_log("[ABORT] Stopped by user.", C["neon_red"])
        self._set_phase("error", "Aborted")

    def _send_text_command(self):
        cmd = self.cmd_input.text().strip()
        if not cmd: return
        self.cmd_input.clear()
        if not self.is_connected: self._toggle_power()
        self._append_log(f"[YOU] {cmd}", C["neon_cyan"])
        self._run_task(cmd)

    def _handle_voice_input(self, text: str):
        self.signals.voice_heard.emit(text)

    def _on_voice_heard(self, text: str):
        if self.duplex_mode == "half" and self.agent.voice.is_busy(): return
        self._append_log(f"[HEARD] \"{text}\"", C["neon_cyan"])
        self._run_task(text)

    def _run_task(self, goal: str):
        if self.agent.is_running:
            self.agent.abort()

        self._set_phase("generating", "THINKING...")

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
        def _on_step(cur, tot): self.signals.step_updated.emit(cur, tot)
        def _on_status(st): self.signals.status_phase.emit(st.lower(), "")
        def _on_log(txt, lvl):
            col = C["neon_green"] if lvl == "green" else (C["neon_red"] if lvl == "error" else C["text_bright"])
            self.signals.log_message.emit(txt, col)

        try:
            await self.agent.execute_turn(goal, on_step=_on_step, on_log=_on_log, on_status=_on_status)
        except Exception as e:
            self.signals.log_message.emit(f"[Agent Execution Error]: {e}", C["neon_red"])
        finally:
            self.signals.task_finished.emit()

    def _append_log(self, text: str, color: str):
        t_stamp = time.strftime("[%H:%M:%S]")
        self.log_box.append(f"<span style='color:{C['text_dim']}'>{t_stamp}</span> <span style='color:{color}'>{text}</span>")
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self, text: str, color: str = None):
        self.lbl_status.setText(text)
        if color:
            self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold; border: none;")

    def _update_step(self, current: int, total: int):
        self.lbl_step.setText(f"Action Step: {current}")

    def _update_screen_preview(self, pil_img):
        pass

    def _on_task_finished(self):
        self.lbl_step.setText("Step: Ready")
        self._update_session_display()
        if self.is_connected:
            self._set_phase("ready")
        else:
            self._set_phase("standby")

    def _open_session_selector(self):
        dlg = SessionSelectorDialog(self.agent.current_session, self.agent.session_manager, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_sess = dlg.selected_session
            if new_sess != self.agent.current_session:
                switched = self.agent.switch_session(new_sess)
                self._update_session_display()
                self._append_log(f"[SESSION] Switched to '{switched}'.", C["neon_cyan"])

    def _update_session_display(self):
        self.lbl_session_name.setText(f"📁 {self.agent.current_session.upper()}")

    def _on_idle_time_changed(self, idx: int):
        try:
            self.idle_timeout_seconds = int(self.combo_idle_time.currentText().replace("s", ""))
        except ValueError:
            pass

    def _check_proactivity(self):
        pass


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = AgentMainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()