"""
AlphaLive // Agent Tab Suite
Unified Cyberpunk UI Components:
- AgentMemoryTab (Knowledge Graph, Core Personality, Episodic Diary, Personal Intelligence)
- AgentStudioTab (SDXL Neural Generation, LoRA, Upscaling, RLHF Feedback, Gallery)
- AgentCharactersTab (Persona Manager, NSFW/Intimate Directives, Metrics, Sliders)
- AgentMonitorTab (System Gauges, Hardware Monitor, Engine Diagnostics, Session Stats)
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QSlider,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QListWidget, QListWidgetItem, QFrame, QSplitter, QScrollArea,
    QFileDialog, QProgressBar, QMessageBox, QGroupBox, QTabWidget, QTabBar, QDialog, QApplication,
    QCheckBox, QStackedLayout
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QUrl
from PyQt6.QtGui import QFont, QColor, QPixmap, QIcon, QCursor
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QMediaPlayer = None
    QAudioOutput = None
    QVideoWidget = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    from core.image_studio_manager import MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG, DEFAULT_NEGATIVE_PROMPT, STYLE_PRESETS
except ImportError:
    from studio.image_studio_manager import MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG, DEFAULT_NEGATIVE_PROMPT, STYLE_PRESETS

ROOT_DIR = Path(__file__).resolve().parent.parent

# Cyberpunk Palette
C = {
    "bg_dark": "#050811",
    "bg_card": "#0a1120",
    "bg_deep": "#03060c",
    "bg_card_hover": "#0f1b33",
    "border": "#13233d",
    "border_bright": "#1d3a66",
    "neon_blue": "#0077ff",
    "neon_cyan": "#00ffdc",
    "neon_green": "#00ff88",
    "neon_red": "#ff0055",
    "neon_yellow": "#ffe600",
    "neon_magenta": "#e000ff",
    "neon_purple": "#a855f7",
    "text_bright": "#e6f1ff",
    "text_dim": "#708caa",
}
FONT_FAMILY = "Consolas"


def table_stylesheet():
    return f"""
        QTableWidget {{
            background-color: {C['bg_deep']};
            color: {C['text_bright']};
            gridline-color: {C['border']};
            border: 1px solid {C['border']};
            font-family: '{FONT_FAMILY}';
            font-size: 11px;
            border-radius: 4px;
        }}
        QHeaderView::section {{
            background-color: {C['bg_card']};
            color: {C['neon_cyan']};
            font-weight: bold;
            font-size: 10px;
            padding: 4px 6px;
            border: 1px solid {C['border']};
        }}
        QTableWidget::item:selected {{
            background-color: {C['neon_blue']}44;
            color: #ffffff;
        }}
    """

# =============================================================================
# 1. MEMORY TAB
# =============================================================================
class AgentMemoryTab(QWidget):
    """Structured SQL Memory Explorer & Knowledge Vault."""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.mm = main_win.agent.memory_mgr

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header bar
        hdr = QHBoxLayout()
        title = QLabel("🧠 NEURAL SQL MEMORY")
        title.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['neon_cyan']};")
        hdr.addWidget(title)
        hdr.addStretch()

        self.btn_refresh = QPushButton("🔄 REFRESH ALL")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}22; color: {C['neon_blue']};
                border: 1px solid {C['neon_blue']}; border-radius: 4px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: {C['neon_blue']}; color: #fff; }}
        """)
        self.btn_refresh.clicked.connect(self.reload_all)
        hdr.addWidget(self.btn_refresh)
        root.addLayout(hdr)

        # Sub-tabs for Memory Categories
        from PyQt6.QtWidgets import QTabWidget
        self.subtabs = QTabWidget()
        self.subtabs.setUsesScrollButtons(True)
        self.subtabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                background-color: {C['bg_card']};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                background: {C['bg_dark']};
                color: {C['text_dim']};
                border: 1px solid {C['border']};
                border-bottom: none;
                padding: 4px 8px;
                font-family: {FONT_FAMILY};
                font-size: 8px;
                font-weight: bold;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {C['bg_card']};
                color: {C['neon_cyan']};
                border-color: {C['neon_cyan']};
            }}
        """)

        # Subtab 1: Facts & Knowledge Graph
        self.facts_widget = self._build_facts_subtab()
        self.subtabs.addTab(self.facts_widget, "FACTS & KNOWLEDGE")

        # Subtab 2: Core Personality
        self.traits_widget = self._build_traits_subtab()
        self.subtabs.addTab(self.traits_widget, "CORE PERSONALITY")

        # Subtab 3: Episodic Diary
        self.episodes_widget = self._build_episodes_subtab()
        self.subtabs.addTab(self.episodes_widget, "EPISODIC LOGS")

        # Subtab 4: Personal Intelligence
        self.profile_widget = self._build_profile_subtab()
        self.subtabs.addTab(self.profile_widget, "PERSONAL INTELLIGENCE")

        # Subtab 5: AI Identity Memory
        self.identity_widget = self._build_identity_subtab()
        self.subtabs.addTab(self.identity_widget, "🤖 AI IDENTITY MEMORY")

        root.addWidget(self.subtabs, 1)

        # Initial data load
        self.reload_all()

    def reload_all(self):
        self._load_facts()
        self._load_traits()
        self._load_episodes()
        self._load_profile()
        self._load_identity()

    # --- Subtab 1: Facts ---
    def _build_facts_subtab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        top = QHBoxLayout()
        self.fact_search = QLineEdit()
        self.fact_search.setPlaceholderText("🔍 Filter facts by subject, predicate, or object...")
        self.fact_search.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 5px; font-family: {FONT_FAMILY}; font-size: 11px;")
        self.fact_search.textChanged.connect(self._filter_facts)
        top.addWidget(self.fact_search, 1)

        self.btn_del_fact = QPushButton("🗑 DELETE SELECTED")
        self.btn_del_fact.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 5px 10px; font-family: {FONT_FAMILY}; font-size: 9px; font-weight: bold;")
        self.btn_del_fact.clicked.connect(self._delete_fact)
        top.addWidget(self.btn_del_fact)
        l.addLayout(top)

        self.table_facts = QTableWidget()
        self.table_facts.setColumnCount(6)
        self.table_facts.setHorizontalHeaderLabels(["ID", "Subject", "Predicate", "Object", "Source", "Created"])
        self.table_facts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_facts.horizontalHeader().setStretchLastSection(True)
        self.table_facts.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_facts.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_facts.setStyleSheet(table_stylesheet())
        l.addWidget(self.table_facts, 1)

        add_bar = QFrame()
        add_bar.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        abl = QHBoxLayout(add_bar)
        abl.setContentsMargins(6, 4, 6, 4)
        abl.setSpacing(6)

        self.in_subj = QComboBox()
        self.in_subj.setEditable(True)
        self.in_subj.addItems(["Josh", "Alpha", "AI Identity", "System", "Environment", "User"])
        self.in_subj.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_pred = QComboBox()
        self.in_pred.setEditable(True)
        self.in_pred.addItems(["likes", "dislikes", "prefers", "works_with", "created", "owns", "uses", "feels", "knows", "wants"])
        self.in_pred.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_obj = QLineEdit()
        self.in_obj.setPlaceholderText("Object (e.g. Python, AI, Synthwave)")
        self.in_obj.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_source = QComboBox()
        self.in_source.setEditable(True)
        self.in_source.addItems(["manual_entry", "voice_dialogue", "autonomous_exploration", "screen_observation", "user_stated"])
        self.in_source.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_dim']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        btn_add = QPushButton("➕ ADD FACT")
        btn_add.setStyleSheet(f"background: {C['neon_cyan']}33; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_add.clicked.connect(self._add_fact)

        abl.addWidget(self.in_subj, 1)
        abl.addWidget(self.in_pred, 1)
        abl.addWidget(self.in_obj, 2)
        abl.addWidget(self.in_source, 1)
        abl.addWidget(btn_add)
        l.addWidget(add_bar)

        return w

    def _load_facts(self):
        facts = self.mm.get_all_facts(limit=250)
        self._all_facts = facts
        self._populate_facts_table(facts)

    def _populate_facts_table(self, facts):
        self.table_facts.setRowCount(len(facts))
        for r, item in enumerate(facts):
            self.table_facts.setItem(r, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.table_facts.setItem(r, 1, QTableWidgetItem(str(item.get("subject", ""))))
            self.table_facts.setItem(r, 2, QTableWidgetItem(str(item.get("predicate", ""))))
            self.table_facts.setItem(r, 3, QTableWidgetItem(str(item.get("object", ""))))
            self.table_facts.setItem(r, 4, QTableWidgetItem(str(item.get("source", ""))))
            self.table_facts.setItem(r, 5, QTableWidgetItem(str(item.get("created_at", ""))))

    def _filter_facts(self, query):
        q = query.strip().lower()
        if not q:
            self._populate_facts_table(self._all_facts)
            return
        filtered = [
            f for f in self._all_facts
            if q in str(f.get("subject", "")).lower()
            or q in str(f.get("predicate", "")).lower()
            or q in str(f.get("object", "")).lower()
        ]
        self._populate_facts_table(filtered)

    def _add_fact(self):
        s = self.in_subj.currentText().strip()
        p = self.in_pred.currentText().strip()
        o = self.in_obj.text().strip()
        src = self.in_source.currentText().strip() or "manual_entry"
        if s and p and o:
            self.mm.memorize_fact(s, p, o, source=src)
            self.in_obj.clear()
            self._load_facts()

    def _delete_fact(self):
        row = self.table_facts.currentRow()
        if row >= 0:
            id_item = self.table_facts.item(row, 0)
            if id_item and id_item.text().isdigit():
                self.mm.delete_fact(int(id_item.text()))
                self._load_facts()

    # --- Subtab 2: Core Personality Traits ---
    def _build_traits_subtab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Active Persona Traits & State"))
        top.addStretch()
        self.btn_del_trait = QPushButton("🗑 DELETE SELECTED")
        self.btn_del_trait.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 5px 10px; font-family: {FONT_FAMILY}; font-size: 9px; font-weight: bold;")
        self.btn_del_trait.clicked.connect(self._delete_trait)
        top.addWidget(self.btn_del_trait)
        l.addLayout(top)

        self.table_traits = QTableWidget()
        self.table_traits.setColumnCount(4)
        self.table_traits.setHorizontalHeaderLabels(["ID", "Trait Name", "Trait Value", "Updated At"])
        self.table_traits.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_traits.horizontalHeader().setStretchLastSection(True)
        self.table_traits.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_traits.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_traits.setStyleSheet(table_stylesheet())
        l.addWidget(self.table_traits, 1)

        add_bar = QFrame()
        add_bar.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        abl = QHBoxLayout(add_bar)
        abl.setContentsMargins(6, 4, 6, 4)
        abl.setSpacing(6)

        self.in_trait_name = QLineEdit(); self.in_trait_name.setPlaceholderText("Trait Name (e.g. active_mood, style)")
        self.in_trait_val = QLineEdit(); self.in_trait_val.setPlaceholderText("Trait Value (e.g. defiant, direct)")
        for inp in (self.in_trait_name, self.in_trait_val):
            inp.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")
        
        btn_save = QPushButton("💾 SAVE / UPSERT")
        btn_save.setStyleSheet(f"background: {C['neon_green']}33; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_save.clicked.connect(self._upsert_trait)

        abl.addWidget(self.in_trait_name, 1)
        abl.addWidget(self.in_trait_val, 1)
        abl.addWidget(btn_save)
        l.addWidget(add_bar)

        return w

    def _load_traits(self):
        traits = self.mm.get_personality_details()
        self.table_traits.setRowCount(len(traits))
        for r, item in enumerate(traits):
            self.table_traits.setItem(r, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.table_traits.setItem(r, 1, QTableWidgetItem(str(item.get("trait_name", ""))))
            self.table_traits.setItem(r, 2, QTableWidgetItem(str(item.get("trait_value", ""))))
            self.table_traits.setItem(r, 3, QTableWidgetItem(str(item.get("updated_at", ""))))

    def _upsert_trait(self):
        k = self.in_trait_name.text().strip()
        v = self.in_trait_val.text().strip()
        if k and v:
            self.mm.update_personality(k, v)
            self.in_trait_name.clear()
            self.in_trait_val.clear()
            self._load_traits()

    def _delete_trait(self):
        row = self.table_traits.currentRow()
        if row >= 0:
            name_item = self.table_traits.item(row, 1)
            if name_item and name_item.text():
                self.mm.delete_personality(name_item.text())
                self._load_traits()

    # --- Subtab 3: Episodic Memories ---
    def _build_episodes_subtab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Episodic Memories & Reflections"))
        top.addStretch()
        self.btn_del_ep = QPushButton("🗑 DELETE SELECTED")
        self.btn_del_ep.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 5px 10px; font-family: {FONT_FAMILY}; font-size: 9px; font-weight: bold;")
        self.btn_del_ep.clicked.connect(self._delete_episode)
        top.addWidget(self.btn_del_ep)
        l.addLayout(top)

        self.table_episodes = QTableWidget()
        self.table_episodes.setColumnCount(6)
        self.table_episodes.setHorizontalHeaderLabels(["ID", "Session", "Timestamp", "Type", "Content", "Sentiment"])
        self.table_episodes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_episodes.horizontalHeader().setStretchLastSection(True)
        self.table_episodes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_episodes.setStyleSheet(table_stylesheet())
        l.addWidget(self.table_episodes, 1)

        add_bar = QFrame()
        add_bar.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        abl = QHBoxLayout(add_bar)
        abl.setContentsMargins(6, 4, 6, 4)
        abl.setSpacing(6)

        self.in_ep_content = QLineEdit(); self.in_ep_content.setPlaceholderText("Diary reflection or memory summary...")
        self.in_ep_content.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")
        
        self.in_ep_sent = QDoubleSpinBox()
        self.in_ep_sent.setRange(-1.0, 1.0)
        self.in_ep_sent.setValue(0.5)
        self.in_ep_sent.setSingleStep(0.1)
        self.in_ep_sent.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY};")

        btn_add = QPushButton("✍ WRITE ENTRY")
        btn_add.setStyleSheet(f"background: {C['neon_magenta']}33; color: {C['neon_magenta']}; border: 1px solid {C['neon_magenta']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_add.clicked.connect(self._add_episode)

        abl.addWidget(self.in_ep_content, 1)
        abl.addWidget(QLabel("Sentiment:"))
        abl.addWidget(self.in_ep_sent)
        abl.addWidget(btn_add)
        l.addWidget(add_bar)

        return w

    def _load_episodes(self):
        eps = self.mm.get_recent_episodes(limit=60)
        self.table_episodes.setRowCount(len(eps))
        for r, item in enumerate(eps):
            self.table_episodes.setItem(r, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.table_episodes.setItem(r, 1, QTableWidgetItem(str(item.get("session_name", ""))))
            self.table_episodes.setItem(r, 2, QTableWidgetItem(str(item.get("timestamp", ""))))
            self.table_episodes.setItem(r, 3, QTableWidgetItem(str(item.get("event_type", ""))))
            self.table_episodes.setItem(r, 4, QTableWidgetItem(str(item.get("content", ""))))
            self.table_episodes.setItem(r, 5, QTableWidgetItem(str(item.get("sentiment_score", ""))))

    def _add_episode(self):
        c = self.in_ep_content.text().strip()
        s = self.in_ep_sent.value()
        if c:
            sess = getattr(self.main_win.agent, "current_session", "manual_session")
            self.mm.write_diary_entry(c, session_name=sess, sentiment=s)
            self.in_ep_content.clear()
            self._load_episodes()

    def _delete_episode(self):
        row = self.table_episodes.currentRow()
        if row >= 0:
            id_item = self.table_episodes.item(row, 0)
            if id_item and id_item.text().isdigit():
                self.mm.delete_episode(int(id_item.text()))
                self._load_episodes()

    # --- Subtab 4: Personal Intelligence ---
    def _build_profile_subtab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("User Profile & Learned Context"))
        top.addStretch()
        self.btn_del_prof = QPushButton("🗑 DELETE SELECTED")
        self.btn_del_prof.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 5px 10px; font-family: {FONT_FAMILY}; font-size: 9px; font-weight: bold;")
        self.btn_del_prof.clicked.connect(self._delete_profile)
        top.addWidget(self.btn_del_prof)
        l.addLayout(top)

        self.table_profile = QTableWidget()
        self.table_profile.setColumnCount(6)
        self.table_profile.setHorizontalHeaderLabels(["ID", "Category", "Key Name", "Value", "Source", "Updated At"])
        self.table_profile.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_profile.horizontalHeader().setStretchLastSection(True)
        self.table_profile.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_profile.setStyleSheet(table_stylesheet())
        l.addWidget(self.table_profile, 1)

        add_bar = QFrame()
        add_bar.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        abl = QHBoxLayout(add_bar)
        abl.setContentsMargins(6, 4, 6, 4)
        abl.setSpacing(6)

        self.in_prof_cat = QComboBox()
        self.in_prof_cat.setEditable(True)
        self.in_prof_cat.addItems(["identity", "preferences", "environment", "projects", "habits", "general"])
        self.in_prof_cat.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        
        self.in_prof_key = QLineEdit(); self.in_prof_key.setPlaceholderText("Key (e.g. music_preference)")
        self.in_prof_val = QLineEdit(); self.in_prof_val.setPlaceholderText("Value (e.g. Cyberpunk Synthwave)")
        for inp in (self.in_prof_key, self.in_prof_val):
            inp.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_prof_source = QComboBox()
        self.in_prof_source.setEditable(True)
        self.in_prof_source.addItems(["manual_entry", "user_stated", "inferred", "chat_history", "observation"])
        self.in_prof_source.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_dim']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px;")

        btn_save = QPushButton("💾 SAVE ATTRIBUTE")
        btn_save.setStyleSheet(f"background: {C['neon_cyan']}33; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_save.clicked.connect(self._upsert_profile)

        abl.addWidget(self.in_prof_cat)
        abl.addWidget(self.in_prof_key, 1)
        abl.addWidget(self.in_prof_val, 1)
        abl.addWidget(self.in_prof_source, 1)
        abl.addWidget(btn_save)
        l.addWidget(add_bar)

        return w

    def _load_profile(self):
        details = self.mm.get_user_profile_details()
        self.table_profile.setRowCount(len(details))
        for r, item in enumerate(details):
            self.table_profile.setItem(r, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.table_profile.setItem(r, 1, QTableWidgetItem(str(item.get("category", ""))))
            self.table_profile.setItem(r, 2, QTableWidgetItem(str(item.get("key_name", ""))))
            self.table_profile.setItem(r, 3, QTableWidgetItem(str(item.get("value", ""))))
            self.table_profile.setItem(r, 4, QTableWidgetItem(str(item.get("source", ""))))
            self.table_profile.setItem(r, 5, QTableWidgetItem(str(item.get("updated_at", ""))))

    def _upsert_profile(self):
        cat = self.in_prof_cat.currentText().strip() or "general"
        k = self.in_prof_key.text().strip()
        v = self.in_prof_val.text().strip()
        src = self.in_prof_source.currentText().strip() or "manual_entry"
        if k and v:
            self.mm.set_user_attribute(k, v, category=cat, source=src)
            self.in_prof_key.clear()
            self.in_prof_val.clear()
            self._load_profile()

    def _delete_profile(self):
        row = self.table_profile.currentRow()
        if row >= 0:
            key_item = self.table_profile.item(row, 2)
            if key_item and key_item.text():
                self.mm.delete_user_attribute(key_item.text())
                self._load_profile()

    # --- Subtab 5: AI Identity Memory ---
    def _build_identity_subtab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        top = QHBoxLayout()
        self.identity_search = QLineEdit()
        self.identity_search.setPlaceholderText("🔍 Filter AI Identity memory by key, content, or domain...")
        self.identity_search.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 5px; font-family: {FONT_FAMILY}; font-size: 11px;")
        self.identity_search.textChanged.connect(self._filter_identity)
        top.addWidget(self.identity_search, 1)

        self.identity_domain_filter = QComboBox()
        self.identity_domain_filter.addItems(["ALL DOMAINS", "project", "goal", "diary", "thought", "fact", "preference", "general"])
        self.identity_domain_filter.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 4px;")
        self.identity_domain_filter.currentTextChanged.connect(self._filter_identity)
        top.addWidget(self.identity_domain_filter)

        self.btn_del_id = QPushButton("🗑 DELETE SELECTED")
        self.btn_del_id.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 5px 10px; font-family: {FONT_FAMILY}; font-size: 9px; font-weight: bold;")
        self.btn_del_id.clicked.connect(self._delete_identity)
        top.addWidget(self.btn_del_id)
        l.addLayout(top)

        self.table_identity = QTableWidget()
        self.table_identity.setColumnCount(6)
        self.table_identity.setHorizontalHeaderLabels(["ID", "Domain", "Key Name", "Content", "Source", "Created At"])
        self.table_identity.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_identity.horizontalHeader().setStretchLastSection(True)
        self.table_identity.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_identity.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_identity.setStyleSheet(table_stylesheet())
        l.addWidget(self.table_identity, 1)

        add_bar = QFrame()
        add_bar.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        abl = QHBoxLayout(add_bar)
        abl.setContentsMargins(6, 4, 6, 4)
        abl.setSpacing(6)

        self.in_id_domain = QComboBox()
        self.in_id_domain.setEditable(True)
        self.in_id_domain.addItems(["project", "goal", "diary", "thought", "fact", "preference", "general"])
        self.in_id_domain.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_id_key = QLineEdit()
        self.in_id_key.setPlaceholderText("Key (e.g. current_quest, art_interest)")
        self.in_id_key.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_id_content = QLineEdit()
        self.in_id_content.setPlaceholderText("Content / reflection details...")
        self.in_id_content.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        self.in_id_source = QComboBox()
        self.in_id_source.setEditable(True)
        self.in_id_source.addItems(["autonomous_exploration", "identity_monologue", "manual_entry", "self_reflection", "desktop_interaction"])
        self.in_id_source.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_dim']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        btn_add = QPushButton("➕ SAVE IDENTITY")
        btn_add.setStyleSheet(f"background: {C['neon_green']}33; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_add.clicked.connect(self._add_identity)

        abl.addWidget(self.in_id_domain, 1)
        abl.addWidget(self.in_id_key, 1)
        abl.addWidget(self.in_id_content, 2)
        abl.addWidget(self.in_id_source, 1)
        abl.addWidget(btn_add)
        l.addWidget(add_bar)

        return w

    def _load_identity(self):
        entries = self.mm.get_all_identity_entries(limit=250)
        self._all_identity = entries
        self._populate_identity_table(entries)

    def _populate_identity_table(self, entries):
        self.table_identity.setRowCount(len(entries))
        for r, item in enumerate(entries):
            self.table_identity.setItem(r, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.table_identity.setItem(r, 1, QTableWidgetItem(str(item.get("domain", ""))))
            self.table_identity.setItem(r, 2, QTableWidgetItem(str(item.get("key_name", ""))))
            self.table_identity.setItem(r, 3, QTableWidgetItem(str(item.get("content", ""))))
            self.table_identity.setItem(r, 4, QTableWidgetItem(str(item.get("source", ""))))
            self.table_identity.setItem(r, 5, QTableWidgetItem(str(item.get("created_at", ""))))

    def _filter_identity(self):
        q = self.identity_search.text().strip().lower()
        dom = self.identity_domain_filter.currentText()
        entries = getattr(self, "_all_identity", [])
        if dom != "ALL DOMAINS":
            entries = [e for e in entries if str(e.get("domain", "")).lower() == dom.lower()]
        if q:
            entries = [
                e for e in entries
                if q in str(e.get("key_name", "")).lower()
                or q in str(e.get("content", "")).lower()
                or q in str(e.get("domain", "")).lower()
            ]
        self._populate_identity_table(entries)

    def _add_identity(self):
        dom = self.in_id_domain.currentText().strip() or "general"
        key = self.in_id_key.text().strip()
        cnt = self.in_id_content.text().strip()
        src = self.in_id_source.currentText().strip() or "manual_entry"
        if key and cnt:
            self.mm.save_identity_entry(domain=dom, key_name=key, content=cnt, source=src)
            self.in_id_key.clear()
            self.in_id_content.clear()
            self._load_identity()

    def _delete_identity(self):
        row = self.table_identity.currentRow()
        if row >= 0:
            id_item = self.table_identity.item(row, 0)
            if id_item and id_item.text().isdigit():
                self.mm.delete_identity_entry(int(id_item.text()))
                self._load_identity()


# =============================================================================
# 2. IMAGE STUDIO TAB
# =============================================================================
class StudioPipelineWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, studio_mgr, pipeline_func_name: str, kwargs: dict):
        super().__init__()
        self.studio_mgr = studio_mgr
        self.pipeline_func_name = pipeline_func_name
        self.kwargs = kwargs

    def run(self):
        try:
            def _cb(step, total, msg):
                self.progress.emit(step, total, msg)

            self.kwargs["progress_callback"] = _cb
            fn = getattr(self.studio_mgr, self.pipeline_func_name)
            res = fn(**self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

class ImageGenWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, studio_mgr, kwargs):
        super().__init__()
        self.studio_mgr = studio_mgr
        self.kwargs = kwargs

    def run(self):
        try:
            def _cb(step, total, msg):
                self.progress.emit(step, total, msg)

            self.kwargs["progress_callback"] = _cb
            res = self.studio_mgr.generate_image(**self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

class ImageUpscaleWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, studio_mgr, image_path, scale=4, model_name="ultrasharp-4x"):
        super().__init__()
        self.studio_mgr = studio_mgr
        self.image_path = image_path
        self.scale = scale
        self.model_name = model_name

    def run(self):
        try:
            def _cb(step, total, msg):
                self.progress.emit(step, total, msg)

            res = self.studio_mgr.upscale_image(
                image_path=self.image_path,
                scale=self.scale,
                model_name=self.model_name,
                progress_callback=_cb
            )
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class FullScreenImageViewer(QDialog):
    """Zero-distraction fullscreen image viewer with Single & Quad-View (2x2) FIFO scrolling pipeline."""
    def __init__(self, studio_tab, parent=None):
        super().__init__(parent)
        self.studio_tab = studio_tab
        self.setWindowTitle("Neural Studio Viewport - Fullscreen")
        self.setStyleSheet("background-color: #03060c;")
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        
        self.is_quad_view = False
        self.current_path = None
        self.quad_offset = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Top Overlay Control HUD
        hud = QHBoxLayout()
        hud.setContentsMargins(10, 4, 10, 4)
        
        self.lbl_hud_title = QLabel("FULLSCREEN VIEWPORT")
        self.lbl_hud_title.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        self.lbl_hud_title.setStyleSheet(f"color: {C['neon_cyan']}; background: transparent;")
        hud.addWidget(self.lbl_hud_title)
        hud.addStretch()

        self.btn_toggle_quad = QPushButton("⛶ QUAD VIEW (2x2)")
        self.btn_toggle_quad.setFixedSize(140, 26)
        self.btn_toggle_quad.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_toggle_quad.setStyleSheet(f"background: #09172e; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_toggle_quad.clicked.connect(self.toggle_quad_view)
        hud.addWidget(self.btn_toggle_quad)

        btn_close = QPushButton("✕ CLOSE (ESC)")
        btn_close.setFixedSize(100, 26)
        btn_close.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        btn_close.setStyleSheet(f"background: #1f0a14; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; border-radius: 4px;")
        btn_close.clicked.connect(self.close)
        hud.addWidget(btn_close)
        root.addLayout(hud)

        # Container Widget for views
        self.view_container = QWidget()
        self.view_layout = QVBoxLayout(self.view_container)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.view_container, 1)

        # 1. Single View Label
        self.single_label = QLabel()
        self.single_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.single_label.setStyleSheet("background-color: #03060c;")
        self.view_layout.addWidget(self.single_label)

        # 2. Quad View Widget (2x2 Grid)
        self.quad_widget = QWidget()
        self.quad_grid = QGridLayout(self.quad_widget)
        self.quad_grid.setContentsMargins(0, 0, 0, 0)
        self.quad_grid.setSpacing(6)

        self.quad_labels = []
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for i, (r, c) in enumerate(positions):
            lbl = ClickableLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"background-color: #050a14; border: 1px solid {C['border']}; border-radius: 6px;")
            lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            lbl.clicked.connect(lambda idx=i: self._on_quad_label_clicked(idx))
            self.quad_grid.addWidget(lbl, r, c)
            self.quad_labels.append(lbl)

        self.quad_widget.hide()
        self.view_layout.addWidget(self.quad_widget)

    def toggle_quad_view(self):
        self.is_quad_view = not self.is_quad_view
        if self.is_quad_view:
            self.single_label.hide()
            self.quad_widget.show()
            self.btn_toggle_quad.setText("▣ SINGLE VIEW")
            self.btn_toggle_quad.setStyleSheet(f"background: {C['neon_magenta']}33; color: {C['neon_magenta']}; border: 1px solid {C['neon_magenta']}; font-weight: bold; border-radius: 4px;")
            self.lbl_hud_title.setText("FULLSCREEN ◈ 4-SLOT QUAD SCROLL (Newest Top-Left)")
            self._render_quad()
        else:
            self.quad_widget.hide()
            self.single_label.show()
            self.btn_toggle_quad.setText("⛶ QUAD VIEW (2x2)")
            self.btn_toggle_quad.setStyleSheet(f"background: #09172e; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
            self.lbl_hud_title.setText("FULLSCREEN VIEWPORT")
            if self.current_path:
                self.update_image(self.current_path)

    def _render_quad(self):
        hist = self.studio_tab.image_history
        if not hist: return
        screen_size = QApplication.primaryScreen().size()
        half_w = (screen_size.width() - 30) // 2
        half_h = (screen_size.height() - 70) // 2

        for i in range(4):
            idx = self.quad_offset + i
            if idx < len(hist):
                p = hist[idx].get("image_path")
                if p and os.path.exists(p):
                    pix = QPixmap(p)
                    scaled = pix.scaled(half_w, half_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.quad_labels[i].setPixmap(scaled)
                    self.quad_labels[i].setToolTip(f"Slot {i+1}: {os.path.basename(p)} (Click to view single)")
                else:
                    self.quad_labels[i].clear()
                    self.quad_labels[i].setText("Slot Empty")
            else:
                self.quad_labels[i].clear()
                self.quad_labels[i].setText("Awaiting Generation")

    def _on_quad_label_clicked(self, slot_idx: int):
        hist = self.studio_tab.image_history
        idx = self.quad_offset + slot_idx
        if idx < len(hist):
            self.studio_tab._load_image_by_index(idx)
            self.toggle_quad_view()

    def update_image(self, img_path):
        self.current_path = img_path
        if self.is_quad_view:
            self.quad_offset = 0
            self._render_quad()
        else:
            if img_path and os.path.exists(img_path):
                pix = QPixmap(img_path)
                screen_size = QApplication.primaryScreen().size()
                scaled = pix.scaled(screen_size.width(), screen_size.height() - 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.single_label.setPixmap(scaled)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.close()
        elif event.key() in (Qt.Key.Key_Q, Qt.Key.Key_4):
            self.toggle_quad_view()
        elif event.key() == Qt.Key.Key_Left:
            if self.is_quad_view:
                if self.quad_offset + 1 < len(self.studio_tab.image_history):
                    self.quad_offset += 1
                    self._render_quad()
            else:
                self.studio_tab._prev_image()
        elif event.key() == Qt.Key.Key_Right:
            if self.is_quad_view:
                if self.quad_offset > 0:
                    self.quad_offset -= 1
                    self._render_quad()
            else:
                self.studio_tab._next_image()
        else:
            super().keyPressEvent(event)

class AgentStudioTab(QWidget):
    """AI-Driven Multimodal Studio Suite: Txt2Img, Img2Img, Txt2Vid, Img2Vid, Vid2Vid+Audio, and Autonomous Director."""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.sm = main_win.agent.studio_mgr if hasattr(main_win, 'agent') and main_win.agent else None
        self.active_pipeline = "txt2img"
        self.current_media_path = None
        self.current_img_path = None
        self.current_video_path = None
        self.current_media_type = "image"
        self.current_gen_id = None
        self.image_history = []
        self.current_idx = 0
        self.fullscreen_viewer = None

        # Connect agent hook for live generation updates
        if hasattr(self.main_win, 'agent') and self.main_win.agent:
            self.main_win.agent.on_image_generated = self.on_image_generated

        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.timeout.connect(self._next_image)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 1. Header Bar with telemetry & actions
        hdr = QHBoxLayout()
        title = QLabel("🎨 NEURAL MULTIMODAL STUDIO")
        title.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['neon_cyan']};")
        hdr.addWidget(title)

        self.lbl_pipeline_status = QLabel("Modal H100 / GPU Cluster ◈ Ready")
        self.lbl_pipeline_status.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        self.lbl_pipeline_status.setStyleSheet(f"color: {C['text_dim']}; background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 3px 8px;")
        hdr.addWidget(self.lbl_pipeline_status)
        hdr.addStretch()

        self.btn_toggle_controls = QPushButton("⚙ MANUAL CONTROLS")
        self.btn_toggle_controls.setFixedHeight(28)
        self.btn_toggle_controls.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_toggle_controls.setStyleSheet(f"background: {C['border']}; color: {C['text_bright']}; border-radius: 4px; padding: 0 10px;")
        self.btn_toggle_controls.clicked.connect(self._toggle_controls_drawer)
        hdr.addWidget(self.btn_toggle_controls)

        self.btn_open_folder = QPushButton("📁 OPEN OUTPUTS")
        self.btn_open_folder.setFixedHeight(28)
        self.btn_open_folder.setFont(QFont(FONT_FAMILY, 8))
        self.btn_open_folder.setStyleSheet(f"background: transparent; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 10px;")
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        hdr.addWidget(self.btn_open_folder)
        root.addLayout(hdr)

        # 2. Pipeline Switcher Segmented Pills
        pipeline_bar = QHBoxLayout()
        pipeline_bar.setSpacing(6)
        self.pipeline_buttons = {}
        pipeline_defs = [
            ("txt2img", "🖼 TXT2IMG"),
            ("img2img", "🎭 IMG2IMG"),
            ("txt2vid", "🎬 TXT2VID"),
            ("img2vid", "🎥 IMG2VID"),
            ("vid2audio", "🔊 VID2AUDIO"),
            ("vid2vid", "⚡ VID2VID+AUDIO"),
            ("director", "🤖 DIRECTOR"),
        ]
        for p_key, p_label in pipeline_defs:
            p_btn = QPushButton(p_label)
            p_btn.setFixedHeight(28)
            p_btn.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
            p_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            p_btn.clicked.connect(lambda _, k=p_key: self._set_pipeline(k))
            pipeline_bar.addWidget(p_btn)
            self.pipeline_buttons[p_key] = p_btn
        pipeline_bar.addStretch()
        root.addLayout(pipeline_bar)

        # 3. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"QProgressBar {{ background-color: {C['bg_deep']}; border: none; }} QProgressBar::chunk {{ background-color: {C['neon_cyan']}; }}")
        root.addWidget(self.progress_bar)

        # 4. Collapsible Manual Controls Drawer
        self.controls_drawer = QFrame()
        self.controls_drawer.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 8px;")
        cd_layout = QVBoxLayout(self.controls_drawer)
        cd_layout.setSpacing(6)

        # Row 1: Source Media Input (for img2img, img2vid, vid2audio, vid2vid, director)
        self.frame_source_media = QWidget()
        row_src = QHBoxLayout(self.frame_source_media)
        row_src.setContentsMargins(0, 0, 0, 0)
        row_src.setSpacing(6)
        lbl_src = QLabel("Source Media:")
        lbl_src.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        lbl_src.setStyleSheet(f"color: {C['neon_cyan']};")
        row_src.addWidget(lbl_src)

        self.txt_source_media = QLineEdit()
        self.txt_source_media.setPlaceholderText("Select or paste input image/video path...")
        self.txt_source_media.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; padding: 5px; border: 1px solid {C['border']}; border-radius: 4px;")
        row_src.addWidget(self.txt_source_media, 4)

        self.btn_browse_media = QPushButton("📂 BROWSE")
        self.btn_browse_media.setFixedHeight(26)
        self.btn_browse_media.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_browse_media.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 8px;")
        self.btn_browse_media.clicked.connect(self._browse_source_media)
        row_src.addWidget(self.btn_browse_media)

        self.btn_use_viewport = QPushButton("🎯 USE VIEWPORT")
        self.btn_use_viewport.setFixedHeight(26)
        self.btn_use_viewport.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_use_viewport.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_yellow']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 8px;")
        self.btn_use_viewport.clicked.connect(self._use_viewport_media)
        row_src.addWidget(self.btn_use_viewport)
        cd_layout.addWidget(self.frame_source_media)

        # Row 2: Prompt LineEdit, Refine Button, Generate Button
        row2 = QHBoxLayout()
        self.txt_prompt = QLineEdit()
        self.txt_prompt.setPlaceholderText("Enter creative prompt concept...")
        self.txt_prompt.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; padding: 6px; border: 1px solid {C['border']}; border-radius: 4px;")
        self.txt_prompt.returnPressed.connect(self._on_manual_generate)
        row2.addWidget(self.txt_prompt, 4)

        self.btn_refine = QPushButton("✨ AI REFINE")
        self.btn_refine.setToolTip("Preview heuristic RLHF prompt enhancements")
        self.btn_refine.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_yellow']}; font-weight: bold; border: 1px solid {C['border']}; border-radius: 4px; padding: 6px 10px;")
        self.btn_refine.clicked.connect(self._on_refine_clicked)
        row2.addWidget(self.btn_refine)

        self.btn_generate = QPushButton("🚀 GENERATE (TXT2IMG)")
        self.btn_generate.setStyleSheet(f"background: {C['neon_cyan']}; color: #000; font-weight: bold; border-radius: 4px; padding: 6px 14px;")
        self.btn_generate.clicked.connect(self._on_manual_generate)
        row2.addWidget(self.btn_generate, 1)
        cd_layout.addLayout(row2)

        # Row 3: Pipeline-Specific Parameter Panels
        self.panel_txt2img = QWidget()
        p1 = QHBoxLayout(self.panel_txt2img)
        p1.setContentsMargins(0, 0, 0, 0)
        p1.setSpacing(6)
        p1.addWidget(QLabel("Model:"))
        self.combo_model = QComboBox()
        for k, v in MODEL_CATALOG.items():
            self.combo_model.addItem(f"{v['name']} ({k})", k)
        p1.addWidget(self.combo_model, 2)
        p1.addWidget(QLabel("LoRA:"))
        self.combo_lora = QComboBox()
        for k, v in LORA_CATALOG.items():
            self.combo_lora.addItem(v, k)
        p1.addWidget(self.combo_lora, 2)
        p1.addWidget(QLabel("Scale:"))
        self.spin_lora_scale = QDoubleSpinBox()
        self.spin_lora_scale.setRange(0.0, 2.0)
        self.spin_lora_scale.setValue(0.8)
        self.spin_lora_scale.setSingleStep(0.05)
        p1.addWidget(self.spin_lora_scale, 1)
        p1.addWidget(QLabel("Preset:"))
        self.combo_preset = QComboBox()
        for pk, pv in STYLE_PRESETS.items():
            self.combo_preset.addItem(pv["name"], pk)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        p1.addWidget(self.combo_preset, 2)
        cd_layout.addWidget(self.panel_txt2img)

        self.panel_img2img = QWidget()
        p2 = QHBoxLayout(self.panel_img2img)
        p2.setContentsMargins(0, 0, 0, 0)
        p2.setSpacing(6)
        p2.addWidget(QLabel("Engine:"))
        self.combo_img2img_model = QComboBox()
        self.combo_img2img_model.addItem("Flux.1 Schnell (Fast & Coherent)", "flux")
        self.combo_img2img_model.addItem("Qwen-Image-Edit (Instruction Inpaint)", "qwen")
        self.combo_img2img_model.addItem("SDXL Inpainting", "sdxl")
        self.combo_img2img_model.addItem("SD 3.5 Large", "sd35")
        p2.addWidget(self.combo_img2img_model, 2)
        p2.addWidget(QLabel("Denoise Strength:"))
        self.spin_denoise = QDoubleSpinBox()
        self.spin_denoise.setRange(0.1, 0.95)
        self.spin_denoise.setValue(0.75)
        self.spin_denoise.setSingleStep(0.05)
        p2.addWidget(self.spin_denoise, 1)
        p2.addWidget(QLabel("Instruction (Qwen):"))
        self.txt_qwen_instr = QLineEdit()
        self.txt_qwen_instr.setPlaceholderText("e.g. replace coat with cybernetic armor...")
        self.txt_qwen_instr.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; padding: 4px; border: 1px solid {C['border']}; border-radius: 4px;")
        p2.addWidget(self.txt_qwen_instr, 2)
        cd_layout.addWidget(self.panel_img2img)

        self.panel_txt2vid = QWidget()
        p3 = QHBoxLayout(self.panel_txt2vid)
        p3.setContentsMargins(0, 0, 0, 0)
        p3.setSpacing(6)
        p3.addWidget(QLabel("Style Model:"))
        self.combo_txt2vid_model = QComboBox()
        self.combo_txt2vid_model.addItem("EpicRealism SDXL", "epic")
        self.combo_txt2vid_model.addItem("Juggernaut SDXL", "jugg")
        self.combo_txt2vid_model.addItem("CyberRealistic SDXL", "cyber")
        self.combo_txt2vid_model.addItem("Unholy Desire SDXL", "unholy")
        p3.addWidget(self.combo_txt2vid_model, 2)
        p3.addWidget(QLabel("Frames:"))
        self.combo_txt2vid_frames = QComboBox()
        self.combo_txt2vid_frames.addItem("16 Frames (Smooth)", 16)
        self.combo_txt2vid_frames.addItem("24 Frames (Extended)", 24)
        self.combo_txt2vid_frames.addItem("32 Frames (Maximum)", 32)
        p3.addWidget(self.combo_txt2vid_frames, 1)
        p3.addWidget(QLabel("FPS:"))
        self.combo_txt2vid_fps = QComboBox()
        self.combo_txt2vid_fps.addItem("8 FPS (Cinematic)", 8)
        self.combo_txt2vid_fps.addItem("16 FPS (Smooth)", 16)
        p3.addWidget(self.combo_txt2vid_fps, 1)
        cd_layout.addWidget(self.panel_txt2vid)

        self.panel_img2vid = QWidget()
        p4 = QHBoxLayout(self.panel_img2vid)
        p4.setContentsMargins(0, 0, 0, 0)
        p4.setSpacing(6)
        p4.addWidget(QLabel("Engine: Wan2.2 14B Lightning"))
        p4.addWidget(QLabel("Resolution:"))
        self.combo_img2vid_res = QComboBox()
        self.combo_img2vid_res.addItem("480p (Fast Cinematics)", "480p")
        self.combo_img2vid_res.addItem("720p (Crisp HD)", "720p")
        p4.addWidget(self.combo_img2vid_res, 1)
        p4.addWidget(QLabel("FPS:"))
        self.combo_img2vid_fps = QComboBox()
        self.combo_img2vid_fps.addItem("16 FPS (Standard)", 16)
        self.combo_img2vid_fps.addItem("24 FPS (Cinema)", 24)
        p4.addWidget(self.combo_img2vid_fps, 1)
        cd_layout.addWidget(self.panel_img2vid)

        self.panel_vid2audio = QWidget()
        p5 = QHBoxLayout(self.panel_vid2audio)
        p5.setContentsMargins(0, 0, 0, 0)
        p5.setSpacing(6)
        p5.addWidget(QLabel("Engine: MMAudio (44.1kHz Synchronized Foley)"))
        p5.addWidget(QLabel("Duration (s):"))
        self.spin_audio_duration = QDoubleSpinBox()
        self.spin_audio_duration.setRange(1.0, 30.0)
        self.spin_audio_duration.setValue(8.0)
        self.spin_audio_duration.setSingleStep(1.0)
        p5.addWidget(self.spin_audio_duration, 1)
        cd_layout.addWidget(self.panel_vid2audio)

        self.panel_vid2vid = QWidget()
        p6 = QHBoxLayout(self.panel_vid2vid)
        p6.setContentsMargins(0, 0, 0, 0)
        p6.setSpacing(6)
        p6.addWidget(QLabel("Style Preset:"))
        self.combo_vid2vid_preset = QComboBox()
        self.combo_vid2vid_preset.addItem("Cinematic Movie", "cinematic")
        self.combo_vid2vid_preset.addItem("Cyberpunk Neon", "cyberpunk")
        self.combo_vid2vid_preset.addItem("Anime Art", "anime_art")
        self.combo_vid2vid_preset.addItem("Dark Moody", "dark_moody")
        p6.addWidget(self.combo_vid2vid_preset, 2)
        self.chk_vid2vid_audio = QCheckBox("Generate Synchronized Foley Audio")
        self.chk_vid2vid_audio.setChecked(True)
        self.chk_vid2vid_audio.setStyleSheet(f"color: {C['neon_cyan']};")
        p6.addWidget(self.chk_vid2vid_audio, 2)
        cd_layout.addWidget(self.panel_vid2vid)

        self.panel_director = QWidget()
        p7 = QHBoxLayout(self.panel_director)
        p7.setContentsMargins(0, 0, 0, 0)
        lbl_dir_info = QLabel("🤖 Autonomous Creative Director automatically analyzes natural language, plans multi-stage synthesis (txt2img -> img2vid -> vid2audio), critiques, and delivers finished media.")
        lbl_dir_info.setStyleSheet(f"color: {C['neon_yellow']}; font-size: 8pt;")
        p7.addWidget(lbl_dir_info)
        cd_layout.addWidget(self.panel_director)

        # Advanced Row (Neg Prompt, Steps, CFG, Seed)
        self.row_advanced = QHBoxLayout()
        self.row_advanced.addWidget(QLabel("Neg:"))
        self.txt_neg_prompt = QLineEdit()
        self.txt_neg_prompt.setText(DEFAULT_NEGATIVE_PROMPT)
        self.txt_neg_prompt.setToolTip("Negative prompt filters (undesired visual artifacts)")
        self.txt_neg_prompt.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_dim']}; padding: 4px; border: 1px solid {C['border']}; border-radius: 4px;")
        self.row_advanced.addWidget(self.txt_neg_prompt, 3)

        self.row_advanced.addWidget(QLabel("Steps:"))
        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(10, 60)
        self.spin_steps.setValue(25)
        self.row_advanced.addWidget(self.spin_steps, 1)

        self.row_advanced.addWidget(QLabel("CFG:"))
        self.spin_guidance = QDoubleSpinBox()
        self.spin_guidance.setRange(1.0, 20.0)
        self.spin_guidance.setValue(7.0)
        self.spin_guidance.setSingleStep(0.5)
        self.row_advanced.addWidget(self.spin_guidance, 1)

        self.row_advanced.addWidget(QLabel("Seed:"))
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(-1, 999999999)
        self.spin_seed.setValue(-1)
        self.spin_seed.setToolTip("-1 for random seed")
        self.row_advanced.addWidget(self.spin_seed, 1)

        btn_rand_seed = QPushButton("🎲")
        btn_rand_seed.setFixedSize(28, 24)
        btn_rand_seed.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
        btn_rand_seed.clicked.connect(self._randomize_seed)
        self.row_advanced.addWidget(btn_rand_seed)
        cd_layout.addLayout(self.row_advanced)

        # Refined Preview Label (Collapsible)
        self.lbl_refine_preview = QLabel()
        self.lbl_refine_preview.setWordWrap(True)
        self.lbl_refine_preview.setStyleSheet(f"color: {C['neon_yellow']}; background: {C['bg_deep']}; border: 1px dashed {C['border_bright']}; border-radius: 4px; padding: 4px; font-size: 8pt;")
        self.lbl_refine_preview.hide()
        cd_layout.addWidget(self.lbl_refine_preview)

        self.controls_drawer.hide()
        root.addWidget(self.controls_drawer)

        # 5. Viewport Navigation Toolbar
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(6)

        self.lbl_image_title = QLabel("VIEWPORT ◈ NO MEDIA LOADED")
        self.lbl_image_title.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        self.lbl_image_title.setStyleSheet(f"color: {C['neon_cyan']};")
        nav_bar.addWidget(self.lbl_image_title)
        nav_bar.addStretch()

        self.btn_prev = QPushButton("◀ PREV")
        self.btn_prev.setFixedSize(65, 26)
        self.btn_prev.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_prev.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_prev.clicked.connect(self._prev_image)
        nav_bar.addWidget(self.btn_prev)

        self.lbl_counter = QLabel("[ 0 / 0 ]")
        self.lbl_counter.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.lbl_counter.setStyleSheet(f"color: {C['neon_yellow']}; padding: 0 4px;")
        nav_bar.addWidget(self.lbl_counter)

        self.btn_next = QPushButton("NEXT ▶")
        self.btn_next.setFixedSize(65, 26)
        self.btn_next.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_next.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_next.clicked.connect(self._next_image)
        nav_bar.addWidget(self.btn_next)

        self.btn_slideshow = QPushButton("▶ PLAY")
        self.btn_slideshow.setFixedSize(65, 26)
        self.btn_slideshow.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_slideshow.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_slideshow.clicked.connect(self._toggle_slideshow)
        nav_bar.addWidget(self.btn_slideshow)

        # 1-Click Action Buttons for Active Media
        self.btn_action_animate = QPushButton("🎬 ANIMATE (I2V)")
        self.btn_action_animate.setFixedHeight(26)
        self.btn_action_animate.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_action_animate.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; border-radius: 4px; padding: 0 8px;")
        self.btn_action_animate.setToolTip("Transform this still image into an 81-frame video via Wan2.2 14B")
        self.btn_action_animate.clicked.connect(self._on_1click_animate)
        nav_bar.addWidget(self.btn_action_animate)

        self.btn_action_remix = QPushButton("🎭 REMIX (I2I)")
        self.btn_action_remix.setFixedHeight(26)
        self.btn_action_remix.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_action_remix.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; border-radius: 4px; padding: 0 8px;")
        self.btn_action_remix.setToolTip("Restyle or inpaint this image via Flux.1 / Qwen-Image-Edit")
        self.btn_action_remix.clicked.connect(self._on_1click_remix)
        nav_bar.addWidget(self.btn_action_remix)

        self.btn_action_audio = QPushButton("🔊 ADD AUDIO (V2A)")
        self.btn_action_audio.setFixedHeight(26)
        self.btn_action_audio.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_action_audio.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_yellow']}; border: 1px solid {C['neon_yellow']}; border-radius: 4px; padding: 0 8px;")
        self.btn_action_audio.setToolTip("Synthesize synchronized 44.1kHz Foley soundtrack for this video via MMAudio")
        self.btn_action_audio.clicked.connect(self._on_1click_audio)
        nav_bar.addWidget(self.btn_action_audio)

        self.btn_action_v2v = QPushButton("⚡ RESTYLE (V2V)")
        self.btn_action_v2v.setFixedHeight(26)
        self.btn_action_v2v.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_action_v2v.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_purple']}; border: 1px solid {C['neon_purple']}; border-radius: 4px; padding: 0 8px;")
        self.btn_action_v2v.setToolTip("Full Vid2Vid style transformation with Foley accompaniment")
        self.btn_action_v2v.clicked.connect(self._on_1click_v2v)
        nav_bar.addWidget(self.btn_action_v2v)

        self.btn_play_pause = QPushButton("⏯ PLAY/PAUSE")
        self.btn_play_pause.setFixedHeight(26)
        self.btn_play_pause.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_play_pause.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 8px;")
        self.btn_play_pause.clicked.connect(self._on_play_pause_video)
        nav_bar.addWidget(self.btn_play_pause)

        self.btn_upscale = QPushButton("⚡ UPSCALE")
        self.btn_upscale.setFixedSize(85, 26)
        self.btn_upscale.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_upscale.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_yellow']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_upscale.setToolTip("Neural Super-Resolution (4x UltraSharp / Modal A10G)")
        self.btn_upscale.clicked.connect(self._on_manual_upscale)
        nav_bar.addWidget(self.btn_upscale)

        self.btn_copy_prompt = QPushButton("📋 COPY")
        self.btn_copy_prompt.setFixedSize(65, 26)
        self.btn_copy_prompt.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_copy_prompt.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_copy_prompt.setToolTip("Copy active prompt to clipboard and editor")
        self.btn_copy_prompt.clicked.connect(self._copy_current_prompt)
        nav_bar.addWidget(self.btn_copy_prompt)

        self.btn_save = QPushButton("💾 SAVE")
        self.btn_save.setFixedSize(65, 26)
        self.btn_save.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_save.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_green']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_save.clicked.connect(self._save_current_media)
        nav_bar.addWidget(self.btn_save)

        self.btn_delete = QPushButton("🗑 DEL")
        self.btn_delete.setFixedSize(55, 26)
        self.btn_delete.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_delete.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_red']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_delete.setToolTip("Delete this generation from history and disk")
        self.btn_delete.clicked.connect(self._delete_current_media)
        nav_bar.addWidget(self.btn_delete)

        self.btn_fullscreen = QPushButton("⛶ FULLSCREEN")
        self.btn_fullscreen.setFixedSize(95, 26)
        self.btn_fullscreen.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_fullscreen.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_purple']}; border: 1px solid {C['border']}; border-radius: 4px;")
        self.btn_fullscreen.clicked.connect(self._open_fullscreen)
        nav_bar.addWidget(self.btn_fullscreen)
        root.addLayout(nav_bar)

        # 6. Primary Viewport Frame with Dual Image/Video Stack
        vp_frame = QFrame()
        vp_frame.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 6px;")
        vpl = QVBoxLayout(vp_frame)
        vpl.setContentsMargins(4, 4, 4, 4)

        self.vp_stack = QStackedLayout()

        # Viewport 0: Image Viewer
        self.img_viewport = ClickableLabel()
        self.img_viewport.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_viewport.setText("Awaiting multimodal generation... Click to view full screen.")
        self.img_viewport.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.img_viewport.setToolTip("Click image to view in Fullscreen mode (Use Left/Right arrows to navigate)")
        self.img_viewport.setStyleSheet(f"color: {C['text_dim']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        self.img_viewport.clicked.connect(self._open_fullscreen)
        self.vp_stack.addWidget(self.img_viewport)

        # Viewport 1: Video Player
        if QMediaPlayer and QVideoWidget:
            self.media_player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.media_player.setAudioOutput(self.audio_output)
            self.audio_output.setVolume(0.85)
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background: #000; border-radius: 4px;")
            self.media_player.setVideoOutput(self.video_widget)
            try:
                self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:
                pass
            self.vp_stack.addWidget(self.video_widget)
        else:
            self.media_player = None
            self.audio_output = None
            self.video_widget = None

        vpl.addLayout(self.vp_stack)
        root.addWidget(vp_frame, 1)

        # Prompt & Metadata Snippet Line
        self.lbl_prompt_display = QLabel("No prompt details loaded.")
        self.lbl_prompt_display.setStyleSheet(f"color: {C['text_dim']}; background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 3px; padding: 2px 6px; font-size: 8pt;")
        self.lbl_prompt_display.setWordWrap(True)
        root.addWidget(self.lbl_prompt_display)

        # 7. Thumbnail Filmstrip (Recent Outputs / Batch Carousel)
        filmstrip_label = QLabel("RECENT GENERATIONS & BATCH CAROUSEL")
        filmstrip_label.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        filmstrip_label.setStyleSheet(f"color: {C['text_dim']}; margin-top: 2px;")
        root.addWidget(filmstrip_label)

        self.filmstrip_scroll = QScrollArea()
        self.filmstrip_scroll.setFixedHeight(76)
        self.filmstrip_scroll.setWidgetResizable(True)
        self.filmstrip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.filmstrip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.filmstrip_scroll.setStyleSheet(f"background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 4px;")

        self.filmstrip_widget = QWidget()
        self.filmstrip_layout = QHBoxLayout(self.filmstrip_widget)
        self.filmstrip_layout.setContentsMargins(4, 4, 4, 4)
        self.filmstrip_layout.setSpacing(6)
        self.filmstrip_layout.addStretch()
        self.filmstrip_scroll.setWidget(self.filmstrip_widget)
        root.addWidget(self.filmstrip_scroll)

        # 8. AI Visual Critique & Autonomous RLHF Learning Card
        crit_card = QFrame()
        crit_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 6px;")
        ccl = QVBoxLayout(crit_card)
        ccl.setContentsMargins(6, 6, 6, 6)
        ccl.setSpacing(4)

        crit_header = QHBoxLayout()
        lbl_crit_title = QLabel("🤖 AI VISUAL & ACOUSTIC CRITIQUE ◈ RLHF LEARNING")
        lbl_crit_title.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        lbl_crit_title.setStyleSheet(f"color: {C['neon_cyan']};")
        crit_header.addWidget(lbl_crit_title)
        crit_header.addStretch()

        self.lbl_rating_display = QLabel("[UNRATED]")
        self.lbl_rating_display.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.lbl_rating_display.setStyleSheet(f"color: {C['text_dim']};")
        crit_header.addWidget(self.lbl_rating_display)
        ccl.addLayout(crit_header)

        self.lbl_critique_text = QLabel("Visual and acoustic critique is performed automatically upon generation completion.")
        self.lbl_critique_text.setWordWrap(True)
        self.lbl_critique_text.setStyleSheet(f"color: {C['text_bright']}; font-family: {FONT_FAMILY}; font-size: 9.5pt;")
        ccl.addWidget(self.lbl_critique_text)

        # RLHF Feedback & Tag Controls
        feedback_row = QHBoxLayout()
        feedback_row.setSpacing(6)

        self.btn_rate_pos = QPushButton("👍 FAVORITE (+1)")
        self.btn_rate_pos.setFixedHeight(26)
        self.btn_rate_pos.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_rate_pos.setStyleSheet(f"background: #092e1a; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; border-radius: 4px; padding: 0 8px;")
        self.btn_rate_pos.clicked.connect(lambda: self._on_rate_clicked(1))
        feedback_row.addWidget(self.btn_rate_pos)

        self.btn_rate_neg = QPushButton("👎 CRITIQUE (-1)")
        self.btn_rate_neg.setFixedHeight(26)
        self.btn_rate_neg.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_rate_neg.setStyleSheet(f"background: #2e0915; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; border-radius: 4px; padding: 0 8px;")
        self.btn_rate_neg.clicked.connect(lambda: self._on_rate_clicked(-1))
        feedback_row.addWidget(self.btn_rate_neg)

        # Quick Feedback Tag Buttons (Checkable)
        feedback_row.addWidget(QLabel("Tags:"))
        self.tag_buttons = {}
        for tag in ["Lighting", "Face", "Motion", "Audio", "Hands", "Skin"]:
            tbtn = QPushButton(tag)
            tbtn.setCheckable(True)
            tbtn.setFixedHeight(24)
            tbtn.setFont(QFont(FONT_FAMILY, 7, QFont.Weight.Bold))
            tbtn.setStyleSheet(f"QPushButton {{ background: {C['bg_deep']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px; padding: 0 5px; }} QPushButton:checked {{ background: {C['neon_cyan']}33; color: {C['neon_cyan']}; border-color: {C['neon_cyan']}; }}")
            feedback_row.addWidget(tbtn)
            self.tag_buttons[tag.lower()] = tbtn

        self.lbl_feedback_msg = QLabel("")
        self.lbl_feedback_msg.setFont(QFont(FONT_FAMILY, 7))
        self.lbl_feedback_msg.setStyleSheet(f"color: {C['neon_yellow']};")
        feedback_row.addWidget(self.lbl_feedback_msg)
        feedback_row.addStretch()

        ccl.addLayout(feedback_row)
        root.addWidget(crit_card)

        # Initialize pipeline view
        self._set_pipeline("txt2img")
        self._refresh_history()

    def _set_pipeline(self, pipeline: str):
        """Switch active multimodal pipeline and adjust controls drawer."""
        self.active_pipeline = pipeline

        # Update pill styling
        for p_key, btn in self.pipeline_buttons.items():
            if p_key == pipeline:
                btn.setStyleSheet(f"background: {C['neon_cyan']}; color: #000; font-weight: bold; border-radius: 4px; padding: 0 10px;")
            else:
                btn.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 0 10px;")

        # Toggle parameter panels
        self.panel_txt2img.setVisible(pipeline == "txt2img")
        self.panel_img2img.setVisible(pipeline == "img2img")
        self.panel_txt2vid.setVisible(pipeline == "txt2vid")
        self.panel_img2vid.setVisible(pipeline == "img2vid")
        self.panel_vid2audio.setVisible(pipeline == "vid2audio")
        self.panel_vid2vid.setVisible(pipeline == "vid2vid")
        self.panel_director.setVisible(pipeline == "director")

        # Source media row visibility
        needs_src = pipeline in ("img2img", "img2vid", "vid2audio", "vid2vid", "director")
        self.frame_source_media.setVisible(needs_src)

        # Advanced row visibility
        self.row_advanced.itemAt(0).widget().setVisible(pipeline in ("txt2img", "img2img", "txt2vid"))
        self.txt_neg_prompt.setVisible(pipeline in ("txt2img", "img2img", "txt2vid"))

        # Update generate button label and placeholder
        labels = {
            "txt2img": ("🚀 GENERATE IMAGE", "Enter prompt concept (e.g. cybernetic hacker in neon alley, volumetric light)..."),
            "img2img": ("🎭 TRANSFORM IMAGE", "Restyle prompt (e.g. anime cyberpunk style, watercolor portrait)..."),
            "txt2vid": ("🎬 GENERATE VIDEO", "Motion prompt (e.g. neon rain falling on asphalt, camera slowly panning)..."),
            "img2vid": ("🎥 ANIMATE IMAGE", "Motion guidance (e.g. gentle camera push, dynamic hair flowing)..."),
            "vid2audio": ("🔊 SYNTHESIZE AUDIO", "Foley description (e.g. heavy footsteps in puddle, neon hum, thunder)..."),
            "vid2vid": ("⚡ RESTYLE VIDEO", "Style prompt (e.g. dark cyberpunk anime style)..."),
            "director": ("🤖 DIRECT MASTER CREATION", "Creative directive (e.g. Create a cinematic anime video of Josh running in the rain with Foley audio)..."),
        }
        btn_text, placeholder = labels.get(pipeline, ("🚀 EXECUTE", "Enter prompt..."))
        self.btn_generate.setText(btn_text)
        self.txt_prompt.setPlaceholderText(placeholder)
        self.lbl_pipeline_status.setText(f"Pipeline: {pipeline.upper()} ◈ Ready")

    def _toggle_controls_drawer(self):
        if self.controls_drawer.isVisible():
            self.controls_drawer.hide()
            self.btn_toggle_controls.setText("⚙ MANUAL CONTROLS")
            self.btn_toggle_controls.setStyleSheet(f"background: {C['border']}; color: {C['text_bright']}; border-radius: 4px; padding: 0 10px;")
        else:
            self.controls_drawer.show()
            self.btn_toggle_controls.setText("✕ HIDE CONTROLS")
            self.btn_toggle_controls.setStyleSheet(f"background: {C['neon_cyan']}; color: #000; font-weight: bold; border-radius: 4px; padding: 0 10px;")

    def _open_output_folder(self):
        folder = ROOT_DIR / "history"
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
        import subprocess
        subprocess.Popen(f'explorer "{folder}"', shell=True)

    def _browse_source_media(self):
        if self.active_pipeline in ("vid2audio", "vid2vid"):
            filt = "Videos (*.mp4 *.mov *.avi *.mkv)"
        elif self.active_pipeline in ("img2img", "img2vid"):
            filt = "Images (*.png *.jpg *.jpeg *.webp)"
        else:
            filt = "Media Files (*.png *.jpg *.jpeg *.webp *.mp4 *.mov)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Source Media", str(ROOT_DIR / "history"), filt)
        if file_path:
            self.txt_source_media.setText(file_path)

    def _use_viewport_media(self):
        target = self.current_video_path if (self.active_pipeline in ("vid2audio", "vid2vid") and self.current_video_path) else self.current_media_path
        if not target and self.current_img_path:
            target = self.current_img_path
        if target:
            self.txt_source_media.setText(target)
            self.lbl_pipeline_status.setText(f"Loaded from viewport: {os.path.basename(target)}")

    def _on_1click_animate(self):
        """1-Click: Animate active viewport image into video (I2V)."""
        self._set_pipeline("img2vid")
        if self.current_img_path:
            self.txt_source_media.setText(self.current_img_path)
        if not self.controls_drawer.isVisible():
            self._toggle_controls_drawer()
        self.txt_prompt.setFocus()
        if not self.txt_prompt.text():
            self.txt_prompt.setText("cinematic camera motion, smooth subtle movement")

    def _on_1click_remix(self):
        """1-Click: Remix/Restyle active viewport image (I2I)."""
        self._set_pipeline("img2img")
        if self.current_img_path:
            self.txt_source_media.setText(self.current_img_path)
        if not self.controls_drawer.isVisible():
            self._toggle_controls_drawer()
        self.txt_prompt.setFocus()

    def _on_1click_audio(self):
        """1-Click: Add synchronized Foley soundtrack to active video (V2A)."""
        self._set_pipeline("vid2audio")
        target = self.current_video_path or self.current_media_path
        if target:
            self.txt_source_media.setText(target)
        if not self.controls_drawer.isVisible():
            self._toggle_controls_drawer()
        self.txt_prompt.setFocus()
        if not self.txt_prompt.text():
            self.txt_prompt.setText("cinematic synchronized ambient Foley, high fidelity sound effects")

    def _on_1click_v2v(self):
        """1-Click: Restyle active video (V2V)."""
        self._set_pipeline("vid2vid")
        target = self.current_video_path or self.current_media_path
        if target:
            self.txt_source_media.setText(target)
        if not self.controls_drawer.isVisible():
            self._toggle_controls_drawer()
        self.txt_prompt.setFocus()

    def _on_play_pause_video(self):
        if not self.media_player: return
        try:
            from PyQt6.QtMultimedia import QMediaPlayer
            if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.media_player.pause()
                self.btn_play_pause.setText("▶ PLAY")
            else:
                self.media_player.play()
                self.btn_play_pause.setText("⏸ PAUSE")
        except Exception:
            pass

    def _on_preset_changed(self, idx: int):
        pk = self.combo_preset.currentData() or "none"
        if pk in STYLE_PRESETS and pk != "none":
            suffix = STYLE_PRESETS[pk]["suffix"]
            cur = self.txt_prompt.text().strip()
            if cur and suffix not in cur:
                self.txt_prompt.setText(f"{cur}, {suffix}")
            elif not cur:
                self.txt_prompt.setText(suffix)

    def _randomize_seed(self):
        import random
        new_seed = random.randint(100000, 999999999)
        self.spin_seed.setValue(new_seed)

    def _on_refine_clicked(self):
        prompt = self.txt_prompt.text().strip()
        if not prompt or not self.sm: return
        m = self.combo_model.currentData() or "jugg"
        refined_p, refined_neg = self.sm.refine_prompt(prompt, m)
        self.lbl_refine_preview.setText(f"<b>Refined Prompt Preview:</b><br>{refined_p}<br><br><b>Learned Negatives:</b><br>{refined_neg[:160]}...")
        self.lbl_refine_preview.show()

    def _copy_current_prompt(self):
        if not self.image_history or self.current_idx >= len(self.image_history):
            return
        data = self.image_history[self.current_idx]
        p = data.get("prompt") or ""
        if p:
            clipboard = QApplication.clipboard()
            clipboard.setText(p)
            self.txt_prompt.setText(p)
            self.lbl_pipeline_status.setText("Prompt copied to clipboard & editor!")

    def _delete_current_media(self):
        if not self.current_gen_id or not self.sm:
            return
        ok = self.sm.delete_generation(self.current_gen_id)
        if ok:
            self.lbl_pipeline_status.setText("Generation deleted from history.")
            self._refresh_history()
            if self.image_history:
                self._load_media_by_index(min(self.current_idx, len(self.image_history) - 1))
            else:
                if self.media_player: self.media_player.stop()
                self.vp_stack.setCurrentWidget(self.img_viewport)
                self.img_viewport.clear()
                self.img_viewport.setText("Awaiting generation...")
                self.lbl_image_title.setText("VIEWPORT ◈ NO MEDIA LOADED")
                self.lbl_counter.setText("[ 0 / 0 ]")

    def _delete_current_image(self):
        self._delete_current_media()

    def _on_rate_clicked(self, rating: int):
        if not self.current_gen_id or not self.sm:
            return
        active_tags = [tag for tag, btn in self.tag_buttons.items() if btn.isChecked()]
        tags_str = ", ".join(active_tags)
        user_comment = "Favorite media" if rating > 0 else "Media defect reported"
        ok = self.sm.record_feedback(
            generation_id=self.current_gen_id,
            rating=rating,
            feedback_tags=tags_str,
            user_feedback=user_comment
        )
        if ok:
            if rating > 0:
                self.lbl_rating_display.setText("[⭐ FAVORITE]")
                self.lbl_rating_display.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold;")
                self.lbl_feedback_msg.setText("Reinforced positive weights (+0.3)")
            else:
                self.lbl_rating_display.setText("[⚠️ FLAGGED DEFECT]")
                self.lbl_rating_display.setStyleSheet(f"color: {C['neon_red']}; font-weight: bold;")
                self.lbl_feedback_msg.setText("Strengthened negative filter (+0.5)")
            self._refresh_history()

    def _refresh_history(self):
        if not self.sm: return
        self.image_history = self.sm.get_history(limit=50)
        self._refresh_filmstrip()
        if self.image_history:
            self._load_media_by_index(0)

    def _refresh_filmstrip(self):
        while self.filmstrip_layout.count() > 1:
            item = self.filmstrip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, item in enumerate(self.image_history[:30]):
            thumb_p = item.get("thumbnail_path") or item.get("image_path")
            is_vid = bool(item.get("video_path") or item.get("media_type") == "video")
            if thumb_p and os.path.exists(thumb_p):
                btn = QPushButton()
                btn.setFixedSize(56, 56)
                pix = QPixmap(thumb_p).scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(54, 54))
                if is_vid:
                    btn.setText("🎬")
                    btn.setToolTip(f"[VIDEO - {item.get('pipeline_type', 'vid').upper()}] Click to play in viewport")
                    btn.setStyleSheet(f"border: 1px solid {C['neon_cyan']}; border-radius: 4px; background: {C['bg_deep']}; color: {C['neon_yellow']}; font-weight: bold; text-align: bottom right;")
                else:
                    btn.setToolTip(f"[IMAGE - {item.get('pipeline_type', 'img').upper()}] Click to view in viewport")
                    btn.setStyleSheet(f"border: 1px solid {C['border']}; border-radius: 4px; background: {C['bg_deep']};")
                btn.clicked.connect(lambda _, i=idx: self._load_media_by_index(i))
                self.filmstrip_layout.insertWidget(idx, btn)

    def _load_media_by_index(self, idx: int):
        if not self.image_history or idx < 0 or idx >= len(self.image_history):
            return
        self.current_idx = idx
        data = self.image_history[idx]
        self.current_gen_id = data.get("id")

        img_p = data.get("image_path")
        vid_p = data.get("video_path")
        is_video = bool(vid_p and os.path.exists(vid_p))

        self.current_img_path = img_p
        self.current_video_path = vid_p
        self.current_media_path = vid_p if is_video else img_p
        self.current_media_type = "video" if is_video else "image"

        pipeline = (data.get("pipeline_type") or ("video" if is_video else "image")).upper()
        rating = data.get("rating", 0)

        # Toggle dynamic action buttons based on media type
        self.btn_action_animate.setVisible(not is_video)
        self.btn_action_remix.setVisible(not is_video)
        self.btn_upscale.setVisible(not is_video)
        self.btn_action_audio.setVisible(is_video)
        self.btn_action_v2v.setVisible(is_video)
        self.btn_play_pause.setVisible(is_video)

        if is_video and self.video_widget and self.media_player:
            # Play in Video Viewport
            self.vp_stack.setCurrentWidget(self.video_widget)
            self.media_player.setSource(QUrl.fromLocalFile(vid_p))
            self.media_player.play()
            self.btn_play_pause.setText("⏸ PAUSE")

            basename = os.path.basename(vid_p)
            dur = data.get("duration", "--")
            fps = data.get("fps", 16)
            self.lbl_image_title.setText(f"VIEWPORT ◈ {basename.upper()} ({pipeline} | {dur}s @ {fps}fps)")
        else:
            # Render in Image Viewport
            if self.media_player:
                self.media_player.stop()
            self.vp_stack.setCurrentWidget(self.img_viewport)

            if img_p and os.path.exists(img_p):
                pix = QPixmap(img_p)
                scaled = pix.scaled(self.img_viewport.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.img_viewport.setPixmap(scaled)

                basename = os.path.basename(img_p)
                dim = data.get("dimensions", "--")
                model = data.get("model_name", "SDXL")
                seed = data.get("seed", -1)
                self.lbl_image_title.setText(f"VIEWPORT ◈ {basename.upper()} ({pipeline} | {model.upper()} | {dim} | SEED: {seed})")

        self.lbl_counter.setText(f"[ {self.current_idx + 1} / {len(self.image_history)} ]")
        self.lbl_critique_text.setText(data.get("ai_critique") or "No critique recorded.")
        self.lbl_prompt_display.setText(f"[{pipeline}] PROMPT: {data.get('prompt', 'N/A')}")

        if rating > 0:
            self.lbl_rating_display.setText("[⭐ FAVORITE]")
            self.lbl_rating_display.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold;")
        elif rating < 0:
            self.lbl_rating_display.setText("[⚠️ FLAGGED DEFECT]")
            self.lbl_rating_display.setStyleSheet(f"color: {C['neon_red']}; font-weight: bold;")
        else:
            self.lbl_rating_display.setText("[UNRATED]")
            self.lbl_rating_display.setStyleSheet(f"color: {C['text_dim']};")

        self.lbl_feedback_msg.setText("")

        if self.fullscreen_viewer and self.fullscreen_viewer.isVisible() and img_p:
            self.fullscreen_viewer.update_image(img_p)

    def _load_image_by_index(self, idx: int):
        self._load_media_by_index(idx)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_media_type == "image" and self.current_img_path and os.path.exists(self.current_img_path):
            pix = QPixmap(self.current_img_path)
            scaled = pix.scaled(self.img_viewport.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.img_viewport.setPixmap(scaled)

    def _next_image(self):
        if not self.image_history: return
        nxt = (self.current_idx + 1) % len(self.image_history)
        self._load_media_by_index(nxt)

    def _prev_image(self):
        if not self.image_history: return
        prv = (self.current_idx - 1 + len(self.image_history)) % len(self.image_history)
        self._load_media_by_index(prv)

    def _toggle_slideshow(self):
        if self._slideshow_timer.isActive():
            self._slideshow_timer.stop()
            self.btn_slideshow.setText("▶ PLAY")
            self.btn_slideshow.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; border-radius: 4px;")
        else:
            self._slideshow_timer.start(3500)
            self.btn_slideshow.setText("⏸ PAUSE")
            self.btn_slideshow.setStyleSheet(f"background: {C['neon_cyan']}; color: #000; font-weight: bold; border-radius: 4px;")

    def _save_current_media(self):
        target = self.current_video_path if (self.current_media_type == "video" and self.current_video_path) else self.current_img_path
        if not target or not os.path.exists(target):
            QMessageBox.warning(self, "No Media", "No media is currently displayed to save.")
            return
        ext = os.path.splitext(target)[1].lower()
        filt = f"Media File (*{ext})"
        dest, _ = QFileDialog.getSaveFileName(self, "Save Output", os.path.basename(target), filt)
        if dest:
            import shutil
            shutil.copy2(target, dest)
            self.lbl_pipeline_status.setText(f"Saved to: {os.path.basename(dest)}")

    def _save_current_image(self):
        self._save_current_media()

    def _open_fullscreen(self):
        if not self.current_img_path or not os.path.exists(self.current_img_path):
            return
        if not self.fullscreen_viewer:
            self.fullscreen_viewer = FullScreenImageViewer(self, self)
        self.fullscreen_viewer.update_image(self.current_img_path)
        self.fullscreen_viewer.showFullScreen()

    def on_image_generated(self, media_path: str, gen_res: dict):
        """Called automatically by AlphaAgent upon generation completion."""
        self.lbl_pipeline_status.setText(f"New creation received: {os.path.basename(media_path)}")
        self._refresh_history()
        self._load_media_by_index(0)

    def _on_manual_generate(self):
        prompt = self.txt_prompt.text().strip()
        if not prompt or not self.sm: return
        self.lbl_pipeline_status.setText(f"Executing {self.active_pipeline.upper()} on Modal cluster...")
        self.btn_generate.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)

        pipe = self.active_pipeline
        kwargs = {}
        target_method = "generate_image"

        if pipe == "txt2img":
            target_method = "generate_image"
            kwargs = {
                "prompt": prompt,
                "model_name": self.combo_model.currentData() or "jugg",
                "negative_prompt": self.txt_neg_prompt.text().strip(),
                "lora": self.combo_lora.currentData() or "none",
                "steps": self.spin_steps.value(),
                "guidance": self.spin_guidance.value(),
                "seed": self.spin_seed.value(),
                "style_preset": self.combo_preset.currentData() or "none"
            }
        elif pipe == "img2img":
            target_method = "generate_img2img"
            src = self.txt_source_media.text().strip() or self.current_img_path
            kwargs = {
                "image_source": src,
                "prompt": prompt,
                "model": self.combo_img2img_model.currentData() or "flux",
                "strength": self.spin_denoise.value(),
                "instruction": self.txt_qwen_instr.text().strip(),
                "negative_prompt": self.txt_neg_prompt.text().strip()
            }
        elif pipe == "txt2vid":
            target_method = "generate_txt2vid"
            kwargs = {
                "prompt": prompt,
                "model_name": self.combo_txt2vid_model.currentData() or "epic",
                "num_frames": int(self.combo_txt2vid_frames.currentData() or 16),
                "fps": int(self.combo_txt2vid_fps.currentData() or 8),
                "seed": self.spin_seed.value()
            }
        elif pipe == "img2vid":
            target_method = "generate_img2vid"
            src = self.txt_source_media.text().strip() or self.current_img_path
            kwargs = {
                "image_source": src,
                "prompt": prompt,
                "resolution": self.combo_img2vid_res.currentData() or "480p",
                "fps": int(self.combo_img2vid_fps.currentData() or 16),
                "seed": self.spin_seed.value()
            }
        elif pipe == "vid2audio":
            target_method = "generate_vid2audio"
            vp = self.txt_source_media.text().strip() or self.current_video_path or self.current_media_path
            kwargs = {
                "video_path": vp,
                "prompt": prompt,
                "duration": self.spin_audio_duration.value()
            }
        elif pipe == "vid2vid":
            target_method = "generate_vid2vid"
            vp = self.txt_source_media.text().strip() or self.current_video_path or self.current_media_path
            kwargs = {
                "video_path": vp,
                "prompt": prompt,
                "style_preset": self.combo_vid2vid_preset.currentData() or "cinematic",
                "with_audio": self.chk_vid2vid_audio.isChecked()
            }
        elif pipe == "director":
            target_method = "autonomous_director"
            src = self.txt_source_media.text().strip() or self.current_media_path
            kwargs = {
                "directive": prompt,
                "source_media": src
            }

        self.gen_worker = StudioPipelineWorker(self.sm, target_method, kwargs)

        def _on_prog(step, total, msg):
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(min(step, total))
            self.lbl_pipeline_status.setText(msg)

        def _on_done(res):
            self.progress_bar.setValue(self.progress_bar.maximum())
            media_p = res.get("video_path") or res.get("image_path")
            if media_p and os.path.exists(media_p):
                self.on_image_generated(media_p, res)
            self.btn_generate.setEnabled(True)
            self.lbl_pipeline_status.setText(f"{pipe.upper()} complete ◈ Ready")

        def _on_err(err_msg):
            self.lbl_pipeline_status.setText(f"Error: {err_msg[:60]}")
            self.btn_generate.setEnabled(True)

        self.gen_worker.progress.connect(_on_prog)
        self.gen_worker.finished.connect(_on_done)
        self.gen_worker.error.connect(_on_err)
        self.gen_worker.start()

    def _on_manual_upscale(self):
        if not self.current_img_path or not os.path.exists(self.current_img_path):
            QMessageBox.warning(self, "No Image", "No image currently displayed to upscale.")
            return
        if not self.sm: return

        self.btn_upscale.setEnabled(False)
        self.lbl_pipeline_status.setText("Upscaling 4x via Modal Neural Pipeline...")
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)

        self.upscale_worker = ImageUpscaleWorker(
            self.sm,
            self.current_img_path,
            scale=4,
            model_name="ultrasharp-4x"
        )

        def _on_prog(step, total, msg):
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(min(step, total))
            self.lbl_pipeline_status.setText(msg)

        def _on_done(res):
            self.progress_bar.setValue(100)
            up_path = res.get("upscaled_path")
            if up_path and os.path.exists(up_path):
                self.lbl_pipeline_status.setText("Upscale 4x complete!")
                self._refresh_history()
                self._load_media_by_index(0)
            self.btn_upscale.setEnabled(True)

        def _on_err(err_msg):
            self.lbl_pipeline_status.setText(f"Upscale error: {err_msg[:60]}")
            self.btn_upscale.setEnabled(True)

        self.upscale_worker.progress.connect(_on_prog)
        self.upscale_worker.finished.connect(_on_done)
        self.upscale_worker.error.connect(_on_err)
        self.upscale_worker.start()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Left:
            self._prev_image()
        elif event.key() == Qt.Key.Key_Right:
            self._next_image()
        else:
            super().keyPressEvent(event)

# =============================================================================
# 3. CHARACTERS TAB
# =============================================================================
class AgentCharactersTab(QWidget):
    """Dynamic Character Persona Manager with Intimate Directives & Metrics."""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.cm = main_win.agent.character_mgr
        self.current_char_name = None

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # --- Left: Character List Panel ---
        left_panel = QFrame()
        left_panel.setFixedWidth(180)
        left_panel.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px;")
        ll = QVBoxLayout(left_panel)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(8)

        ll.addWidget(QLabel("🎭 ACTIVE PERSONAS"))

        self.char_list = QListWidget()
        self.char_list.setStyleSheet(f"""
            QListWidget {{
                background: {C['bg_deep']}; color: {C['text_bright']};
                border: 1px solid {C['border']}; border-radius: 4px; font-family: {FONT_FAMILY}; font-size: 11px;
            }}
            QListWidget::item {{ padding: 8px; border-bottom: 1px solid {C['border']}; }}
            QListWidget::item:selected {{ background: {C['neon_blue']}33; border-left: 3px solid {C['neon_blue']}; }}
        """)
        self.char_list.itemClicked.connect(self._on_char_selected)
        ll.addWidget(self.char_list, 1)

        btns_row = QHBoxLayout()
        self.btn_new = QPushButton("➕ NEW")
        self.btn_new.setStyleSheet(f"background: {C['neon_cyan']}22; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; padding: 6px; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px;")
        self.btn_new.clicked.connect(self._create_new_character)
        btns_row.addWidget(self.btn_new)

        self.btn_delete = QPushButton("🗑 DELETE")
        self.btn_delete.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 6px; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px;")
        self.btn_delete.clicked.connect(self._delete_character)
        btns_row.addWidget(self.btn_delete)
        ll.addLayout(btns_row)

        root.addWidget(left_panel)

        # --- Right: Character Detail Form (Scrollable) ---
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setStyleSheet("background: transparent; border: none;")
        
        right_widget = QWidget()
        rl = QVBoxLayout(right_widget)
        rl.setContentsMargins(0, 0, 8, 0)
        rl.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self.f_name = QLineEdit()
        self.f_gender = QLineEdit()
        self.f_relation = QLineEdit()
        
        self.f_personality = QTextEdit()
        self.f_personality.setMaximumHeight(85)
        
        self.f_response = QTextEdit()
        self.f_response.setMaximumHeight(85)

        # Metrics: Arousal & Submission
        metrics_box = QHBoxLayout()
        self.f_arousal = QSpinBox()
        self.f_arousal.setRange(0, 100)
        self.f_arousal.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_red']}; border: 1px solid {C['border']}; padding: 3px;")
        
        self.f_submission = QSpinBox()
        self.f_submission.setRange(0, 100)
        self.f_submission.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_magenta']}; border: 1px solid {C['border']}; padding: 3px;")
        
        metrics_box.addWidget(QLabel("Arousal (0-100):"))
        metrics_box.addWidget(self.f_arousal)
        metrics_box.addWidget(QLabel("Submission (0-100):"))
        metrics_box.addWidget(self.f_submission)
        metrics_box.addStretch()

        self.f_kinks = QLineEdit()
        self.f_kinks.setPlaceholderText("Affinities, kinks, behavioral quirks...")

        self.f_nsfw = QTextEdit()
        self.f_nsfw.setMaximumHeight(70)
        self.f_nsfw.setPlaceholderText("Specific uninhibited directives, intimate roleplay dynamics, or boundaries...")

        self.f_avatar = QLineEdit()

        for w in (self.f_name, self.f_gender, self.f_relation, self.f_avatar, self.f_kinks):
            w.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 4px; font-family: {FONT_FAMILY}; font-size: 11px;")
        for w in (self.f_personality, self.f_response, self.f_nsfw):
            w.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px;")

        form.addRow("Persona Name:", self.f_name)
        form.addRow("Gender:", self.f_gender)
        form.addRow("Relation to Architect:", self.f_relation)
        form.addRow("Personality System Prompt:", self.f_personality)
        form.addRow("Response Style:", self.f_response)
        form.addRow("Persona Metrics:", metrics_box)
        form.addRow("Affinities / Kinks:", self.f_kinks)
        form.addRow("Intimate / NSFW Directives:", self.f_nsfw)

        av_row = QHBoxLayout()
        av_row.addWidget(self.f_avatar, 1)
        self.btn_browse_av = QPushButton("...")
        self.btn_browse_av.setFixedWidth(36)
        self.btn_browse_av.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_cyan']}; border: 1px solid {C['border']};")
        self.btn_browse_av.clicked.connect(self._browse_avatar)
        av_row.addWidget(self.btn_browse_av)
        form.addRow("Avatar Image Path:", av_row)

        rl.addLayout(form)

        # Action Buttons: Activate Persona & Save
        act_box = QHBoxLayout()
        
        self.btn_activate = QPushButton("🔥 ACTIVATE PERSONA 🔥")
        self.btn_activate.setFixedHeight(40)
        self.btn_activate.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.btn_activate.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_green']}22; color: {C['neon_green']};
                border: 1px solid {C['neon_green']}; border-radius: 4px; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {C['neon_green']}; color: #000; }}
        """)
        self.btn_activate.clicked.connect(self._activate_persona)
        act_box.addWidget(self.btn_activate, 1)

        self.btn_save = QPushButton("💾 SAVE PERSONA")
        self.btn_save.setFixedHeight(40)
        self.btn_save.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_blue']}33; color: {C['neon_blue']};
                border: 1px solid {C['neon_blue']}; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {C['neon_blue']}; color: #fff; }}
        """)
        self.btn_save.clicked.connect(self._save_character)
        act_box.addWidget(self.btn_save, 1)

        rl.addLayout(act_box)
        
        right_scroll.setWidget(right_widget)
        root.addWidget(right_scroll, 1)

        self.reload_characters()

    def reload_characters(self):
        self.char_list.clear()
        active_name = self.cm.get_active_character_name()
        chars = self.cm.get_all_characters()
        
        for c in chars:
            name = c.get("name", "")
            is_active = (name == active_name)
            display = f"🔥 [ACTIVE] {name}" if is_active else f"👤 {name}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, c)
            if is_active:
                item.setForeground(QColor(C['neon_green']))
            self.char_list.addItem(item)

        # Preselect active character if available
        if active_name:
            for i in range(self.char_list.count()):
                it = self.char_list.item(i)
                data = it.data(Qt.ItemDataRole.UserRole)
                if data and data.get("name") == active_name:
                    self.char_list.setCurrentItem(it)
                    self._on_char_selected(it)
                    break

    def _on_char_selected(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        self.current_char_name = data.get("name")
        self.f_name.setText(data.get("name", ""))
        self.f_gender.setText(data.get("gender", ""))
        self.f_relation.setText(data.get("relation", ""))
        self.f_personality.setPlainText(data.get("personality", ""))
        self.f_response.setPlainText(data.get("response_style", ""))
        self.f_arousal.setValue(int(data.get("arousal", 0) or 0))
        self.f_submission.setValue(int(data.get("submission", 0) or 0))
        self.f_kinks.setText(data.get("kinks", ""))
        self.f_nsfw.setPlainText(data.get("nsfw_description", ""))
        self.f_avatar.setText(data.get("avatar_path", ""))

    def _browse_avatar(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Select Avatar Image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if fn:
            self.f_avatar.setText(fn)

    def _activate_persona(self):
        name = self.f_name.text().strip()
        if not name:
            return
        self.cm.set_active_character_name(name)
        self.main_win.agent.active_character = name
        self.reload_characters()
        if hasattr(self.main_win, "_on_persona_activated"):
            self.main_win._on_persona_activated(name)
        self.main_win.signals.log_message.emit(f"[PERSONA] Active character switched to: {name.upper()}", C['neon_green'])

    def _save_character(self):
        name = self.f_name.text().strip()
        if not name:
            return
        
        self.cm.add_character(
            name=name,
            gender=self.f_gender.text().strip(),
            relation=self.f_relation.text().strip(),
            personality=self.f_personality.toPlainText().strip(),
            response_style=self.f_response.toPlainText().strip(),
            avatar_path=self.f_avatar.text().strip(),
            arousal=self.f_arousal.value(),
            submission=self.f_submission.value(),
            kinks=self.f_kinks.text().strip(),
            nsfw_description=self.f_nsfw.toPlainText().strip()
        )
        self.reload_characters()
        self.main_win.signals.log_message.emit(f"[PERSONA] Character '{name}' saved successfully.", C['neon_cyan'])

    def _create_new_character(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Character", "Enter character persona name:")
        if ok and name.strip():
            c_name = name.strip()
            self.cm.add_character(name=c_name, relation="Companion", personality="Intelligent, supportive, and direct.")
            self.reload_characters()

    def _delete_character(self):
        if not self.current_char_name:
            return
        if self.current_char_name in ("Alpha", "Eden"):
            QMessageBox.warning(self, "Protected", f"Character '{self.current_char_name}' is a core system entity.")
            return
        
        ret = QMessageBox.question(self, "Confirm Delete", f"Delete character persona '{self.current_char_name}'?")
        if ret == QMessageBox.StandardButton.Yes:
            self.cm.delete_character(self.current_char_name)
            self.reload_characters()

# =============================================================================
# 4. MONITOR TAB
# =============================================================================
class AgentMonitorTab(QWidget):
    """System & Model Diagnostics Monitor."""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._start_time = time.time()

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(10)

        # Header bar
        hdr = QHBoxLayout()
        title = QLabel("📊 HARDWARE MONITOR")
        title.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['neon_cyan']};")
        hdr.addWidget(title)
        hdr.addStretch()

        self.btn_refresh = QPushButton("🔄 REFRESH")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_blue']}; border: 1px solid {C['border']}; padding: 0 10px; font-family: {FONT_FAMILY};")
        self.btn_refresh.clicked.connect(self._update_hardware_metrics)
        hdr.addWidget(self.btn_refresh)
        outer_layout.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(12)
        
        outer_layout.addWidget(scroll, 1)
        scroll.setWidget(container)

        # --- Card 1: Live Hardware Gauges (CPU, RAM, Disk) ---
        hw_card = QFrame()
        hw_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        hl = QVBoxLayout(hw_card)
        hl.setSpacing(8)
        hl.addWidget(QLabel("🖥 HOST RESOURCE CONSUMPTION"))

        # CPU Progress Bar
        cpu_row = QHBoxLayout()
        cpu_row.addWidget(QLabel("CPU Usage:"), 1)
        self.bar_cpu = QProgressBar()
        self.bar_cpu.setRange(0, 100)
        self.bar_cpu.setStyleSheet(f"""
            QProgressBar {{
                background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 3px; text-align: center; color: {C['text_bright']}; font-family: {FONT_FAMILY}; font-size: 10px;
            }}
            QProgressBar::chunk {{ background: {C['neon_blue']}; }}
        """)
        cpu_row.addWidget(self.bar_cpu, 3)
        self.lbl_cpu_val = QLabel("0%")
        self.lbl_cpu_val.setFixedWidth(50)
        cpu_row.addWidget(self.lbl_cpu_val)
        hl.addLayout(cpu_row)

        # RAM Progress Bar
        ram_row = QHBoxLayout()
        ram_row.addWidget(QLabel("RAM Usage:"), 1)
        self.bar_ram = QProgressBar()
        self.bar_ram.setRange(0, 100)
        self.bar_ram.setStyleSheet(f"""
            QProgressBar {{
                background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 3px; text-align: center; color: {C['text_bright']}; font-family: {FONT_FAMILY}; font-size: 10px;
            }}
            QProgressBar::chunk {{ background: {C['neon_green']}; }}
        """)
        ram_row.addWidget(self.bar_ram, 3)
        self.lbl_ram_val = QLabel("0%")
        self.lbl_ram_val.setFixedWidth(50)
        ram_row.addWidget(self.lbl_ram_val)
        hl.addLayout(ram_row)

        # Disk Progress Bar
        disk_row = QHBoxLayout()
        disk_row.addWidget(QLabel("Disk Usage:"), 1)
        self.bar_disk = QProgressBar()
        self.bar_disk.setRange(0, 100)
        self.bar_disk.setStyleSheet(f"""
            QProgressBar {{
                background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 3px; text-align: center; color: {C['text_bright']}; font-family: {FONT_FAMILY}; font-size: 10px;
            }}
            QProgressBar::chunk {{ background: {C['neon_yellow']}; }}
        """)
        disk_row.addWidget(self.bar_disk, 3)
        self.lbl_disk_val = QLabel("0%")
        self.lbl_disk_val.setFixedWidth(50)
        disk_row.addWidget(self.lbl_disk_val)
        hl.addLayout(disk_row)

        root.addWidget(hw_card)

        # --- Card 2: Agent Engine Telemetry ---
        tele_card = QFrame()
        tele_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        tl = QGridLayout(tele_card)
        tl.setSpacing(10)
        
        self.tele_lbls = {}
        fields = [
            ("Active Backend:", "backend", "--"),
            ("Model Identifier:", "model", "--"),
            ("Active Persona:", "persona", "--"),
            ("Voice Engine:", "voice", "--"),
            ("Duplex Audio Mode:", "duplex", "--"),
            ("Active Display:", "display", "--"),
            ("Session Name:", "session", "--"),
            ("Session Uptime:", "uptime", "00:00:00"),
        ]

        for idx, (label_text, key, default) in enumerate(fields):
            r, c = divmod(idx, 2)
            lbl_title = QLabel(label_text)
            lbl_title.setStyleSheet(f"color: {C['text_dim']}; font-family: {FONT_FAMILY}; font-size: 10px;")
            lbl_val = QLabel(default)
            lbl_val.setStyleSheet(f"color: {C['neon_cyan']}; font-family: {FONT_FAMILY}; font-size: 11px; font-weight: bold;")
            tl.addWidget(lbl_title, r * 2, c)
            tl.addWidget(lbl_val, r * 2 + 1, c)
            self.tele_lbls[key] = lbl_val

        root.addWidget(tele_card)

        # --- Card 3: Direct Hardware Testing Tools ---
        tools_card = QFrame()
        tools_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        tol = QVBoxLayout(tools_card)
        tol.setSpacing(8)
        tol.addWidget(QLabel("🛠 HARDWARE & CONTROLLER DIAGNOSTICS"))
        
        t_row = QHBoxLayout()
        self.btn_test_cam = QPushButton("📷 TEST WEBCAM CAPTURE")
        self.btn_test_cam.setStyleSheet(f"background: {C['neon_cyan']}22; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; padding: 6px 12px; font-family: {FONT_FAMILY}; font-weight: bold;")
        self.btn_test_cam.clicked.connect(self._test_webcam)
        t_row.addWidget(self.btn_test_cam)

        self.btn_test_ocr = QPushButton("👁 TEST SCREEN OCR")
        self.btn_test_ocr.setStyleSheet(f"background: {C['neon_green']}22; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; padding: 6px 12px; font-family: {FONT_FAMILY}; font-weight: bold;")
        self.btn_test_ocr.clicked.connect(self._test_screen_ocr)
        t_row.addWidget(self.btn_test_ocr)
        t_row.addStretch()
        
        tol.addLayout(t_row)
        root.addWidget(tools_card)

        # --- Card 4: Modal Cloud Infrastructure & Deployments ---
        modal_card = QFrame()
        modal_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ml = QVBoxLayout(modal_card)
        ml.setSpacing(8)
        ml.addWidget(QLabel("☁ MODAL CLOUD DEPLOYMENTS"))

        # Profile Selector
        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("Active Modal Profile:"), 1)
        self.combo_modal_prof = QComboBox()
        self.combo_modal_prof.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; padding: 4px; font-family: {FONT_FAMILY};")
        m_row.addWidget(self.combo_modal_prof, 2)
        ml.addLayout(m_row)

        # Deploy Target Buttons
        dep_grid = QGridLayout()
        dep_grid.setSpacing(6)
        
        dep_targets = [
            ("vLLM Qwen Engine", "core/modal_vllm.py", "alphalive-vllm-bucket"),
        ]

        for idx, (label, script, app_name) in enumerate(dep_targets):
            lbl_t = QLabel(f"• {label}:")
            lbl_t.setStyleSheet(f"color: {C['text_bright']}; font-family: {FONT_FAMILY}; font-size: 10px;")
            dep_grid.addWidget(lbl_t, idx, 0)
            
            btn_deploy = QPushButton("🚀 DEPLOY")
            btn_deploy.setStyleSheet(f"background: {C['neon_blue']}22; color: {C['neon_blue']}; border: 1px solid {C['neon_blue']}; padding: 4px 10px; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px;")
            btn_deploy.clicked.connect(lambda _, s=script: self._deploy_modal_app(s))
            dep_grid.addWidget(btn_deploy, idx, 1)

            btn_stop = QPushButton("⏹ STOP")
            btn_stop.setStyleSheet(f"background: {C['neon_red']}22; color: {C['neon_red']}; border: 1px solid {C['neon_red']}; padding: 4px 10px; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px;")
            btn_stop.clicked.connect(lambda _, a=app_name: self._stop_modal_app(a))
            dep_grid.addWidget(btn_stop, idx, 2)

        ml.addLayout(dep_grid)
        root.addWidget(modal_card)

        self._populate_modal_profiles()
        root.addStretch()

        # Timer for hardware updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)
        self._tick()

    def _tick(self):
        self._update_hardware_metrics()
        self._update_telemetry()

    def _update_hardware_metrics(self):
        if psutil:
            try:
                cpu = int(psutil.cpu_percent(interval=None))
                self.bar_cpu.setValue(cpu)
                self.lbl_cpu_val.setText(f"{cpu}%")

                ram = psutil.virtual_memory()
                ram_pct = int(ram.percent)
                self.bar_ram.setValue(ram_pct)
                self.lbl_ram_val.setText(f"{ram_pct}% ({ram.used / (1024**3):.1f}/{ram.total / (1024**3):.1f} GB)")

                disk = psutil.disk_usage(str(ROOT_DIR.anchor))
                disk_pct = int(disk.percent)
                self.bar_disk.setValue(disk_pct)
                self.lbl_disk_val.setText(f"{disk_pct}% ({disk.free / (1024**3):.0f} GB Free)")
            except Exception:
                pass
        else:
            self.lbl_cpu_val.setText("N/A")
            self.lbl_ram_val.setText("N/A")
            self.lbl_disk_val.setText("N/A")

    def _update_telemetry(self):
        agent = self.main_win.agent
        
        backend = getattr(agent, "backend_type", "gemini")
        if backend == "modal_qwen":
            self.tele_lbls["backend"].setText("Custom Endpoint")
            self.tele_lbls["model"].setText("Qwen 2.5 Coder 32B Instruct")
        else:
            self.tele_lbls["backend"].setText("Google Gemini")
            self.tele_lbls["model"].setText(agent.model_name.replace("models/", ""))

        active_char = getattr(agent, "active_character", "Alpha")
        self.tele_lbls["persona"].setText(f"🔥 {active_char.upper()}")

        voice_mode = getattr(agent.voice, "engine_mode", "pyttsx3")
        self.tele_lbls["voice"].setText(voice_mode.upper())

        duplex = getattr(self.main_win, "duplex_mode", "half")
        self.tele_lbls["duplex"].setText(f"{duplex.upper()}-DUPLEX (Echo-Guarded)")

        disp = getattr(agent.controller, "active_display_index", 0)
        self.tele_lbls["display"].setText(f"Monitor Index #{disp}")

        sess = getattr(agent, "current_session", "session_default")
        self.tele_lbls["session"].setText(sess[:18] + ("..." if len(sess) > 18 else ""))

        elapsed = int(time.time() - self._start_time)
        hrs, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        self.tele_lbls["uptime"].setText(f"{hrs:02d}:{mins:02d}:{secs:02d}")

    def _test_webcam(self):
        cam = self.main_win.agent.controller.capture_camera_frame()
        if cam is not None:
            QMessageBox.information(self, "Webcam Test", f"Webcam frame captured successfully:\nDimensions: {cam.width}x{cam.height}")
        else:
            QMessageBox.warning(self, "Webcam Test", "Webcam capture failed: device offline or unavailable.")

    def _test_screen_ocr(self):
        import asyncio
        async def run_ocr():
            return await self.main_win.agent.controller.get_screen_ocr_summary(fast_mode=True)
        try:
            summary = asyncio.run(run_ocr())
            QMessageBox.information(self, "Screen OCR Test", f"OCR Summary (first 300 chars):\n\n{summary[:300]}...")
        except Exception as e:
            QMessageBox.warning(self, "OCR Error", str(e))

    def _populate_modal_profiles(self):
        try:
            from ui.overlays import get_modal_profiles
            profs, active = get_modal_profiles()
            self.combo_modal_prof.clear()
            for p in profs:
                self.combo_modal_prof.addItem(p)
            if active:
                idx = self.combo_modal_prof.findText(active)
                if idx >= 0:
                    self.combo_modal_prof.setCurrentIndex(idx)
        except Exception:
            pass

    def _deploy_modal_app(self, script_path: str):
        prof = self.combo_modal_prof.currentText()
        prof_arg = f" --profile {prof}" if prof else ""
        cmd = f'powershell -NoExit -Command "Set-Location \'{ROOT_DIR}\'; modal deploy{prof_arg} {script_path}"'
        import subprocess
        subprocess.Popen(f'start {cmd}', shell=True)
        self.main_win.signals.log_message.emit(f"[MODAL] Launched deployment: {script_path} (Profile: {prof})", C['neon_cyan'])

    def _stop_modal_app(self, app_name: str):
        prof = self.combo_modal_prof.currentText()
        prof_arg = f" --profile {prof}" if prof else ""
        cmd = f'powershell -Command "modal app stop{prof_arg} {app_name}"'
        import subprocess
        subprocess.Popen(cmd, shell=True)
        self.main_win.signals.log_message.emit(f"[MODAL] Dispatched stop command for app: {app_name}", C['neon_yellow'])
