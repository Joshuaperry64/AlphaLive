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

class VoiceBar(QWidget):
    """Animated cyber voice activity bar visualizer."""

    def __init__(self, bars=26, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self._bars    = bars
        self._heights = [0.08] * bars
        self._targets = [0.08] * bars
        self._state   = "idle"   # idle | user | ai
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
    """Custom cyber-styled item widget representing a conversation session in the selector list."""
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
            active_badge.setStyleSheet(f"""
                background-color: {C['neon_green']}22;
                color: {C['neon_green']};
                border: 1px solid {C['neon_green']};
                border-radius: 3px;
                padding: 1px 6px;
            """)
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

        # Snippet preview
        preview_text = self.session_data.get("preview", "").strip()
        preview_text = " ".join(preview_text.split())
        if len(preview_text) > 135:
            preview_text = preview_text[:132] + "..."
        if not preview_text:
            preview_text = "Empty session transcript."

        snip_lbl = QLabel(preview_text)
        snip_lbl.setFont(QFont("Consolas", 8))
        snip_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none; background: transparent;")
        snip_lbl.setWordWrap(True)
        layout.addWidget(snip_lbl)


class SessionSelectorDialog(QDialog):
    """Cyberpunk modal dialog for searching, selecting, creating, and managing conversation sessions."""
    def __init__(self, current_session: str, session_manager, parent=None):
        super().__init__(parent)
        self.current_session = current_session
        self.session_manager = session_manager
        self.selected_session = current_session
        self.all_sessions = []

        self.setWindowTitle("AlphaCore // Conversation Session & Context Manager")
        self.resize(740, 560)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {C['bg_dark']};
                border: 1px solid {C['border']};
            }}
        """)
        self._build_ui()
        self._load_sessions()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel("CONVERSATION SESSIONS & CONTEXT")
        title_lbl.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        title_box.addWidget(title_lbl)

        sub_lbl = QLabel("Select a session to resume context, create a new session, or delete old logs.")
        sub_lbl.setFont(QFont("Consolas", 8))
        sub_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        title_box.addWidget(sub_lbl)
        root.addLayout(title_box)

        # Search Bar
        search_box = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(34)
        self.search_input.setFont(QFont("Consolas", 9))
        self.search_input.setPlaceholderText("🔍 Search sessions by name or conversation snippet...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_card']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 10px;
            }}
            QLineEdit:focus {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.search_input.textChanged.connect(self._filter_sessions)
        search_box.addWidget(self.search_input)
        root.addLayout(search_box)

        # List of sessions
        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Consolas", 9))
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_card']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 4px;
            }}
            QListWidget::item {{
                background-color: {C['bg_dark']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                margin-bottom: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {C['neon_blue']}22;
                border: 1px solid {C['neon_cyan']};
            }}
            QListWidget::item:hover {{
                border-color: {C['neon_blue']};
            }}
        """)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.list_widget, 1)

        # Bottom Action Bar
        act_bar = QHBoxLayout()
        act_bar.setSpacing(8)

        # New Session Button
        self.btn_new = QPushButton("➕ NEW SESSION")
        self.btn_new.setFixedHeight(34)
        self.btn_new.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_new.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_green']}22;
                color: {C['neon_green']};
                border: 1px solid {C['neon_green']};
                border-radius: 4px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C['neon_green']};
                color: #000;
            }}
        """)
        self.btn_new.clicked.connect(self._on_new_session)
        act_bar.addWidget(self.btn_new)

        # Delete Button
        self.btn_delete = QPushButton("🗑 DELETE")
        self.btn_delete.setFixedHeight(34)
        self.btn_delete.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: {C['neon_red']};
                border: 1px solid {C['neon_red']};
                border-radius: 4px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #fff;
            }}
        """)
        self.btn_delete.clicked.connect(self._on_delete_session)
        act_bar.addWidget(self.btn_delete)

        # Open Folder Button
        self.btn_folder = QPushButton("📂 OPEN FOLDER")
        self.btn_folder.setFixedHeight(34)
        self.btn_folder.setFont(QFont("Consolas", 8))
        self.btn_folder.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                border-color: {C['neon_blue']};
                color: {C['text_bright']};
            }}
        """)
        self.btn_folder.clicked.connect(self._open_history_folder)
        act_bar.addWidget(self.btn_folder)

        act_bar.addStretch()

        # Cancel Button
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setFont(QFont("Consolas", 8))
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                color: {C['text_bright']};
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        act_bar.addWidget(self.btn_cancel)

        # Select & Resume Button
        self.btn_select = QPushButton("⚡ RESUME SESSION")
        self.btn_select.setFixedHeight(34)
        self.btn_select.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_select.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']};
                color: #000;
                border-radius: 4px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: #fff;
            }}
        """)
        self.btn_select.clicked.connect(self._on_resume_clicked)
        act_bar.addWidget(self.btn_select)

        root.addLayout(act_bar)

    def _load_sessions(self, filter_text: str = ""):
        self.list_widget.clear()
        if not self.session_manager:
            return
        self.all_sessions = self.session_manager.list_sessions()
        f_lower = filter_text.strip().lower()

        for s in self.all_sessions:
            if f_lower:
                if f_lower not in s["name"].lower() and f_lower not in s.get("preview", "").lower():
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
        else:
            QMessageBox.information(self, "Select Session", "Please select a session from the list.")

    def _on_item_double_clicked(self, item):
        self.selected_session = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_new_session(self):
        name, ok = QInputDialog.getText(
            self,
            "Create New Session",
            "Enter new session name (e.g. workspace_tasks, night_chat):",
            QLineEdit.EchoMode.Normal,
            ""
        )
        if ok and name.strip():
            clean = self.session_manager.create_session(name)
            self.current_session = clean
            self.selected_session = clean
            self._load_sessions()
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == clean:
                    self.list_widget.setCurrentItem(it)
                    break

    def _on_delete_session(self):
        curr = self.list_widget.currentItem()
        if not curr:
            QMessageBox.information(self, "Delete Session", "Please select a session to delete.")
            return
        name = curr.data(Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to permanently delete session '{name}' and its transcript file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            success = self.session_manager.delete_session(name)
            if success:
                if self.current_session == name:
                    self.current_session = "alpha"
                    self.session_manager.set_active_session_name("alpha")
                self._load_sessions()

    def _open_history_folder(self):
        if self.session_manager and self.session_manager.history_dir.exists():
            os.startfile(str(self.session_manager.history_dir))


class MiniStatusHUD(QWidget):
    """Sleek, minimal, draggable floating status pill providing instant state assurance
    (Ready=Cyan, Listening=Green, Generating=Yellow, Processing=Magenta, Speaking=Blue, Offline=Dim).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(205, 38)

        # Position at top-right corner of available desktop space
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
        self.pill_layout.setSpacing(6)

        # Move grip handle
        self.grip = QLabel("⋮⋮")
        self.grip.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.grip.setStyleSheet(f"color: {C['text_dim']}; border: none; background: transparent;")
        self.grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self.pill_layout.addWidget(self.grip)

        # Glowing status dot
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.pill_layout.addWidget(self.dot)

        # Status text
        self.lbl_text = QLabel("STANDBY")
        self.lbl_text.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_text.setStyleSheet("border: none; background: transparent;")
        self.pill_layout.addWidget(self.lbl_text, 1)

        # Close / Hide button
        self.btn_hide = QPushButton("✕")
        self.btn_hide.setFixedSize(16, 16)
        self.btn_hide.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self.btn_hide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hide.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                color: {C['neon_red']};
                background: {C['neon_red']}22;
            }}
        """)
        self.btn_hide.clicked.connect(self.hide)
        self.pill_layout.addWidget(self.btn_hide)

        self.main_layout.addWidget(self.pill_frame)

    def set_state(self, state: str, details: str = ""):
        self.current_state = state.lower()
        if self.current_state == "ready":
            color = C["neon_cyan"]
            bg_color = "rgba(4, 18, 20, 240)"
            text = "READY"
            tip = "Alpha is ready. Speak into microphone or type command."
        elif self.current_state == "listening":
            color = C["neon_green"]
            bg_color = "rgba(4, 22, 10, 240)"
            text = "LISTENING"
            tip = "Microphone active. Capturing your voice..."
        elif self.current_state in ("generating", "working"):
            color = C["neon_yellow"]
            bg_color = "rgba(22, 18, 4, 240)"
            text = "GENERATING" if not details else details[:11].upper()
            tip = f"Alpha is thinking & generating response. {details}"
        elif self.current_state == "processing":
            color = C["neon_magenta"]
            bg_color = "rgba(20, 4, 22, 240)"
            text = "PROCESSING"
            tip = "Synthesizing vocal speech from response..."
        elif self.current_state == "speaking":
            color = C["neon_blue"]
            bg_color = "rgba(4, 12, 26, 240)"
            text = "SPEAKING"
            tip = "Alpha is speaking."
        elif self.current_state == "error":
            color = C["neon_red"]
            bg_color = "rgba(24, 4, 8, 245)"
            text = "ERROR"
            tip = f"Error detected: {details or 'API / Connection Error'}"
        elif self.current_state in ("disconnected", "offline"):
            color = C["neon_red"]
            bg_color = "rgba(18, 4, 6, 235)"
            text = "OFFLINE"
            tip = "Agent is disconnected. Click Start Agent to connect."
        else: # standby
            color = C["text_dim"]
            bg_color = "rgba(6, 10, 20, 235)"
            text = "STANDBY"
            tip = "Agent in standby. Click Start Agent to activate."

        self.lbl_text.setText(text)
        self.lbl_text.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        self.setToolTip(f"{tip}\n(Drag to move anywhere • Click ✕ to hide)")

        self.dot.setStyleSheet(f"""
            background-color: {color};
            border-radius: 5px;
            border: 1px solid {color};
        """)

        self.pill_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 1.5px solid {color};
                border-radius: 18px;
            }}
        """)

    def mouseDoubleClickEvent(self, event):
        self.hide()

    # Draggable handling
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
    log_message = pyqtSignal(str, str)     # text, color
    status_updated = pyqtSignal(str, str)  # status_text, color
    status_phase = pyqtSignal(str, str)    # phase, details
    step_updated = pyqtSignal(int, int)    # current_step, max_steps
    screen_updated = pyqtSignal(object)    # PIL image
    task_finished = pyqtSignal()
    voice_heard = pyqtSignal(str)          # transcribed text
    modal_health_updated = pyqtSignal(dict) # health result dict

class AgentMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AlphaCore // Autonomous Desktop Agent")
        self.setStyleSheet(f"background-color: {C['bg_dark']};")
        
        # Bind Application Icon
        ico_p = ROOT_DIR / "alphalive.ico"
        if ico_p.exists():
            self.setWindowIcon(QIcon(str(ico_p)))

        self._initial_positioned = False

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
        self.overlay = None
        self.calib_overlay = None
        self.modal_health_status = None
        self._modal_checking = False

        # State management: Standby until user explicitly starts the agent
        self.is_connected = False
        self.mic_enabled = True
        self.proactivity_enabled = True
        self.idle_timeout_seconds = 35
        self.last_activity_time = time.time()
        self._proactive_triggered = False

        # Load duplex mode from config (default 'half' for rock-solid stability without self-interruptions)
        self.duplex_mode = "half"
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                    am = cfg.get("Global", {}).get("AudioMode") or cfg.get("core/alpha_core.py", {}).get("AudioMode")
                    if am in ("half", "full"):
                        self.duplex_mode = am
            except Exception:
                pass

        # Build UI
        self._build_ui()
        self._position_on_right_half()
        self._update_session_display()
        if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
            self._append_log("[ENGINE] Active: 🔥 Modal HuiHui-Qwen3-14B (Uncensored vLLM). In Standby (GPU will wake upon pressing Start).", C["neon_red"])
        else:
            self._append_log(f"[ENGINE] Active: ⚡ Google Gemini ({self.agent.model_name.replace('models/', '')}).", C["neon_cyan"])

        # Floating Mini Status HUD (starts in Standby mode)
        self.hud = MiniStatusHUD()
        self.hud.show()
        self.hud.set_state("standby")

        self._current_task_thread = None

        # Background Voice Listener (instantiated with device selection & half-duplex self-interrupt suppression)
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
            saved_sens = self._load_saved_mic_sensitivity()
            self.voice_listener.set_sensitivity(saved_sens)

        # Connect speech started/finished callbacks to agent voice
        self.agent.voice.on_speech_started = lambda: self.signals.status_phase.emit("speaking", "")
        self.agent.voice.on_speech_finished = lambda: self.signals.status_phase.emit("ready", "")

        # Proactivity Timer
        self.proact_timer = QTimer(self)
        self.proact_timer.timeout.connect(self._check_proactivity)
        self.proact_timer.start(2500)

    def closeEvent(self, event):
        if self.hud:
            self.hud.close()
        if self.overlay:
            self.overlay.close()
        if self.calib_overlay:
            self.calib_overlay.close()
        if self.voice_listener:
            self.voice_listener.stop()
        try:
            from integrations.alexa_ingress import stop_ingress_server
            stop_ingress_server()
        except Exception:
            pass
        event.accept()

    def _position_on_right_half(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            target_w = geom.width() // 2
            min_w = self.minimumSizeHint().width() if hasattr(self, "minimumSizeHint") else 660
            target_w = max(target_w, min(min_w, geom.width() - 20))
            target_w = min(target_w, geom.width() - 4)
            target_h = max(500, geom.height() - 8)
            start_x = geom.x() + (geom.width() - target_w) - 2
            start_y = geom.y() + (geom.height() - target_h) // 2
            self.setGeometry(start_x, start_y, target_w, target_h)
            self.setMinimumSize(580, 480)
        else:
            self.resize(740, 800)

    def _apply_native_win32_icon(self):
        try:
            ico_p = ROOT_DIR / "alphalive.ico"
            if not ico_p.exists():
                return

            hwnd = int(self.winId())
            if not hwnd:
                return

            import ctypes
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            LR_LOADFROMFILE = 0x00000010
            IMAGE_ICON = 1
            hicon_sm = ctypes.windll.user32.LoadImageW(None, str(ico_p), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            hicon_bg = ctypes.windll.user32.LoadImageW(None, str(ico_p), IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
            if not hicon_bg:
                hicon_bg = ctypes.windll.user32.LoadImageW(None, str(ico_p), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if hicon_sm:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_sm)
            if hicon_bg:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_bg)

            try:
                ctypes.windll.user32.SetClassLongPtrW(hwnd, -14, hicon_bg)
                ctypes.windll.user32.SetClassLongPtrW(hwnd, -34, hicon_sm)
            except Exception:
                pass

            try:
                from win32com.propsys import propsys, pscon
                import pythoncom
                store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
                propvar = propsys.PROPVARIANTType("alphacore.alphalive.agent.v4", pythoncom.VT_LPWSTR)
                store.SetValue(pscon.PKEY_AppUserModel_ID, propvar)
                icon_prop = propsys.PROPVARIANTType(f"{ico_p},0", pythoncom.VT_LPWSTR)
                store.SetValue(pscon.PKEY_AppUserModel_RelaunchIconResource, icon_prop)
                store.Commit()
            except Exception:
                pass
        except Exception as e:
            print(f"[Native Icon Error]: {e}", flush=True)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_native_win32_icon()
        if not getattr(self, "_initial_positioned", False):
            self._initial_positioned = True
            self._position_on_right_half()

    def _load_saved_mic_index(self) -> int | None:
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                val = cfg.get("Global", {}).get("MicrophoneIndex")
                if val is not None:
                    return int(val)
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
                    cfg = json.load(f)
                val = cfg.get("Global", {}).get("MicrophoneSensitivity")
                if val is not None:
                    return int(val)
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
            monitors = self.agent.controller.get_available_monitors()
            for m in monitors:
                self.combo_display.addItem(m["name"], m["index"])
            active_idx = getattr(self.agent.controller, "active_monitor_index", 0)
            idx_to_select = self.combo_display.findData(active_idx)
            if idx_to_select >= 0:
                self.combo_display.setCurrentIndex(idx_to_select)
            elif self.combo_display.count() > 0:
                self.combo_display.setCurrentIndex(0)
        except Exception as e:
            print(f"[Display Enum Error]: {e}", flush=True)
        finally:
            self.combo_display.blockSignals(False)

    def _on_display_changed(self, index: int):
        target_idx = self.combo_display.currentData()
        if target_idx is not None:
            self.agent.controller.set_monitor_index(target_idx)
            disp_name = self.combo_display.currentText()
            self._append_log(f"[DISPLAY TARGET] Navigating on: {disp_name}", C["neon_cyan"])
            cfg_p = ROOT_DIR / "config.json"
            try:
                cfg = {}
                if cfg_p.exists():
                    with open(cfg_p, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                cfg.setdefault("Global", {})["DisplayMonitorIndex"] = int(target_idx)
                with open(cfg_p, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass

    def _on_mood_changed(self, index: int):
        mood_key = self.combo_mood.currentData()
        if mood_key:
            self.agent.set_mood(mood_key)
            self._append_log(f"[PERSONA MOOD] Switched tone to: {self.combo_mood.currentText()}", C["neon_yellow"])

    def _populate_microphones(self):
        if not hasattr(self, "combo_mic_device") or self.combo_mic_device is None:
            return
        self.combo_mic_device.blockSignals(True)
        self.combo_mic_device.clear()
        if not HAS_SR:
            self.combo_mic_device.addItem("Microphone not available (SpeechRecognition missing)", None)
            self.combo_mic_device.blockSignals(False)
            return

        self.combo_mic_device.addItem("Default System Microphone", None)
        saved_idx = self._load_saved_mic_index()
        selected_index = 0

        try:
            mics = sr.Microphone.list_microphone_names()
            for idx, name in enumerate(mics):
                display_name = f"[{idx}] {name}"
                self.combo_mic_device.addItem(display_name, idx)
                if saved_idx is not None and saved_idx == idx:
                    selected_index = self.combo_mic_device.count() - 1
        except Exception as e:
            self.combo_mic_device.addItem(f"Error enumerating mics: {e}", None)

        self.combo_mic_device.setCurrentIndex(selected_index)
        self.combo_mic_device.blockSignals(False)

    def _on_mic_device_changed(self, combo_idx: int):
        dev_idx = self.combo_mic_device.currentData()
        if self.voice_listener:
            self.voice_listener.set_device_index(dev_idx)
        self._save_mic_index(dev_idx)
        dev_name = self.combo_mic_device.currentText()
        self._append_log(f"[MIC CONFIG] Active microphone switched to: {dev_name}", C["neon_cyan"])

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
        self._append_log(f"[MIC CONFIG] Microphone sensitivity threshold set to: {val}", C["text_dim"])

    def _save_gemini_key(self):
        new_key = self.input_gemini_key.text().strip()
        if not new_key:
            QMessageBox.warning(self, "API Key", "API key cannot be empty.")
            return
        os.environ["GEMINI_API_KEY"] = new_key
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["ApiKey"] = new_key
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception as e:
                self._append_log(f"[CONFIG ERROR] Failed to save Gemini key: {e}", C["neon_red"])
        try:
            from google import genai
            self.agent.client = genai.Client(api_key=new_key)
            self.agent.voice.client = self.agent.client
            self._append_log("[API CONFIG] Google Gemini API Key saved and client refreshed.", C["neon_green"])
            QMessageBox.information(self, "Saved", "Google Gemini API Key saved successfully.")
        except Exception as e:
            self._append_log(f"[API CONFIG WARNING] Key saved, client reload warning: {e}", C["neon_yellow"])

    def _test_gemini_key(self):
        key = self.input_gemini_key.text().strip() or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            QMessageBox.warning(self, "Test API", "Please enter a Gemini API Key first.")
            return
        self.btn_test_gemini.setText("🔌 TESTING...")
        self.btn_test_gemini.setEnabled(False)

        def _worker():
            try:
                from google import genai
                test_client = genai.Client(api_key=key)
                t0 = time.time()
                resp = test_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents="Ping"
                )
                latency = round((time.time() - t0) * 1000)
                reply = resp.text[:20].strip() if resp and resp.text else "OK"
                self.signals.log_message.emit(f"[API TEST] Gemini API responded successfully in {latency}ms: '{reply}'", C["neon_green"])
            except Exception as e:
                self.signals.log_message.emit(f"[API TEST FAILED] Gemini API Error: {e}", C["neon_red"])
            finally:
                QTimer.singleShot(0, lambda: self.btn_test_gemini.setText("🔌 TEST"))
                QTimer.singleShot(0, lambda: self.btn_test_gemini.setEnabled(True))

        threading.Thread(target=_worker, daemon=True).start()

    def _save_modal_endpoint(self):
        new_url = self.input_modal_endpoint.text().strip()
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["VllmEndpoint"] = new_url
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
                self.agent.vllm_endpoint = new_url
                self._append_log(f"[MODAL CONFIG] Modal vLLM Endpoint saved: {new_url}", C["neon_cyan"])
                QMessageBox.information(self, "Saved", "Modal vLLM Endpoint URL saved.")
            except Exception as e:
                self._append_log(f"[CONFIG ERROR] Failed to save Modal endpoint: {e}", C["neon_red"])

    def _save_modal_key(self):
        new_token = self.input_modal_key.text().strip()
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["VllmApiKey"] = new_token
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
                self.agent.vllm_api_key = new_token
                self._append_log("[MODAL CONFIG] Modal API Token saved.", C["neon_cyan"])
                QMessageBox.information(self, "Saved", "Modal API Token saved.")
            except Exception as e:
                self._append_log(f"[CONFIG ERROR] Failed to save Modal key: {e}", C["neon_red"])

    def _test_voice_playback(self):
        self._append_log("[VOICE TEST] Testing Google Leda voice synthesis...", C["neon_blue"])
        def _worker():
            try:
                self.agent.voice.speak_sync("Voice synthesis operational. Google Leda ready.", wait=True)
            except Exception as e:
                self.signals.log_message.emit(f"[VOICE TEST ERROR] {e}", C["neon_red"])
        threading.Thread(target=_worker, daemon=True).start()

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
        display_text = {
            "ready": "READY // LISTENING",
            "listening": "CAPTURING VOICE...",
            "generating": "GENERATING RESPONSE...",
            "processing": "PROCESSING SPEECH...",
            "speaking": "SPEAKING (LEDA)...",
            "standby": "STANDBY // OFFLINE",
            "offline": "STANDBY // OFFLINE",
            "error": f"ERROR: {details}" if details else "ERROR DETECTED",
        }.get(phase_l, phase.upper())

        if hasattr(self, "lbl_status") and self.lbl_status is not None:
            self.lbl_status.setText(display_text)
            self.lbl_status.setStyleSheet(f"color: {col}; font-weight: bold; border: none;")
        if hasattr(self, "status_card") and self.status_card is not None:
            self.status_card.setStyleSheet(f"background: {C['bg_dark']}; border: 1.5px solid {col}55; border-radius: 6px; padding: 6px;")
        if self.hud:
            self.hud.set_state(phase_l, details)
        if hasattr(self, "voice_bar") and self.voice_bar is not None:
            if phase_l in ("listening", "user"):
                self.voice_bar.set_state("user")
            elif phase_l in ("speaking", "ai"):
                self.voice_bar.set_state("ai")
            else:
                self.voice_bar.set_state("idle")

    def _init_settings_controls(self):
        # 1. Cognitive Backend
        self.backend_card = QFrame()
        self.btn_backend_gemini = QPushButton("⚡ Google Gemini (Flash-Lite)")
        self.btn_backend_gemini.setFixedHeight(32)
        self.btn_backend_gemini.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_backend_gemini.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backend_gemini.clicked.connect(lambda: self._select_backend("gemini"))

        self.btn_backend_modal = QPushButton("🔥 Modal HuiHui-Qwen3 (Uncensored)")
        self.btn_backend_modal.setFixedHeight(32)
        self.btn_backend_modal.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_backend_modal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backend_modal.clicked.connect(lambda: self._select_backend("modal_qwen"))

        self.btn_deploy_vllm = QPushButton("🚀 DEPLOY MODAL vLLM")
        self.btn_deploy_vllm.setFixedHeight(28)
        self.btn_deploy_vllm.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_deploy_vllm.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: #ff5577;
                border: 1px solid {C['neon_red']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #fff;
            }}
        """)
        self.btn_deploy_vllm.clicked.connect(self._deploy_modal_vllm)

        # 2. Voice
        self.voice_card = QFrame()
        self.btn_voice_leda = QPushButton("✨ Google Leda  [ACTIVE ✓]")
        self.btn_voice_leda.setFixedHeight(30)
        self.btn_voice_leda.setFont(QFont("Consolas", 8, QFont.Weight.Bold))

        # 3. Desktop & Tools
        self.btn_desktop_ctrl = QPushButton()
        self.btn_desktop_ctrl.setFixedHeight(28)
        self.btn_desktop_ctrl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_desktop_ctrl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_desktop_ctrl.clicked.connect(self._toggle_desktop_control)
        self._update_desktop_control_style()

        self.btn_duplex = QPushButton()
        self.btn_duplex.setFixedHeight(28)
        self.btn_duplex.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_duplex.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_duplex.clicked.connect(self._toggle_duplex_mode)
        self._update_duplex_style()

        self.btn_overlay = QPushButton("🌐 COORDINATE GRID [OFF]")
        self.btn_overlay.setFixedHeight(28)
        self.btn_overlay.setFont(QFont("Consolas", 8))
        self.btn_overlay.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.btn_overlay.clicked.connect(self._toggle_overlay)

        self.btn_calib = QPushButton("🎯 SCREEN CALIBRATION")
        self.btn_calib.setFixedHeight(28)
        self.btn_calib.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_calib.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_blue']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_calib.clicked.connect(self._start_calibration_task)

        # 4. Proactivity
        self.btn_proact = QPushButton("🤖 PROACTIVE [ON]")
        self.btn_proact.setFixedHeight(28)
        self.btn_proact.setFont(QFont("Consolas", 8))
        self.btn_proact.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_cyan']};
                border-radius: 3px;
            }}
        """)
        self.btn_proact.clicked.connect(self._toggle_proactivity)

        self.combo_idle_time = QComboBox()
        self.combo_idle_time.setFixedHeight(28)
        self.combo_idle_time.setFont(QFont("Consolas", 8))
        self.combo_idle_time.addItems(["30s", "45s", "60s", "90s"])
        self.combo_idle_time.setCurrentText("45s")
        self.combo_idle_time.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 4px;
            }}
        """)
        self.combo_idle_time.currentIndexChanged.connect(self._on_idle_time_changed)

        # 5. Mic Toggle
        self.btn_mic = QPushButton("🎙 MIC: MUTED [STANDBY]")
        self.btn_mic.setFixedHeight(28)
        self.btn_mic.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_mic.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.btn_mic.clicked.connect(self._toggle_mic)

        # Mood & Persona Controls
        self.combo_mood = QComboBox()
        self.combo_mood.setFont(QFont("Consolas", 8))
        self.combo_mood.setFixedHeight(28)
        self.combo_mood.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
            QComboBox:focus {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.combo_mood.addItem("Default / Direct Alpha", "default")
        self.combo_mood.addItem("Sassy & Playful", "sassy")
        self.combo_mood.addItem("Professional & Technical", "professional")
        self.combo_mood.addItem("Goofy & Humorous", "goofy")
        self.combo_mood.addItem("Tactical & Minimal", "tactical")
        self.combo_mood.addItem("Darkened State / Luci", "luci")
        curr_m = getattr(self.agent, "current_mood", "default")
        idx_m = self.combo_mood.findData(curr_m)
        if idx_m >= 0:
            self.combo_mood.setCurrentIndex(idx_m)
        self.combo_mood.currentIndexChanged.connect(self._on_mood_changed)

        # Multi-Monitor Display Selector
        self.combo_display = QComboBox()
        self.combo_display.setFont(QFont("Consolas", 8))
        self.combo_display.setFixedHeight(28)
        self.combo_display.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
            QComboBox:focus {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.combo_display.currentIndexChanged.connect(self._on_display_changed)

        self.btn_refresh_displays = QPushButton("🔄 REFRESH")
        self.btn_refresh_displays.setFixedSize(85, 28)
        self.btn_refresh_displays.setFont(QFont("Consolas", 8))
        self.btn_refresh_displays.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_refresh_displays.clicked.connect(self._populate_displays)

        # 6. Alexa
        self.btn_alexa = QPushButton("📡 ALEXA INGRESS [OFF]")
        self.btn_alexa.setFixedHeight(28)
        self.btn_alexa.setFont(QFont("Consolas", 8))
        self.btn_alexa.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {C['neon_cyan']};
                color: {C['text_bright']};
            }}
        """)
        self.btn_alexa.clicked.connect(self._toggle_alexa_ingress)

        self.btn_alexa_cfg = QPushButton("⚙️")
        self.btn_alexa_cfg.setFixedSize(28, 28)
        self.btn_alexa_cfg.setFont(QFont("Consolas", 9))
        self.btn_alexa_cfg.setStyleSheet(f"""
            QPushButton {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.btn_alexa_cfg.clicked.connect(self._open_alexa_dialog)

    def _build_console_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Top Bar (Header + Session + HUD toggle + Clear log)
        top_bar = QHBoxLayout()
        term_title = QLabel("EXECUTION LOG")
        term_title.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        term_title.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        top_bar.addWidget(term_title)

        # Animated Audio Reactive VoiceBar
        self.voice_bar = VoiceBar(bars=16, parent=widget)
        top_bar.addSpacing(6)
        top_bar.addWidget(self.voice_bar, 1)
        top_bar.addSpacing(6)

        self.btn_session_top = QPushButton("📁 SESSIONS")
        self.btn_session_top.setFixedSize(78, 22)
        self.btn_session_top.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_session_top.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_session_top.clicked.connect(self._open_session_selector)
        top_bar.addWidget(self.btn_session_top)

        self.btn_hud_toggle = QPushButton("💡 HUD [ON]")
        self.btn_hud_toggle.setFixedSize(85, 22)
        self.btn_hud_toggle.setFont(QFont("Consolas", 8))
        self.btn_hud_toggle.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_cyan']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_cyan']}44;
            }}
        """)
        self.btn_hud_toggle.clicked.connect(self._toggle_hud)
        top_bar.addWidget(self.btn_hud_toggle)

        self.btn_clear = QPushButton("CLEAR")
        self.btn_clear.setFixedSize(55, 22)
        self.btn_clear.setFont(QFont("Consolas", 8))
        self.btn_clear.setStyleSheet(f"color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        self.btn_clear.clicked.connect(lambda: self.log_box.clear())
        top_bar.addWidget(self.btn_clear)
        layout.addLayout(top_bar)

        # Terminal Log View
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
                line-height: 1.4;
            }}
        """)
        layout.addWidget(self.log_box, 1)

        # Bottom Input Row
        inp_row = QHBoxLayout()
        inp_row.setSpacing(8)

        prompt_lbl = QLabel(">>")
        prompt_lbl.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        prompt_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        inp_row.addWidget(prompt_lbl)

        self.cmd_input = QLineEdit()
        self.cmd_input.setFixedHeight(36)
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setPlaceholderText("Type objective here or speak naturally into your microphone...")
        self.cmd_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_dark']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 10px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C['neon_cyan']};
            }}
        """)
        self.cmd_input.returnPressed.connect(self._send_text_command)
        inp_row.addWidget(self.cmd_input, 1)

        self.btn_send = QPushButton("EXECUTE")
        self.btn_send.setFixedSize(90, 36)
        self.btn_send.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_send.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']};
                color: #000;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: #fff;
            }}
        """)
        self.btn_send.clicked.connect(self._send_text_command)
        inp_row.addWidget(self.btn_send)
        layout.addLayout(inp_row)

        return widget

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {C['bg_dark']};
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {C['border']};
                min-height: 25px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C['neon_cyan']};
            }}
        """)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Card 1: Audio & Microphone Hardware ──────────────────────
        card_audio = QFrame()
        card_audio.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ca_layout = QVBoxLayout(card_audio)
        ca_layout.setSpacing(8)

        ca_hdr = QLabel("🎙 AUDIO & MICROPHONE HARDWARE")
        ca_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        ca_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        ca_layout.addWidget(ca_hdr)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(6)
        lbl_mic_dev = QLabel("Microphone Device:")
        lbl_mic_dev.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_mic_dev.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        dev_row.addWidget(lbl_mic_dev)

        self.combo_mic_device = QComboBox()
        self.combo_mic_device.setFont(QFont("Consolas", 8))
        self.combo_mic_device.setFixedHeight(28)
        self.combo_mic_device.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
            QComboBox:focus {{
                border-color: {C['neon_cyan']};
            }}
        """)
        self.combo_mic_device.currentIndexChanged.connect(self._on_mic_device_changed)
        dev_row.addWidget(self.combo_mic_device, 1)

        self.btn_refresh_mics = QPushButton("🔄 REFRESH")
        self.btn_refresh_mics.setFixedSize(85, 28)
        self.btn_refresh_mics.setFont(QFont("Consolas", 8))
        self.btn_refresh_mics.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_refresh_mics.clicked.connect(self._populate_microphones)
        dev_row.addWidget(self.btn_refresh_mics)
        ca_layout.addLayout(dev_row)

        sens_row = QHBoxLayout()
        sens_row.setSpacing(6)
        lbl_sens = QLabel("Voice Sensitivity:")
        lbl_sens.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_sens.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        sens_row.addWidget(lbl_sens)

        self.combo_mic_sens = QComboBox()
        self.combo_mic_sens.setFont(QFont("Consolas", 8))
        self.combo_mic_sens.setFixedHeight(28)
        self.combo_mic_sens.addItems([
            "High Sensitivity (150)",
            "Normal Sensitivity (240) [Default]",
            "Low Sensitivity (450)",
            "Noisy Environment (800)"
        ])
        saved_th = self._load_saved_mic_sensitivity()
        if saved_th <= 180:
            self.combo_mic_sens.setCurrentIndex(0)
        elif saved_th <= 300:
            self.combo_mic_sens.setCurrentIndex(1)
        elif saved_th <= 600:
            self.combo_mic_sens.setCurrentIndex(2)
        else:
            self.combo_mic_sens.setCurrentIndex(3)

        self.combo_mic_sens.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
        """)
        self.combo_mic_sens.currentTextChanged.connect(self._on_mic_sens_changed)
        sens_row.addWidget(self.combo_mic_sens, 1)
        ca_layout.addLayout(sens_row)

        mic_ctrl_row = QHBoxLayout()
        mic_ctrl_row.setSpacing(8)
        mic_ctrl_row.addWidget(self.btn_duplex, 1)
        mic_ctrl_row.addWidget(self.btn_mic, 1)
        ca_layout.addLayout(mic_ctrl_row)

        layout.addWidget(card_audio)

        # ── Card 2: API Keys & Credentials ───────────────────────────
        card_api = QFrame()
        card_api.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        api_layout = QVBoxLayout(card_api)
        api_layout.setSpacing(8)

        api_hdr = QLabel("🔑 API KEYS & MODEL CREDENTIALS")
        api_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        api_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        api_layout.addWidget(api_hdr)

        lbl_gem = QLabel("Google Gemini API Key:")
        lbl_gem.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_gem.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        api_layout.addWidget(lbl_gem)

        gem_row = QHBoxLayout()
        gem_row.setSpacing(6)
        self.input_gemini_key = QLineEdit()
        self.input_gemini_key.setFixedHeight(28)
        self.input_gemini_key.setFont(QFont("Consolas", 8))
        self.input_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        gem_existing = os.environ.get("GEMINI_API_KEY", "")
        if not gem_existing:
            cfg_p = ROOT_DIR / "config.json"
            if cfg_p.exists():
                try:
                    with open(cfg_p, "r") as f:
                        gem_existing = json.load(f).get("Global", {}).get("ApiKey", "")
                except Exception:
                    pass
        self.input_gemini_key.setText(gem_existing)
        self.input_gemini_key.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
        """)
        gem_row.addWidget(self.input_gemini_key, 1)

        self.btn_toggle_gem = QPushButton("👁")
        self.btn_toggle_gem.setFixedSize(28, 28)
        self.btn_toggle_gem.setFont(QFont("Consolas", 8))
        self.btn_toggle_gem.setToolTip("Show/Hide Key")
        self.btn_toggle_gem.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        def _toggle_gem_echo():
            if self.input_gemini_key.echoMode() == QLineEdit.EchoMode.Password:
                self.input_gemini_key.setEchoMode(QLineEdit.EchoMode.Normal)
                self.btn_toggle_gem.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; border-radius: 3px;")
            else:
                self.input_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
                self.btn_toggle_gem.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        self.btn_toggle_gem.clicked.connect(_toggle_gem_echo)
        gem_row.addWidget(self.btn_toggle_gem)

        self.btn_save_gem = QPushButton("💾 SAVE")
        self.btn_save_gem.setFixedSize(70, 28)
        self.btn_save_gem.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_save_gem.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_cyan']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_cyan']};
                color: #000;
            }}
        """)
        self.btn_save_gem.clicked.connect(self._save_gemini_key)
        gem_row.addWidget(self.btn_save_gem)

        self.btn_test_gemini = QPushButton("🔌 TEST")
        self.btn_test_gemini.setFixedSize(65, 28)
        self.btn_test_gemini.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_test_gemini.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_green']}22;
                color: {C['neon_green']};
                border: 1px solid {C['neon_green']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_green']};
                color: #000;
            }}
        """)
        self.btn_test_gemini.clicked.connect(self._test_gemini_key)
        gem_row.addWidget(self.btn_test_gemini)
        api_layout.addLayout(gem_row)

        lbl_mod = QLabel("Modal vLLM Endpoint URL:")
        lbl_mod.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_mod.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        api_layout.addWidget(lbl_mod)

        mod_row = QHBoxLayout()
        mod_row.setSpacing(6)
        self.input_modal_endpoint = QLineEdit()
        self.input_modal_endpoint.setFixedHeight(28)
        self.input_modal_endpoint.setFont(QFont("Consolas", 8))
        self.input_modal_endpoint.setText(getattr(self.agent, "vllm_endpoint", ""))
        self.input_modal_endpoint.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_card']};
                color: {C['neon_red']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
        """)
        mod_row.addWidget(self.input_modal_endpoint, 1)

        self.btn_save_modal_ep = QPushButton("💾 SAVE")
        self.btn_save_modal_ep.setFixedSize(70, 28)
        self.btn_save_modal_ep.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_save_modal_ep.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: #ff5577;
                border: 1px solid {C['neon_red']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #fff;
            }}
        """)
        self.btn_save_modal_ep.clicked.connect(self._save_modal_endpoint)
        mod_row.addWidget(self.btn_save_modal_ep)
        api_layout.addLayout(mod_row)

        lbl_mod_key = QLabel("Modal API Key / Token (Optional):")
        lbl_mod_key.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_mod_key.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        api_layout.addWidget(lbl_mod_key)

        mod_key_row = QHBoxLayout()
        mod_key_row.setSpacing(6)
        self.input_modal_key = QLineEdit()
        self.input_modal_key.setFixedHeight(28)
        self.input_modal_key.setFont(QFont("Consolas", 8))
        self.input_modal_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_modal_key.setText(getattr(self.agent, "vllm_api_key", ""))
        self.input_modal_key.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_card']};
                color: {C['text_bright']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 6px;
            }}
        """)
        mod_key_row.addWidget(self.input_modal_key, 1)

        self.btn_toggle_mod = QPushButton("👁")
        self.btn_toggle_mod.setFixedSize(28, 28)
        self.btn_toggle_mod.setFont(QFont("Consolas", 8))
        self.btn_toggle_mod.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        def _toggle_mod_echo():
            if self.input_modal_key.echoMode() == QLineEdit.EchoMode.Password:
                self.input_modal_key.setEchoMode(QLineEdit.EchoMode.Normal)
                self.btn_toggle_mod.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; border-radius: 3px;")
            else:
                self.input_modal_key.setEchoMode(QLineEdit.EchoMode.Password)
                self.btn_toggle_mod.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        self.btn_toggle_mod.clicked.connect(_toggle_mod_echo)
        mod_key_row.addWidget(self.btn_toggle_mod)

        self.btn_save_mod_key = QPushButton("💾 SAVE")
        self.btn_save_mod_key.setFixedSize(70, 28)
        self.btn_save_mod_key.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_save_mod_key.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_save_mod_key.clicked.connect(self._save_modal_key)
        mod_key_row.addWidget(self.btn_save_mod_key)
        api_layout.addLayout(mod_key_row)

        layout.addWidget(card_api)

        # ── Card 3: Cognitive Backend ────────────────────────────────
        self.backend_card.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        be_layout = QVBoxLayout(self.backend_card)
        be_layout.setSpacing(8)

        be_hdr = QLabel("🧠 COGNITIVE BACKEND ENGINE")
        be_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        be_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        be_layout.addWidget(be_hdr)

        be_row = QHBoxLayout()
        be_row.setSpacing(8)
        be_row.addWidget(self.btn_backend_gemini, 1)
        be_row.addWidget(self.btn_backend_modal, 1)
        be_layout.addLayout(be_row)

        be_layout.addWidget(self.btn_deploy_vllm)
        layout.addWidget(self.backend_card)

        # ── Card 4: Voice Synthesis ──────────────────────────────────
        card_voice = QFrame()
        card_voice.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        cv_layout = QVBoxLayout(card_voice)
        cv_layout.setSpacing(8)

        cv_hdr = QLabel("🔊 VOICE SYNTHESIS")
        cv_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        cv_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        cv_layout.addWidget(cv_hdr)

        cv_row = QHBoxLayout()
        cv_row.setSpacing(8)
        cv_row.addWidget(self.btn_voice_leda, 1)

        self.btn_test_voice = QPushButton("🔊 TEST VOICE")
        self.btn_test_voice.setFixedHeight(30)
        self.btn_test_voice.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_test_voice.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_test_voice.clicked.connect(self._test_voice_playback)
        cv_row.addWidget(self.btn_test_voice)
        cv_layout.addLayout(cv_row)

        layout.addWidget(card_voice)

        # ── Card 5: Persona & Mood Tuning ────────────────────────────
        card_mood = QFrame()
        card_mood.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        cm_layout = QVBoxLayout(card_mood)
        cm_layout.setSpacing(8)

        cm_hdr = QLabel("🎭 PERSONA & MOOD TUNING")
        cm_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        cm_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        cm_layout.addWidget(cm_hdr)

        mood_row = QHBoxLayout()
        mood_row.setSpacing(6)
        lbl_mood = QLabel("Agent Mood:")
        lbl_mood.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_mood.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        mood_row.addWidget(lbl_mood)
        mood_row.addWidget(self.combo_mood, 1)
        cm_layout.addLayout(mood_row)
        layout.addWidget(card_mood)

        # ── Card 6: Automation & Screen Tools ────────────────────────
        card_tools = QFrame()
        card_tools.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ct_layout = QVBoxLayout(card_tools)
        ct_layout.setSpacing(8)

        ct_hdr = QLabel("🖥 DESKTOP AUTOMATION & OVERLAYS")
        ct_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        ct_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        ct_layout.addWidget(ct_hdr)

        # Display selection row
        disp_row = QHBoxLayout()
        disp_row.setSpacing(6)
        lbl_disp = QLabel("Target Display:")
        lbl_disp.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_disp.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        disp_row.addWidget(lbl_disp)
        disp_row.addWidget(self.combo_display, 1)
        disp_row.addWidget(self.btn_refresh_displays)
        ct_layout.addLayout(disp_row)

        tools_grid = QGridLayout()
        tools_grid.setSpacing(8)
        tools_grid.addWidget(self.btn_desktop_ctrl, 0, 0)
        tools_grid.addWidget(self.btn_overlay, 0, 1)
        tools_grid.addWidget(self.btn_calib, 1, 0)

        self.btn_hud_settings = QPushButton("💡 STATUS HUD [ON]")
        self.btn_hud_settings.setFixedHeight(28)
        self.btn_hud_settings.setFont(QFont("Consolas", 8))
        self.btn_hud_settings.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_cyan']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_cyan']}44;
            }}
        """)
        self.btn_hud_settings.clicked.connect(self._toggle_hud)
        tools_grid.addWidget(self.btn_hud_settings, 1, 1)
        ct_layout.addLayout(tools_grid)

        layout.addWidget(card_tools)

        # ── Card 6: Proactivity & Integrations ───────────────────────
        card_integ = QFrame()
        card_integ.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ci_layout = QVBoxLayout(card_integ)
        ci_layout.setSpacing(8)

        ci_hdr = QLabel("🤖 PROACTIVITY & INTEGRATIONS")
        ci_hdr.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        ci_hdr.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        ci_layout.addWidget(ci_hdr)

        proact_row = QHBoxLayout()
        proact_row.setSpacing(6)
        proact_row.addWidget(self.btn_proact, 1)
        proact_row.addWidget(self.combo_idle_time)
        ci_layout.addLayout(proact_row)

        alexa_row = QHBoxLayout()
        alexa_row.setSpacing(6)
        alexa_row.addWidget(self.btn_alexa, 1)
        alexa_row.addWidget(self.btn_alexa_cfg)
        ci_layout.addLayout(alexa_row)

        layout.addWidget(card_integ)

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

        # ── Window Control Header (Title Bar + Minimize + Close) ────────────
        win_header = QFrame()
        win_header.setFixedHeight(34)
        win_header.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_dark']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 0 4px;
            }}
        """)
        wh_layout = QHBoxLayout(win_header)
        wh_layout.setContentsMargins(8, 0, 8, 0)
        wh_layout.setSpacing(8)

        app_icon = QLabel("⚡")
        app_icon.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        app_icon.setStyleSheet(f"color: {C['neon_cyan']}; border: none; background: transparent;")
        wh_layout.addWidget(app_icon)

        app_title = QLabel("ALPHA AGENT // v4.0")
        app_title.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        app_title.setStyleSheet(f"color: {C['text_bright']}; border: none; background: transparent;")
        wh_layout.addWidget(app_title)

        wh_layout.addStretch()

        # Minimize Button
        self.btn_win_min = QPushButton("🗕")
        self.btn_win_min.setFixedSize(28, 24)
        self.btn_win_min.setFont(QFont("Consolas", 9))
        self.btn_win_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_win_min.setToolTip("Minimize Window")
        self.btn_win_min.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: none;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']}33;
                color: {C['neon_cyan']};
            }}
        """)
        self.btn_win_min.clicked.connect(self.showMinimized)
        wh_layout.addWidget(self.btn_win_min)

        # Close / Exit Button
        self.btn_win_close = QPushButton("✕")
        self.btn_win_close.setFixedSize(28, 24)
        self.btn_win_close.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_win_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_win_close.setToolTip("Exit Application")
        self.btn_win_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: none;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #ffffff;
            }}
        """)
        self.btn_win_close.clicked.connect(self.close)
        wh_layout.addWidget(self.btn_win_close)

        root_vlayout.addWidget(win_header)

        # ── Main Content Area (Sidebar + Tabs) ──────────────────────────────
        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)

        # ── Left Sidebar (Streamlined, Non-Cluttered Controls) ───────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(215)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_card']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(10, 10, 10, 10)
        s_layout.setSpacing(8)

        # Model / Engine Badge
        self.model_lbl = QLabel()
        self.model_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.model_lbl.setWordWrap(True)
        s_layout.addWidget(self.model_lbl)

        # Power Button
        self.btn_power = QPushButton("⚡ START AGENT")
        self.btn_power.setFixedHeight(40)
        self.btn_power.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_power.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']};
                color: #000;
                border: none;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background: #ffffff;
            }}
        """)
        self.btn_power.clicked.connect(self._toggle_power)
        s_layout.addWidget(self.btn_power)

        # Status Card
        self.status_card = QFrame()
        self.status_card.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 6px;")
        sc_layout = QVBoxLayout(self.status_card)
        sc_layout.setSpacing(4)

        sc_lbl = QLabel("SYSTEM STATUS")
        sc_lbl.setFont(QFont("Consolas", 8))
        sc_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sc_layout.addWidget(sc_lbl)

        self.lbl_status = QLabel("STANDBY // OFFLINE")
        self.lbl_status.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sc_layout.addWidget(self.lbl_status)

        self.lbl_step = QLabel("Step: Ready")
        self.lbl_step.setFont(QFont("Consolas", 8))
        self.lbl_step.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sc_layout.addWidget(self.lbl_step)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C['border']};
                border-radius: 2px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {C['neon_cyan']};
                border-radius: 2px;
            }}
        """)
        sc_layout.addWidget(self.progress_bar)
        s_layout.addWidget(self.status_card)

        # Active Session Card
        self.session_card = QFrame()
        self.session_card.setStyleSheet(f"""
            QFrame {{
                background: {C['bg_dark']};
                border: 1px solid {C['border']};
                border-radius: 6px;
            }}
            QFrame:hover {{
                border-color: {C['neon_blue']};
            }}
        """)
        sess_layout = QVBoxLayout(self.session_card)
        sess_layout.setSpacing(4)
        sess_layout.setContentsMargins(8, 8, 8, 8)

        sess_hdr = QLabel("ACTIVE CONVERSATION")
        sess_hdr.setFont(QFont("Consolas", 8))
        sess_hdr.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sess_layout.addWidget(sess_hdr)

        self.lbl_session_name = QLabel(f"📁 {self.agent.current_session.upper()}")
        self.lbl_session_name.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_session_name.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        sess_layout.addWidget(self.lbl_session_name)

        self.lbl_session_stats = QLabel("Turns: ...")
        self.lbl_session_stats.setFont(QFont("Consolas", 8))
        self.lbl_session_stats.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sess_layout.addWidget(self.lbl_session_stats)

        self.btn_session = QPushButton("🔄 SWITCH SESSION...")
        self.btn_session.setFixedHeight(26)
        self.btn_session.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_session.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22;
                color: {C['neon_cyan']};
                border: 1px solid {C['neon_blue']};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C['neon_blue']};
                color: #000;
            }}
        """)
        self.btn_session.clicked.connect(self._open_session_selector)
        sess_layout.addWidget(self.btn_session)
        s_layout.addWidget(self.session_card)

        s_layout.addStretch()

        # Emergency Abort Button
        self.btn_abort = QPushButton("⛔ ABORT TASK (Ctrl+Z)")
        self.btn_abort.setFixedHeight(34)
        self.btn_abort.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_abort.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: {C['neon_red']};
                border: 1px solid {C['neon_red']};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #fff;
            }}
        """)
        self.btn_abort.clicked.connect(self._abort_task)
        s_layout.addWidget(self.btn_abort)

        main_layout.addWidget(sidebar)

        # ── Initialize Settings Controls ────────────────────────────────────
        self._init_settings_controls()

        # ── Right Area: Tabs (Console + Settings) ───────────────────────────
        self.main_tabs = QTabWidget()
        self.main_tabs.setUsesScrollButtons(True)
        self.main_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                background-color: {C['bg_card']};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background: {C['bg_dark']};
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-bottom: none;
                padding: 5px 8px;
                font-family: Consolas;
                font-size: 9px;
                font-weight: bold;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border-color: {C['neon_cyan']};
                border-bottom: 2px solid {C['neon_cyan']};
            }}
            QTabBar::tab:hover {{
                color: {C['text_bright']};
                border-color: {C['neon_blue']};
            }}
        """)

        # Tab 1: Console Tab
        console_widget = self._build_console_tab()
        self.main_tabs.addTab(console_widget, "💬 CONSOLE")

        # Tab 2: Memory Tab
        self.memory_tab = AgentMemoryTab(self)
        self.main_tabs.addTab(self.memory_tab, "🧠 MEMORY")

        # Tab 3: Studio Tab
        self.studio_tab = AgentStudioTab(self)
        self.main_tabs.addTab(self.studio_tab, "🎨 STUDIO")

        # Tab 4: Characters Tab
        self.characters_tab = AgentCharactersTab(self)
        self.main_tabs.addTab(self.characters_tab, "🎭 CHARACTERS")

        # Tab 5: Monitor Tab
        self.monitor_tab = AgentMonitorTab(self)
        self.main_tabs.addTab(self.monitor_tab, "📊 MONITOR")

        # Tab 6: Settings Tab
        settings_widget = self._build_settings_tab()
        self.main_tabs.addTab(settings_widget, "⚙️ SETTINGS")

        main_layout.addWidget(self.main_tabs, 1)
        root_vlayout.addLayout(main_layout, 1)

        # Update initial styles
        self._update_backend_style()
        self._update_voice_style()

        # Initial log
        self._append_log("AlphaCore Autonomous Desktop Agent Loaded.", C["neon_cyan"])
        self._append_log("Status: STANDBY. Configure your session or click 'START AGENT' to begin.", C["text_dim"])
        if HAS_SR:
            self._append_log("Voice recognition ready: will listen once the agent is started.", C["text_dim"])
        else:
            self._append_log("Note: speech_recognition not found. Type commands in the input box.", C["neon_yellow"])

    # ── Power & Connection Control ────────────────────────────────────────────
    def _toggle_power(self):
        if not self.is_connected:
            self._connect_agent()
        else:
            self._disconnect_agent()

    def _connect_agent(self):
        self.is_connected = True
        self.btn_power.setText("⏹ STOP AGENT")
        self.btn_power.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_red']}22;
                color: {C['neon_red']};
                border: 1.5px solid {C['neon_red']};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background: {C['neon_red']};
                color: #fff;
            }}
        """)
        if HAS_SR and self.voice_listener and self.mic_enabled:
            started = self.voice_listener.start()
            if started:
                self.btn_mic.setText("🎙 MIC: LISTENING [ON]")
                self.btn_mic.setStyleSheet(f"""
                    QPushButton {{
                        background: {C['neon_cyan']}22;
                        color: {C['neon_cyan']};
                        border: 1px solid {C['neon_cyan']};
                        border-radius: 3px;
                    }}
                """)
        self._update_status("READY // LISTENING", C["neon_green"])
        if self.hud:
            self.hud.set_state("listening")
        self._on_activity()
        self._append_log("[SYSTEM] AlphaCore Agent online and listening. Voice & vision active.", C["neon_green"])

        # Wake Modal GPU only when START AGENT is clicked
        if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
            self._trigger_modal_health_check()

    def _disconnect_agent(self):
        self.is_connected = False
        self._modal_checking = False
        self.modal_health_status = None
        self._update_backend_style()
        self.btn_power.setText("⚡ START AGENT")
        self.btn_power.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']};
                color: #000;
                border: none;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background: #ffffff;
            }}
        """)
        if HAS_SR and self.voice_listener and self.voice_listener.is_active:
            self.voice_listener.stop()
            self.btn_mic.setText("🎙 MIC: MUTED [STANDBY]")
            self.btn_mic.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                }}
            """)
        if self.agent.is_running:
            self.agent.is_running = False
        self._update_status("STANDBY // OFFLINE", C["text_dim"])
        if self.hud:
            self.hud.set_state("disconnected")
        self._append_log("[SYSTEM] AlphaCore Agent disconnected. In standby.", C["text_dim"])

    # ── Assistant Toolbox & Navigation Controls ───────────────────────────────
    def _toggle_mic(self):
        if not HAS_SR or not self.voice_listener:
            QMessageBox.information(self, "No Mic", "speech_recognition is not available on this machine.")
            return

        self.mic_enabled = not self.mic_enabled
        if not self.mic_enabled:
            if self.voice_listener.is_active:
                self.voice_listener.stop()
            self.btn_mic.setText("🎙 MIC: MUTED [OFF]")
            self.btn_mic.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_red']}22;
                    color: {C['neon_red']};
                    border: 1px solid {C['neon_red']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Microphone muted.", C["text_dim"])
        else:
            if self.is_connected:
                started = self.voice_listener.start()
                if started:
                    self.btn_mic.setText("🎙 MIC: LISTENING [ON]")
                    self.btn_mic.setStyleSheet(f"""
                        QPushButton {{
                            background: {C['neon_cyan']}22;
                            color: {C['neon_cyan']};
                            border: 1px solid {C['neon_cyan']};
                            border-radius: 3px;
                        }}
                    """)
                    self._append_log("Microphone listening in background...", C["neon_cyan"])
            else:
                self.btn_mic.setText("🎙 MIC: ARMED (START AGENT)")
                self.btn_mic.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {C['neon_cyan']};
                        border: 1px solid {C['neon_cyan']};
                        border-radius: 3px;
                    }}
                """)

    def _toggle_hud(self):
        if self.hud.isVisible():
            self.hud.hide()
            text_short = "💡 HUD [OFF]"
            text_long = "💡 STATUS HUD [OFF]"
            style = f"background: transparent; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;"
            self._append_log("Mini Status HUD hidden.", C["text_dim"])
        else:
            self.hud.show()
            text_short = "💡 HUD [ON]"
            text_long = "💡 STATUS HUD [ON]"
            style = f"background: {C['neon_cyan']}22; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; border-radius: 3px;"
            self._append_log("Mini Status HUD enabled (draggable floating status pill).", C["neon_cyan"])

        if hasattr(self, "btn_hud_toggle") and self.btn_hud_toggle:
            self.btn_hud_toggle.setText(text_short)
            self.btn_hud_toggle.setStyleSheet(style)
        if hasattr(self, "btn_hud_settings") and self.btn_hud_settings:
            self.btn_hud_settings.setText(text_long)
            self.btn_hud_settings.setStyleSheet(style)

    def _toggle_proactivity(self):
        self.proactivity_enabled = not self.proactivity_enabled
        if self.proactivity_enabled:
            self.btn_proact.setText("🤖 PROACTIVE [ON]")
            self.btn_proact.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_cyan']}22;
                    color: {C['neon_cyan']};
                    border: 1px solid {C['neon_cyan']};
                    border-radius: 3px;
                }}
            """)
            self._append_log(f"Idle Proactivity enabled ({self.idle_timeout_seconds}s threshold).", C["neon_cyan"])
            self._on_activity()
        else:
            self.btn_proact.setText("🤖 PROACTIVE [OFF]")
            self.btn_proact.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Idle Proactivity disabled.", C["text_dim"])

    def _select_backend(self, backend_type: str):
        if getattr(self.agent, "backend_type", None) == backend_type:
            if backend_type == "modal_qwen" and self.is_connected and not self._modal_checking:
                self._trigger_modal_health_check()
            return
        self.agent.set_backend(backend_type)
        self._update_backend_style()
        if backend_type == "modal_qwen":
            self._append_log("[COGNITIVE BACKEND] Switched to 🔥 Modal HuiHui-Qwen3-14B (Abliterated/Uncensored vLLM on A10G).", C["neon_red"])
            if self.is_connected:
                self._trigger_modal_health_check()
        else:
            self._append_log("[COGNITIVE BACKEND] Switched to ⚡ Google Gemini (Flash-Lite / 3.8). Multimodal vision & fallback cascade active.", C["neon_cyan"])

    def _trigger_modal_health_check(self):
        if self._modal_checking:
            return
        self._modal_checking = True
        self._modal_check_start = time.time()
        self._update_backend_style()
        self._append_log("[MODAL HEALTH] Probing Modal vLLM endpoint (waking GPU from cold boot, up to 4 minutes)...", C["neon_yellow"])
        self._update_status("WAKING MODAL GPU...", C["neon_yellow"])
        if self.hud:
            self.hud.set_state("working", "WAKING GPU")

        # Live elapsed timer updating UI every second while cold-booting
        if not hasattr(self, "_modal_timer") or not self._modal_timer:
            self._modal_timer = QTimer(self)
            self._modal_timer.timeout.connect(self._on_modal_timer_tick)
        self._modal_timer.start(1000)

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                res = loop.run_until_complete(self.agent.check_modal_health(timeout=240.0))
                self.signals.modal_health_updated.emit(res)
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_modal_timer_tick(self):
        if not self._modal_checking:
            if hasattr(self, "_modal_timer") and self._modal_timer:
                self._modal_timer.stop()
            return
        elapsed = int(time.time() - getattr(self, "_modal_check_start", time.time()))
        mins, secs = divmod(elapsed, 60)
        time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
        self.btn_backend_modal.setText(f"🔥 Modal Qwen3  [WAKING GPU... {time_str}]")
        self.model_lbl.setText(f"ENGINE: HUIHUI-QWEN3-14B (WAKING GPU... {time_str})")
        if self.hud:
            self.hud.set_state("working", f"WAKING {time_str}")

    def _on_modal_health_updated(self, res: dict):
        self._modal_checking = False
        if hasattr(self, "_modal_timer") and self._modal_timer:
            self._modal_timer.stop()
        self.modal_health_status = res
        self._update_backend_style()
        if res.get("online"):
            ms = res.get("latency_ms", 0)
            cold_note = f" (Cold-Boot Wakeup in {round(ms/1000, 1)}s)" if res.get("is_cold") else ""
            self._append_log(f"[MODAL HEALTH] Endpoint is ONLINE and responsive ({ms}ms){cold_note}.", C["neon_green"])
            if getattr(self.agent, "backend_type", "") == "modal_qwen":
                if self.is_connected:
                    self._update_status("READY // LISTENING", C["neon_green"])
                    if self.hud:
                        self.hud.set_state("listening")
                else:
                    self._update_status("STANDBY // MODAL LIVE", C["neon_green"])
                    if self.hud:
                        self.hud.set_state("standby")
        else:
            err = res.get("error", "Unreachable")
            self._append_log(f"[MODAL HEALTH] Endpoint OFFLINE / TIMEOUT: {err}. Click '🚀 DEPLOY MODAL vLLM' to deploy or restart container.", C["neon_red"])
            if getattr(self.agent, "backend_type", "") == "modal_qwen":
                self._update_status("MODAL TIMEOUT", C["neon_red"])
                if self.hud:
                    self.hud.set_state("error", "Modal Timeout")

    def _update_backend_style(self):
        backend = getattr(self.agent, "backend_type", "gemini")
        if backend == "modal_qwen":
            if self._modal_checking:
                self.model_lbl.setText("ENGINE: HUIHUI-QWEN3-14B (WAKING GPU / CHECKING...)")
                self.model_lbl.setStyleSheet(f"color: {C['neon_yellow']}; border: none;")
                self.backend_card.setStyleSheet(f"""
                    QFrame {{
                        background: #191404;
                        border: 1.5px solid {C['neon_yellow']};
                        border-radius: 6px;
                    }}
                """)
                self.btn_backend_modal.setText("🔥 Modal Qwen3  [CHECKING / WAKING...]")
                self.btn_backend_modal.setStyleSheet(f"""
                    QPushButton {{
                        background: {C['neon_yellow']}25;
                        color: {C['neon_yellow']};
                        border: 1.5px solid {C['neon_yellow']};
                        border-radius: 4px;
                        text-align: left;
                        padding-left: 8px;
                    }}
                    QPushButton:hover {{
                        background: {C['neon_yellow']}40;
                    }}
                """)
            elif self.modal_health_status and self.modal_health_status.get("online"):
                ms = self.modal_health_status.get("latency_ms", 0)
                tag = f"[LIVE ✓ ({ms}ms)]"
                self.model_lbl.setText(f"ENGINE: HUIHUI-QWEN3-14B (MODAL A10G // {ms}ms // UNCENSORED)")
                self.model_lbl.setStyleSheet(f"color: {C['neon_red']}; border: none;")
                self.backend_card.setStyleSheet(f"""
                    QFrame {{
                        background: #14070d;
                        border: 1px solid {C['neon_red']};
                        border-radius: 6px;
                    }}
                """)
                self.btn_backend_modal.setText(f"🔥 Modal Qwen3-14B  {tag}")
                self.btn_backend_modal.setStyleSheet(f"""
                    QPushButton {{
                        background: {C['neon_red']}28;
                        color: #ff3366;
                        border: 1.5px solid {C['neon_red']};
                        border-radius: 4px;
                        text-align: left;
                        padding-left: 8px;
                    }}
                    QPushButton:hover {{
                        background: {C['neon_red']}44;
                    }}
                """)
            elif self.modal_health_status and not self.modal_health_status.get("online"):
                self.model_lbl.setText("ENGINE: HUIHUI-QWEN3-14B (OFFLINE // CHECK DEPLOY)")
                self.model_lbl.setStyleSheet(f"color: {C['neon_red']}; border: none;")
                self.backend_card.setStyleSheet(f"""
                    QFrame {{
                        background: #14070d;
                        border: 1px dashed {C['neon_red']};
                        border-radius: 6px;
                    }}
                """)
                self.btn_backend_modal.setText("🔥 Modal Qwen3-14B  [OFFLINE / UNREACHABLE]")
                self.btn_backend_modal.setStyleSheet(f"""
                    QPushButton {{
                        background: {C['neon_red']}18;
                        color: #ff6688;
                        border: 1.5px dashed {C['neon_red']};
                        border-radius: 4px;
                        text-align: left;
                        padding-left: 8px;
                    }}
                    QPushButton:hover {{
                        background: {C['neon_red']}30;
                    }}
                """)
            else:
                self.model_lbl.setText("ENGINE: HUIHUI-QWEN3-14B (MODAL A10G // UNCENSORED)")
                self.model_lbl.setStyleSheet(f"color: {C['neon_red']}; border: none;")
                self.backend_card.setStyleSheet(f"""
                    QFrame {{
                        background: #14070d;
                        border: 1px solid {C['neon_red']};
                        border-radius: 6px;
                    }}
                """)
                self.btn_backend_modal.setText("🔥 Modal Qwen3-14B  [ACTIVE ✓]")
                self.btn_backend_modal.setStyleSheet(f"""
                    QPushButton {{
                        background: {C['neon_red']}28;
                        color: #ff3366;
                        border: 1.5px solid {C['neon_red']};
                        border-radius: 4px;
                        text-align: left;
                        padding-left: 8px;
                    }}
                    QPushButton:hover {{
                        background: {C['neon_red']}44;
                    }}
                """)

            self.btn_backend_gemini.setText("⚡ Google Gemini (Flash-Lite)")
            self.btn_backend_gemini.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    border-color: {C['neon_cyan']};
                    color: {C['text_bright']};
                }}
            """)
        else:
            engine_name = self.agent.model_name.replace('models/', '').upper() if hasattr(self.agent, "model_name") else "GEMINI 2.5 FLASH-LITE"
            self.model_lbl.setText(f"ENGINE: {engine_name}")
            self.model_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
            self.backend_card.setStyleSheet(f"""
                QFrame {{
                    background: {C['bg_dark']};
                    border: 1px solid {C['neon_cyan']}55;
                    border-radius: 6px;
                }}
            """)
            self.btn_backend_gemini.setText("⚡ Google Gemini  [ACTIVE ✓]")
            self.btn_backend_gemini.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_cyan']}28;
                    color: {C['neon_cyan']};
                    border: 1.5px solid {C['neon_cyan']};
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    background: {C['neon_cyan']}44;
                }}
            """)
            if self.modal_health_status and self.modal_health_status.get("online"):
                self.btn_backend_modal.setText(f"🔥 Modal Qwen3 (Standby ✓ {self.modal_health_status['latency_ms']}ms)")
            else:
                self.btn_backend_modal.setText("🔥 Modal Qwen3 (Uncensored)")
            self.btn_backend_modal.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 4px;
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    border-color: {C['neon_red']};
                    color: {C['text_bright']};
                }}
            """)

    def _select_voice(self, voice_mode: str = "leda"):
        self.agent.set_voice_mode("leda")
        self._update_voice_style()
        self._append_log("[VOICE SYNTHESIS] Dedicated voice: ✨ Google Leda (Gemini Speech API).", C["neon_blue"])

    def _update_voice_style(self):
        self.voice_card.setStyleSheet(f"""
            QFrame {{
                background: {C['bg_dark']};
                border: 1px solid {C['neon_blue']}55;
                border-radius: 6px;
            }}
        """)
        self.btn_voice_leda.setText("✨ Google Leda  [ACTIVE ✓]")
        self.btn_voice_leda.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}28;
                color: {C['neon_cyan']};
                border: 1.5px solid {C['neon_blue']};
                border-radius: 4px;
                text-align: left;
                padding-left: 8px;
            }}
        """)

    def _toggle_desktop_control(self):
        new_val = not getattr(self.agent, "desktop_control", True)
        self.agent.set_desktop_control(new_val)
        self._update_desktop_control_style()
        if new_val:
            self._append_log("[DESKTOP CONTROL] OS mouse & keyboard control ENABLED.", C["neon_green"])
        else:
            self._append_log("[DESKTOP CONTROL] OS desktop control DISABLED. Operating in conversational/analytical mode.", C["neon_yellow"])

    def _update_desktop_control_style(self):
        dc = getattr(self.agent, "desktop_control", True)
        if dc:
            self.btn_desktop_ctrl.setText("🖥 DESKTOP CTRL: [ON]")
            self.btn_desktop_ctrl.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_green']}22;
                    color: {C['neon_green']};
                    border: 1px solid {C['neon_green']};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {C['neon_green']}44;
                }}
            """)
        else:
            self.btn_desktop_ctrl.setText("🖥 DESKTOP CTRL: [OFF]")
            self.btn_desktop_ctrl.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_yellow']}22;
                    color: {C['neon_yellow']};
                    border: 1px solid {C['neon_yellow']};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {C['neon_yellow']}44;
                }}
            """)

    def _toggle_duplex_mode(self):
        self.duplex_mode = "full" if self.duplex_mode == "half" else "half"
        if self.voice_listener:
            self.voice_listener.set_duplex_mode(self.duplex_mode)
        self._update_duplex_style()
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                cfg.setdefault("Global", {})["AudioMode"] = self.duplex_mode
                with open(cfg_path, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass
        if self.duplex_mode == "half":
            self._append_log("[MIC DUPLEX] Half-Duplex active: Mic pauses while Alpha speaks (zero self-interruptions).", C["neon_cyan"])
        else:
            self._append_log("[MIC DUPLEX] Full-Duplex active: Mic continuously active with live voice barge-in.", C["neon_yellow"])

    def _update_duplex_style(self):
        if self.duplex_mode == "half":
            self.btn_duplex.setText("🎙 MIC: HALF-DUPLEX [STABLE]")
            self.btn_duplex.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_cyan']}22;
                    color: {C['neon_cyan']};
                    border: 1px solid {C['neon_cyan']};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {C['neon_cyan']}44;
                }}
            """)
        else:
            self.btn_duplex.setText("🎙 MIC: FULL-DUPLEX [BARGE-IN]")
            self.btn_duplex.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_yellow']}22;
                    color: {C['neon_yellow']};
                    border: 1px solid {C['neon_yellow']};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {C['neon_yellow']}44;
                }}
            """)

    def _on_idle_time_changed(self, idx: int):
        val = self.combo_idle_time.currentText().replace("s", "").strip()
        try:
            self.idle_timeout_seconds = int(val)
            self._append_log(f"Idle Proactivity timeout set to {self.idle_timeout_seconds}s.", C["text_dim"])
            self._on_activity()
        except ValueError:
            pass

    def _check_proactivity(self):
        if not self.is_connected or not self.proactivity_enabled:
            return
        if self.agent.is_running or self._proactive_triggered:
            return

        elapsed = time.time() - self.last_activity_time
        if elapsed >= self.idle_timeout_seconds:
            self._proactive_triggered = True
            self._append_log(f"[IDLE PROACTIVITY] {int(elapsed)}s quiet. Inspecting desktop for proactive remarks...", C["neon_yellow"])
            goal = (
                f"[System Idle Proactivity]: Architect has been quiet for {int(elapsed)} seconds. "
                "Examine what is visible on Architect's screen in the screenshot. In Alpha's sharp, direct, charismatic "
                "personality, make a brief unsolicited remark, observation, or helpful reaction about what he is "
                "currently looking at or doing. Keep it concise (1-2 sentences). Do not mention that this was an automated idle trigger."
            )
            self._run_task(goal, is_proactive=True)

    def _on_activity(self):
        self.last_activity_time = time.time()
        self._proactive_triggered = False

    def _handle_voice_input(self, text: str):
        self.signals.voice_heard.emit(text)

    def _on_voice_heard(self, text: str):
        # Half-duplex guard: Drop speech if agent is busy (speaking, queued, or cooling down)
        if self.duplex_mode == "half" and self.agent.voice.is_busy():
            return

        # Echo suppression fallback: Drop if recognized text matches recent Alpha speech
        if hasattr(self.agent.voice, "is_echo") and self.agent.voice.is_echo(text):
            self._append_log(f"[ECHO SUPPRESSED] \"{text}\"", C["text_dim"])
            return

        self._on_activity()
        if not self.agent.is_running and not self.agent.voice.is_busy():
            self._append_log(f"[HEARD VOICE] \"{text}\"", C["neon_cyan"])
            self._run_task(text)
        else:
            if self.duplex_mode == "half":
                # Continuous voice steering during action execution without waiting for speech
                self._append_log(f"[VOICE STEERING] Steering instruction: \"{text}\"", C["neon_yellow"])
                self.agent.abort()
                QTimer.singleShot(100, lambda: self._run_task(text))
            else:
                # Full-duplex barge-in mode
                self._append_log(f"[VOICE BARGE-IN] Interrupted with: \"{text}\"", C["neon_yellow"])
                self.agent.abort()
                QTimer.singleShot(100, lambda: self._run_task(text))

    def _send_text_command(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        self.cmd_input.clear()
        if not self.is_connected:
            self._connect_agent()
        self._append_log(f"[YOU] {cmd}", C["neon_cyan"])
        self._on_activity()
        self._run_task(cmd)

    def _start_calibration_task(self):
        if self.calib_overlay is not None:
            self.calib_overlay.close()
        self.calib_overlay = CalibrationOverlay()
        self.calib_overlay.finished.connect(lambda: self._append_log("Calibration overlay finished!", C["neon_green"]))
        if not self.is_connected:
            self._connect_agent()
        self._on_activity()
        QTimer.singleShot(1000, lambda: self._run_task("Click the red boxes one at a time on the calibration screen until calibration is complete."))

    def _toggle_overlay(self):
        if self.overlay is None:
            self.overlay = CoordinateOverlay()
            self.btn_overlay.setText("🌐 COORDINATE GRID [ON]")
            self.btn_overlay.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_cyan']}22;
                    color: {C['neon_cyan']};
                    border: 1px solid {C['neon_cyan']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Coordinate Grid Overlay enabled (200px lines + live crosshair).", C["neon_cyan"])
        else:
            self.overlay.close()
            self.overlay = None
            self.btn_overlay.setText("🌐 COORDINATE GRID [OFF]")
            self.btn_overlay.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_bright']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Coordinate Grid Overlay closed.", C["text_dim"])

    def _deploy_modal_vllm(self):
        reply = QMessageBox.question(
            self,
            "Deploy Modal vLLM",
            "Deploy warshanks/HuiHui-Qwen3-14B-AWQ (Uncensored) to Modal GPU (A10G)?\n\nThis executes 'modal deploy Vllm.py' in the background.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._append_log("[MODAL DEPLOY] Launching deployment of HuiHui-Qwen3-14B on Modal A10G...", C["neon_red"])
        self.btn_deploy_vllm.setEnabled(False)
        self.btn_deploy_vllm.setText("🚀 DEPLOYING...")

        def _worker():
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "modal", "deploy", "Vllm.py"],
                    cwd=str(ROOT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                for line in proc.stdout:
                    l = line.strip()
                    if l:
                        self.signals.log_message.emit(f"[MODAL] {l}", C["text_dim"])
                proc.wait()
                if proc.returncode == 0:
                    self.signals.log_message.emit("[MODAL DEPLOY] Deployment successful! Endpoint is online.", C["neon_green"])
                    QTimer.singleShot(500, self._trigger_modal_health_check)
                else:
                    self.signals.log_message.emit(f"[MODAL DEPLOY] Deployment finished with exit code {proc.returncode}.", C["neon_yellow"])
            except Exception as e:
                self.signals.log_message.emit(f"[MODAL DEPLOY ERROR] {e}", C["neon_red"])
            finally:
                QTimer.singleShot(0, lambda: self.btn_deploy_vllm.setEnabled(True))
                QTimer.singleShot(0, lambda: self.btn_deploy_vllm.setText("🚀 DEPLOY MODAL vLLM"))

        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_alexa_ingress(self):
        try:
            from integrations.alexa_ingress import start_ingress_server_thread, stop_ingress_server, is_ingress_running
            if not is_ingress_running():
                started = start_ingress_server_thread(port=8765)
                if started:
                    self.btn_alexa.setText("📡 ALEXA INGRESS [ON]")
                    self.btn_alexa.setStyleSheet(f"""
                        QPushButton {{
                            background: {C['neon_green']}22;
                            color: {C['neon_green']};
                            border: 1px solid {C['neon_green']};
                            border-radius: 3px;
                        }}
                    """)
                    self._append_log("[ALEXA INGRESS] Listener active on http://0.0.0.0:8765. Remote voice & vision-grounded desktop control enabled.", C["neon_green"])
            else:
                stop_ingress_server()
                self.btn_alexa.setText("📡 ALEXA INGRESS [OFF]")
                self.btn_alexa.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {C['text_dim']};
                        border: 1px solid {C['border']};
                        border-radius: 3px;
                    }}
                """)
                self._append_log("[ALEXA INGRESS] Ingress server stopped.", C["text_dim"])
        except Exception as e:
            self._append_log(f"[ALEXA INGRESS ERROR] {e}", C["neon_red"])

    def _open_alexa_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Alexa Ingress & Webhook Configuration")
        dlg.resize(520, 320)
        dlg.setStyleSheet(f"background-color: {C['bg_dark']}; border: 1px solid {C['border']}; color: {C['text_bright']};")
        d_layout = QVBoxLayout(dlg)
        d_layout.setContentsMargins(16, 16, 16, 16)
        d_layout.setSpacing(10)

        title = QLabel("📡 ALEXA / LAMBDA INGRESS INTEGRATION")
        title.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        d_layout.addWidget(title)

        info = QLabel(
            "The Alexa Ingress Listener receives remote voice & visual grounding commands from your Alexa Skill / Lambda function.\n\n"
            "• Local Webhook URL: http://localhost:8765/api/action\n"
            "• Vision-Grounded Click URL: http://localhost:8765/api/vision_click\n"
            "• Health Check: http://localhost:8765/health"
        )
        info.setFont(QFont("Consolas", 8))
        info.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        info.setWordWrap(True)
        d_layout.addWidget(info)

        url_lbl = QLabel("External Tunnel URL (Cloudflare Tunnel, Ngrok, or Tailscale):")
        url_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        url_lbl.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        d_layout.addWidget(url_lbl)

        url_input = QLineEdit()
        url_input.setFixedHeight(32)
        url_input.setFont(QFont("Consolas", 9))
        url_input.setPlaceholderText("https://your-tunnel.trycloudflare.com")

        # Load existing config
        cfg_path = ROOT_DIR / "config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    c = json.load(f)
                    url_input.setText(c.get("Global", {}).get("AlexaWebhookUrl", ""))
            except Exception:
                pass

        url_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 4px;
                padding: 0 8px;
            }}
        """)
        d_layout.addWidget(url_input)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_save = QPushButton("SAVE CONFIG")
        btn_save.setFixedSize(120, 32)
        btn_save.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']};
                color: #000;
                border-radius: 4px;
            }}
        """)
        def _save_cfg():
            new_url = url_input.text().strip()
            if cfg_path.exists():
                try:
                    with open(cfg_path, "r") as f:
                        c = json.load(f)
                    c.setdefault("Global", {})["AlexaWebhookUrl"] = new_url
                    with open(cfg_path, "w") as f:
                        json.dump(c, f, indent=4)
                    self._append_log(f"[ALEXA CONFIG] Tunnel URL updated: {new_url}", C["neon_cyan"])
                except Exception as ex:
                    self._append_log(f"[ALEXA CONFIG ERROR] {ex}", C["neon_red"])
            dlg.accept()

        btn_save.clicked.connect(_save_cfg)
        btn_box.addWidget(btn_save)

        d_layout.addLayout(btn_box)
        dlg.exec()

    def _abort_task(self):
        self.agent.abort()
        self._append_log("[ABORT] Emergency stop triggered by user.", C["neon_red"])
        self._set_phase("error", "Task Aborted")

    def _run_task(self, goal: str, is_proactive: bool = False):
        if self.agent.is_running:
            # Preempt previous task cleanly instead of blocking
            self.agent.abort()
            if hasattr(self, "_current_task_thread") and self._current_task_thread and self._current_task_thread.is_alive():
                self._current_task_thread.join(timeout=0.25)

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
        def _on_step(current, total):
            self.signals.step_updated.emit(current, total)

        def _on_status(status_str):
            st = status_str.lower()
            if "gen" in st:
                self.signals.status_phase.emit("generating", "")
            elif "proc" in st:
                self.signals.status_phase.emit("processing", "")
            elif "speak" in st:
                self.signals.status_phase.emit("speaking", "")
            elif "ready" in st:
                self.signals.status_phase.emit("ready", "")

        def _on_log(text, level):
            color = C["text_bright"]
            if level in ("error", "red"):
                color = C["neon_red"]
                self.signals.status_phase.emit("error", "API ERROR")
            elif level in ("warn", "yellow"):
                color = C["neon_yellow"]
            elif level in ("cyan", "action"):
                color = C["neon_cyan"]
            elif level in ("green", "success"):
                color = C["neon_green"]
            elif level in ("dim", "step"):
                color = C["text_dim"]
            self.signals.log_message.emit(text, color)

        try:
            await self.agent.execute_turn(goal, on_step=_on_step, on_log=_on_log, on_status=_on_status)
        except Exception as e:
            self.signals.log_message.emit(f"[Agent Execution Error]: {e}", C["neon_red"])
            self.signals.status_phase.emit("error", str(e))
        finally:
            self.signals.task_finished.emit()

    def _append_log(self, text: str, color: str):
        t_stamp = time.strftime("[%H:%M:%S]")
        html = f"<span style='color:{C['text_dim']}'>{t_stamp}</span> <span style='color:{color}'>{text}</span>"
        self.log_box.append(html)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self, text: str, color: str = None):
        t_upper = text.upper()
        if "ERR" in t_upper or "ABORT" in t_upper:
            self._set_phase("error", text)
        elif "GEN" in t_upper:
            self._set_phase("generating", text)
        elif "PROC" in t_upper:
            self._set_phase("processing", text)
        elif "SPEAK" in t_upper:
            self._set_phase("speaking", text)
        elif "WORK" in t_upper or "EXEC" in t_upper:
            self._set_phase("generating", text)
        elif "LISTEN" in t_upper:
            self._set_phase("listening")
        elif "READY" in t_upper:
            self._set_phase("ready")
        elif "DISCONNECT" in t_upper or "OFFLINE" in t_upper:
            self._set_phase("offline")
        elif "STANDBY" in t_upper:
            self._set_phase("standby")
        else:
            self.lbl_status.setText(text)
            if color:
                self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold; border: none;")
            if self.hud:
                self.hud.set_state("working", text)

    def _update_step(self, current: int, total: int):
        self.lbl_step.setText(f"Action Step: {current}")
        self.lbl_status.setText(f"EXECUTING STEP {current}")
        self.lbl_status.setStyleSheet(f"color: {C['neon_yellow']}; font-weight: bold; border: none;")
        self.progress_bar.setRange(0, 0)
        if self.hud:
            self.hud.set_state("generating", f"STEP {current}")

    def _update_screen_preview(self, pil_img):
        pass

    def _on_task_finished(self):
        self.lbl_step.setText("Step: Ready")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._update_session_display()
        self._on_activity()

        if "ERR" in self.lbl_status.text().upper():
            self._set_phase("error", "Task execution error")
        else:
            if self.is_connected:
                self._set_phase("ready")
            else:
                self._set_phase("standby")

    def _open_session_selector(self):
        dlg = SessionSelectorDialog(
            current_session=self.agent.current_session,
            session_manager=self.agent.session_manager,
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_sess = dlg.selected_session
            if new_sess != self.agent.current_session:
                switched = self.agent.switch_session(new_sess)
                self._update_session_display()
                self._append_log(f"[SESSION ACTIVATED] Switched to '{switched}'. Prior history and memory context injected.", C["neon_cyan"])
                threading.Thread(target=lambda: self.agent.voice.speak(f"Session {switched} loaded."), daemon=True).start()

    def _update_session_display(self):
        sess_name = self.agent.current_session
        self.lbl_session_name.setText(f"📁 {sess_name.upper()}")
        if self.agent.session_manager:
            sess_file = self.agent.session_manager.get_session_file(sess_name)
            if sess_file.exists():
                try:
                    size_kb = round(sess_file.stat().st_size / 1024, 1)
                    with open(sess_file, "r", encoding="utf-8", errors="ignore") as f:
                        turns = sum(1 for ln in f if ln.strip().startswith("[You]:"))
                    self.lbl_session_stats.setText(f"Turns: {turns}  |  Size: {size_kb} KB")
                    return
                except Exception:
                    pass
        self.lbl_session_stats.setText("Turns: 0  |  Size: 0 KB")

def from_system_prompt():
    from core.alpha_agent import ALPHACORE_SYSTEM_PROMPT
    return ALPHACORE_SYSTEM_PROMPT

def _ensure_taskbar_registration():
    try:
        import win32com.client
        from win32com.propsys import propsys, pscon
        import pythoncom

        ico_path = ROOT_DIR / "alphalive.ico"
        target_bat = ROOT_DIR / "start.bat"

        # Start Menu shortcut
        appdata = os.environ.get("APPDATA")
        if appdata:
            start_menu_lnk = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\AlphaLive.lnk")
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(start_menu_lnk)
            sc.TargetPath = str(target_bat)
            sc.WorkingDirectory = str(ROOT_DIR)
            sc.IconLocation = f"{ico_path},0"
            sc.Description = "AlphaLive Autonomous AI Agent"
            sc.Save()

            store = propsys.SHGetPropertyStoreFromParsingName(start_menu_lnk, None, 2, propsys.IID_IPropertyStore)
            appid_prop = propsys.PROPVARIANTType("alphacore.alphalive.agent.v4", pythoncom.VT_LPWSTR)
            store.SetValue(pscon.PKEY_AppUserModel_ID, appid_prop)
            store.Commit()

        # Desktop shortcut
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            desktop_lnk = os.path.join(user_profile, r"Desktop\AlphaLive.lnk")
            if os.path.exists(desktop_lnk):
                store = propsys.SHGetPropertyStoreFromParsingName(desktop_lnk, None, 2, propsys.IID_IPropertyStore)
                appid_prop = propsys.PROPVARIANTType("alphacore.alphalive.agent.v4", pythoncom.VT_LPWSTR)
                store.SetValue(pscon.PKEY_AppUserModel_ID, appid_prop)
                store.Commit()
    except Exception:
        pass

def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("alphacore.alphalive.agent.v4")
    except Exception:
        pass
    _ensure_taskbar_registration()
    app = QApplication.instance() or QApplication(sys.argv)
    ico_p = ROOT_DIR / "alphalive.ico"
    if ico_p.exists():
        app.setWindowIcon(QIcon(str(ico_p)))
    win = AgentMainWindow()
    win.show()
    win._apply_native_win32_icon()
    app.exec()

if __name__ == "__main__":
    main()
