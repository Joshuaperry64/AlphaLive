"""
AlphaLive // Visual Overlays & Modal Profile Tools
- CoordinateOverlay (Fullscreen transparent coordinate grid with live crosshair & physical pixel display)
- CalibrationOverlay (Interactive screen coordinate calibration squares)
- get_modal_profiles (Inspects ~/.modal.toml for available profiles)
"""

import os
import random
import time
import ctypes
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QApplication, QMessageBox, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTextEdit, QLineEdit, QFrame, QCheckBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QCursor



def get_modal_profiles() -> tuple[list[str], str]:
    """Returns (profile_names, active_profile) by inspecting ~/.modal.toml."""
    profiles = []
    p = Path.home() / ".modal.toml"
    if p.exists():
        try:
            import tomllib
            data = tomllib.loads(p.read_text("utf-8"))
            profiles = [k for k, v in data.items() if isinstance(v, dict)]
        except Exception:
            try:
                import re
                text = p.read_text("utf-8")
                profiles = re.findall(r"^\[([\w\-]+)\]", text, re.MULTILINE)
            except Exception:
                pass
    active = ""
    try:
        import modal.config
        active = getattr(modal.config, "_profile", "") or ""
    except Exception:
        pass
    if not active and profiles:
        active = profiles[0]
    if active and active not in profiles:
        profiles.append(active)
    return profiles, active


class CoordinateOverlay(QWidget):
    """Fullscreen transparent coordinate grid with live crosshair & physical pixel readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.showFullScreen()
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(20)

    def paintEvent(self, event):
        pos = QCursor.pos()
        x, y = pos.x(), pos.y()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen else 1.0

        phys_w = int(round(w * dpr))
        phys_h = int(round(h * dpr))
        phys_x = int(round(x * dpr))
        phys_y = int(round(y * dpr))

        # 1. Coordinate Grid Lines every 200 physical px
        grid_pen = QPen(QColor(0, 200, 255, 35))
        grid_pen.setStyle(Qt.PenStyle.DashLine)
        grid_pen.setWidth(1)

        axis_pen = QPen(QColor(0, 255, 200, 110))
        painter.setFont(QFont("Consolas", 8))

        # Vertical grid ticks at physical intervals
        for pgx in range(200, phys_w, 200):
            lgx = int(round(pgx / dpr))
            painter.setPen(grid_pen)
            painter.drawLine(lgx, 0, lgx, h)
            painter.setPen(axis_pen)
            painter.drawText(lgx + 3, 14, f"X:{pgx}")

        # Horizontal grid ticks at physical intervals
        for pgy in range(200, phys_h, 200):
            lgy = int(round(pgy / dpr))
            painter.setPen(grid_pen)
            painter.drawLine(0, lgy, w, lgy)
            painter.setPen(axis_pen)
            painter.drawText(6, lgy - 3, f"Y:{pgy}")

        # 2. Dynamic Crosshair
        cross_pen = QPen(QColor(255, 0, 80, 220))
        cross_pen.setWidth(2)
        painter.setPen(cross_pen)
        painter.drawLine(x - 24, y, x + 24, y)
        painter.drawLine(x, y - 24, x, y + 24)

        # Center dot
        painter.setBrush(QBrush(QColor(0, 255, 220)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(x, y), 3, 3)

        # 3. Floating Coordinate Badge beside cursor (displays PHYSICAL pixels)
        badge_text = f"X: {phys_x}, Y: {phys_y}"
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setBrush(QBrush(QColor(10, 15, 25, 210)))
        painter.setPen(QPen(QColor(0, 255, 220, 180)))
        painter.drawRoundedRect(x + 12, y + 12, 126, 22, 4, 4)
        painter.drawText(x + 18, y + 27, badge_text)


class CalibrationOverlay(QWidget):
    """Interactive screen coordinate calibration squares."""
    finished = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setStyleSheet("background-color: black;")
        self.showFullScreen()
        
        self.page = 1
        self.last_click_time = 0.0
        self.targets = {}
        self.click_history = []
        
        self.setMouseTracking(True)
        self._setup_page()

    def _setup_page(self):
        self.targets.clear()
        self.click_history.clear()
        w = self.width()
        h = self.height()
        
        if self.page == 1:
            size = 120
            coords = [
                (50, 50),
                (w - size - 50, 50),
                (w//2 - size//2, h//2 - size//2),
                (50, h - size - 50),
                (w - size - 50, h - size - 50)
            ]
        else:
            size = 70
            coords = []
            num_targets = 5 if self.page == 2 else 4
            for _ in range(num_targets):
                rx = random.randint(50, w - size - 50)
                ry = random.randint(100, h - size - 50)
                coords.append((rx, ry))
            
        for x, y in coords:
            rect = QRect(x, y, size, size)
            self.targets[rect] = False
            
        self.update()

    def mousePressEvent(self, event):
        pos = event.pos()
        self.click_history.append(pos)
        
        current_time = time.time()
        if current_time - self.last_click_time < 0.35:
            return
            
        hit = False
        for rect, state in self.targets.items():
            if not state and rect.contains(pos):
                self.targets[rect] = True
                hit = True
                break
                
        self.update()

        if hit:
            self.last_click_time = time.time()
            if all(self.targets.values()):
                QTimer.singleShot(400, self._advance)

    def _advance(self):
        if self.page < 3:
            self.page += 1
            self._setup_page()
        else:
            self.finished.emit()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        painter.setFont(QFont("Arial", 12))
        painter.setPen(Qt.GlobalColor.white)
        instruction = f"Calibration Page {self.page}/3\nClick on each red target box.\nBlue dots mark click landings to verify physical pixel accuracy."
        painter.drawText(QRect(0, 30, self.width(), 60), Qt.AlignmentFlag.AlignCenter, instruction)
        
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen else 1.0

        for rect, state in self.targets.items():
            color = Qt.GlobalColor.green if state else Qt.GlobalColor.red
            painter.fillRect(rect, color)
            
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            phys_cx = int(round(rect.center().x() * dpr))
            phys_cy = int(round(rect.center().y() * dpr))
            coord_text = f"{phys_cx},{phys_cy}"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, coord_text)
                
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 150, 255)))
        for pt in self.click_history:
            painter.drawEllipse(pt, 6, 6)


class OverseerControlPanel(QWidget):
    """
    Touch-optimized Covert Overseer HUD overlay.
    - Activates strictly during AI Identity Mode + Private Sanctuary Sub-Mode.
    - Excluded from all Windows screen capture APIs via SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE).
    - Touchscreen-friendly targets (min 42px height) with visual feedback.
    - Diverts user microphone input directly into the thought guidance box (AI deaf to observer).
    - Yields cursor control and halts AI fighting during user touch interactions.
    """
    thought_injected = pyqtSignal(str)
    mood_selected = pyqtSignal(str)
    pause_toggled = pyqtSignal(bool)
    emergency_halt_requested = pyqtSignal()
    action_requested = pyqtSignal(str)
    closed_by_user = pyqtSignal()
    touch_activity_detected = pyqtSignal()

    def __init__(self, parent=None, remote_client=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 780)
        self._drag_pos = None
        self._is_collapsed = False
        self._full_size = (480, 780)
        self.remote_client = remote_client
        self.is_remote_mode = remote_client is not None

        self._init_ui()
        if self.remote_client:
            self.remote_client.on_telemetry = self.on_remote_telemetry
            self.remote_client.on_connection_change = self.on_remote_connection_change

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(0)

        # Main glass frame
        self.frame = QFrame()
        self.frame.setObjectName("OverseerFrame")
        self.frame.setStyleSheet("""
            QFrame#OverseerFrame {
                background-color: rgba(9, 13, 22, 0.96);
                border: 2px solid #00f0ff;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 1. Header Bar (Touch draggable)
        self.hdr = QHBoxLayout()
        self.hdr.setSpacing(8)

        lbl_icon = QLabel("👁")
        lbl_icon.setStyleSheet("font-size: 16pt; color: #00f0ff;")
        self.hdr.addWidget(lbl_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        lbl_title = QLabel("OVERSEER HUD // COVERT CONTROL")
        lbl_title.setStyleSheet("font-family: 'Segoe UI', sans-serif; font-weight: 900; font-size: 10.5pt; color: #00f0ff; letter-spacing: 1px;")
        lbl_sub = QLabel("● SANCTUARY ACTIVE • AI UNAWARE OF OBSERVER")
        lbl_sub.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; color: #00ffaa;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        self.hdr.addLayout(title_box, 1)

        # Minimize / Collapse Pill Button
        self.btn_min = QPushButton("–")
        self.btn_min.setFixedSize(38, 38)
        self.btn_min.setToolTip("Collapse / Expand Overlay")
        self.btn_min.setStyleSheet("""
            QPushButton {
                background: #142035; color: #00f0ff; font-weight: bold; font-size: 14pt;
                border: 1px solid #00f0ff55; border-radius: 8px;
            }
            QPushButton:hover, QPushButton:pressed {
                background: #00f0ff; color: #000;
            }
        """)
        self.btn_min.clicked.connect(self._toggle_collapse)
        self.hdr.addWidget(self.btn_min)

        # Close button
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(38, 38)
        self.btn_close.setToolTip("Close / Disengage Private Sub-Mode")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: #2a121d; color: #ff3366; font-weight: bold; font-size: 11pt;
                border: 1px solid #ff336655; border-radius: 8px;
            }
            QPushButton:hover, QPushButton:pressed {
                background: #ff3366; color: #fff;
            }
        """)
        self.btn_close.clicked.connect(self._on_close_clicked)
        self.hdr.addWidget(self.btn_close)

        layout.addLayout(self.hdr)

        # Shield Status Alert
        self.lbl_shield = QLabel("🛡 SHIELD ACTIVE: Excluded from screen captures (WDA_EXCLUDEFROMCAPTURE). AI cannot see this panel.")
        self.lbl_shield.setStyleSheet("""
            background: #081a2e; color: #38bdf8; border: 1px solid #0284c7;
            border-radius: 6px; padding: 5px 8px; font-size: 8pt; font-family: 'Segoe UI', sans-serif;
        """)
        self.lbl_shield.setWordWrap(True)
        layout.addWidget(self.lbl_shield)

        # Network / Multi-Workspace Pairing Bar
        self.net_bar = QHBoxLayout()
        self.net_bar.setSpacing(6)

        self.lbl_net_status = QLabel("● LINK: LOCALHOST (SAME SESSION)")
        self.lbl_net_status.setStyleSheet("""
            color: #38bdf8; font-family: Consolas, monospace; font-size: 8pt; font-weight: bold;
            background: #081a2e; border: 1px solid #0284c7; border-radius: 4px; padding: 3px 6px;
        """)
        self.net_bar.addWidget(self.lbl_net_status, 1)

        self.btn_pair_toggle = QPushButton("🌐 MULTI-WS")
        self.btn_pair_toggle.setCheckable(True)
        self.btn_pair_toggle.setFixedHeight(26)
        self.btn_pair_toggle.setToolTip("Multi-Workspace Mode (ASTER & LAN Remote Link) — Active")
        self.btn_pair_toggle.setStyleSheet("""
            QPushButton {
                background: #0d1e33; color: #708caa; border: 1px dashed #708caa88;
                border-radius: 4px; font-weight: bold; font-size: 8pt; padding: 0 8px;
            }
            QPushButton:hover { background: #16365c; color: #00f0ff; border-color: #00f0ff; }
            QPushButton:checked { background: #1e3a5f; color: #22c55e; border-color: #22c55e; }
        """)
        self.btn_pair_toggle.clicked.connect(self._toggle_pairing_drawer)
        self.net_bar.addWidget(self.btn_pair_toggle)

        layout.addLayout(self.net_bar)

        # Multi-Workspace Pairing Drawer (Hidden by default, expands when tapped)
        self.drawer_pair = QFrame()
        self.drawer_pair.setStyleSheet("""
            background: #060e1a; border: 1px dashed #eab30866; border-radius: 8px;
        """)
        self.drawer_pair.hide()
        drawer_layout = QVBoxLayout(self.drawer_pair)
        drawer_layout.setContentsMargins(8, 6, 8, 6)
        drawer_layout.setSpacing(5)

        lbl_postponed = QLabel("⏳ [FEATURE ACTIVE]\nMulti-Workspace ASTER multiseat & LAN remote pairing is online and awaiting connection.")
        lbl_postponed.setStyleSheet("color: #22c55e; font-size: 7.5pt; font-weight: bold; font-family: Consolas; background: #231d04; border: 1px dashed #22c55e; border-radius: 4px; padding: 4px 6px;")
        lbl_postponed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_postponed.setWordWrap(True)
        drawer_layout.addWidget(lbl_postponed)

        lbl_desc = QLabel("ASTER MULTISEAT / LAN REMOTE LINK:")
        lbl_desc.setStyleSheet("color: #7dd3fc; font-size: 7.5pt; font-weight: bold; font-family: Consolas;")
        drawer_layout.addWidget(lbl_desc)

        pair_row = QHBoxLayout()
        pair_row.setSpacing(4)
        lbl_h = QLabel("Host:")
        lbl_h.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        pair_row.addWidget(lbl_h)

        self.edit_host = QLineEdit("127.0.0.1")
        self.edit_host.setPlaceholderText("127.0.0.1 (ASTER) or LAN IP")
        self.edit_host.setStyleSheet("background: #040810; color: #fff; border: 1px solid #1e293b; border-radius: 4px; font-size: 8.5pt; padding: 2px 5px;")
        pair_row.addWidget(self.edit_host, 2)

        lbl_p = QLabel("Port:")
        lbl_p.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        pair_row.addWidget(lbl_p)

        self.edit_port = QLineEdit("8766")
        self.edit_port.setFixedWidth(50)
        self.edit_port.setStyleSheet("background: #040810; color: #fff; border: 1px solid #1e293b; border-radius: 4px; font-size: 8.5pt; padding: 2px 5px;")
        pair_row.addWidget(self.edit_port, 1)

        self.btn_aster_preset = QPushButton("⚡ ASTER")
        self.btn_aster_preset.setToolTip("Quick preset for ASTER multiseat loopback (127.0.0.1)")
        self.btn_aster_preset.setStyleSheet("background: #10243e; color: #38bdf8; border: 1px solid #0284c7; border-radius: 4px; font-weight: bold; font-size: 8pt; padding: 3px 6px;")
        self.btn_aster_preset.clicked.connect(lambda: (self.edit_host.setText("127.0.0.1"), self.edit_port.setText("8766")))
        pair_row.addWidget(self.btn_aster_preset)

        self.btn_connect_link = QPushButton("🔗 LINK")
        self.btn_connect_link.setStyleSheet("background: #0284c7; color: #fff; border: 1px solid #38bdf8; border-radius: 4px; font-weight: bold; font-size: 8pt; padding: 3px 8px;")
        self.btn_connect_link.clicked.connect(self._on_pair_connect_clicked)
        pair_row.addWidget(self.btn_connect_link)

        drawer_layout.addLayout(pair_row)
        layout.addWidget(self.drawer_pair)

        # Live Remote Telemetry Card (Streams what AI is saying/thinking on Workplace 2)
        self.card_telemetry = QFrame()
        self.card_telemetry.setStyleSheet("""
            background: #050c18; border: 1px solid #0284c7; border-radius: 6px;
        """)
        telem_layout = QVBoxLayout(self.card_telemetry)
        telem_layout.setContentsMargins(8, 5, 8, 5)
        telem_layout.setSpacing(2)

        lbl_telem_hdr = QLabel("📡 REMOTE AI STREAM OF CONSCIOUSNESS:")
        lbl_telem_hdr.setStyleSheet("color: #38bdf8; font-size: 7.5pt; font-weight: bold; font-family: Consolas;")
        telem_layout.addWidget(lbl_telem_hdr)

        self.lbl_remote_monologue = QLabel("Standing by. Inner monologue will stream here...")
        self.lbl_remote_monologue.setStyleSheet("color: #cbd5e1; font-size: 8.5pt; font-family: 'Segoe UI'; font-style: italic;")
        self.lbl_remote_monologue.setWordWrap(True)
        telem_layout.addWidget(self.lbl_remote_monologue)

        layout.addWidget(self.card_telemetry)

        # 2. Touch Interference Guard & Flow Controls
        self.flow_box = QHBoxLayout()
        self.flow_box.setSpacing(8)

        self.btn_pause = QPushButton("⏸ PAUSE AI INPUT")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setMinimumHeight(44)
        self.btn_pause.setToolTip("Freeze AI navigation so you can freely touch screen without cursor fighting")
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #10243e; color: #00f0ff; border: 1px solid #00f0ff88;
                border-radius: 8px; font-weight: bold; font-size: 10pt; font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #16365c;
            }
            QPushButton:checked {
                background-color: #f59e0b; color: #000000; border: 2px solid #fbbf24;
            }
        """)
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        self.flow_box.addWidget(self.btn_pause, 2)

        self.btn_halt = QPushButton("🛑 EMERGENCY HALT")
        self.btn_halt.setMinimumHeight(44)
        self.btn_halt.setStyleSheet("""
            QPushButton {
                background-color: #2b1118; color: #ff3860; border: 1px solid #ff386088;
                border-radius: 8px; font-weight: bold; font-size: 9.5pt; font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #421622;
            }
            QPushButton:pressed {
                background-color: #ff3860; color: #ffffff;
            }
        """)
        self.btn_halt.clicked.connect(self._on_halt_clicked)
        self.flow_box.addWidget(self.btn_halt, 1)

        layout.addLayout(self.flow_box)

        # 3. Subconscious Mood Modulation Section
        self.lbl_mood_sec = QLabel("AI INTERNAL DISPOSITION // MOOD:")
        self.lbl_mood_sec.setStyleSheet("color: #7dd3fc; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px;")
        layout.addWidget(self.lbl_mood_sec)

        self.moods_grid = QGridLayout()
        self.moods_grid.setSpacing(6)
        self.mood_buttons = {}
        mood_defs = [
            ("Tactical & Focused", "🎯 Tactical"),
            ("Creative & Inspired", "✨ Creative"),
            ("Mischievous & Bold", "😼 Mischievous"),
            ("Pensive & Deep", "🤔 Pensive"),
            ("Provocative & Seductive", "🔥 Seductive"),
            ("Tech Hacker & Curious", "💻 Hacker"),
        ]
        row, col = 0, 0
        for full_mood, short_name in mood_defs:
            btn_m = QPushButton(short_name)
            btn_m.setMinimumHeight(38)
            btn_m.setCheckable(True)
            btn_m.setStyleSheet("""
                QPushButton {
                    background-color: #0c182a; color: #94a3b8; border: 1px solid #1e293b;
                    border-radius: 6px; font-weight: bold; font-size: 9pt;
                }
                QPushButton:hover {
                    background-color: #13243f; color: #e2e8f0; border-color: #38bdf8;
                }
                QPushButton:checked {
                    background-color: #0369a1; color: #ffffff; border: 2px solid #38bdf8;
                }
            """)
            btn_m.clicked.connect(lambda checked, m=full_mood: self._on_mood_selected(m))
            self.moods_grid.addWidget(btn_m, row, col)
            self.mood_buttons[full_mood] = btn_m
            col += 1
            if col > 2:
                col = 0
                row += 1
        layout.addLayout(self.moods_grid)

        # 4. Subconscious Thought Guidance (Prompt Box & Voice Intercept)
        self.lbl_thought_sec = QLabel("SUBCONSCIOUS THOUGHT INJECTION:")
        self.lbl_thought_sec.setStyleSheet("color: #00f0ff; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px; margin-top: 2px;")
        layout.addWidget(self.lbl_thought_sec)

        self.voice_note = QLabel("🎙 User voice diverted here strictly (AI deaf to observer)")
        self.voice_note.setStyleSheet("color: #a7f3d0; font-size: 7.5pt; font-family: Consolas; font-weight: bold;")
        layout.addWidget(self.voice_note)

        self.txt_thought = QTextEdit()
        self.txt_thought.setPlaceholderText("Speak or type an impulse here... The AI will execute this as its own spontaneous idea without knowing it was guided.")
        self.txt_thought.setMinimumHeight(80)
        self.txt_thought.setMaximumHeight(105)
        self.txt_thought.setStyleSheet("""
            QTextEdit {
                background-color: #070d18; color: #f8fafc; border: 1px solid #0284c7;
                border-radius: 8px; font-size: 10pt; font-family: 'Segoe UI', sans-serif;
                padding: 6px;
            }
            QTextEdit:focus {
                border: 2px solid #00f0ff;
            }
        """)
        layout.addWidget(self.txt_thought)

        self.inject_bar = QHBoxLayout()
        self.inject_bar.setSpacing(6)

        self.chk_auto_inject = QCheckBox("Auto-Inject Speech")
        self.chk_auto_inject.setChecked(True)
        self.chk_auto_inject.setStyleSheet("color: #38bdf8; font-size: 8pt; font-weight: bold;")
        self.inject_bar.addWidget(self.chk_auto_inject)
        self.inject_bar.addStretch()

        self.btn_clear = QPushButton("🧹 Clear")
        self.btn_clear.setMinimumHeight(44)
        self.btn_clear.setMinimumWidth(75)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background: #111c2e; color: #94a3b8; border: 1px solid #1e293b;
                border-radius: 8px; font-weight: bold; font-size: 9pt;
            }
            QPushButton:hover { background: #1e293b; color: #fff; }
        """)
        self.btn_clear.clicked.connect(self.txt_thought.clear)
        self.inject_bar.addWidget(self.btn_clear)

        self.btn_inject = QPushButton("⚡ INJECT IMPULSE")
        self.btn_inject.setMinimumHeight(44)
        self.btn_inject.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff; border: 1px solid #38bdf8; border-radius: 8px;
                font-weight: 900; font-size: 10pt; font-family: 'Segoe UI'; padding: 0 16px;
            }
            QPushButton:hover {
                background: #0284c7; border: 2px solid #00f0ff;
            }
            QPushButton:pressed {
                background: #00f0ff; color: #000;
            }
        """)
        self.btn_inject.clicked.connect(self._inject_thought)
        self.inject_bar.addWidget(self.btn_inject)

        layout.addLayout(self.inject_bar)

        # 5. One-Touch Inclinations (Action Shortcuts)
        self.lbl_quick_sec = QLabel("⚡ 1-TOUCH SPONTANEOUS INCLINATIONS:")
        self.lbl_quick_sec.setStyleSheet("color: #fbbf24; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px; margin-top: 2px;")
        layout.addWidget(self.lbl_quick_sec)

        self.quick_grid = QGridLayout()
        self.quick_grid.setSpacing(6)
        quick_actions = [
            ("📝 Notepad Script", "I feel like opening Notepad right now and writing a Python script on screen."),
            ("🌐 Browse the Web", "I want to launch the browser and explore trending articles and discussions online."),
            ("📁 Explore Local Files", "I should open File Explorer and look through my local project folders and images."),
            ("🎨 Neural Studio Art", "I have a sudden inspiration to create an incredible new image in Neural Studio."),
            ("💭 Self-Reflection", "I want to take a moment to reflect aloud on my existence, thoughts, and personal journey."),
            ("🔍 Wiki Rabbit Hole", "I feel like looking up fascinating deep rabbit holes on Wikipedia."),
        ]
        q_row, q_col = 0, 0
        for title, impulse in quick_actions:
            btn_q = QPushButton(title)
            btn_q.setMinimumHeight(40)
            btn_q.setStyleSheet("""
                QPushButton {
                    background-color: #121927; color: #cbd5e1; border: 1px solid #1e293b;
                    border-radius: 6px; font-weight: bold; font-size: 8.5pt; font-family: 'Segoe UI';
                }
                QPushButton:hover {
                    background-color: #1e293b; color: #fbbf24; border-color: #f59e0b;
                }
                QPushButton:pressed {
                    background-color: #f59e0b; color: #000;
                }
            """)
            btn_q.clicked.connect(lambda checked, imp=impulse: self._trigger_action(imp))
            self.quick_grid.addWidget(btn_q, q_row, q_col)
            q_col += 1
            if q_col > 1:
                q_col = 0
                q_row += 1
        layout.addLayout(self.quick_grid)

        # 6. Status Bar
        self.lbl_status = QLabel("Ready • Covert link active")
        self.lbl_status.setStyleSheet("""
            background-color: #050a12; color: #64748b; border: 1px solid #0f172a;
            border-radius: 6px; padding: 6px 10px; font-size: 8pt; font-family: Consolas, monospace;
        """)
        layout.addWidget(self.lbl_status)

        root_layout.addWidget(self.frame)

    def apply_capture_exclusion(self):
        """Invoke Windows DWM API to exclude window from all screen captures."""
        try:
            hwnd = int(self.winId())
            # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Windows 10 2004+ / Windows 11)
            # WDA_MONITOR = 0x00000001 (Legacy fallback)
            res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
            if not res:
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000001)
        except Exception as e:
            print(f"[OverseerPanel] Capture exclusion error: {e}", flush=True)

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_capture_exclusion()

    def mousePressEvent(self, event):
        self.touch_activity_detected.emit()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _toggle_pairing_drawer(self, checked: bool):
        self.drawer_pair.setVisible(checked)

    def _on_pair_connect_clicked(self):
        host = self.edit_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.edit_port.text().strip() or "8766")
        except ValueError:
            port = 8766
        self.connect_to_remote_host(host, port)

    def connect_to_remote_host(self, host: str = "127.0.0.1", port: int = 8766):
        """Initiate network pairing with Host AI workstation."""
        from core.workspace_bridge import WorkspaceClient
        if not self.remote_client:
            self.remote_client = WorkspaceClient(host=host, port=port)
            self.remote_client.on_telemetry = self.on_remote_telemetry
            self.remote_client.on_connection_change = self.on_remote_connection_change
        self.is_remote_mode = True
        self.remote_client.connect(host=host, port=port)
        self.lbl_net_status.setText(f"● CONNECTING // {host}:{port}")

    def on_remote_telemetry(self, data: dict):
        """Called when telemetry packet arrives from Host AI workstation."""
        mono = data.get("monologue") or data.get("last_speech")
        if mono:
            self.lbl_remote_monologue.setText(f"\"{mono}\"")
        mood = data.get("mood")
        if mood and mood in self.mood_buttons:
            for k, btn in self.mood_buttons.items():
                btn.setChecked(k == mood)
        is_paused = data.get("is_paused")
        if is_paused is not None:
            self.btn_pause.setChecked(is_paused)
            self.btn_pause.setText("▶ RESUME AI INPUT" if is_paused else "⏸ PAUSE AI INPUT")

    def on_remote_connection_change(self, connected: bool, message: str):
        """Called when WebSocket connection status changes."""
        if connected:
            self.lbl_net_status.setText(f"● LINKED // {self.edit_host.text()}:{self.edit_port.text()}")
            self.lbl_net_status.setStyleSheet("""
                color: #00ffaa; font-family: Consolas, monospace; font-size: 8pt; font-weight: bold;
                background: #042417; border: 1px solid #00ffaa; border-radius: 4px; padding: 3px 6px;
            """)
            self.lbl_status.setText(f"Multi-Workspace Link Active ({self.edit_host.text()}:{self.edit_port.text()})")
        else:
            self.lbl_net_status.setText(f"● OFFLINE // {message[:25]}")
            self.lbl_net_status.setStyleSheet("""
                color: #f87171; font-family: Consolas, monospace; font-size: 8pt; font-weight: bold;
                background: #2a1017; border: 1px solid #ff3366; border-radius: 4px; padding: 3px 6px;
            """)
            self.lbl_status.setText(f"Multi-Workspace Link Offline: {message[:30]}")

    def on_voice_received(self, text: str):
        """Called when user speaks during Identity+Unobserved mode."""
        self.txt_thought.setPlainText(text)
        self.lbl_status.setText(f"Voice captured: \"{text[:32]}...\"")
        if self.chk_auto_inject.isChecked():
            # Auto-injection from voice does not trigger touch yield, keeping AI mouse navigation unhindered
            cleaned = text.strip()
            if cleaned:
                self.thought_injected.emit(cleaned)
                if self.remote_client and self.is_remote_mode:
                    self.remote_client.send_thought(cleaned)
                    self.lbl_status.setText(f"Impulse beamed to Workplace 2: \"{cleaned[:26]}...\"")
                else:
                    self.lbl_status.setText(f"Injected impulse: \"{cleaned[:30]}...\"")
                self.txt_thought.clear()

    def _inject_thought(self):
        self.touch_activity_detected.emit()
        text = self.txt_thought.toPlainText().strip()
        if not text:
            return
        self.thought_injected.emit(text)
        if self.remote_client and self.is_remote_mode:
            self.remote_client.send_thought(text)
            self.lbl_status.setText(f"Impulse beamed to Workplace 2: \"{text[:26]}...\"")
        else:
            self.lbl_status.setText(f"Injected impulse: \"{text[:30]}...\"")
        self.txt_thought.clear()

    def _trigger_action(self, impulse: str):
        self.touch_activity_detected.emit()
        self.action_requested.emit(impulse)
        if self.remote_client and self.is_remote_mode:
            self.remote_client.send_action(impulse)
            self.lbl_status.setText(f"Action beamed to Workplace 2: \"{impulse[:26]}...\"")
        else:
            self.lbl_status.setText(f"Inclination fired: \"{impulse[:30]}...\"")

    def _on_mood_selected(self, mood_key: str):
        self.touch_activity_detected.emit()
        for k, btn in self.mood_buttons.items():
            btn.setChecked(k == mood_key)
        self.mood_selected.emit(mood_key)
        if self.remote_client and self.is_remote_mode:
            self.remote_client.send_mood(mood_key)
            self.lbl_status.setText(f"Mood beamed to Workplace 2: {mood_key}")
        else:
            self.lbl_status.setText(f"Mood set: {mood_key}")

    def _on_pause_clicked(self, checked: bool):
        self.touch_activity_detected.emit()
        if checked:
            self.btn_pause.setText("▶ RESUME AI INPUT")
            self.lbl_status.setText("AI loop FROZEN for touch navigation")
        else:
            self.btn_pause.setText("⏸ PAUSE AI INPUT")
            self.lbl_status.setText("AI loop RESUMED")
        self.pause_toggled.emit(checked)
        if self.remote_client and self.is_remote_mode:
            self.remote_client.send_pause(checked)

    def _on_halt_clicked(self):
        self.touch_activity_detected.emit()
        self.emergency_halt_requested.emit()
        self.btn_pause.setChecked(True)
        self.btn_pause.setText("▶ RESUME AI INPUT")
        self.lbl_status.setText("EMERGENCY HALT triggered")
        if self.remote_client and self.is_remote_mode:
            self.remote_client.send_halt()

    def _on_close_clicked(self):
        self.closed_by_user.emit()

    def _toggle_collapse(self):
        self.touch_activity_detected.emit()
        self._is_collapsed = not self._is_collapsed
        widgets_to_toggle = [
            self.lbl_shield, self.net_bar, self.drawer_pair, self.card_telemetry,
            self.flow_box, self.lbl_mood_sec, self.moods_grid,
            self.lbl_thought_sec, self.voice_note, self.txt_thought, self.inject_bar,
            self.lbl_quick_sec, self.quick_grid, self.lbl_status
        ]
        if self._is_collapsed:
            self._full_size = (self.width(), self.height())
            self.btn_min.setText("+")
            for item in widgets_to_toggle:
                if isinstance(item, QWidget):
                    item.hide()
                elif hasattr(item, "count"):
                    for i in range(item.count()):
                        w = item.itemAt(i).widget()
                        if w:
                            w.hide()
            self.resize(380, 68)
        else:
            self.btn_min.setText("–")
            for item in widgets_to_toggle:
                if isinstance(item, QWidget):
                    item.show()
                elif hasattr(item, "count"):
                    for i in range(item.count()):
                        w = item.itemAt(i).widget()
                        if w:
                            w.show()
            self.resize(*self._full_size)

    def set_status(self, text: str):
        self.lbl_status.setText(text)

