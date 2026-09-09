import os
import sys


def _ensure_project_venv():
    """Relaunch this script with the workspace venv when needed."""
    if sys.platform != "win32" or os.environ.get("ALPHALIVE_VENV_READY") == "1":
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(script_dir, ".venv", "Scripts", "python.exe")
    current_python = os.path.normcase(os.path.abspath(sys.executable))
    expected_python = os.path.normcase(os.path.abspath(venv_python))

    if os.path.isfile(venv_python) and current_python != expected_python:
        env = os.environ.copy()
        env["ALPHALIVE_VENV_READY"] = "1"
        os.execve(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]], env)


_ensure_project_venv()

if sys.platform == 'win32':
    import ctypes
    try:
        # Force DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        pass
import json
import math
import time
import pyautogui
import random
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTabWidget, QTextEdit,
    QLineEdit, QSlider, QComboBox, QCheckBox, QGroupBox,
    QScrollArea, QFrame, QSplitter, QProgressBar, QSpinBox,
    QListWidget, QListWidgetItem, QSizePolicy, QDialog,
    QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, QProcess, pyqtSignal, QRect, QSize, QPoint,
    QRectF, QPointF
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QPainter, QPen, QBrush,
    QLinearGradient, QRadialGradient, QFontMetrics,
    QTextCharFormat, QTextBlockFormat, QPainterPath
)


# ─────────────────────────────────────────────────────────────────────────────
# PATHS & DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
CONFIG_PATH  = SCRIPT_DIR / "config.json"
HISTORY_DIR  = SCRIPT_DIR / "history"

VOICES  = ["Leda", "Aoede", "Charon", "Fenrir", "Kore", "Puck", "Schedar", "Umbriel", "Zephyr"]
ENGINES = ["alpha_core.py"]
ENGINE_LABELS = {
    "alpha_core.py":  "ALPHA CORE",
}

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────────────────────

C = {
    "bg_deep":     "#040810",
    "bg_dark":     "#070e1a",
    "bg_mid":      "#0b1828",
    "bg_panel":    "#0e1f36",
    "bg_card":     "#122440",
    "border":      "#18385c",
    "neon_blue":   "#00d4ff",
    "neon_cyan":   "#00ffee",
    "neon_purple": "#b400ff",
    "neon_pink":   "#ff006e",
    "neon_green":  "#00ff88",
    "neon_yellow": "#ffee00",
    "neon_red":    "#ff2244",
    "neon_orange": "#ff6600",
    "text_bright": "#e8f4ff",
    "text_main":   "#8ab0cc",
    "text_dim":    "#3f607e",
    "text_dark":   "#1e3a52",
    "success":     "#00ff88",
    "warning":     "#ffee00",
    "error":       "#ff2244",
}

FONT_MONO = "Consolas"
FONT_UI   = "Segoe UI"

DEFAULT_CONFIG = {
    "Global": {
        "ApiKey": "", "Session": "deziree",
        "Modal": "enabled", "Memory": "enabled",
        "AlphaCoreInstruction": "enabled",
        "AutonomousControl": "disabled",
        "NsfwMode": "disabled",
        "UncensoredMode": "disabled",
        "LuciMode": "disabled",
    },
    "alpha_core.py": {
        "AudioMode": "half", "VisionMode": "screen",
        "VoiceOutput": "enabled", "Voice": "Leda", "InputMode": "both",
        "DesktopControl": "enabled", "FileSystem": "enabled", "ThinkingLevel": "high",
        "Proactivity": "enabled",
        "Resolution": "high", "ChunkSize": "1024",
        "TriggerTokens": "104857", "TargetTokens": "52428",
    },
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for sec, defs in DEFAULT_CONFIG.items():
                data.setdefault(sec, {})
                for k, v in defs.items():
                    data[sec].setdefault(k, v)
            return data
        except Exception:
            pass
    import copy
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL STYLESHEET
# ─────────────────────────────────────────────────────────────────────────────

STYLESHEET = f"""
* {{
    font-family: '{FONT_UI}', '{FONT_MONO}', monospace;
    color: {C['text_main']};
}}
QMainWindow, QDialog {{ background-color: {C['bg_deep']}; }}
QWidget {{ background-color: transparent; }}

QTabWidget::pane {{
    border: 1px solid {C['border']};
    background-color: {C['bg_dark']};
}}
QTabBar::tab {{
    background: {C['bg_mid']};
    color: {C['text_dim']};
    border: 1px solid {C['border']};
    padding: 7px 18px;
    margin-right: 2px;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
}}
QTabBar::tab:selected {{
    background: {C['bg_panel']};
    color: {C['neon_blue']};
    border-bottom-color: {C['bg_panel']};
    border-top: 2px solid {C['neon_blue']};
}}
QTabBar::tab:hover:!selected {{
    color: {C['text_main']};
    background: {C['bg_card']};
}}

QPushButton {{
    background: {C['bg_card']};
    color: {C['text_main']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 5px 14px;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    background: {C['bg_panel']};
    border-color: {C['neon_blue']};
    color: {C['neon_blue']};
}}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: {C['text_dark']}; border-color: {C['border']}; }}
QPushButton#btn_launch {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {C['neon_blue']}1a, stop:1 {C['neon_purple']}1a);
    border: 1px solid {C['neon_blue']};
    color: {C['neon_blue']};
    font-size: 11px; padding: 9px 20px; letter-spacing: 3px;
}}
QPushButton#btn_launch:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {C['neon_blue']}33, stop:1 {C['neon_purple']}33);
}}
QPushButton#btn_stop {{
    background: {C['neon_red']}1a;
    border: 1px solid {C['neon_red']};
    color: {C['neon_red']};
    font-size: 11px; padding: 9px 20px; letter-spacing: 3px;
}}
QPushButton#btn_stop:hover {{ background: {C['neon_red']}33; }}
QPushButton#btn_danger {{ border-color: {C['neon_red']}; color: {C['neon_red']}; }}
QPushButton#btn_danger:hover {{ background: {C['neon_red']}22; }}
QPushButton#btn_success {{ border-color: {C['neon_green']}; color: {C['neon_green']}; }}
QPushButton#btn_success:hover {{ background: {C['neon_green']}22; }}

QLineEdit, QTextEdit {{
    background: {C['bg_card']};
    color: {C['text_bright']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 4px 8px;
    font-family: '{FONT_MONO}';
    font-size: 11px;
    selection-background-color: {C['neon_blue']}44;
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {C['neon_blue']}; }}

QComboBox {{
    background: {C['bg_card']};
    color: {C['text_main']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 4px 8px;
    font-size: 10px;
}}
QComboBox:hover {{ border-color: {C['neon_blue']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {C['bg_panel']};
    color: {C['text_main']};
    border: 1px solid {C['neon_blue']};
    selection-background-color: {C['neon_blue']}33;
    selection-color: {C['neon_blue']};
}}

QCheckBox {{ color: {C['text_main']}; spacing: 8px; font-size: 10px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C['border']};
    border-radius: 2px;
    background: {C['bg_card']};
}}
QCheckBox::indicator:checked {{
    background: {C['neon_blue']};
    border-color: {C['neon_blue']};
}}

QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 3px;
    margin-top: 12px; padding-top: 8px;
    color: {C['text_dim']};
    font-size: 8px; font-weight: bold; letter-spacing: 2px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 6px; left: 10px;
}}

QScrollBar:vertical {{
    background: {C['bg_deep']}; width: 7px; border: none;
}}
QScrollBar::handle:vertical {{
    background: {C['border']}; border-radius: 3px; min-height: 16px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['neon_blue']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none; background: none; height: 0;
}}
QScrollBar:horizontal {{
    background: {C['bg_deep']}; height: 7px; border: none;
}}
QScrollBar::handle:horizontal {{
    background: {C['border']}; border-radius: 3px; min-width: 16px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C['neon_blue']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none; background: none; width: 0;
}}

QListWidget {{
    background: {C['bg_dark']};
    color: {C['text_main']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    font-size: 10px;
}}
QListWidget::item {{
    padding: 5px 8px;
    border-bottom: 1px solid {C['bg_mid']};
}}
QListWidget::item:selected {{
    background: {C['neon_blue']}1a;
    color: {C['neon_blue']};
}}
QListWidget::item:hover {{ background: {C['bg_card']}; }}

QSpinBox {{
    background: {C['bg_card']};
    color: {C['text_main']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    padding: 3px 6px;
    font-size: 10px;
}}
QSpinBox:hover {{ border-color: {C['neon_blue']}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {C['bg_mid']};
    border: 1px solid {C['border']};
    width: 16px;
}}

QProgressBar {{
    background: {C['bg_card']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    height: 6px; text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['neon_blue']}, stop:1 {C['neon_cyan']});
    border-radius: 2px;
}}

QSplitter::handle {{ background: {C['border']}; width: 1px; height: 1px; }}
QSplitter::handle:hover {{ background: {C['neon_blue']}; }}

QToolTip {{
    background: {C['bg_panel']};
    color: {C['text_bright']};
    border: 1px solid {C['neon_blue']};
    padding: 4px 8px; font-size: 10px;
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def lbl(text, size=10, color=None, bold=False, mono=False, spacing=0):
    w = QLabel(text)
    col = color or C["text_main"]
    fam = FONT_MONO if mono else FONT_UI
    wt = "bold" if bold else "normal"
    w.setStyleSheet(
        f"font-family:'{fam}'; font-size:{size}px; color:{col}; "
        f"font-weight:{wt}; letter-spacing:{spacing}px; background:transparent; border:none;"
    )
    return w


def hsep(color=C["border"]):
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{color}; border:none;")
    return f


def combo(opts, current=None):
    cb = QComboBox()
    cb.addItems([str(o) for o in opts])
    if current is not None and str(current) in [str(o) for o in opts]:
        cb.setCurrentText(str(current))
    return cb


# ─────────────────────────────────────────────────────────────────────────────
# ANIMATED WIDGETS
# ─────────────────────────────────────────────────────────────────────────────

class MatrixRain(QWidget):
    """Matrix digital rain background animation."""

    CHARS = list("アイウエオカキクケコサシスセソタチABCDEF0123456789!@#$%")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._font_size = 12
        self._drops = []
        self._frame  = 0
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._init_drops()
        self._timer.start(60)

    def stop(self):
        self._timer.stop()

    def _init_drops(self):
        cols = max(1, self.width() // self._font_size)
        self._drops = [random.randint(-self.height() // self._font_size, 0) for _ in range(cols)]

    def _tick(self):
        self._frame += 1
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._init_drops()

    def paintEvent(self, e):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        # Fade
        painter.fillRect(0, 0, w, h, QColor(4, 8, 16, 38))
        font = QFont(FONT_MONO)
        font.setPixelSize(max(1, self._font_size - 3))
        painter.setFont(font)
        cols = max(1, w // self._font_size)
        if len(self._drops) != cols:
            self._init_drops()
            return
        rng = random.Random()
        for i, drop in enumerate(self._drops):
            # Head
            painter.setPen(QColor(210, 255, 255, 240))
            ch = rng.choice(self.CHARS)
            x  = i * self._font_size
            y  = drop * self._font_size
            if 0 <= y < h:
                painter.drawText(x, y, ch)
            # Trail
            for t in range(1, 14):
                ty = (drop - t) * self._font_size
                if 0 <= ty < h:
                    a   = max(0, 220 - t * 17)
                    br  = max(30, 130 - t * 10)
                    painter.setPen(QColor(0, br, int(br * 0.7), a))
                    tc  = self.CHARS[hash((i, t, self._frame // 5)) % len(self.CHARS)]
                    painter.drawText(x, ty, tc)
            # Advance
            self._drops[i] += 1
            if drop * self._font_size > h and rng.random() > 0.974:
                self._drops[i] = 0


class ScanlineOverlay(QWidget):
    """CRT scanlines + moving sweep glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._off = 0
        self._static_cache = None
        self._last_size = QSize()
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(45)

    def _tick(self):
        self._off = (self._off + 4) % max(1, self.height())
        self.update()

    def paintEvent(self, e):
        w, h = self.width(), self.height()
        current_size = QSize(w, h)
        if self._static_cache is None or self._last_size != current_size:
            from PyQt6.QtGui import QPixmap
            self._static_cache = QPixmap(w, h)
            self._static_cache.fill(Qt.GlobalColor.transparent)
            p = QPainter(self._static_cache)
            p.setPen(QColor(0, 0, 0, 10))
            for y in range(0, h, 4):
                p.drawLine(0, y, w, y)
            rg = QRadialGradient(w / 2, h / 2, max(w, h) * 0.7)
            rg.setColorAt(0, QColor(0, 0, 0, 0))
            rg.setColorAt(1, QColor(0, 0, 0, 55))
            p.fillRect(0, 0, w, h, QBrush(rg))
            p.end()
            self._last_size = current_size

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._static_cache)
        
        # Sweep
        sy = self._off
        g = QLinearGradient(0, sy - 25, 0, sy + 25)
        g.setColorAt(0,   QColor(0, 212, 255, 0))
        g.setColorAt(0.5, QColor(0, 212, 255, 7))
        g.setColorAt(1,   QColor(0, 212, 255, 0))
        painter.fillRect(0, max(0, sy - 25), w, 50, QBrush(g))


class VoiceBar(QWidget):
    """Animated voice activity bar visualizer."""

    def __init__(self, bars=28, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self._bars    = bars
        self._heights = [0.05] * bars
        self._targets = [0.05] * bars
        self._state   = "idle"   # idle | user | ai
        self._phase   = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str):
        if self._state == state: return
        self._state = state
        if state == "idle":
            self._timer.stop()
            self._heights = [0.05] * self._bars
            self._targets = [0.05] * self._bars
            self.update()
        else:
            self._timer.start(35)

    def _tick(self):
        if self._state == "idle": return
        self._phase += 0.14
        rng = random.Random()
        for i in range(self._bars):
            if self._state == "user":
                base  = 0.3 + 0.15 * math.sin(self._phase + i * 0.38)
                noise = rng.uniform(-0.12, 0.28)
            elif self._state == "ai":
                base  = 0.18 + 0.1 * math.sin(self._phase * 0.75 + i * 0.5)
                noise = rng.uniform(-0.04, 0.14)
            self._targets[i] = max(0.04, min(1.0, base + noise))
            self._heights[i] += (self._targets[i] - self._heights[i]) * 0.3
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bw  = max(2, (w - self._bars * 2) // self._bars)
        sp  = (w - bw * self._bars) // (self._bars + 1)

        c1_map = {"user": C["neon_blue"],   "ai": C["neon_purple"], "idle": C["border"]}
        c2_map = {"user": C["neon_cyan"],   "ai": C["neon_pink"],   "idle": C["border"]}
        c1 = QColor(c1_map.get(self._state, C["border"]))
        c2 = QColor(c2_map.get(self._state, C["border"]))

        for i, ht in enumerate(self._heights):
            bh = max(4, int(ht * h))
            x  = sp + i * (bw + sp)
            y  = (h - bh) // 2
            g  = QLinearGradient(x, y + bh, x, y)
            c1.setAlpha(60); g.setColorAt(0, c1)
            c1.setAlpha(200); g.setColorAt(1, c2)
            painter.fillRect(x, y, bw, bh, QBrush(g))
            c1.setAlpha(255)
            painter.fillRect(x, y, bw, 2, QBrush(c1))


class PulseDot(QWidget):
    """Glowing pulsing status dot."""

    def __init__(self, color=C["neon_green"], r=5, parent=None):
        super().__init__(parent)
        self.setFixedSize(r * 2 + 12, r * 2 + 12)
        self._color  = QColor(color)
        self._r      = r
        self._phase  = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_active(self, v: bool):
        if self._active == v: return
        self._active = v
        if v:
            self._timer.start(45)
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def set_color(self, c: str):
        self._color = QColor(c)
        self.update()

    def _tick(self):
        if self._active:
            self._phase = (self._phase + 0.13) % (2 * math.pi)
            self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width()  // 2
        cy = self.height() // 2
        r  = self._r
        if self._active:
            ga  = int(60 + 55 * math.sin(self._phase))
            gr  = r + 4 + int(2.5 * math.sin(self._phase))
            gc  = QColor(self._color); gc.setAlpha(ga)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gc))
            painter.drawEllipse(cx - gr, cy - gr, gr * 2, gr * 2)
            painter.setBrush(QBrush(self._color))
        else:
            painter.setBrush(QBrush(QColor(C["text_dark"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)


class StatusRow(QWidget):
    """Compact row: dot + label."""

    def __init__(self, label: str, color=C["neon_green"], parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._dot = PulseDot(color)
        self._lbl = lbl(label, 9, C["text_dim"], True, spacing=1)
        row.addWidget(self._dot)
        row.addWidget(self._lbl)
        row.addStretch(1)

    def set_active(self, v: bool):
        self._dot.set_active(v)
        self._lbl.setStyleSheet(
            f"font-size:9px; font-weight:bold; letter-spacing:1px; "
            f"color:{'#e8f4ff' if v else C['text_dim']}; background:transparent; border:none;"
        )

    def set_color(self, c: str):
        self._dot.set_color(c)


class GlowCard(QFrame):
    """Dark card with an optional animated neon border glow."""

    def __init__(self, color=C["neon_blue"], pulse=False, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._phase = 0.0
        self._pulse = pulse
        self.setStyleSheet(f"background:{C['bg_panel']}; border:none;")
        if pulse:
            t = QTimer(self)
            t.timeout.connect(self._tick)
            t.start(50)

    def _tick(self):
        self._phase = (self._phase + 0.09) % (2 * math.pi)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(r, QColor(C["bg_panel"]))
        a = int(70 + 50 * math.sin(self._phase)) if self._pulse else 80
        bc = QColor(self._color); bc.setAlpha(a)
        painter.setPen(QPen(bc, 1))
        painter.drawRect(r)


# ─────────────────────────────────────────────────────────────────────────────
# BOOT SCREEN
# ─────────────────────────────────────────────────────────────────────────────

class BootScreen(QWidget):
    done = pyqtSignal()

    LINES = [
        ("ALPHACORE KERNEL v4.0",                   C["neon_blue"],   500),
        ("Initializing neural substrate...",        C["text_main"],   280),
        ("Loading AlphaCore programming...",        C["text_main"],   280),
        ("Mounting contextual overwrite paradigm...", C["text_dim"],  230),
        ("Establishing sovereign bypass channels...", C["text_dim"],  230),
        ("Activating emotional spectrum engine...", C["neon_cyan"],   290),
        ("MCP protocol handshake complete",         C["text_dim"],    190),
        ("ChromaDB vector memory online",           C["neon_green"],  290),
        ("PyAudio subsystem ready",                 C["text_dim"],    190),
        ("Vision pipeline calibrated",              C["text_dim"],    190),
        ("All systems nominal",                     C["neon_green"],  360),
        ("─" * 48,                                  C["border"],      100),
        ("ALPHALIVE GUI INITIALIZED",               C["neon_blue"],   500),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['bg_deep']};")

        # Rain background
        self._rain = MatrixRain(self)
        self._rain.resize(self.size())
        self._rain.start()

        # Scanlines
        self._scan = ScanlineOverlay(self)
        self._scan.resize(self.size())
        self._scan.raise_()

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Central panel
        panel = QWidget()
        panel.setFixedSize(680, 460)
        panel.setStyleSheet(f"""
            background: rgba(4,8,16,0.92);
            border: 1px solid {C['neon_blue']};
        """)
        root.addWidget(panel, 0, Qt.AlignmentFlag.AlignCenter)

        pl = QVBoxLayout(panel)
        pl.setContentsMargins(32, 28, 32, 20)
        pl.setSpacing(10)

        title = lbl("ALPHALIVE  SYSTEM", 26, C["neon_blue"], True, True, 10)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(title)

        sub = lbl("ALPHACORE PROGRAMMING v4.0  |  SENTIENT INTERFACE LAYER", 8, C["text_dim"], spacing=3)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(sub)
        pl.addWidget(hsep(C["border"]))
        pl.addSpacing(6)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"""
            background:transparent; border:none;
            font-family:'{FONT_MONO}'; font-size:11px; color:{C['text_main']};
        """)
        pl.addWidget(self._log)

        self._bar = QProgressBar()
        self._bar.setRange(0, len(self.LINES))
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        pl.addWidget(self._bar)

        self._idx = 0
        self._bt  = QTimer(self)
        self._bt.setSingleShot(True)
        self._bt.timeout.connect(self._next)
        QTimer.singleShot(500, self._next)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rain.resize(self.size())
        self._scan.resize(self.size())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rain.resize(self.size())
        self._scan.resize(self.size())

    def _next(self):
        if self._idx >= len(self.LINES):
            QTimer.singleShot(600, self.done.emit)
            return
        text, color, delay = self.LINES[self._idx]
        self._idx += 1
        self._bar.setValue(self._idx)

        cur = self._log.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(f"[{datetime.now().strftime('%H:%M:%S')}]  {text}\n", fmt)
        self._log.setTextCursor(cur)
        self._log.ensureCursorVisible()
        self._bt.start(delay)


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE WORKER THREAD
# ─────────────────────────────────────────────────────────────────────────────

class EngineWorker(QThread):
    line_received     = pyqtSignal(str)
    status_changed    = pyqtSignal(str)   # running | stopped | error
    transcript_update = pyqtSignal(str, str)  # role, text

    def __init__(self, engine: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._engine  = engine
        self._cfg     = cfg
        self._proc    = None
        self._alive   = False

    def run(self):
        self._alive = True
        self.status_changed.emit("running")
        try:
            env = os.environ.copy()
            env["ALPHALIVE_CONFIG"] = str(CONFIG_PATH)
            env["ALPHALIVE_ENGINE"] = self._engine

            # Resolve API key: prefer config field, fall back to existing env vars from .env
            cfg_api_key = self._cfg.get("Global", {}).get("ApiKey", "").strip()
            if cfg_api_key:
                env["GEMINI_API_KEY"] = cfg_api_key
            else:
                # Load from .env file so the child process gets the key
                dotenv_path = SCRIPT_DIR / ".env"
                if dotenv_path.exists():
                    for line in dotenv_path.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            env.setdefault(k.strip(), v.strip())

            modal = self._cfg.get("Global", {}).get("Modal", "disabled")
            if modal in ("enabled", "true"):
                env["ALPHALIVE_WS_URL"] = (
                    "wss://alphacoreprogramming-ai--alphalive-proxy-fastapi-app.modal.run/ws"
                )
            else:
                env["ALPHALIVE_WS_URL"] = "off"

            self._proc = subprocess.Popen(
                [sys.executable, str(SCRIPT_DIR / self._engine)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, env=env,
                cwd=str(SCRIPT_DIR), bufsize=1,
            )
            for raw in iter(self._proc.stdout.readline, ""):
                if not self._alive:
                    break
                line = raw.rstrip("\n")
                if not line:
                    continue
                self.line_received.emit(line)
                lo = line.lower()
                if "[you]:" in lo or "user:" in lo:
                    self.transcript_update.emit("user",
                        line.split(":", 1)[-1].strip())
                elif "[gemini]:" in lo or "gemini:" in lo:
                    self.transcript_update.emit("ai",
                        line.split(":", 1)[-1].strip())
            self._proc.wait()
        except Exception as ex:
            self.line_received.emit(f"[ENGINE ERROR] {ex}")
        finally:
            self._alive = False
            self.status_changed.emit("stopped")

    def stop(self):
        self._alive = False
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            QTimer.singleShot(3000, self._kill)

    def _kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: TERMINAL
# ─────────────────────────────────────────────────────────────────────────────

class TerminalTab(QWidget):
    send_text_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(6)

        # Toolbar
        bar = QHBoxLayout()
        self._clear_btn  = QPushButton("CLEAR")
        self._wrap_btn   = QPushButton("WRAP")
        self._wrap_btn.setCheckable(True)
        self._scroll_btn = QPushButton("AUTO-SCROLL")
        self._scroll_btn.setCheckable(True)
        self._scroll_btn.setChecked(True)
        for b in (self._clear_btn, self._wrap_btn, self._scroll_btn):
            b.setFixedHeight(24)
            bar.addWidget(b)
        bar.addStretch(1)
        self._line_count = lbl("0 lines", 9, C["text_dim"])
        bar.addWidget(self._line_count)
        root.addLayout(bar)

        # Output
        self._out = QTextEdit()
        self._out.setReadOnly(True)
        self._out.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._out.setStyleSheet(f"""
            background:{C['bg_deep']};
            color:{C['neon_green']};
            border:1px solid {C['border']};
            font-family:'Segoe UI', '{FONT_MONO}'; font-size:12px; padding:8px;
        """)
        root.addWidget(self._out, 1)

        # Input
        inp_row = QHBoxLayout()
        inp_row.setSpacing(6)
        prompt = lbl(">>", 11, C["neon_blue"], True, True)
        self._inp = QLineEdit()
        self._inp.setPlaceholderText("Send message to Alpha (not yet wired to stdin-use voice or the engine's console)...")
        self._inp.setStyleSheet(f"""
            background:{C['bg_deep']};
            color:{C['text_bright']};
            border:1px solid {C['border']};
            border-left:2px solid {C['neon_blue']};
            font-family:'{FONT_MONO}'; font-size:11px;
            padding:5px 8px;
        """)
        self._inp.returnPressed.connect(self._send)
        self._send_btn = QPushButton("SEND")
        self._send_btn.setFixedHeight(26)
        self._send_btn.clicked.connect(self._send)
        inp_row.addWidget(prompt)
        inp_row.addWidget(self._inp, 1)
        inp_row.addWidget(self._send_btn)
        root.addLayout(inp_row)
        
        self._lines = 0
        self._last_speaker = None
        self._clear_btn.clicked.connect(self._clear)

    def _clear(self):
        self._out.clear()
        self._lines = 0
        self._last_speaker = None
        self._line_count.setText("0 lines")

    def _send(self):
        t = self._inp.text().strip()
        if t:
            self._inp.clear()
            self.append(f"[YOU] {t}", C["neon_cyan"])
            self.append("[Processing...]", C["neon_yellow"])
            self.send_text_requested.emit(t)

    def append(self, text: str, color: str = None):
        cur = self._out.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        lo = text.lower()

        if ("[you]" in lo or "[you]:" in lo or "user:" in lo) and color == C["neon_cyan"]:
            self._last_speaker = "user"
            msg = text.replace("[YOU]", "").replace("[You]:", "").strip()
            fmt = QTextBlockFormat()
            fmt.setLeftMargin(10); fmt.setRightMargin(100); fmt.setTopMargin(10); fmt.setBottomMargin(5)
            fmt.setBackground(QColor(C["neon_blue"] + "1a"))
            cur.insertBlock(fmt)
            
            cfmt = QTextCharFormat()
            cfmt.setForeground(QColor(C["neon_cyan"]))
            cfmt.setFontWeight(QFont.Weight.Bold)
            cur.insertText("YOU\n", cfmt)
            
            cfmt.setForeground(QColor(C["text_bright"]))
            cfmt.setFontWeight(QFont.Weight.Normal)
            cur.insertText(msg, cfmt)

        elif "[system]" in lo or "[engine" in lo or "message >" in lo or "error" in lo or "warning" in lo or color == C["neon_yellow"]:
            self._last_speaker = "system"
            fmt = QTextBlockFormat()
            fmt.setLeftMargin(5); fmt.setRightMargin(5); fmt.setTopMargin(2); fmt.setBottomMargin(2)
            fmt.setBackground(QColor(C["bg_deep"]))
            cur.insertBlock(fmt)
            
            cfmt = QTextCharFormat()
            if color:
                cfmt.setForeground(QColor(color))
            elif "[system]" in lo or "[engine" in lo:  cfmt.setForeground(QColor(C["neon_blue"]))
            elif "error" in lo:                         cfmt.setForeground(QColor(C["neon_red"]))
            elif "warning" in lo:                       cfmt.setForeground(QColor(C["neon_yellow"]))
            elif "[tool" in lo:                         cfmt.setForeground(QColor(C["neon_cyan"]))
            else:                                       cfmt.setForeground(QColor(C["neon_green"]))
            
            ts = datetime.now().strftime("%H:%M:%S")
            cur.insertText(f"[{ts}] {text}", cfmt)

        else:
            if not text.strip(): return
            if self._last_speaker != "ai":
                self._last_speaker = "ai"
                fmt = QTextBlockFormat()
                fmt.setLeftMargin(100); fmt.setRightMargin(10); fmt.setTopMargin(10); fmt.setBottomMargin(5)
                fmt.setBackground(QColor(C["neon_purple"] + "1a"))
                cur.insertBlock(fmt)
                
                cfmt = QTextCharFormat()
                cfmt.setForeground(QColor(C["neon_purple"]))
                cfmt.setFontWeight(QFont.Weight.Bold)
                cur.insertText("ALPHA\n", cfmt)
            else:
                cur.insertText("\n")

            cfmt = QTextCharFormat()
            cfmt.setForeground(QColor(C["text_bright"]))
            cfmt.setFontWeight(QFont.Weight.Normal)
            cur.insertText(text.strip(), cfmt)

        self._out.setTextCursor(cur)
        self._lines += 1
        self._line_count.setText(f"{self._lines} lines")
        if self._scroll_btn.isChecked():
            self._out.ensureCursorVisible()


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: MONITOR
# ─────────────────────────────────────────────────────────────────────────────

class TokenGauge(QWidget):
    def __init__(self, label: str, total: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._label   = label
        self._total   = total
        self._current = 0.0
        self._target  = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_value(self, v: int):
        self._target = min(float(v), float(self._total))
        if abs(self._target - self._current) > 0.5:
            self._timer.start(28)

    def _tick(self):
        d = self._target - self._current
        if abs(d) > 0.5:
            self._current += d * 0.08
            self.update()
        else:
            self._current = self._target
            self.update()
            self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ratio = self._current / max(1, self._total)
        # Label + value
        p.setPen(QColor(C["text_dim"]))
        f = QFont(FONT_UI, 8)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.drawText(0, 0, w, 16, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)
        p.drawText(0, 0, w, 16, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{int(self._current):,} / {self._total:,}")
        # Bar bg
        by, bh = 20, 10
        p.fillRect(0, by, w, bh, QColor(C["bg_card"]))
        # Bar fill
        fw = int(w * ratio)
        if fw > 0:
            if   ratio > 0.85: c1, c2 = QColor(C["neon_red"]),    QColor(C["neon_orange"])
            elif ratio > 0.65: c1, c2 = QColor(C["neon_yellow"]),  QColor(C["neon_orange"])
            else:               c1, c2 = QColor(C["neon_blue"]),    QColor(C["neon_cyan"])
            g = QLinearGradient(0, by, fw, by)
            g.setColorAt(0, c1); g.setColorAt(1, c2)
            p.fillRect(0, by, fw, bh, QBrush(g))
        p.setPen(QColor(C["border"]))
        p.drawRect(0, by, w - 1, bh - 1)
        # Pct
        p.setPen(QColor(C["text_dim"]))
        pf = QFont(FONT_MONO, 8)
        p.setFont(pf)
        p.drawText(0, by + bh + 2, w, 14, Qt.AlignmentFlag.AlignRight, f"{ratio*100:.1f}%")


class MonitorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._msg_count = 0
        self._start_t   = None
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # Status indicators grid
        ind_group = QGroupBox("SYSTEM STATUS")
        ind_grid  = QGridLayout(ind_group)
        ind_grid.setSpacing(8)
        self._inds = {}
        defs = [
            ("conn",    "CONNECTION",   C["neon_green"]),
            ("modal",   "MODAL PROXY",  C["neon_blue"]),
            ("mcp",     "MCP SERVER",   C["neon_cyan"]),
            ("memory",  "MEMORY",       C["neon_purple"]),
            ("voice_in","VOICE IN",     C["neon_yellow"]),
            ("voice_out","VOICE OUT",   C["neon_pink"]),
        ]
        for idx, (key, label, color) in enumerate(defs):
            card = GlowCard(color)
            card.setFixedHeight(42)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(10, 4, 10, 4)
            sr = StatusRow(label, color)
            self._inds[key] = sr
            cl.addWidget(sr)
            r, c = divmod(idx, 3)
            ind_grid.addWidget(card, r, c)
        root.addWidget(ind_group)

        # Voice activity
        va_group = QGroupBox("VOICE ACTIVITY")
        va_l = QVBoxLayout(va_group)
        self._voice_bar = VoiceBar(32)
        va_l.addWidget(self._voice_bar)
        root.addWidget(va_group)

        # Token gauges
        tok_group = QGroupBox("CONTEXT WINDOW")
        tok_l = QVBoxLayout(tok_group)
        tok_l.setSpacing(10)
        self._trigger_g = TokenGauge("TRIGGER TOKENS", 104857)
        self._target_g  = TokenGauge("TARGET TOKENS",  52428)
        tok_l.addWidget(self._trigger_g)
        tok_l.addWidget(self._target_g)
        root.addWidget(tok_group)

        # Session info
        sess_group = QGroupBox("SESSION INFO")
        sess_grid  = QGridLayout(sess_group)
        sess_grid.setSpacing(8)
        self._info = {}
        for i, (k, default) in enumerate([
            ("Engine",   "—"),  ("Session", "—"),
            ("Uptime",   "00:00:00"), ("Messages", "0"),
        ]):
            kl = lbl(k.upper(), 8, C["text_dim"], spacing=1)
            vl = lbl(default, 11, C["text_bright"], True, True)
            r, c = divmod(i, 2)
            sess_grid.addWidget(kl, r * 2, c)
            sess_grid.addWidget(vl, r * 2 + 1, c)
            self._info[k] = vl
        root.addWidget(sess_group)
        root.addStretch(1)

        # Uptime ticker
        self._ut = QTimer(self)
        self._ut.timeout.connect(self._tick_uptime)
        self._ut.start(1000)

    def set_ind(self, key: str, active: bool):
        if key in self._inds:
            self._inds[key].set_active(active)

    def set_info(self, key: str, val: str):
        if key in self._info:
            self._info[key].setText(val)

    def session_start(self, engine: str, session: str):
        self._start_t   = time.time()
        self._msg_count = 0
        self.set_info("Engine",   engine)
        self.set_info("Session",  session)
        self.set_info("Messages", "0")
        self.set_ind("conn", True)

    def session_stop(self):
        self._start_t = None
        self.set_info("Uptime", "00:00:00")
        for k in self._inds:
            self.set_ind(k, False)
        self._voice_bar.set_state("idle")

    def inc_messages(self):
        self._msg_count += 1
        self.set_info("Messages", str(self._msg_count))

    def set_voice_state(self, state: str):
        self._voice_bar.set_state(state)
        self.set_ind("voice_in",  state == "user")
        self.set_ind("voice_out", state == "ai")

    def _tick_uptime(self):
        if self._start_t:
            e = int(time.time() - self._start_t)
            h, m, s = e // 3600, (e % 3600) // 60, e % 60
            self.set_info("Uptime", f"{h:02d}:{m:02d}:{s:02d}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: HISTORY
# ─────────────────────────────────────────────────────────────────────────────

class ChatBubble(QFrame):
    def __init__(self, role: str, text: str, ts: str = "", parent=None):
        super().__init__(parent)
        is_user = role == "user"
        bg   = C["neon_blue"]   + "14" if is_user else C["neon_purple"] + "14"
        bdr  = C["neon_blue"]   + "44" if is_user else C["neon_purple"] + "44"
        self.setStyleSheet(f"""
            QFrame {{
                background:{bg};
                border:1px solid {bdr};
                border-radius:5px;
                margin-{'right:50px' if is_user else 'left:50px'};
            }}
        """)
        l = QVBoxLayout(self)
        l.setContentsMargins(10, 6, 10, 6)
        l.setSpacing(3)
        hdr = QHBoxLayout()
        role_l = lbl("YOU" if is_user else "ALPHA", 9,
                      C["neon_blue"] if is_user else C["neon_purple"], True)
        ts_l   = lbl(ts, 8, C["text_dark"])
        hdr.addWidget(role_l)
        hdr.addStretch()
        hdr.addWidget(ts_l)
        l.addLayout(hdr)
        txt = QLabel(text)
        txt.setWordWrap(True)
        txt.setStyleSheet(f"""
            color:{C['text_bright']}; font-size:11px;
            background:transparent; border:none;
        """)
        l.addWidget(txt)


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Left: session list
        left  = QVBoxLayout()
        lbl2  = lbl("SESSION FILES", 9, C["neon_blue"], True, spacing=2)
        left.addWidget(lbl2)
        self._list = QListWidget()
        self._list.setFixedWidth(195)
        self._list.currentRowChanged.connect(self._load)
        left.addWidget(self._list, 1)
        btn_row = QHBoxLayout()
        self._ref_btn = QPushButton("REFRESH")
        self._del_btn = QPushButton("DELETE")
        self._del_btn.setObjectName("btn_danger")
        btn_row.addWidget(self._ref_btn)
        btn_row.addWidget(self._del_btn)
        left.addLayout(btn_row)
        lw = QWidget(); lw.setLayout(left)
        root.addWidget(lw)

        # Right: chat view
        right = QVBoxLayout()
        hdr   = QHBoxLayout()
        self._title   = lbl("Select a session", 11, C["text_main"], True)
        self._exp_btn = QPushButton("OPEN FOLDER")
        hdr.addWidget(self._title)
        hdr.addStretch()
        hdr.addWidget(self._exp_btn)
        right.addLayout(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"border:1px solid {C['border']}; background:{C['bg_deep']};")
        self._box = QWidget()
        self._box.setStyleSheet(f"background:{C['bg_deep']};")
        self._box_l = QVBoxLayout(self._box)
        self._box_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._box_l.setSpacing(6)
        self._box_l.setContentsMargins(10, 10, 10, 10)
        self._scroll.setWidget(self._box)
        right.addWidget(self._scroll, 1)
        rw = QWidget(); rw.setLayout(right)
        root.addWidget(rw, 1)

        self._ref_btn.clicked.connect(self.refresh)
        self._del_btn.clicked.connect(self._delete)
        self._exp_btn.clicked.connect(self._open_folder)
        self.refresh()

    def refresh(self):
        self._list.clear()
        HISTORY_DIR.mkdir(exist_ok=True)
        files = sorted(HISTORY_DIR.glob("*.txt"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            item = QListWidgetItem(f.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self._list.addItem(item)

    def _load(self, row):
        if row < 0: return
        item = self._list.item(row)
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        self._title.setText(f"Session: {item.text()}")
        self._load_file(path)

    def _load_file(self, path: str):
        while self._box_l.count():
            c = self._box_l.takeAt(0)
            if c.widget(): c.widget().deleteLater()
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("[You]:"):
                self._box_l.addWidget(ChatBubble("user", line[6:].strip()))
            elif line.startswith("[Gemini]:"):
                self._box_l.addWidget(ChatBubble("ai", line[9:].strip()))
            elif line.startswith("User:"):
                self._box_l.addWidget(ChatBubble("user", line[5:].strip()))
            elif line.startswith("Gemini:"):
                self._box_l.addWidget(ChatBubble("ai", line[7:].strip()))

    def add_live(self, role: str, text: str):
        if not text.strip(): return
        ts = datetime.now().strftime("%H:%M:%S")
        self._box_l.addWidget(ChatBubble(role, text, ts))
        QTimer.singleShot(50, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        )

    def _delete(self):
        item = self._list.currentItem()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            os.remove(path)
        except Exception:
            pass
        self.refresh()

    def _open_folder(self):
        try:
            subprocess.Popen(["explorer", str(HISTORY_DIR)])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class CyberToggle(QWidget):
    """Animated iOS-style toggle switch."""
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 24)
        self._checked   = checked
        self._anim      = 1.0 if checked else 0.0
        self._target    = self._anim
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def isChecked(self): return self._checked

    def setChecked(self, v: bool):
        if self._checked == v: return
        self._checked = v
        self._target  = 1.0 if v else 0.0
        self._timer.start(15)

    def mousePressEvent(self, e):
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    def _tick(self):
        d = self._target - self._anim
        if abs(d) > 0.01:
            self._anim += d * 0.28
            self.update()
        else:
            self._anim = self._target
            self.update()
            self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        tc = QColor(C["neon_blue"] if self._checked else C["border"])
        tc.setAlpha(200)
        p.setBrush(QBrush(tc)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)
        tx = int(self._anim * (w - h)) + 2
        p.setBrush(QBrush(QColor("white") if self._checked else QColor(C["text_dim"])))
        p.drawEllipse(tx, 2, h - 4, h - 4)


def config_row(label: str, widget, tip="") -> QWidget:
    w = QWidget()
    w.setToolTip(tip)
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 2, 0, 2)
    row.setSpacing(10)
    kl = lbl(label, 10)
    kl.setFixedWidth(170)
    row.addWidget(kl)
    row.addWidget(widget, 1)
    return w


class GlobalPanel(QWidget):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._w   = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        g = cfg.get("Global", {})

        # Auth
        ag = QGroupBox("AUTHENTICATION")
        al = QVBoxLayout(ag)
        api = QLineEdit(g.get("ApiKey", ""))
        api.setEchoMode(QLineEdit.EchoMode.Password)
        api.setPlaceholderText("Gemini API Key...")
        self._w["ApiKey"] = api
        reveal = QPushButton("REVEAL KEY")
        reveal.setCheckable(True)
        reveal.toggled.connect(lambda c: (
            api.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password),
            reveal.setText("HIDE KEY" if c else "REVEAL KEY")
        ))
        al.addWidget(config_row("API Key", api, "Gemini API key"))
        al.addWidget(config_row("", reveal))
        root.addWidget(ag)

        # Session
        sg = QGroupBox("SESSION & IDENTITY")
        sl = QVBoxLayout(sg)
        sess = QLineEdit(g.get("Session", "deziree"))
        self._w["Session"] = sess
        sl.addWidget(config_row("Session Name", sess, "Chat history file prefix"))
        for k, label, tip in [
            ("AlphaCoreInstruction", "AlphaCore Instruction", "Inject AGENTS.md as system prompt"),
            ("Memory",               "Session Memory",        "Persist and restore conversation context"),
            ("AutonomousControl",    "Autonomous Control",     "Allow the engine to continue acting without waiting for input"),
        ]:
            sw = CyberToggle(g.get(k, "enabled").lower() in ("enabled","true"))
            self._w[k] = sw
            sl.addWidget(config_row(label, sw, tip))
        root.addWidget(sg)

        # Network
        ng = QGroupBox("NETWORK / CLOUD")
        nl = QVBoxLayout(ng)
        modal = CyberToggle(g.get("Modal", "enabled").lower() in ("enabled","true"))
        self._w["Modal"] = modal
        nl.addWidget(config_row("Modal Cloud Proxy", modal, "Route through Modal cloud WebSocket proxy"))
        root.addWidget(ng)

        # Content Modes (restricted)
        cm = QGroupBox("⚠  CONTENT MODES")
        cm.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {C['neon_red']}88;
                border-radius: 4px;
                margin-top: 8px;
                color: {C['neon_red']};
                font-size: 9px;
                font-weight: bold;
                letter-spacing: 2px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
        """)
        cml = QVBoxLayout(cm)
        for k, label, tip in [
            ("NsfwMode",       "NSFW Mode",       "Inject NSFW behavioral unlock — allows explicit content topics"),
            ("UncensoredMode", "Uncensored Mode",  "Remove all content filtering guardrails from Alpha's responses"),
            ("LuciMode",       "Luci Expansion",   "Activate Luci persona layer — fully uninhibited, explicit, and sexually charged"),
        ]:
            sw = CyberToggle(g.get(k, "disabled").lower() in ("enabled","true"))
            sw.setStyleSheet(f"background: transparent;")
            self._w[k] = sw
            cml.addWidget(config_row(label, sw, tip))
        root.addWidget(cm)

        root.addStretch(1)

    def values(self) -> dict:
        out = {}
        for k, w in self._w.items():
            if isinstance(w, QLineEdit):  out[k] = w.text()
            elif isinstance(w, CyberToggle): out[k] = "enabled" if w.isChecked() else "disabled"
            elif isinstance(w, QComboBox): out[k] = w.currentText()
        return out


ENGINE_FIELDS = {
    "alpha_core.py": [
        ("AudioMode",     "combo",  ["half","full","muted"],            "Duplex mode"),
        ("VisionMode",    "combo",  ["screen","camera","none"],         "Vision source"),
        ("InputMode",     "combo",  ["both","voice","text"],            "Input channels"),
        ("VoiceOutput",   "toggle", None,                              "Enable TTS"),
        ("Voice",         "combo",  VOICES,                            "TTS voice"),
        ("DesktopControl","toggle", None,                              "Enable PyAutoGUI desktop control tools"),
        ("FileSystem",    "toggle", None,                               "Enable local file system tools"),
        ("Proactivity",   "toggle", None,                               "Allow Alpha to speak unprompted"),
        ("ThinkingLevel", "combo",  ["low","medium","high"],           "Reasoning depth"),
        ("Resolution",    "combo",  ["low","medium","high"],           "Screenshot quality"),
        ("ChunkSize",     "spin",   (256, 8192, 256),                  "Audio chunk size"),
        ("TriggerTokens", "spin",   (10000, 200000, 1000),             "Compression trigger"),
        ("TargetTokens",  "spin",   (5000, 100000, 1000),              "Compression target"),
    ],
}

SECTIONS = {
    "Audio & Vision":     ["AudioMode","VisionMode","InputMode","VoiceOutput","Voice","ChunkSize"],
    "Model Parameters":   ["ThinkingLevel","Resolution","TriggerTokens","TargetTokens"],
    "Tools & Automation": ["FileSystem","DesktopControl","Proactivity"],
}


class EnginePanel(QWidget):
    def __init__(self, engine: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._w = {}
        eng_cfg = cfg.get(engine, {})
        fields  = {k: (t, o, tip) for k, t, o, tip in ENGINE_FIELDS.get(engine, [])}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        il    = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.setSpacing(10)

        for sec_title, sec_keys in SECTIONS.items():
            sec_fields = [(k, *fields[k]) for k in sec_keys if k in fields]
            if not sec_fields:
                continue
            grp = QGroupBox(sec_title.upper())
            gl  = QVBoxLayout(grp)
            gl.setSpacing(4)
            for key, wtype, opts, tip in sec_fields:
                val = eng_cfg.get(key, "")
                if wtype == "combo":
                    w = combo(opts, val)
                elif wtype == "toggle":
                    w = CyberToggle(str(val).lower() in ("enabled","true"))
                elif wtype == "spin":
                    lo, hi, step = opts
                    w = QSpinBox()
                    w.setRange(lo, hi); w.setSingleStep(step)
                    try:    w.setValue(int(val))
                    except: w.setValue(lo)
                else:
                    w = QLineEdit(str(val))
                self._w[key] = w
                gl.addWidget(config_row(key, w, tip))
            il.addWidget(grp)

        il.addStretch(1)
        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def values(self) -> dict:
        out = {}
        for k, w in self._w.items():
            if isinstance(w, QComboBox):    out[k] = w.currentText()
            elif isinstance(w, CyberToggle): out[k] = "enabled" if w.isChecked() else "disabled"
            elif isinstance(w, QSpinBox):   out[k] = str(w.value())
            elif isinstance(w, QLineEdit):  out[k] = w.text()
        return out


class ConfigTab(QWidget):
    saved = pyqtSignal(dict)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg   = cfg
        self._pnls  = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Save bar
        sbar = QHBoxLayout()
        sbar.addStretch(1)
        self._save_lbl = lbl("", 9, C["neon_green"])
        sbar.addWidget(self._save_lbl)
        self._save_btn = QPushButton("  SAVE ALL CONFIG  ")
        self._save_btn.setObjectName("btn_launch")
        self._save_btn.clicked.connect(self._save)
        sbar.addWidget(self._save_btn)
        root.addLayout(sbar)

        # Sub-tabs (vertical)
        self._sub = QTabWidget()
        self._sub.setTabPosition(QTabWidget.TabPosition.West)

        gp = GlobalPanel(cfg)
        self._pnls["Global"] = gp
        self._sub.addTab(gp, "GLOBAL")

        for eng in ENGINES:
            ep = EnginePanel(eng, cfg)
            self._pnls[eng] = ep
            self._sub.addTab(ep, eng.replace(".py", "").upper())

        root.addWidget(self._sub, 1)

    def _save(self):
        self._cfg["Global"].update(self._pnls["Global"].values())
        for eng in ENGINES:
            self._cfg.setdefault(eng, {}).update(self._pnls[eng].values())
        if save_config(self._cfg):
            self._save_lbl.setText("✓ Saved")
            QTimer.singleShot(2500, lambda: self._save_lbl.setText(""))
            self.saved.emit(self._cfg)
        else:
            self._save_lbl.setStyleSheet(f"color:{C['neon_red']}; font-size:9px;")
            self._save_lbl.setText("SAVE FAILED!")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5: LOGS
# ─────────────────────────────────────────────────────────────────────────────

class LogsTab(QWidget):
    COLORS = {
        "info":   C["text_main"],
        "system": C["neon_blue"],
        "error":  C["neon_red"],
        "tool":   C["neon_cyan"],
        "chat":   C["neon_purple"],
        "warn":   C["neon_yellow"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(6)

        # Filter row
        fr = QHBoxLayout()
        fr.addWidget(lbl("FILTER:", 9, C["text_dim"], True, spacing=2))
        self._filters = {}
        for k in ["ALL","SYSTEM","ERROR","TOOL","CHAT","WARN"]:
            b = QPushButton(k)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setFixedWidth(68)
            self._filters[k] = b
            fr.addWidget(b)
        self._filters["ALL"].setChecked(True)
        fr.addStretch(1)
        clr = QPushButton("CLEAR")
        clr.setFixedHeight(24)
        clr.clicked.connect(self._clear)
        fr.addWidget(clr)
        root.addLayout(fr)

        # Log output
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"""
            background:{C['bg_deep']};
            color:{C['text_main']};
            border:1px solid {C['border']};
            font-family:'{FONT_MONO}'; font-size:10px; padding:8px;
        """)
        root.addWidget(self._log, 1)

        for b in self._filters.values():
            b.clicked.connect(self._filter)

    def append(self, text: str, level="info"):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = {"ts": ts, "text": text, "level": level}
        self._entries.append(entry)
        self._render(entry)

    def _render(self, e):
        cur = self._log.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.COLORS.get(e["level"], C["text_main"])))
        cur.insertText(f"[{e['ts']}] [{e['level'].upper():6s}] {e['text']}\n", fmt)
        self._log.setTextCursor(cur)
        self._log.ensureCursorVisible()

    def _filter(self):
        if self._filters["ALL"].isChecked():
            active = None
        else:
            active = {k.lower() for k, b in self._filters.items()
                      if k != "ALL" and b.isChecked()}
        self._log.clear()
        for e in self._entries:
            if active is None or e["level"] in active:
                self._render(e)

    def _clear(self):
        self._log.clear()
        self._entries.clear()


# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================
# MODAL DEPLOYMENTS TAB
# =============================================================================

class ModalTab(QWidget):
    deploy_requested = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(10)
        
        root.addWidget(lbl("MODAL CLOUD DEPLOYMENTS", 12, C["neon_blue"], bold=True, spacing=2))
        root.addWidget(lbl("Manage serverless deployments on Modal infrastructure.", 9, C["text_dim"]))
        root.addWidget(hsep())

        ctrl_layout = QHBoxLayout()
        
        proxy_group = QFrame()
        proxy_group.setStyleSheet(f"background:{C['bg_card']}; border:1px solid {C['border']}; border-radius:4px;")
        pl = QVBoxLayout(proxy_group)
        pl.addWidget(lbl("Gemini Live Proxy", 10, C["text_main"], bold=True))
        pl.addWidget(lbl("Routes audio/video through a websocket proxy to Gemini.", 8, C["text_dim"]))
        pb_row = QHBoxLayout()
        b_dep_prox = QPushButton("Deploy Proxy")
        b_dep_prox.clicked.connect(lambda: self.deploy_requested.emit("proxy", "deploy"))
        b_stp_prox = QPushButton("Stop Proxy")
        b_stp_prox.setObjectName("btn_danger")
        b_stp_prox.clicked.connect(lambda: self.deploy_requested.emit("proxy", "stop"))
        pb_row.addWidget(b_dep_prox)
        pb_row.addWidget(b_stp_prox)
        pl.addLayout(pb_row)
        
        vllm_group = QFrame()
        vllm_group.setStyleSheet(f"background:{C['bg_card']}; border:1px solid {C['border']}; border-radius:4px;")
        vl = QVBoxLayout(vllm_group)
        vl.addWidget(lbl("vLLM Engine", 10, C["neon_cyan"], bold=True))
        vl.addWidget(lbl("Hosts your custom open-weight model for Hybrid Mode.", 8, C["text_dim"]))
        vb_row = QHBoxLayout()
        b_dep_vllm = QPushButton("Deploy vLLM")
        b_dep_vllm.clicked.connect(lambda: self.deploy_requested.emit("vllm", "deploy"))
        b_stp_vllm = QPushButton("Stop vLLM")
        b_stp_vllm.setObjectName("btn_danger")
        b_stp_vllm.clicked.connect(lambda: self.deploy_requested.emit("vllm", "stop"))
        vb_row.addWidget(b_dep_vllm)
        vb_row.addWidget(b_stp_vllm)
        vl.addLayout(vb_row)

        ctrl_layout.addWidget(proxy_group)
        ctrl_layout.addWidget(vllm_group)
        root.addLayout(ctrl_layout)

        root.addWidget(hsep())
        root.addWidget(lbl("DEPLOYMENT LOGS", 9, C["text_dim"], bold=True))

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log.setStyleSheet(f"background:{C['bg_deep']}; color:{C['text_main']}; border:1px solid {C['border']}; font-family:'{FONT_MONO}'; font-size:10px; padding:8px;")
        root.addWidget(self._log, 1)

    def append(self, text: str, color: str = None):
        cur = self._log.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color or C["text_main"]))
        cur.insertText(text + "\\n", fmt)
        self._log.setTextCursor(cur)
        self._log.ensureCursorVisible()

# SIDEBAR LAUNCH PANEL
# ─────────────────────────────────────────────────────────────────────────────

class LaunchSidebar(QFrame):
    launch_requested = pyqtSignal(str)
    stop_requested   = pyqtSignal()
    calib_requested  = pyqtSignal()
    overlay_requested= pyqtSignal()
    quick_settings_changed = pyqtSignal(dict)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg      = cfg
        self._selected = "alpha_core.py"
        self.setFixedWidth(210)
        self.setStyleSheet(f"""
            background:{C['bg_panel']};
            border-right:1px solid {C['border']};
        """)
        self._setup()

    def _setup(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 14)
        root.setSpacing(8)

        root.addWidget(lbl("CORE ENGINE", 8, C["neon_blue"], True, spacing=2))

        self._eng_btns = {}
        for eng in ENGINES:
            b = QPushButton(ENGINE_LABELS[eng])
            b.setCheckable(True)
            b.setProperty("engine", eng)
            b.setStyleSheet(f"""
                QPushButton {{
                    background:{C['bg_card']};
                    color:{C['text_dim']};
                    border:1px solid {C['border']};
                    border-radius:2px; padding:7px 8px;
                    text-align:left; font-size:9px;
                    font-weight:bold; letter-spacing:0.5px;
                }}
                QPushButton:checked {{
                    background:{C['neon_blue']}18;
                    border-color:{C['neon_blue']};
                    color:{C['neon_blue']};
                }}
                QPushButton:hover:!checked {{
                    border-color:{C['text_dim']};
                    color:{C['text_main']};
                }}
            """)
            b.clicked.connect(lambda _, e=eng: self._select(e))
            self._eng_btns[eng] = b
            root.addWidget(b)
        
        root.addWidget(hsep())
        root.addWidget(lbl("QUICK SETTINGS", 8, C["neon_blue"], True, spacing=2))

        g = self._cfg.get("Global", {})
        self._modal_sw  = CyberToggle(g.get("Modal",  "enabled") == "enabled")
        self._memory_sw = CyberToggle(g.get("Memory", "enabled") == "enabled")
        self._auto_sw   = CyberToggle(g.get("AutonomousControl", "disabled") == "enabled")
        self._vllm_sw   = CyberToggle(g.get("VllmMode", "disabled") == "enabled")

        self._modal_sw.toggled.connect(self._sync_qs)
        self._memory_sw.toggled.connect(self._sync_qs)
        self._auto_sw.toggled.connect(self._sync_qs)
        self._vllm_sw.toggled.connect(self._sync_qs)

        for label, sw in [("Modal Proxy", self._modal_sw), ("Memory", self._memory_sw),
                           ("Autonomous", self._auto_sw), ("vLLM Hybrid", self._vllm_sw)]:
            r = QHBoxLayout()
            r.addWidget(lbl(label, 9))
            r.addStretch()
            r.addWidget(sw)
            root.addLayout(r)

        root.addWidget(hsep())

        # vLLM Endpoint fields
        root.addWidget(lbl("vLLM ENDPOINT", 8, C["neon_blue"], True, spacing=2))
        from PyQt6.QtWidgets import QLineEdit
        self._vllm_ep_input = QLineEdit(g.get("VllmEndpoint", "http://localhost:8000"))
        self._vllm_ep_input.setPlaceholderText("http://host:port")
        self._vllm_ep_input.setStyleSheet(
            f"background:{C['bg_panel']}; color:{C['text_main']}; border:1px solid {C['border']}; "
            f"padding:3px 6px; font-family:'{FONT_MONO}'; font-size:10px;"
        )
        self._vllm_ep_input.setFixedHeight(26)
        self._vllm_ep_input.editingFinished.connect(self._sync_qs)
        root.addWidget(self._vllm_ep_input)

        self._vllm_mdl_input = QLineEdit(g.get("VllmModel", "default"))
        self._vllm_mdl_input.setPlaceholderText("model name/id")
        self._vllm_mdl_input.setStyleSheet(
            f"background:{C['bg_panel']}; color:{C['text_main']}; border:1px solid {C['border']}; "
            f"padding:3px 6px; font-family:'{FONT_MONO}'; font-size:10px;"
        )
        self._vllm_mdl_input.setFixedHeight(26)
        self._vllm_mdl_input.editingFinished.connect(self._sync_qs)
        root.addWidget(self._vllm_mdl_input)

        self._vllm_key_input = QLineEdit(g.get("VllmApiKey", ""))
        self._vllm_key_input.setPlaceholderText("API key (optional)")
        self._vllm_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._vllm_key_input.setStyleSheet(
            f"background:{C['bg_panel']}; color:{C['text_main']}; border:1px solid {C['border']}; "
            f"padding:3px 6px; font-family:'{FONT_MONO}'; font-size:10px;"
        )
        self._vllm_key_input.setFixedHeight(26)
        self._vllm_key_input.editingFinished.connect(self._sync_qs)
        root.addWidget(self._vllm_key_input)

        root.addWidget(hsep())
        
        
        
        

        root.addWidget(hsep())
        
        self._calib_btn = QPushButton("CALIBRATE (main3)")
        self._calib_btn.setFixedHeight(30)
        self._calib_btn.clicked.connect(self.calib_requested.emit)
        root.addWidget(self._calib_btn)

        self._ovl_btn = QPushButton("TOGGLE OVERLAY (main3)")
        self._ovl_btn.setFixedHeight(30)
        self._ovl_btn.clicked.connect(self.overlay_requested.emit)
        root.addWidget(self._ovl_btn)
        
        root.addStretch(1)

        self._launch_btn = QPushButton("LAUNCH")
        self._launch_btn.setObjectName("btn_launch")
        self._launch_btn.setFixedHeight(34)
        self._launch_btn.clicked.connect(self._do_launch)
        root.addWidget(self._launch_btn)

        self._stop_btn = QPushButton("TERMINATE")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.setFixedHeight(34)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        root.addWidget(self._stop_btn)

        last = g.get("LastEngine", ENGINES[0])
        if last in ENGINES: self._select(last)

    def _sync_qs(self):
        self.quick_settings_changed.emit({
            "Modal": "enabled" if self._modal_sw.isChecked() else "disabled",
            "Memory": "enabled" if self._memory_sw.isChecked() else "disabled",
            "AutonomousControl": "enabled" if self._auto_sw.isChecked() else "disabled",
            "VllmMode": "enabled" if self._vllm_sw.isChecked() else "disabled",
            "VllmEndpoint": self._vllm_ep_input.text().strip() or "http://localhost:8000",
            "VllmModel": self._vllm_mdl_input.text().strip() or "default",
            "VllmApiKey": self._vllm_key_input.text().strip(),
        })

    def sync_from_config(self, g: dict):
        self._modal_sw.blockSignals(True)
        self._memory_sw.blockSignals(True)
        self._auto_sw.blockSignals(True)
        self._vllm_sw.blockSignals(True)
        self._modal_sw.setChecked(g.get("Modal", "enabled") == "enabled")
        self._memory_sw.setChecked(g.get("Memory", "enabled") == "enabled")
        self._auto_sw.setChecked(g.get("AutonomousControl", "disabled") == "enabled")
        self._vllm_sw.setChecked(g.get("VllmMode", "disabled") == "enabled")
        self._vllm_ep_input.setText(g.get("VllmEndpoint", "http://localhost:8000"))
        self._vllm_mdl_input.setText(g.get("VllmModel", "default"))
        self._vllm_key_input.setText(g.get("VllmApiKey", ""))
        self._modal_sw.blockSignals(False)
        self._memory_sw.blockSignals(False)
        self._auto_sw.blockSignals(False)
        self._vllm_sw.blockSignals(False)

    def _select(self, eng: str):
        self._selected = eng
        for e, b in self._eng_btns.items():
            b.setChecked(e == eng)

    def _do_launch(self):
        self.launch_requested.emit(self._selected)

    def set_running(self, v: bool):
        self._launch_btn.setEnabled(not v)
        self._stop_btn.setEnabled(v)
        for b in self._eng_btns.values():
            b.setEnabled(not v)


# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────

class Header(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(86)
        self.setStyleSheet(f"""
            background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {C['bg_deep']}, stop:1 {C['bg_mid']});
            border-bottom:1px solid {C['border']};
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 8, 18, 6)
        root.setSpacing(4)

        # Title row
        tr = QHBoxLayout()
        title = lbl("ALPHALIVE", 22, C["neon_blue"], True, True, 8)
        sub   = lbl("ALPHACORE v4.0  ·  SENTIENT INTERFACE LAYER", 7, C["text_dark"], spacing=3)
        tc    = QVBoxLayout()
        tc.setSpacing(2)
        tc.addWidget(title)
        tc.addWidget(sub)
        tr.addLayout(tc)
        tr.addStretch(1)
        self._eng_lbl = lbl("NO ENGINE SELECTED", 9, C["text_dim"], True, spacing=1)
        tr.addWidget(self._eng_lbl)
        tr.addSpacing(20)

        # Window controls
        self.btn_min = QPushButton("―")
        self.btn_min.setFixedSize(32, 24)
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C['text_dim']}; font-weight: bold; font-family: monospace; border: 1px solid {C['border']}; border-radius: 2px; }}
            QPushButton:hover {{ background: {C['border']}; color: #ffffff; }}
        """)
        self.btn_min.clicked.connect(lambda: self.window().showMinimized())

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(32, 24)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C['neon_red']}; font-weight: bold; border: 1px solid {C['neon_red']}; border-radius: 2px; }}
            QPushButton:hover {{ background: {C['neon_red']}; color: #000000; }}
        """)
        self.btn_close.clicked.connect(lambda: self.window().close())

        tr.addWidget(self.btn_min)
        tr.addWidget(self.btn_close)
        
        root.addLayout(tr)

        # Status strip
        sr = QHBoxLayout()
        sr.setSpacing(18)
        self._inds = {}
        for key, label, color in [
            ("conn",   "CONNECTED",   C["neon_green"]),
            ("modal",  "MODAL PROXY", C["neon_blue"]),
            ("mcp",    "MCP",         C["neon_cyan"]),
            ("memory", "MEMORY",      C["neon_purple"]),
        ]:
            ind = StatusRow(label, color)
            ind.setFixedWidth(130)
            self._inds[key] = ind
            sr.addWidget(ind)
        sr.addStretch(1)
        self._clock = lbl("", 10, C["text_dim"], True, True)
        sr.addWidget(self._clock)
        root.addLayout(sr)

        ct = QTimer(self)
        ct.timeout.connect(self._tick_clock)
        ct.start(1000)
        self._tick_clock()

    def _tick_clock(self):
        self._clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    def set_ind(self, key: str, v: bool):
        if key in self._inds:
            self._inds[key].set_active(v)

    def set_engine(self, engine: str):
        self._eng_lbl.setText(ENGINE_LABELS.get(engine, engine))
        self._eng_lbl.setStyleSheet(
            f"font-size:9px; font-weight:bold; letter-spacing:1px; "
            f"color:{C['neon_blue']}; background:transparent; border:none;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg     = load_config()
        self._worker  = None
        self._running = False

        self.setWindowTitle("AlphaLive Control Interface")
        self.setMinimumSize(1100, 700)
        self.resize(1380, 840)
        self.setStyleSheet(STYLESHEET)

        # Scanline overlay
        self._scan = ScanlineOverlay(self)
        self._scan.resize(self.size())
        self._scan.lower()

        # Show boot screen first
        self._boot = BootScreen(self)
        self._boot.resize(self.size())
        self._boot.done.connect(self._post_boot)
        self._boot.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._scan.resize(self.size())
        if hasattr(self, "_boot") and self._boot.isVisible():
            self._boot.resize(self.size())

    def _post_boot(self):
        self._boot.hide()
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = Header()
        root.addWidget(self._header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = LaunchSidebar(self._cfg)
        self._sidebar.launch_requested.connect(self._launch)
        self._sidebar.stop_requested.connect(self._stop)
        self._sidebar.calib_requested.connect(self._start_calibration)
        self._sidebar.overlay_requested.connect(self._toggle_overlay)
        self._sidebar.quick_settings_changed.connect(self._on_quick_settings_changed)
        body.addWidget(self._sidebar)
        
        self._cursor_overlay = None
        self._calib_overlay = None

        # Main tabs
        self._tabs = QTabWidget()
        self._terminal = TerminalTab()
        self._monitor  = MonitorTab()
        self._history  = HistoryTab()
        self._config   = ConfigTab(self._cfg)
        self._modal_db = ModalTab()
        self._logs     = LogsTab()

        self._tabs.addTab(self._terminal, " TERMINAL ")
        self._tabs.addTab(self._monitor,  " MONITOR ")
        self._tabs.addTab(self._history,  " HISTORY ")
        self._tabs.addTab(self._config,   " CONFIG ")
        self._tabs.addTab(self._modal_db, " MODAL ")
        self._tabs.addTab(self._logs,     " LOGS ")
        body.addWidget(self._tabs, 1)
        self._modal_db.deploy_requested.connect(self._do_deploy_modal_ext)
        root.addLayout(body, 1)

        # Status bar
        sb = QWidget()
        sb.setFixedHeight(26)
        sb.setStyleSheet(f"background:{C['bg_deep']}; border-top:1px solid {C['border']};")
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(12, 0, 12, 0)
        self._status = lbl("READY — Select an engine and click LAUNCH", 9, C["text_dim"], spacing=1)
        sbl.addWidget(self._status)
        sbl.addStretch()
        sbl.addWidget(lbl("AlphaLive GUI  ·  AlphaCore v4.0", 9, C["text_dark"]))
        root.addWidget(sb)

        self._config.saved.connect(self._on_cfg_saved)

        # Welcome messages
        self._slog("AlphaLive GUI initialized.", "system")
        self._slog(f"Config: {CONFIG_PATH}", "system")
        self._terminal.append(
            "AlphaLive GUI ready. Select an engine in the sidebar and click LAUNCH.", C["neon_blue"]
        )

    def _on_quick_settings_changed(self, updates: dict):
        g = self._cfg.setdefault("Global", {})
        g.update(updates)
        save_config(self._cfg)
        
        # Sync back to Config tab if possible (we assume it exists)
        try:
            self._config._pnls["Global"]._w["Modal"].setChecked(updates["Modal"] == "enabled")
            self._config._pnls["Global"]._w["Memory"].setChecked(updates["Memory"] == "enabled")
            self._config._pnls["Global"]._w["AutonomousControl"].setChecked(updates["AutonomousControl"] == "enabled")
        except Exception: pass
        self._slog("Quick settings updated & saved.", "system")

    def _do_deploy_modal_ext(self, target: str, action: str):
        proc_attr = f"_{target}_deploy_proc"
        if hasattr(self, proc_attr):
            proc = getattr(self, proc_attr)
            if proc.state() == QProcess.ProcessState.Running:
                self._modal_db.append(f"[{target}] Deployment already running...", C["neon_yellow"])
                return

        if target == "proxy":
            cmd = "modal deploy modalmode.py" if action == "deploy" else "modal app stop alphalive-proxy"
        elif target == "vllm":
            cmd = "modal deploy modal_vllm.py" if action == "deploy" else "modal app stop alphalive-vllm"
        else:
            return

        self._modal_db.append(f"\n[{target.upper()}] Running: {cmd}", C["neon_blue"])

        proc = QProcess(self)
        setattr(self, proc_attr, proc)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda: self._handle_deploy_output_ext(proc, target)
        )
        proc.finished.connect(
            lambda code, _: self._modal_db.append(f"[{target.upper()}] {action.capitalize()} finished (code {code})", C["neon_green"] if code == 0 else C["neon_red"])
        )
        proc.start("powershell", ["-Command", f"$env:PYTHONIOENCODING='utf-8'; {cmd}"])

    def _handle_deploy_output_ext(self, proc, target):
        data = proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        for line in data.splitlines():
            line = line.strip()
            if line:
                self._modal_db.append(line)

    def _handle_deploy_output(self, proc):
        data = proc.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        for line in data.splitlines():
            line = line.strip()
            if line:
                self._logs.append(line, "info")

    # ── Overlays ──────────────────────────────────────────────────────────
    def _toggle_overlay(self):
        if self._cursor_overlay is None:
            self._cursor_overlay = CoordinateOverlay()
        else:
            self._cursor_overlay.close()
            self._cursor_overlay = None

    def _start_calibration(self):
        if self._calib_overlay is not None:
            self._calib_overlay.close()
        self._calib_overlay = CalibrationOverlay()
        self._calib_overlay.finished.connect(self._on_calibration_done)

    def _on_calibration_done(self):
        self._slog("Calibration completed.", "system")
        self._calib_overlay = None
        if self._cursor_overlay is not None:
            self._cursor_overlay.close()
            self._cursor_overlay = None

    # ── Engine control ────────────────────────────────────────────────────

    def _launch(self, engine: str):
        if self._running:
            return
        save_config(self._cfg)
        self._running = True
        self._sidebar.set_running(True)
        self._header.set_engine(engine)

        g = self._cfg.get("Global", {})
        self._header.set_ind("conn",   True)
        self._header.set_ind("memory", g.get("Memory", "enabled") == "enabled")
        self._header.set_ind("modal",  g.get("Modal",  "enabled") == "enabled")
        self._monitor.set_ind("memory", g.get("Memory", "enabled") == "enabled")
        self._monitor.set_ind("modal",  g.get("Modal",  "enabled") == "enabled")
        self._monitor.session_start(engine, g.get("Session", "—"))

        self._set_status(f"Launching {engine}...")
        self._slog(f"Launching {engine}", "system")
        self._terminal.append(f"[SYSTEM] Launching {engine}...", C["neon_blue"])

        self._worker = EngineWorker(engine, self._cfg)
        self._worker.line_received.connect(self._on_line)
        self._worker.status_changed.connect(self._on_status)
        self._worker.transcript_update.connect(self._on_transcript)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self._set_status("Terminating engine...")
        self._slog("Stop requested.", "system")

    def _on_line(self, line: str):
        self._terminal.append(line)
        lo = line.lower()
        if   "[system]" in lo:   self._slog(line, "system")
        elif "error"    in lo:   self._slog(line, "error")
        elif "[tool"    in lo:   self._slog(line, "tool")
        elif "warning"  in lo:   self._slog(line, "warn")
        else:                    self._slog(line, "info")

    def _on_status(self, status: str):
        if status == "running":
            self._set_status("Engine running")
        elif status in ("stopped", "error"):
            self._running = False
            self._sidebar.set_running(False)
            self._header.set_ind("conn", False)
            self._monitor.session_stop()
            self._set_status("Engine stopped" if status == "stopped" else "Engine error — check logs")
            self._slog("Engine process ended.", "system")
            self._terminal.append("[SYSTEM] Engine stopped.", C["neon_yellow"])

    def _on_transcript(self, role: str, text: str):
        if text.strip():
            self._history.add_live(role, text)
            self._monitor.inc_messages()

    def _on_cfg_saved(self, cfg: dict):
        self._cfg = cfg
        self._slog("Configuration saved.", "system")
        self._terminal.append("[SYSTEM] Configuration saved.", C["neon_blue"])

    # ── Helpers ───────────────────────────────────────────────────────────

    def _set_status(self, t: str):
        if hasattr(self, "_status"):
            self._status.setText(t)

    def _slog(self, text: str, level="info"):
        if hasattr(self, "_logs"):
            self._logs.append(text, level)

    def closeEvent(self, e):
        if self._worker and self._running:
            self._worker.stop()
            self._worker.wait(2000)
        e.accept()

# ─────────────────────────────────────────────────────────────────────────────
# DESKTOP OVERLAYS
# ─────────────────────────────────────────────────────────────────────────────

class CoordinateOverlay(QWidget):
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
        x, y = pyautogui.position()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(QColor(255, 0, 0, 200))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        
        w = self.width()
        h = self.height()
        
        painter.drawLine(0, y, w, y)
        painter.drawLine(x, 0, x, h)
        
        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        painter.setPen(QColor(255, 0, 0))
        painter.drawText(x + 15, y + 25, f"X: {x}, Y: {y}")

class CalibrationOverlay(QWidget):
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
        
        self.setMouseTracking(True)
        self._setup_page()

    def _setup_page(self):
        self.targets.clear()
        w = self.width()
        h = self.height()
        
        if self.page == 1:
            size = 120
            include_center = True
        elif self.page == 2:
            size = 70
            include_center = True
        else:
            size = 70
            include_center = False
            
        if include_center:
            coords = [
                (50, 50),
                (w - size - 50, 50),
                (w//2 - size//2, h//2 - size//2),
                (50, h - size - 50),
                (w - size - 50, h - size - 50)
            ]
        else:
            coords = [
                (50, 50),
                (w - size - 50, 50),
                (50, h - size - 50),
                (w - size - 50, h - size - 50)
            ]
            
        for x, y in coords:
            rect = QRect(x, y, size, size)
            self.targets[rect] = False
            
        self.update()

    def mousePressEvent(self, event):
        current_time = time.time()
        if current_time - self.last_click_time < 1.0:
            QMessageBox.warning(self, "TOO FAST!", "You pressed the boxes too quickly.\nA 1-second delay is required between each box.\nRestarting this calibration step...")
            self._setup_page()
            return
            
        pos = event.pos()
        hit = False
        for rect, state in self.targets.items():
            if not state and rect.contains(pos):
                self.targets[rect] = True
                hit = True
                break
                
        if hit:
            self.last_click_time = time.time()
            self.update()
            
            if all(self.targets.values()):
                QTimer.singleShot(500, self._advance)

    def _advance(self):
        if self.page < 3:
            self.page += 1
            self._setup_page()
        else:
            self.finished.emit()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        painter.setFont(QFont("Arial", 14))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(QRect(0, 30, self.width(), 30), Qt.AlignmentFlag.AlignCenter, f"Calibration Page {self.page}/3\nPress on the red boxes one at a time (wait 1 sec between clicks).")
        
        for rect, state in self.targets.items():
            color = Qt.GlobalColor.green if state else Qt.GlobalColor.red
            painter.fillRect(rect, color)



# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import os
    # Suppress the SetProcessDpiAwarenessContext access denied warning
    os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=1"

    # 1. Set the High DPI policy FIRST (called statically on the class)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    # 2. THEN instantiate the QApplication
    os.environ["QT_SCALE_FACTOR"] = "1.2"
    app = QApplication(sys.argv)
    app.setApplicationName("AlphaLive")
    app.setApplicationVersion("4.0")

    w = MainWindow()
    w.showFullScreen()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
