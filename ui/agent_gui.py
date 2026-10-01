import os
import sys
import time
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
    QInputDialog, QComboBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QPoint
from PyQt6.QtGui import QFont, QColor, QPixmap, QImage, QCursor

from core.alpha_agent import AlphaAgent, HAS_SR, VoiceListener
from ui.gui import CoordinateOverlay, CalibrationOverlay

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
    "text_bright": "#e6f1ff",
    "text_dim": "#708caa",
}

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
    """Sleek, minimal, draggable floating status pill providing instant state assurance (Green=Listen, Yellow=Work, Red=Error/Offline)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(175, 36)

        # Position at top-right corner of available desktop space
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.x() + geo.width() - 200, geo.y() + 25)

        self._drag_pos = None
        self.current_state = "standby"
        self._build_ui()
        self.set_state("standby")

    def _build_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.pill_frame = QFrame(self)
        self.pill_layout = QHBoxLayout(self.pill_frame)
        self.pill_layout.setContentsMargins(10, 4, 10, 4)
        self.pill_layout.setSpacing(8)

        # Glowing status dot
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.pill_layout.addWidget(self.dot)

        # Status text
        self.lbl_text = QLabel("STANDBY")
        self.lbl_text.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.lbl_text.setStyleSheet("border: none; background: transparent;")
        self.pill_layout.addWidget(self.lbl_text, 1)

        self.main_layout.addWidget(self.pill_frame)

    def set_state(self, state: str, details: str = ""):
        self.current_state = state.lower()
        if self.current_state == "listening":
            color = C["neon_green"]
            bg_color = "rgba(4, 16, 10, 235)"
            text = "LISTENING"
            tip = "Alpha is listening. Speak your instruction anytime."
        elif self.current_state == "working":
            color = C["neon_yellow"]
            bg_color = "rgba(18, 16, 4, 235)"
            text = "WORKING" if not details else details[:11].upper()
            tip = f"Alpha is processing or executing actions. {details}"
        elif self.current_state == "error":
            color = C["neon_red"]
            bg_color = "rgba(22, 4, 8, 240)"
            text = "ERROR"
            tip = f"Error detected: {details or 'API / Connection Error'}"
        elif self.current_state == "disconnected":
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
        self.setToolTip(tip)

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
    step_updated = pyqtSignal(int, int)    # current_step, max_steps
    screen_updated = pyqtSignal(object)    # PIL image
    task_finished = pyqtSignal()
    voice_heard = pyqtSignal(str)          # transcribed text

class AgentMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AlphaCore // Autonomous Desktop Agent")
        self.resize(1080, 750)
        self.setStyleSheet(f"background-color: {C['bg_dark']};")

        self.signals = AgentSignals()
        self.signals.log_message.connect(self._append_log)
        self.signals.status_updated.connect(self._update_status)
        self.signals.step_updated.connect(self._update_step)
        self.signals.screen_updated.connect(self._update_screen_preview)
        self.signals.task_finished.connect(self._on_task_finished)
        self.signals.voice_heard.connect(self._on_voice_heard)

        self.agent = AlphaAgent()
        self.overlay = None
        self.calib_overlay = None

        # State management: Standby until user explicitly starts the agent
        self.is_connected = False
        self.mic_enabled = True
        self.proactivity_enabled = True
        self.idle_timeout_seconds = 35
        self.last_activity_time = time.time()
        self._proactive_triggered = False

        # Build UI
        self._build_ui()
        self._update_session_display()
        if getattr(self.agent, "backend_type", "gemini") == "modal_qwen":
            self._append_log("[ENGINE] Active: 🔥 Modal HuiHui-Qwen3-14B (Uncensored vLLM).", C["neon_red"])
        else:
            self._append_log(f"[ENGINE] Active: ⚡ Google Gemini ({self.agent.model_name.replace('models/', '')}).", C["neon_cyan"])

        # Floating Mini Status HUD (starts in Standby mode)
        self.hud = MiniStatusHUD()
        self.hud.show()
        self.hud.set_state("standby")

        # Background Voice Listener (instantiated, but stays idle until START AGENT is clicked)
        self.voice_listener = None
        if HAS_SR:
            self.voice_listener = VoiceListener(on_speech_callback=self._handle_voice_input)

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
        event.accept()

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # ── Left Sidebar (Controls) ───────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(290)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_card']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(14, 14, 14, 14)
        s_layout.setSpacing(10)

        # Header Title
        title_lbl = QLabel("ALPHA AGENT v4.0")
        title_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C['neon_cyan']}; border: none;")
        s_layout.addWidget(title_lbl)

        self.model_lbl = QLabel()
        self.model_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.model_lbl.setWordWrap(True)
        s_layout.addWidget(self.model_lbl)

        # ── Cognitive Backend Card (Dual Toggle Switch) ─────────────────────
        self.backend_card = QFrame()
        self.backend_card.setStyleSheet(f"""
            QFrame {{
                background: {C['bg_dark']};
                border: 1px solid {C['border']};
                border-radius: 6px;
            }}
        """)
        be_layout = QVBoxLayout(self.backend_card)
        be_layout.setContentsMargins(8, 8, 8, 8)
        be_layout.setSpacing(6)

        be_hdr = QLabel("SWITCH COGNITIVE BACKEND")
        be_hdr.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        be_hdr.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        be_layout.addWidget(be_hdr)

        self.btn_backend_gemini = QPushButton("⚡ Google Gemini (Flash-Lite)")
        self.btn_backend_gemini.setFixedHeight(32)
        self.btn_backend_gemini.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_backend_gemini.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backend_gemini.clicked.connect(lambda: self._select_backend("gemini"))
        be_layout.addWidget(self.btn_backend_gemini)

        self.btn_backend_modal = QPushButton("🔥 Modal HuiHui-Qwen3 (Uncensored)")
        self.btn_backend_modal.setFixedHeight(32)
        self.btn_backend_modal.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_backend_modal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_backend_modal.clicked.connect(lambda: self._select_backend("modal_qwen"))
        be_layout.addWidget(self.btn_backend_modal)

        s_layout.addWidget(self.backend_card)

        self._update_backend_style()

        # Main Power Button (START / STOP)
        self.btn_power = QPushButton("⚡ START AGENT")
        self.btn_power.setFixedHeight(40)
        self.btn_power.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
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

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"background-color: {C['border']}; border: none; max-height: 1px;")
        s_layout.addWidget(sep1)

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
        self.lbl_session_name.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
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

        # Status Card
        status_card = QFrame()
        status_card.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 8px;")
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setSpacing(4)

        sc_lbl = QLabel("SYSTEM STATUS")
        sc_lbl.setFont(QFont("Consolas", 8))
        sc_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none;")
        sc_layout.addWidget(sc_lbl)

        self.lbl_status = QLabel("STANDBY // OFFLINE")
        self.lbl_status.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
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
        s_layout.addWidget(status_card)

        # ── Assistant Toolbox ────────────────────────────────────────────────
        toolbox_card = QFrame()
        toolbox_card.setStyleSheet(f"""
            QFrame {{
                background: {C['bg_dark']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        tb_layout = QVBoxLayout(toolbox_card)
        tb_layout.setSpacing(6)
        tb_layout.setContentsMargins(8, 8, 8, 8)

        tb_title = QLabel("ASSISTANT TOOLBOX")
        tb_title.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        tb_title.setStyleSheet(f"color: {C['neon_blue']}; border: none;")
        tb_layout.addWidget(tb_title)

        # 1. Coordinate Grid & Cursor Overlay
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
        tb_layout.addWidget(self.btn_overlay)

        # 2. Calibration Tool
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
        tb_layout.addWidget(self.btn_calib)

        # 3. Mini Status HUD Toggle
        self.btn_hud_toggle = QPushButton("💡 STATUS HUD [ON]")
        self.btn_hud_toggle.setFixedHeight(28)
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
        tb_layout.addWidget(self.btn_hud_toggle)

        # 4. Proactivity Setting
        proact_row = QHBoxLayout()
        proact_row.setSpacing(4)
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
        proact_row.addWidget(self.btn_proact, 1)

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
        # 5. Voice Profile & Neural Fallback Selector
        voice_card = QFrame()
        voice_card.setStyleSheet("background: transparent; border: none;")
        vc_layout = QVBoxLayout(voice_card)
        vc_layout.setContentsMargins(0, 2, 0, 2)
        vc_layout.setSpacing(3)

        vc_lbl = QLabel("VOICE PROFILE // FALLBACK")
        vc_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        vc_lbl.setStyleSheet(f"color: {C['neon_blue']}; border: none;")
        vc_layout.addWidget(vc_lbl)

        self.combo_voice = QComboBox()
        self.combo_voice.setFixedHeight(28)
        self.combo_voice.setFont(QFont("Consolas", 8))
        self.combo_voice.addItem("🎙 Google Leda (Primary)", "Leda")
        self.combo_voice.addItem("✨ Aria (Expressive / Smooth)", "en-US-AriaNeural")
        self.combo_voice.addItem("🌸 Jenny (Warm Conversational)", "en-US-JennyNeural")
        self.combo_voice.addItem("💎 Sonia (Polished British)", "en-GB-SoniaNeural")
        self.combo_voice.addItem("🌙 Michelle (Calm / Mature)", "en-US-MichelleNeural")
        self.combo_voice.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border: 1px solid {C['border']};
                border-radius: 3px;
                padding: 0 4px;
            }}
            QComboBox QAbstractItemView {{
                background: {C['bg_dark']};
                color: {C['text_bright']};
                selection-background-color: {C['neon_blue']};
                selection-color: #fff;
            }}
        """)
        self.combo_voice.currentIndexChanged.connect(self._on_voice_changed)
        vc_layout.addWidget(self.combo_voice)
        tb_layout.addWidget(voice_card)

        # 6. Mic Toggle Button
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
        tb_layout.addWidget(self.btn_mic)

        s_layout.addWidget(toolbox_card)

        s_layout.addStretch()

        # Emergency Abort Button
        self.btn_abort = QPushButton("⛔ ABORT TASK (Ctrl+Z)")
        self.btn_abort.setFixedHeight(36)
        self.btn_abort.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
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

        # ── Right Main Area ───────────────────────────────────────────────────
        right_panel = QFrame()
        right_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_card']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        r_layout = QVBoxLayout(right_panel)
        r_layout.setContentsMargins(14, 14, 14, 14)
        r_layout.setSpacing(10)

        # Top Bar (Header + Preview toggle)
        top_bar = QHBoxLayout()
        term_title = QLabel("AUTONOMOUS EXECUTION LOG")
        term_title.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        term_title.setStyleSheet(f"color: {C['text_bright']}; border: none;")
        top_bar.addWidget(term_title)
        top_bar.addStretch()

        self.btn_session_top = QPushButton("📁 SESSIONS")
        self.btn_session_top.setFixedSize(90, 24)
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

        self.btn_clear = QPushButton("CLEAR LOG")
        self.btn_clear.setFixedSize(85, 24)
        self.btn_clear.setFont(QFont("Consolas", 8))
        self.btn_clear.setStyleSheet(f"color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
        self.btn_clear.clicked.connect(lambda: self.log_box.clear())
        top_bar.addWidget(self.btn_clear)
        r_layout.addLayout(top_bar)

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
        r_layout.addWidget(self.log_box, 1)

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

        r_layout.addLayout(inp_row)
        main_layout.addWidget(right_panel, 1)

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

    def _disconnect_agent(self):
        self.is_connected = False
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
            self.btn_hud_toggle.setText("💡 STATUS HUD [OFF]")
            self.btn_hud_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Mini Status HUD hidden.", C["text_dim"])
        else:
            self.hud.show()
            self.btn_hud_toggle.setText("💡 STATUS HUD [ON]")
            self.btn_hud_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {C['neon_cyan']}22;
                    color: {C['neon_cyan']};
                    border: 1px solid {C['neon_cyan']};
                    border-radius: 3px;
                }}
            """)
            self._append_log("Mini Status HUD enabled (draggable floating status pill).", C["neon_cyan"])

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
            return
        self.agent.set_backend(backend_type)
        self._update_backend_style()
        if backend_type == "modal_qwen":
            self._append_log("[COGNITIVE BACKEND] Switched to 🔥 Modal HuiHui-Qwen3-14B (Abliterated/Uncensored vLLM on A10G). Real-time OCR perception & Hermes tool use enabled.", C["neon_red"])
        else:
            self._append_log("[COGNITIVE BACKEND] Switched to ⚡ Google Gemini (Flash-Lite / 3.8). Multimodal vision & fallback cascade active.", C["neon_cyan"])

    def _update_backend_style(self):
        backend = getattr(self.agent, "backend_type", "gemini")
        if backend == "modal_qwen":
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

    def _on_voice_changed(self, idx: int):
        v = self.combo_voice.itemData(idx)
        if not v:
            return
        if v == "Leda":
            self.agent.voice.set_voice("Leda")
            self.agent.voice.set_edge_voice("en-US-AriaNeural")
            self._append_log("[VOICE] Active voice: Google Leda (Primary) with Aria Neural fallback.", C["neon_cyan"])
        else:
            self.agent.voice.set_edge_voice(v)
            self._append_log(f"[VOICE] Neural voice set to: {self.combo_voice.currentText()}.", C["neon_cyan"])

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
                f"[System Idle Proactivity]: Josh has been quiet for {int(elapsed)} seconds. "
                "Examine what is visible on Josh's screen in the screenshot. In Alpha's sharp, direct, charismatic "
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
        self._on_activity()
        if not self.agent.is_running and not self.agent.voice.is_speaking:
            self._append_log(f"[HEARD VOICE] \"{text}\"", C["neon_cyan"])
            self._run_task(text)
        else:
            self._append_log(f"[VOICE BARGE-IN] Interrupted speech with: \"{text}\"", C["neon_yellow"])
            # Immediately cut off ongoing speech playback and task execution
            self.agent.abort()
            # Queue execution of Josh's new voice command
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

    def _abort_task(self):
        self.agent.abort()
        self._append_log("[ABORT] Emergency stop triggered by user.", C["neon_red"])
        self._update_status("ABORTED", C["neon_red"])
        if self.hud:
            self.hud.set_state("error", "Task Aborted")

    def _run_task(self, goal: str, is_proactive: bool = False):
        if self.agent.is_running:
            # Preempt previous task cleanly instead of blocking
            self.agent.abort()
            time.sleep(0.08)

        self._update_status("WORKING...", C["neon_yellow"])
        if self.hud:
            self.hud.set_state("working")

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._agent_task_runner(goal))
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    async def _agent_task_runner(self, goal: str):
        def _on_step(current, total):
            self.signals.step_updated.emit(current, total)

        def _on_log(text, level):
            color = C["text_bright"]
            if level in ("error", "red"):
                color = C["neon_red"]
                self.signals.status_updated.emit("API ERROR", C["neon_red"])
            elif level in ("warn", "yellow"):
                color = C["neon_yellow"]
            elif level in ("cyan", "action"):
                color = C["neon_cyan"]
            elif level in ("green", "success"):
                color = C["neon_green"]
            elif level in ("dim", "step"):
                color = C["text_dim"]
            self.signals.log_message.emit(text, color)

        await self.agent.execute_turn(goal, on_step=_on_step, on_log=_on_log)
        self.signals.task_finished.emit()

    def _append_log(self, text: str, color: str):
        t_stamp = time.strftime("[%H:%M:%S]")
        html = f"<span style='color:{C['text_dim']}'>{t_stamp}</span> <span style='color:{color}'>{text}</span>"
        self.log_box.append(html)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self, text: str, color: str):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold; border: none;")
        if self.hud:
            t_upper = text.upper()
            if "ERR" in t_upper or "ABORT" in t_upper:
                self.hud.set_state("error", text)
            elif "EXEC" in t_upper or "PROCESS" in t_upper or "WORK" in t_upper:
                self.hud.set_state("working", text)
            elif "READY" in t_upper or "LISTEN" in t_upper:
                if self.is_connected:
                    self.hud.set_state("listening")
                else:
                    self.hud.set_state("standby")
            elif "DISCONNECT" in t_upper or "OFFLINE" in t_upper:
                self.hud.set_state("disconnected")
            elif "STANDBY" in t_upper:
                self.hud.set_state("standby")

    def _update_step(self, current: int, total: int):
        self.lbl_step.setText(f"Action Step: {current}")
        self.lbl_status.setText(f"EXECUTING STEP {current}")
        self.lbl_status.setStyleSheet(f"color: {C['neon_yellow']}; font-weight: bold; border: none;")
        self.progress_bar.setRange(0, 0)
        if self.hud:
            self.hud.set_state("working", f"STEP {current}")

    def _update_screen_preview(self, pil_img):
        pass

    def _on_task_finished(self):
        self.lbl_step.setText("Step: Ready")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._update_session_display()
        self._on_activity()

        if "ERR" in self.lbl_status.text().upper():
            self._update_status("ERROR DETECTED", C["neon_red"])
            if self.hud:
                self.hud.set_state("error", "Error in task execution")
        else:
            if self.is_connected:
                self._update_status("READY // LISTENING", C["neon_green"])
                if self.hud:
                    self.hud.set_state("listening")
            else:
                self._update_status("STANDBY // OFFLINE", C["text_dim"])
                if self.hud:
                    self.hud.set_state("standby")

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

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = AgentMainWindow()
    win.show()
    app.exec()

if __name__ == "__main__":
    main()
