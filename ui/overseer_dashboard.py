import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFrame,
    QComboBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

C = {
    "bg_dark": "#050811",
    "bg_panel": "#0a0f1d",
    "text_dim": "#708caa",
    "neon_cyan": "#00f0ff",
    "neon_pink": "#ff3366",
    "neon_amber": "#eab308",
}

class EnhancedOverseerDashboard(QMainWindow):
    """
    Upgraded Overseer Dashboard for Workplace 1.
    Designed for the ASTER multiseat setup where the AI is isolated on Workplace 2.
    No need for stealth or frameless windows here.
    """
    def __init__(self, remote_client=None):
        super().__init__()
        self.setWindowTitle("AlphaCore // Enhanced Overseer Dashboard")
        self.resize(900, 700)
        self.setStyleSheet(f"background-color: {C['bg_dark']}; color: white;")
        self.remote_client = remote_client

        self._init_ui()

        if self.remote_client:
            self.remote_client.on_telemetry = self.on_remote_telemetry
            self.remote_client.on_connection_change = self.on_remote_connection_change

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(15)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("ALPHACORE // ENHANCED OVERSEER COMMAND")
        title.setStyleSheet(f"font-family: 'Segoe UI'; font-weight: 900; font-size: 18pt; color: {C['neon_cyan']}; letter-spacing: 2px;")
        hdr.addWidget(title)
        
        self.lbl_net_status = QLabel("STATUS: OFFLINE")
        self.lbl_net_status.setStyleSheet(f"font-family: Consolas; font-size: 12pt; font-weight: bold; color: {C['neon_pink']};")
        hdr.addStretch()
        hdr.addWidget(self.lbl_net_status)
        root_layout.addLayout(hdr)

        # Telemetry Display
        telem_frame = QFrame()
        telem_frame.setStyleSheet(f"background-color: {C['bg_panel']}; border: 1px solid {C['neon_cyan']}; border-radius: 8px;")
        telem_layout = QVBoxLayout(telem_frame)
        
        lbl_telem = QLabel("LIVE TELEMETRY (WORKPLACE 2)")
        lbl_telem.setStyleSheet(f"color: {C['text_dim']}; font-weight: bold;")
        telem_layout.addWidget(lbl_telem)

        self.txt_monologue = QTextEdit()
        self.txt_monologue.setReadOnly(True)
        self.txt_monologue.setStyleSheet(f"background: transparent; border: none; font-family: Consolas; font-size: 11pt; color: {C['neon_cyan']};")
        telem_layout.addWidget(self.txt_monologue)
        
        self.lbl_task = QLabel("Active Task: None")
        self.lbl_task.setStyleSheet(f"color: {C['neon_amber']}; font-weight: bold;")
        telem_layout.addWidget(self.lbl_task)
        
        root_layout.addWidget(telem_frame, 1)

        # Controls
        ctrl_layout = QHBoxLayout()
        
        # Subconscious Injection
        inj_frame = QFrame()
        inj_frame.setStyleSheet(f"background-color: {C['bg_panel']}; border: 1px solid #1e293b; border-radius: 8px;")
        inj_layout = QVBoxLayout(inj_frame)
        lbl_inj = QLabel("SUBCONSCIOUS INJECTION")
        lbl_inj.setStyleSheet(f"color: {C['text_dim']}; font-weight: bold;")
        inj_layout.addWidget(lbl_inj)
        
        self.edit_thought = QTextEdit()
        self.edit_thought.setPlaceholderText("Direct AI thoughts invisibly...")
        self.edit_thought.setFixedHeight(80)
        self.edit_thought.setStyleSheet("background: #040810; color: white; border: 1px solid #1e293b; font-size: 11pt;")
        inj_layout.addWidget(self.edit_thought)
        
        btn_inject = QPushButton("INJECT THOUGHT")
        btn_inject.setFixedHeight(40)
        btn_inject.setStyleSheet(f"background: #0284c7; color: white; font-weight: bold; border-radius: 4px; font-size: 11pt;")
        btn_inject.clicked.connect(self._inject_thought)
        inj_layout.addWidget(btn_inject)
        
        ctrl_layout.addWidget(inj_frame, 2)

        # Actions & State
        act_frame = QFrame()
        act_frame.setStyleSheet(f"background-color: {C['bg_panel']}; border: 1px solid #1e293b; border-radius: 8px;")
        act_layout = QVBoxLayout(act_frame)
        lbl_act = QLabel("STATE & ACTIONS")
        lbl_act.setStyleSheet(f"color: {C['text_dim']}; font-weight: bold;")
        act_layout.addWidget(lbl_act)
        
        self.combo_mood = QComboBox()
        self.combo_mood.addItems(["Tactical & Focused", "Creative & Expressive", "Aggressive & Unfiltered (AlphaCore)", "Darkened Mode"])
        self.combo_mood.setFixedHeight(35)
        self.combo_mood.currentTextChanged.connect(self._change_mood)
        act_layout.addWidget(self.combo_mood)
        
        self.btn_pause = QPushButton("PAUSE AI")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setFixedHeight(40)
        self.btn_pause.setStyleSheet(f"background: #b45309; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_pause.toggled.connect(self._toggle_pause)
        act_layout.addWidget(self.btn_pause)
        
        self.btn_halt = QPushButton("EMERGENCY HALT")
        self.btn_halt.setFixedHeight(40)
        self.btn_halt.setStyleSheet(f"background: {C['neon_pink']}; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_halt.clicked.connect(self._halt)
        act_layout.addWidget(self.btn_halt)
        
        ctrl_layout.addWidget(act_frame, 1)
        root_layout.addLayout(ctrl_layout)

    def on_remote_telemetry(self, telem: dict):
        # Must be careful if called from background thread, but PyQt handles some cross-thread signals automatically if we are just setting text.
        # For safety in PyQt, we should technically use signals. But we'll try direct update first as it often works for simple QLabel/QTextEdit in simple apps.
        import PyQt6.QtCore as QtCore
        QtCore.QMetaObject.invokeMethod(self.txt_monologue, "setPlainText", QtCore.Qt.ConnectionType.QueuedConnection, QtCore.Q_ARG(str, telem.get("monologue", "")))
        
        task = telem.get("active_task", "None")
        QtCore.QMetaObject.invokeMethod(self.lbl_task, "setText", QtCore.Qt.ConnectionType.QueuedConnection, QtCore.Q_ARG(str, f"Active Task: {task}"))

    def on_remote_connection_change(self, connected: bool, message: str):
        import PyQt6.QtCore as QtCore
        color = C['neon_cyan'] if connected else C['neon_pink']
        style = f"font-family: Consolas; font-size: 12pt; font-weight: bold; color: {color};"
        QtCore.QMetaObject.invokeMethod(self.lbl_net_status, "setStyleSheet", QtCore.Qt.ConnectionType.QueuedConnection, QtCore.Q_ARG(str, style))
        QtCore.QMetaObject.invokeMethod(self.lbl_net_status, "setText", QtCore.Qt.ConnectionType.QueuedConnection, QtCore.Q_ARG(str, f"STATUS: {message.upper()}"))

    def on_voice_received(self, text: str):
        if text.strip() and self.remote_client:
            self.remote_client.send_thought(f"[Voice Subconscious Input]: {text.strip()}")

    def _inject_thought(self):
        text = self.edit_thought.toPlainText().strip()
        if text and self.remote_client:
            self.remote_client.send_thought(text)
            self.edit_thought.clear()

    def _change_mood(self, mood: str):
        if self.remote_client:
            self.remote_client.send_mood(mood)

    def _toggle_pause(self, paused: bool):
        self.btn_pause.setText("RESUME AI" if paused else "PAUSE AI")
        if self.remote_client:
            self.remote_client.send_pause(paused)

    def _halt(self):
        if self.remote_client:
            self.remote_client.send_halt()

