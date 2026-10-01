import os
import sys
import json
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QCheckBox, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon

# AlphaLive Theme Colors
C = {
    "bg_dark": "#050811",
    "bg_card": "#0a1120",
    "bg_card_hover": "#0f1b33",
    "border": "#13233d",
    "neon_blue": "#0077ff",
    "neon_cyan": "#00ffdc",
    "neon_yellow": "#ffe600",
    "text_bright": "#e6f1ff",
    "text_dim": "#708caa",
}

class SystemCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, badge: str, desc: list, badge_color: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_card']};
                border: 1px solid {C['border']};
                border-radius: 8px;
                padding: 16px;
            }}
            QFrame:hover {{
                background-color: {C['bg_card_hover']};
                border: 1px solid {badge_color};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        t_lbl = QLabel(title)
        t_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C['text_bright']}; border: none;")

        b_lbl = QLabel(f" {badge} ")
        b_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        b_lbl.setStyleSheet(f"""
            background-color: {badge_color}22;
            color: {badge_color};
            border: 1px solid {badge_color};
            border-radius: 4px;
            padding: 2px 4px;
        """)

        header.addWidget(t_lbl)
        header.addStretch()
        header.addWidget(b_lbl)
        layout.addLayout(header)

        # Descriptions
        for d in desc:
            d_lbl = QLabel(f"• {d}")
            d_lbl.setFont(QFont("Segoe UI", 9))
            d_lbl.setStyleSheet(f"color: {C['text_dim']}; border: none;")
            d_lbl.setWordWrap(True)
            layout.addWidget(d_lbl)

        layout.addStretch()

        # Action Button
        self.btn = QPushButton(f"LAUNCH {title.split()[0]}")
        self.btn.setFixedHeight(34)
        self.btn.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn.setStyleSheet(f"""
            QPushButton {{
                background: {badge_color}22;
                color: {badge_color};
                border: 1px solid {badge_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {badge_color};
                color: #000;
            }}
        """)
        self.btn.clicked.connect(lambda: self.clicked.emit(self.key))
        layout.addWidget(self.btn)

    def mousePressEvent(self, event):
        self.clicked.emit(self.key)


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AlphaCore // Runtime System Selector")
        self.setFixedSize(680, 420)
        self.setStyleSheet(f"background-color: {C['bg_dark']};")

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        # Title
        title_box = QVBoxLayout()
        main_title = QLabel("ALPHALIVE // SELECT SYSTEM RUNTIME")
        main_title.setFont(QFont("Consolas", 15, QFont.Weight.Bold))
        main_title.setStyleSheet(f"color: {C['neon_cyan']}; letter-spacing: 1px;")

        sub_title = QLabel("Choose the operational architecture for this session:")
        sub_title.setFont(QFont("Segoe UI", 10))
        sub_title.setStyleSheet(f"color: {C['text_dim']};")

        title_box.addWidget(main_title)
        title_box.addWidget(sub_title)
        root.addLayout(title_box)

        # Cards Layout
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        # Card 1: Original AlphaLive
        self.card_live = SystemCard(
            key="alphalive",
            title="ALPHA LIVE (ORIGINAL)",
            badge="LIVE WEBSOCKET",
            desc=[
                "Real-time bidirectional Gemini Live streaming audio & video",
                "Full PyQt6 multi-tab dashboard with Image Studio & HUD",
                "Modal cloud proxy support & live microphone interruption",
                "Turn-based conversational persona with dynamic emotional spectrum"
            ],
            badge_color=C["neon_blue"]
        )
        self.card_live.clicked.connect(self._launch_choice)
        cards_layout.addWidget(self.card_live)

        # Card 2: New Alpha Agent
        self.card_agent = SystemCard(
            key="alpha_agent",
            title="ALPHA AGENT (AUTONOMOUS)",
            badge="STABLE REST // COMPUTER USE",
            desc=[
                "Native multi-step OS navigation & autonomous execution loop",
                "Pristine full-resolution 1080p vision (lossless screen capture)",
                "ZERO GoAway drops or 10-minute session timeouts (Stable REST)",
                "100% Free expressive neural voice output via Edge-TTS & Pygame",
                "Completely unconstrained (Safety Block: NONE)"
            ],
            badge_color=C["neon_cyan"]
        )
        self.card_agent.clicked.connect(self._launch_choice)
        cards_layout.addWidget(self.card_agent)

        root.addLayout(cards_layout)

        # Footer
        footer = QHBoxLayout()
        self.chk_remember = QCheckBox("Remember my selection (skip launcher on next startup)")
        self.chk_remember.setFont(QFont("Segoe UI", 9))
        self.chk_remember.setStyleSheet(f"color: {C['text_dim']};")
        footer.addWidget(self.chk_remember)
        footer.addStretch()

        btn_exit = QPushButton("CANCEL")
        btn_exit.setFixedSize(80, 28)
        btn_exit.setFont(QFont("Consolas", 9))
        btn_exit.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                color: #ff4466;
                border-color: #ff4466;
            }}
        """)
        btn_exit.clicked.connect(self.close)
        footer.addWidget(btn_exit)

        root.addLayout(footer)

    def _launch_choice(self, choice: str):
        cfg_file = ROOT_DIR / "config.json"
        if self.chk_remember.isChecked():
            try:
                cfg = {}
                if cfg_file.exists():
                    with open(cfg_file, "r") as f:
                        cfg = json.load(f)
                cfg.setdefault("Global", {})["DefaultSystem"] = choice
                with open(cfg_file, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception as e:
                print(f"[Launcher] Warning saving preference: {e}")

        self.close()

        if choice == "alphalive":
            print("[Launcher] Starting AlphaLive Original GUI...", flush=True)
            from ui import gui
            gui.main()
        elif choice == "alpha_agent":
            print("[Launcher] Starting AlphaCore Autonomous Agent GUI...", flush=True)
            from ui import agent_gui
            agent_gui.main()

def show_launcher():
    app = QApplication.instance() or QApplication(sys.argv)
    win = LauncherWindow()
    win.show()
    app.exec()

if __name__ == "__main__":
    show_launcher()
