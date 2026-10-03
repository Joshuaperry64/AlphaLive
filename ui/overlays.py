"""
AlphaLive // Visual Overlays & Modal Profile Tools
- CoordinateOverlay (Fullscreen transparent coordinate grid with live crosshair & physical pixel display)
- CalibrationOverlay (Interactive screen coordinate calibration squares)
- get_modal_profiles (Inspects ~/.modal.toml for available profiles)
"""

import os
import random
import time
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QApplication, QMessageBox
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
