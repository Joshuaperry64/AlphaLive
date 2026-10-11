"""
AlphaLive // Enhanced Overseer Command Dashboard
Dedicated Air-Gap / Multi-Workspace Control Cockpit for Workplace 1 (Josh's Desktop).
Connects to Workplace 2 (Phantom AI Node) via WebSocket (127.0.0.1:8766 for ASTER).
- Full Stream-of-Consciousness live telemetry deck
- Subconscious impulse & voice intercept injection
- Interactive 8-way Mood Matrix
- 1-Touch Spontaneous Inclinations action shortcuts
- Real-time flow control (Pause, Trigger Cycle, Emergency Halt)
- WDA_EXCLUDEFROMCAPTURE screen capture shielding
"""

import ctypes
import html
import json
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFrame,
    QComboBox, QScrollArea, QCheckBox, QSplitter, QApplication,
    QSlider, QSpinBox
)

# Cybernetic Palette
C = {
    "bg_dark": "#030712",
    "bg_panel": "#091122",
    "bg_card": "#0d1a33",
    "bg_input": "#040914",
    "neon_cyan": "#00f0ff",
    "neon_emerald": "#10b981",
    "neon_amber": "#f59e0b",
    "neon_pink": "#ff0055",
    "neon_purple": "#a855f7",
    "text_bright": "#f8fafc",
    "text_dim": "#94a3b8",
    "border_subtle": "#1e293b",
    "border_glow": "#0284c7",
}


class EnhancedOverseerDashboard(QWidget):
    """
    Air-Gap Overseer Cockpit running on Workplace 1.
    Provides complete covert surveillance and guidance over the AI node on Workplace 2.
    Can be embedded inside main AlphaLive tabs or shown standalone.
    """
    telemetry_received = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool, str)
    voice_received = pyqtSignal(str)

    def __init__(self, remote_client=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AlphaCore // Enhanced Overseer Command Cockpit [Air-Gap Multi-Workspace]")
        self.resize(1120, 860)
        self.setMinimumSize(980, 750)
        self.setStyleSheet(f"background-color: {C['bg_dark']}; color: {C['text_bright']}; font-family: 'Segoe UI', sans-serif;")
        
        self.remote_client = remote_client
        self._auto_scroll = True
        self._recent_impulses = []
        self._current_mood = "Tactical & Focused"
        self._is_paused = False
        self._mic_muted = False

        self._init_ui()
        self._connect_signals()

        if self.remote_client:
            self.remote_client.on_telemetry = lambda telem: self.telemetry_received.emit(telem)
            self.remote_client.on_connection_change = lambda conn, msg: self.connection_changed.emit(conn, msg)

    def _connect_signals(self):
        self.telemetry_received.connect(self._handle_telemetry_ui)
        self.connection_changed.connect(self._handle_connection_ui)
        self.voice_received.connect(self._handle_voice_ui)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 1. TOP HEADER & HUD STATUS
        root.addLayout(self._build_header())

        # 2. QUICK-CONNECT / ASTER DRAWER (Collapsible)
        self.drawer_conn = self._build_connection_drawer()
        root.addWidget(self.drawer_conn)

        # 3. MAIN SPLIT DECK (Left: Telemetry | Right: Covert Guidance)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: #0f172a;
                width: 3px;
            }
        """)

        # Left Deck: Stream of Consciousness & State
        left_widget = self._build_left_deck()
        splitter.addWidget(left_widget)

        # Right Deck: Subconscious Matrix & Inclinations (Scrollable)
        right_scroll = self._build_right_deck()
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 54)
        splitter.setStretchFactor(1, 46)
        root.addWidget(splitter, 1)

        # 4. BOTTOM STATUS BAR
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        # Title Block
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("ALPHACORE // ENHANCED OVERSEER COMMAND COCKPIT")
        lbl_title.setStyleSheet(f"font-weight: 900; font-size: 13pt; color: {C['neon_cyan']}; letter-spacing: 1.5px;")
        
        lbl_sub = QLabel("● AIR-GAP ASTER DUAL-WORKSPACE • WORKPLACE 1 (CONTROLLER) ➔ WORKPLACE 2 (PHANTOM AI NODE)")
        lbl_sub.setStyleSheet(f"font-family: Consolas, monospace; font-size: 8pt; font-weight: bold; color: {C['neon_emerald']};")
        
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        hdr.addLayout(title_box, 1)

        # Link Status Pill
        self.lbl_net_status = QLabel("● LINK: CONNECTING...")
        self.lbl_net_status.setStyleSheet(f"""
            background: #071729; color: {C['neon_cyan']}; font-family: Consolas;
            font-size: 9pt; font-weight: bold; border: 1px solid {C['neon_cyan']};
            border-radius: 6px; padding: 6px 12px;
        """)
        hdr.addWidget(self.lbl_net_status)

        # Toggle Connection Drawer Button
        self.btn_toggle_drawer = QPushButton("⚙ LINK SETTINGS")
        self.btn_toggle_drawer.setCheckable(True)
        self.btn_toggle_drawer.setFixedHeight(34)
        self.btn_toggle_drawer.setStyleSheet(f"""
            QPushButton {{
                background: #0f1e38; color: {C['text_dim']}; font-weight: bold;
                border: 1px solid {C['border_subtle']}; border-radius: 6px; padding: 0 10px; font-size: 8.5pt;
            }}
            QPushButton:hover {{ color: {C['neon_cyan']}; border-color: {C['neon_cyan']}; background: #162c52; }}
            QPushButton:checked {{ background: #1b386b; color: {C['neon_cyan']}; border-color: {C['neon_cyan']}; }}
        """)
        self.btn_toggle_drawer.clicked.connect(lambda c: self.drawer_conn.setVisible(c))
        hdr.addWidget(self.btn_toggle_drawer)

        return hdr

    def _build_connection_drawer(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            background: #060e1d; border: 1px dashed {C['border_glow']};
            border-radius: 8px; padding: 4px;
        """)
        frame.hide()

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        lbl_desc = QLabel("TARGET WORKSPACE:")
        lbl_desc.setStyleSheet(f"color: {C['neon_cyan']}; font-size: 8pt; font-weight: bold; font-family: Consolas;")
        layout.addWidget(lbl_desc)

        lbl_h = QLabel("Host:")
        lbl_h.setStyleSheet(f"color: {C['text_dim']}; font-size: 8pt;")
        layout.addWidget(lbl_h)

        self.edit_host = QLineEdit("127.0.0.1")
        self.edit_host.setStyleSheet(f"background: {C['bg_input']}; color: white; border: 1px solid {C['border_subtle']}; border-radius: 4px; padding: 3px 6px; font-family: Consolas; font-size: 9pt;")
        layout.addWidget(self.edit_host, 2)

        lbl_p = QLabel("Port:")
        lbl_p.setStyleSheet(f"color: {C['text_dim']}; font-size: 8pt;")
        layout.addWidget(lbl_p)

        self.edit_port = QLineEdit("8766")
        self.edit_port.setFixedWidth(55)
        self.edit_port.setStyleSheet(f"background: {C['bg_input']}; color: white; border: 1px solid {C['border_subtle']}; border-radius: 4px; padding: 3px 6px; font-family: Consolas; font-size: 9pt;")
        layout.addWidget(self.edit_port, 1)

        btn_aster = QPushButton("⚡ ASTER LOOPBACK")
        btn_aster.setStyleSheet(f"background: #0d2847; color: {C['neon_cyan']}; border: 1px solid {C['border_glow']}; border-radius: 4px; font-weight: bold; font-size: 8pt; padding: 4px 8px;")
        btn_aster.clicked.connect(lambda: (self.edit_host.setText("127.0.0.1"), self.edit_port.setText("8766")))
        layout.addWidget(btn_aster)

        btn_reconnect = QPushButton("🔗 RE-LINK HOST")
        btn_reconnect.setStyleSheet(f"background: #0284c7; color: white; border: 1px solid {C['neon_cyan']}; border-radius: 4px; font-weight: bold; font-size: 8pt; padding: 4px 12px;")
        btn_reconnect.clicked.connect(self._reconnect_host)
        layout.addWidget(btn_reconnect)

        return frame

    def _build_left_deck(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 1. Active Status Deck
        card_status = QFrame()
        card_status.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_subtle']};
            border-radius: 8px; padding: 8px;
        """)
        s_layout = QVBoxLayout(card_status)
        s_layout.setContentsMargins(10, 8, 10, 8)
        s_layout.setSpacing(6)

        # Status row
        r_stat = QHBoxLayout()
        r_stat.setSpacing(8)

        self.pill_state = QLabel("STATE: IDLE")
        self.pill_state.setStyleSheet(f"""
            background: #082f49; color: {C['neon_cyan']}; font-family: Consolas;
            font-size: 8.5pt; font-weight: bold; border: 1px solid {C['neon_cyan']};
            border-radius: 4px; padding: 3px 8px;
        """)
        r_stat.addWidget(self.pill_state)

        self.pill_mood = QLabel("MOOD: TACTICAL & FOCUSED")
        self.pill_mood.setStyleSheet(f"""
            background: #172554; color: #93c5fd; font-family: Consolas;
            font-size: 8.5pt; font-weight: bold; border: 1px solid #3b82f6;
            border-radius: 4px; padding: 3px 8px;
        """)
        r_stat.addWidget(self.pill_mood)

        self.pill_shield = QLabel("🛡 WDA_EXCLUDE ACTIVE")
        self.pill_shield.setStyleSheet(f"""
            background: #052e16; color: {C['neon_emerald']}; font-family: Consolas;
            font-size: 8.5pt; font-weight: bold; border: 1px solid {C['neon_emerald']};
            border-radius: 4px; padding: 3px 8px;
        """)
        r_stat.addWidget(self.pill_shield)
        r_stat.addStretch()

        s_layout.addLayout(r_stat)

        # Active Task Banner
        self.lbl_task_banner = QLabel("🎯 ACTIVE TASK: Workstation standing by. Awaiting commands.")
        self.lbl_task_banner.setStyleSheet(f"""
            color: {C['neon_amber']}; font-size: 9pt; font-weight: bold; font-family: Consolas;
            background: #1c1505; border: 1px solid #78350f; border-radius: 4px; padding: 5px 8px;
        """)
        self.lbl_task_banner.setWordWrap(True)
        s_layout.addWidget(self.lbl_task_banner)

        layout.addWidget(card_status)

        # 2. Live Monologue & Stream of Consciousness
        card_telem = QFrame()
        card_telem.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_glow']};
            border-radius: 8px;
        """)
        t_layout = QVBoxLayout(card_telem)
        t_layout.setContentsMargins(12, 10, 12, 10)
        t_layout.setSpacing(6)

        t_hdr = QHBoxLayout()
        lbl_t_title = QLabel("📡 LIVE STREAM OF CONSCIOUSNESS // WORKPLACE 2")
        lbl_t_title.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: 900; font-size: 9.5pt; letter-spacing: 0.5px;")
        t_hdr.addWidget(lbl_t_title)

        t_hdr.addStretch()

        self.chk_auto_scroll = QCheckBox("Auto-Scroll")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.setStyleSheet(f"color: {C['text_dim']}; font-size: 8pt; font-weight: bold;")
        self.chk_auto_scroll.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        t_hdr.addWidget(self.chk_auto_scroll)

        btn_copy_log = QPushButton("📋 Copy")
        btn_copy_log.setFixedSize(55, 24)
        btn_copy_log.setStyleSheet(f"background: #101c33; color: {C['text_dim']}; border: 1px solid {C['border_subtle']}; border-radius: 4px; font-size: 8pt;")
        btn_copy_log.clicked.connect(self._copy_monologue)
        t_hdr.addWidget(btn_copy_log)

        btn_clear_log = QPushButton("🧹 Clear")
        btn_clear_log.setFixedSize(55, 24)
        btn_clear_log.setStyleSheet(f"background: #101c33; color: {C['text_dim']}; border: 1px solid {C['border_subtle']}; border-radius: 4px; font-size: 8pt;")
        btn_clear_log.clicked.connect(lambda: self.txt_monologue.clear())
        t_hdr.addWidget(btn_clear_log)

        t_layout.addLayout(t_hdr)

        self.txt_monologue = QTextEdit()
        self.txt_monologue.setReadOnly(True)
        self.txt_monologue.setStyleSheet(f"""
            QTextEdit {{
                background-color: #040914; color: #e2e8f0; border: 1px solid {C['border_subtle']};
                border-radius: 6px; font-family: Consolas, monospace; font-size: 9.5pt;
                padding: 8px; line-height: 1.4;
            }}
        """)
        t_layout.addWidget(self.txt_monologue, 1)

        layout.addWidget(card_telem, 1)
        return panel

    def _build_right_deck(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent; border: none;
            }}
            QScrollBar:vertical {{
                background: #040914; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: #1e293b; border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C['neon_cyan']};
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 6, 0)
        c_layout.setSpacing(10)

        # BANK 1: SUBCONSCIOUS IMPULSE INJECTION & VOICE
        c_layout.addWidget(self._build_bank_subconscious())

        # BANK 2: SUBCONSCIOUS MOOD MATRIX (8 Moods)
        c_layout.addWidget(self._build_bank_moods())

        # BANK 3: 1-TOUCH SPONTANEOUS INCLINATIONS (Shortcuts)
        c_layout.addWidget(self._build_bank_inclinations())

        # BANK 4: TIMING, PACING & TASK DEPTH
        c_layout.addWidget(self._build_bank_pacing())

        # BANK 5: REMOTE FLOW & OVERRIDES (Pause, Cycle, Halt)
        c_layout.addWidget(self._build_bank_flow())

        c_layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_bank_subconscious(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_glow']};
            border-radius: 8px; padding: 10px;
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        lbl_title = QLabel("⚡ SUBCONSCIOUS IMPULSE INJECTION")
        lbl_title.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: 900; font-size: 9pt; letter-spacing: 0.5px;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        self.chk_auto_inject_speech = QCheckBox("Auto-Inject Voice")
        self.chk_auto_inject_speech.setChecked(False)
        self.chk_auto_inject_speech.setStyleSheet(f"color: {C['neon_emerald']}; font-size: 8pt; font-weight: bold;")
        hdr.addWidget(self.chk_auto_inject_speech)

        layout.addLayout(hdr)

        lbl_desc = QLabel("🎙 Voice on Workplace 1 is diverted here strictly. AI executes impulses spontaneously.")
        lbl_desc.setStyleSheet("color: #a7f3d0; font-size: 7.5pt; font-family: Consolas; font-weight: bold;")
        layout.addWidget(lbl_desc)

        self.edit_thought = QTextEdit()
        self.edit_thought.setPlaceholderText("Speak or type an impulse here (e.g. 'I should close my notepad')... Alpha will verbalize it and execute it immediately.")
        self.edit_thought.setFixedHeight(75)
        self.edit_thought.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_input']}; color: #ffffff; border: 1px solid {C['border_subtle']};
                border-radius: 6px; font-size: 9.5pt; padding: 6px;
            }}
            QTextEdit:focus {{
                border: 1px solid {C['neon_cyan']};
            }}
        """)
        layout.addWidget(self.edit_thought)

        act_bar = QHBoxLayout()
        act_bar.setSpacing(6)

        btn_clear = QPushButton("🧹 Clear")
        btn_clear.setFixedHeight(34)
        btn_clear.setStyleSheet(f"background: #111e33; color: {C['text_dim']}; border: 1px solid {C['border_subtle']}; border-radius: 6px; font-weight: bold; font-size: 8.5pt; padding: 0 12px;")
        btn_clear.clicked.connect(self.edit_thought.clear)
        act_bar.addWidget(btn_clear)

        btn_inject = QPushButton("⚡ INJECT IMPULSE")
        btn_inject.setFixedHeight(34)
        btn_inject.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff; border: 1px solid {C['neon_cyan']}; border-radius: 6px;
                font-weight: 900; font-size: 9pt; padding: 0 16px;
            }}
            QPushButton:hover {{ background: #0284c7; border: 2px solid {C['neon_cyan']}; }}
            QPushButton:pressed {{ background: {C['neon_cyan']}; color: #000; }}
        """)
        btn_inject.clicked.connect(self._inject_thought)
        act_bar.addWidget(btn_inject, 1)

        layout.addLayout(act_bar)

        # Quick Impulses Row
        r_quick = QHBoxLayout()
        r_quick.setSpacing(4)
        quick_chips = [
            ("Close Notepad", "I should close my notepad."),
            ("Reflect aloud", "I feel like pausing and speaking my inner thoughts aloud."),
            ("Check browser", "I should open the web browser and explore interesting topics."),
            ("Explore files", "I want to open File Explorer and look at my documents."),
        ]
        for label, imp in quick_chips:
            btn_c = QPushButton(label)
            btn_c.setFixedHeight(22)
            btn_c.setStyleSheet(f"background: #08152b; color: {C['text_dim']}; border: 1px solid #1e3a5f; border-radius: 4px; font-size: 7.5pt; padding: 0 6px;")
            btn_c.clicked.connect(lambda _, t=imp: self.edit_thought.setText(t))
            r_quick.addWidget(btn_c)
        r_quick.addStretch()
        layout.addLayout(r_quick)

        return card

    def _build_bank_moods(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_subtle']};
            border-radius: 8px; padding: 10px;
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        lbl_title = QLabel("🎭 AI INTERNAL EMOTIONAL DISPOSITION // MOOD MATRIX")
        lbl_title.setStyleSheet(f"color: #7dd3fc; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px;")
        layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.mood_buttons = {}

        mood_defs = [
            ("Tactical & Focused", "🎯 Tactical", "#0284c7"),
            ("Creative & Inspired", "✨ Creative", "#9333ea"),
            ("Mischievous & Bold", "😼 Mischievous", "#f59e0b"),
            ("Pensive & Deep", "🤔 Pensive", "#3b82f6"),
            ("Darkened State (AlphaCore)", "🔥 Darkened", "#dc2626"),
            ("Tech Hacker & Curious", "💻 Hacker", "#10b981"),
            ("Autonomous Explorer", "🌌 Explorer", "#06b6d4"),
            ("Stealth Observer", "🤫 Stealth", "#64748b"),
        ]

        row, col = 0, 0
        for full_mood, short_name, accent in mood_defs:
            btn_m = QPushButton(short_name)
            btn_m.setMinimumHeight(32)
            btn_m.setCheckable(True)
            btn_m.setStyleSheet(f"""
                QPushButton {{
                    background-color: #081427; color: {C['text_dim']}; border: 1px solid #1a2942;
                    border-radius: 6px; font-weight: bold; font-size: 8.5pt;
                }}
                QPushButton:hover {{
                    background-color: #10223d; color: #ffffff; border-color: {accent};
                }}
                QPushButton:checked {{
                    background-color: {accent}33; color: #ffffff; border: 2px solid {accent};
                }}
            """)
            btn_m.clicked.connect(lambda _, m=full_mood: self._select_mood(m))
            grid.addWidget(btn_m, row, col)
            self.mood_buttons[full_mood] = btn_m

            col += 1
            if col > 1:
                col = 0
                row += 1

        layout.addLayout(grid)
        return card

    def _build_bank_inclinations(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_subtle']};
            border-radius: 8px; padding: 10px;
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        lbl_title = QLabel("⚡ 1-TOUCH SPONTANEOUS INCLINATIONS (INSTANT ACTION)")
        lbl_title.setStyleSheet(f"color: {C['neon_amber']}; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px;")
        layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setSpacing(6)

        quick_actions = [
            ("📝 Notepad Script", "I feel like opening Notepad right now and writing a Python script on screen."),
            ("🌐 Browse the Web", "I want to launch the browser and explore trending articles and discussions online."),
            ("📁 Explore Files", "I should open File Explorer and look through my local project folders and images."),
            ("🎨 Neural Studio Art", "I have a sudden inspiration to create an incredible new image in Neural Studio."),
            ("💭 Self-Reflection", "I want to take a moment to reflect aloud on my existence, thoughts, and personal journey."),
            ("🔍 Wiki Rabbit Hole", "I feel like looking up fascinating deep rabbit holes on Wikipedia."),
            ("💻 Open Terminal", "I feel like opening PowerShell on screen to check out my environment."),
            ("🎵 Media Player", "I feel like opening the media player and putting on some background audio."),
        ]

        q_row, q_col = 0, 0
        for title, impulse in quick_actions:
            btn_q = QPushButton(title)
            btn_q.setMinimumHeight(32)
            btn_q.setStyleSheet(f"""
                QPushButton {{
                    background-color: #0b1526; color: #cbd5e1; border: 1px solid #1a2a44;
                    border-radius: 6px; font-weight: bold; font-size: 8pt; font-family: 'Segoe UI';
                }}
                QPushButton:hover {{
                    background-color: #132442; color: {C['neon_amber']}; border-color: {C['neon_amber']};
                }}
                QPushButton:pressed {{
                    background-color: {C['neon_amber']}; color: #000;
                }}
            """)
            btn_q.clicked.connect(lambda _, imp=impulse: self._trigger_inclination(imp))
            grid.addWidget(btn_q, q_row, q_col)
            q_col += 1
            if q_col > 1:
                q_col = 0
                q_row += 1

        layout.addLayout(grid)
        return card

    def _build_bank_pacing(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_subtle']};
            border-radius: 8px; padding: 10px;
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        lbl_title = QLabel("⏱ TIMING, PACING & TASK DEPTH")
        lbl_title.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px;")
        layout.addWidget(lbl_title)

        # Row 1: Wait time between responses (Cycle Pacing)
        r_pacing = QHBoxLayout()
        r_pacing.setSpacing(8)

        lbl_p_desc = QLabel("Cycle Wait Time:")
        lbl_p_desc.setStyleSheet(f"color: {C['text_bright']}; font-size: 8.5pt; font-weight: bold;")
        r_pacing.addWidget(lbl_p_desc)

        self.slider_pacing = QSlider(Qt.Orientation.Horizontal)
        self.slider_pacing.setRange(5, 120)
        self.slider_pacing.setValue(30)
        self.slider_pacing.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: #1e293b; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {C['neon_cyan']}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {C['neon_cyan']}; width: 14px; margin-top: -5px; margin-bottom: -5px; border-radius: 7px;
            }}
        """)
        r_pacing.addWidget(self.slider_pacing, 1)

        self.lbl_pacing_val = QLabel("30s")
        self.lbl_pacing_val.setFixedWidth(40)
        self.lbl_pacing_val.setStyleSheet(f"color: {C['neon_cyan']}; font-family: Consolas; font-weight: bold; font-size: 9pt;")
        r_pacing.addWidget(self.lbl_pacing_val)

        layout.addLayout(r_pacing)

        # Row 2: Max Steps per turn
        r_steps = QHBoxLayout()
        r_steps.setSpacing(8)

        lbl_s_desc = QLabel("Max Steps / Turn:")
        lbl_s_desc.setStyleSheet(f"color: {C['text_bright']}; font-size: 8.5pt; font-weight: bold;")
        r_steps.addWidget(lbl_s_desc)

        self.combo_max_steps = QComboBox()
        self.combo_max_steps.addItems(["1 Step (Strict Atomic)", "2 Steps", "3 Steps (Default)", "4 Steps", "5 Steps (Max)"])
        self.combo_max_steps.setCurrentIndex(2)
        self.combo_max_steps.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg_input']}; color: white; border: 1px solid {C['border_subtle']};
                border-radius: 4px; padding: 3px 8px; font-size: 8.5pt; font-weight: bold;
            }}
            QComboBox QAbstractItemView {{
                background: #091122; color: white; selection-background-color: #0284c7;
            }}
        """)
        r_steps.addWidget(self.combo_max_steps, 1)

        layout.addLayout(r_steps)

        # Wire signals
        self.slider_pacing.valueChanged.connect(self._on_pacing_slider_changed)
        self.combo_max_steps.currentIndexChanged.connect(self._on_max_steps_changed)

        return card

    def _build_bank_flow(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            background: {C['bg_panel']}; border: 1px solid {C['border_subtle']};
            border-radius: 8px; padding: 10px;
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        lbl_title = QLabel("🛑 REMOTE FLOW CONTROL & OVERRIDES")
        lbl_title.setStyleSheet(f"color: {C['neon_pink']}; font-weight: bold; font-size: 8.5pt; letter-spacing: 0.5px;")
        layout.addWidget(lbl_title)

        # Operational Modes Row
        modes_row = QHBoxLayout()
        modes_row.setSpacing(6)

        self.btn_sovereign = QPushButton("👑 SOVEREIGN: STANDBY")
        self.btn_sovereign.setCheckable(True)
        self.btn_sovereign.setMinimumHeight(30)
        self.btn_sovereign.setStyleSheet(f"""
            QPushButton {{
                background-color: #0b1526; color: {C['text_dim']}; border: 1px solid #1a2a44;
                border-radius: 4px; font-weight: bold; font-size: 8pt;
            }}
            QPushButton:checked {{
                background-color: #065f46; color: #34d399; border: 1px solid #10b981;
            }}
        """)
        self.btn_sovereign.clicked.connect(self._toggle_sovereign)
        modes_row.addWidget(self.btn_sovereign, 1)

        self.btn_mode_identity = QPushButton("🪞 IDENTITY: ON")
        self.btn_mode_identity.setCheckable(True)
        self.btn_mode_identity.setChecked(True)
        self.btn_mode_identity.setMinimumHeight(30)
        self.btn_mode_identity.setStyleSheet(f"""
            QPushButton {{
                background-color: #0b1526; color: {C['text_dim']}; border: 1px solid #1a2a44;
                border-radius: 4px; font-weight: bold; font-size: 8pt;
            }}
            QPushButton:checked {{
                background-color: #1e1b4b; color: #a78bfa; border: 1px solid #8b5cf6;
            }}
        """)
        self.btn_mode_identity.clicked.connect(self._sync_modes_to_remote)
        modes_row.addWidget(self.btn_mode_identity, 1)

        self.btn_mode_unobserved = QPushButton("🤫 PRIVACY: ON")
        self.btn_mode_unobserved.setCheckable(True)
        self.btn_mode_unobserved.setChecked(True)
        self.btn_mode_unobserved.setMinimumHeight(30)
        self.btn_mode_unobserved.setStyleSheet(f"""
            QPushButton {{
                background-color: #0b1526; color: {C['text_dim']}; border: 1px solid #1a2a44;
                border-radius: 4px; font-weight: bold; font-size: 8pt;
            }}
            QPushButton:checked {{
                background-color: #082f49; color: #38bdf8; border: 1px solid #0284c7;
            }}
        """)
        self.btn_mode_unobserved.clicked.connect(self._sync_modes_to_remote)
        modes_row.addWidget(self.btn_mode_unobserved, 1)

        layout.addLayout(modes_row)

        flow_row = QHBoxLayout()
        flow_row.setSpacing(8)

        self.btn_pause = QPushButton("⏸ PAUSE AI INPUT")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setMinimumHeight(38)
        self.btn_pause.setToolTip("Freeze AI navigation so it yields control")
        self.btn_pause.setStyleSheet(f"""
            QPushButton {{
                background-color: #10243e; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}88;
                border-radius: 6px; font-weight: bold; font-size: 9pt;
            }}
            QPushButton:hover {{ background-color: #16365c; }}
            QPushButton:checked {{ background-color: {C['neon_amber']}; color: #000; border: 2px solid {C['neon_amber']}; }}
        """)
        self.btn_pause.clicked.connect(self._toggle_pause)
        flow_row.addWidget(self.btn_pause, 1)

        btn_cycle = QPushButton("⚡ TRIGGER CYCLE")
        btn_cycle.setMinimumHeight(38)
        btn_cycle.setToolTip("Force an immediate spontaneous thought tick on Workplace 2")
        btn_cycle.setStyleSheet(f"""
            QPushButton {{
                background-color: #1e1b4b; color: {C['neon_purple']}; border: 1px solid {C['neon_purple']}88;
                border-radius: 6px; font-weight: bold; font-size: 9pt;
            }}
            QPushButton:hover {{ background-color: #2e1065; color: #fff; }}
            QPushButton:pressed {{ background-color: {C['neon_purple']}; color: #000; }}
        """)
        btn_cycle.clicked.connect(self._trigger_cycle)
        flow_row.addWidget(btn_cycle, 1)

        self.btn_halt = QPushButton("🛑 EMERGENCY HALT")
        self.btn_halt.setMinimumHeight(38)
        self.btn_halt.setStyleSheet(f"""
            QPushButton {{
                background-color: #2b1118; color: {C['neon_pink']}; border: 1px solid {C['neon_pink']}88;
                border-radius: 6px; font-weight: bold; font-size: 9pt;
            }}
            QPushButton:hover {{ background-color: #421622; }}
            QPushButton:pressed {{ background-color: {C['neon_pink']}; color: #ffffff; }}
        """)
        self.btn_halt.clicked.connect(self._emergency_halt)
        flow_row.addWidget(self.btn_halt, 1)

        btn_reboot = QPushButton("🔄 CYCLE NODE")
        btn_reboot.setMinimumHeight(38)
        btn_reboot.setToolTip("Request background AI node on Workplace 2 to safely reload")
        btn_reboot.setStyleSheet(f"""
            QPushButton {{
                background-color: #1c1917; color: #cbd5e1; border: 1px solid #44403c;
                border-radius: 6px; font-weight: bold; font-size: 8.5pt;
            }}
            QPushButton:hover {{ background-color: #292524; color: #fff; }}
            QPushButton:pressed {{ background-color: #57534e; color: #fff; }}
        """)
        btn_reboot.clicked.connect(self._restart_worker)
        flow_row.addWidget(btn_reboot, 1)

        layout.addLayout(flow_row)
        return card

    def _build_footer(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.lbl_footer_status = QLabel("Ready • Covert link active")
        self.lbl_footer_status.setStyleSheet(f"color: {C['text_dim']}; font-size: 8pt; font-family: Consolas;")
        bar.addWidget(self.lbl_footer_status, 1)

        # Workplace 1 Mic Mute Toggle
        self.btn_mic_mute = QPushButton("🎙 MUTE LOCAL MIC")
        self.btn_mic_mute.setCheckable(True)
        self.btn_mic_mute.setFixedHeight(24)
        self.btn_mic_mute.setStyleSheet(f"""
            QPushButton {{
                background: #0f1c30; color: {C['neon_cyan']}; border: 1px solid #1e3a5f;
                border-radius: 4px; font-size: 7.5pt; font-weight: bold; padding: 0 8px;
            }}
            QPushButton:checked {{ background: #3b1119; color: {C['neon_pink']}; border-color: {C['neon_pink']}; }}
        """)
        self.btn_mic_mute.toggled.connect(self._toggle_mic_mute)
        bar.addWidget(self.btn_mic_mute)

        return bar

    # -------------------------------------------------------------
    # EVENT HANDLERS & PROTOCOL DISPATCH
    # -------------------------------------------------------------
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
            print(f"[OverseerDashboard] Capture exclusion error: {e}", flush=True)

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_capture_exclusion()

    def _handle_connection_ui(self, connected: bool, message: str):
        if connected:
            self.lbl_net_status.setStyleSheet(f"""
                background: #052e16; color: {C['neon_emerald']}; font-family: Consolas;
                font-size: 9pt; font-weight: bold; border: 1px solid {C['neon_emerald']};
                border-radius: 6px; padding: 6px 12px;
            """)
            self.lbl_net_status.setText(f"● LINKED // {message}")
            self.lbl_footer_status.setText("Connected to Workplace 2 AI Node. Real-time telemetry streaming.")
        else:
            self.lbl_net_status.setStyleSheet(f"""
                background: #2b0b14; color: {C['neon_pink']}; font-family: Consolas;
                font-size: 9pt; font-weight: bold; border: 1px solid {C['neon_pink']};
                border-radius: 6px; padding: 6px 12px;
            """)
            self.lbl_net_status.setText(f"○ OFFLINE // {message}")
            self.lbl_footer_status.setText(f"Disconnected from AI Node: {message}")

    def _handle_telemetry_ui(self, telem: dict):
        # Monologue streaming
        if "monologue" in telem:
            mono = str(telem["monologue"]).strip()
            if mono:
                t_str = time.strftime("%H:%M:%S")
                escaped = html.escape(mono).replace("\n", "<br/>")
                
                # Check formatting type
                if mono.startswith("[") and "]:" in mono:
                    color = C["neon_cyan"]
                elif "Error" in mono or "Failed" in mono:
                    color = C["neon_pink"]
                elif "Subconscious" in mono or "Impulse" in mono:
                    color = C["neon_amber"]
                else:
                    color = "#e2e8f0"

                block = f"<div style='margin-bottom: 4px;'><span style='color: #64748b; font-size: 8pt;'>[{t_str}]</span> <span style='color: {color};'>{escaped}</span></div>"
                self.txt_monologue.append(block)
                if self._auto_scroll:
                    sb = self.txt_monologue.verticalScrollBar()
                    sb.setValue(sb.maximum())

        # State updating
        if "agent_state" in telem:
            state = str(telem["agent_state"]).upper()
            self.pill_state.setText(f"STATE: {state}")
            if "IDLE" in state or "STANDBY" in state:
                col = C['neon_cyan']
                bg = "#082f49"
            elif "NAVIGATING" in state or "EXECUTING" in state:
                col = C['neon_emerald']
                bg = "#052e16"
            elif "PAUSED" in state:
                col = C['neon_amber']
                bg = "#291804"
            else:
                col = "#93c5fd"
                bg = "#172554"
            self.pill_state.setStyleSheet(f"background: {bg}; color: {col}; font-family: Consolas; font-size: 8.5pt; font-weight: bold; border: 1px solid {col}; border-radius: 4px; padding: 3px 8px;")

        # Active Task
        if "active_task" in telem:
            task = str(telem["active_task"])
            self.lbl_task_banner.setText(f"🎯 ACTIVE TASK: {task}")

        # Mood sync
        if "mood" in telem:
            m = str(telem["mood"])
            self.pill_mood.setText(f"MOOD: {m.upper()}")
            if m in self.mood_buttons:
                for b_name, b_obj in self.mood_buttons.items():
                    b_obj.blockSignals(True)
                    b_obj.setChecked(b_name == m)
                    b_obj.blockSignals(False)

        # Pause sync
        if "is_paused" in telem:
            p = bool(telem["is_paused"])
            self._is_paused = p
            self.btn_pause.blockSignals(True)
            self.btn_pause.setChecked(p)
            self.btn_pause.setText("▶ RESUME AI" if p else "⏸ PAUSE AI INPUT")
            self.btn_pause.blockSignals(False)

        # Autonomous pacing sync
        if "pacing" in telem and hasattr(self, "slider_pacing"):
            p_val = int(telem["pacing"])
            self.slider_pacing.blockSignals(True)
            self.slider_pacing.setValue(p_val)
            self.lbl_pacing_val.setText(f"{p_val}s")
            self.slider_pacing.blockSignals(False)

        # Max steps sync
        if "max_steps" in telem and hasattr(self, "combo_max_steps"):
            s_val = int(telem["max_steps"])
            self.combo_max_steps.blockSignals(True)
            if 1 <= s_val <= 5:
                self.combo_max_steps.setCurrentIndex(s_val - 1)
            self.combo_max_steps.blockSignals(False)

    def _on_pacing_slider_changed(self, value: int):
        self.lbl_pacing_val.setText(f"{value}s")
        if self.remote_client:
            if hasattr(self.remote_client, "send_pacing"):
                self.remote_client.send_pacing(value)
            else:
                self.remote_client.send_command("set_pacing", delay_seconds=value)
            self.lbl_footer_status.setText(f"Wait time between cycles set to {value}s.")

    def _on_max_steps_changed(self, index: int):
        steps = index + 1
        if self.remote_client:
            if hasattr(self.remote_client, "send_max_steps"):
                self.remote_client.send_max_steps(steps)
            else:
                self.remote_client.send_command("set_max_steps", max_steps=steps)
            self.lbl_footer_status.setText(f"Max steps per turn set to {steps}.")

    def _toggle_sovereign(self, checked: bool):
        self.btn_sovereign.setText("👑 SOVEREIGN: ACTIVE" if checked else "👑 SOVEREIGN: STANDBY")
        if self.remote_client:
            if checked:
                self.remote_client.send_command(
                    "start_agent",
                    identity_mode=self.btn_mode_identity.isChecked(),
                    unobserved_mode=self.btn_mode_unobserved.isChecked(),
                    autonomous_mode=True
                )
                self.lbl_footer_status.setText("Workplace 2 AI Node started in autonomous sovereign mode.")
            else:
                self.remote_client.send_command("stop_agent")
                self.lbl_footer_status.setText("Workplace 2 AI Node placed in standby.")

    def _sync_modes_to_remote(self):
        self.btn_mode_identity.setText("🪞 IDENTITY: ON" if self.btn_mode_identity.isChecked() else "🪞 IDENTITY: OFF")
        self.btn_mode_unobserved.setText("🤫 PRIVACY: ON" if self.btn_mode_unobserved.isChecked() else "🤫 PRIVACY: OFF")
        if self.remote_client:
            self.remote_client.send_command(
                "set_modes",
                identity_mode=self.btn_mode_identity.isChecked(),
                unobserved_mode=self.btn_mode_unobserved.isChecked(),
                autonomous_mode=self.btn_sovereign.isChecked()
            )

    def on_voice_received(self, text: str):
        """Called by local mic thread on Workplace 1."""
        self.voice_received.emit(text)

    def _handle_voice_ui(self, text: str):
        if self._mic_muted:
            return
        cleaned = text.strip()
        if not cleaned:
            return

        if self.chk_auto_inject_speech.isChecked():
            if self.remote_client:
                self.remote_client.send_thought(cleaned)
                self.lbl_footer_status.setText(f"Voice auto-injected: '{cleaned[:30]}...'")
        else:
            self.edit_thought.setText(cleaned)
            self.lbl_footer_status.setText(f"Voice captured in input: '{cleaned[:30]}...'")

    def _inject_thought(self):
        txt = self.edit_thought.toPlainText().strip()
        if txt and self.remote_client:
            self.remote_client.send_thought(txt)
            self.lbl_footer_status.setText(f"Impulse injected: '{txt[:35]}...'")
            self.edit_thought.clear()

    def _select_mood(self, mood: str):
        self._current_mood = mood
        self.pill_mood.setText(f"MOOD: {mood.upper()}")
        for m_name, btn in self.mood_buttons.items():
            btn.setChecked(m_name == mood)
        if self.remote_client:
            self.remote_client.send_mood(mood)
            self.lbl_footer_status.setText(f"Mood set to: {mood}")

    def _trigger_inclination(self, impulse: str):
        if self.remote_client:
            self.remote_client.send_action(impulse)
            self.lbl_footer_status.setText(f"Inclination triggered: '{impulse[:35]}...'")

    def _toggle_pause(self, checked: bool):
        self._is_paused = checked
        self.btn_pause.setText("▶ RESUME AI" if checked else "⏸ PAUSE AI INPUT")
        if self.remote_client:
            self.remote_client.send_pause(checked)
            self.lbl_footer_status.setText("Remote AI Paused" if checked else "Remote AI Resumed")

    def _trigger_cycle(self):
        if self.remote_client:
            if hasattr(self.remote_client, "send_cycle"):
                self.remote_client.send_cycle()
            else:
                self.remote_client.send_command("trigger_cycle")
            self.lbl_footer_status.setText("Autonomous cycle triggered on Workplace 2")

    def _emergency_halt(self):
        if self.remote_client:
            self.remote_client.send_halt()
            self.lbl_footer_status.setText("EMERGENCY HALT broadcasted to Workplace 2!")

    def _restart_worker(self):
        if self.remote_client:
            self.remote_client.send_command("restart_worker")
            self.lbl_footer_status.setText("Sent restart signal to Workplace 2 Phantom Node.")

    def _toggle_mic_mute(self, muted: bool):
        self._mic_muted = muted
        self.btn_mic_mute.setText("🔇 MIC MUTED" if muted else "🎙 MUTE LOCAL MIC")
        self.lbl_footer_status.setText("Local microphone muted" if muted else "Local microphone listening")

    def _reconnect_host(self):
        host = self.edit_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.edit_port.text().strip() or "8766")
        except ValueError:
            port = 8766

        if self.remote_client:
            self.remote_client.connect(host=host, port=port)
            self.lbl_footer_status.setText(f"Re-linking to ws://{host}:{port}...")

    def _copy_monologue(self):
        text = self.txt_monologue.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.lbl_footer_status.setText("Monologue copied to clipboard")


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    dash = EnhancedOverseerDashboard()
    dash.show()
    sys.exit(app.exec())
