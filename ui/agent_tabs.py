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
    QFileDialog, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPixmap, QIcon

try:
    import psutil
except ImportError:
    psutil = None

from studio.image_studio_manager import MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG, DEFAULT_NEGATIVE_PROMPT

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


# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================
# 1. MEMORY TAB
# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────

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

        root.addWidget(self.subtabs, 1)

        # Initial data load
        self.reload_all()

    def reload_all(self):
        self._load_facts()
        self._load_traits()
        self._load_episodes()
        self._load_profile()

    # ── Subtab 1: Facts ──────────────────────────────────────────────────────
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

        self.in_subj = QLineEdit(); self.in_subj.setPlaceholderText("Subject (e.g. Architect)")
        self.in_pred = QLineEdit(); self.in_pred.setPlaceholderText("Predicate (e.g. works_with)")
        self.in_obj  = QLineEdit(); self.in_obj.setPlaceholderText("Object (e.g. Python, AI)")
        for inp in (self.in_subj, self.in_pred, self.in_obj):
            inp.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        btn_add = QPushButton("➕ ADD FACT")
        btn_add.setStyleSheet(f"background: {C['neon_cyan']}33; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_add.clicked.connect(self._add_fact)

        abl.addWidget(self.in_subj, 1)
        abl.addWidget(self.in_pred, 1)
        abl.addWidget(self.in_obj, 1)
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
        s = self.in_subj.text().strip()
        p = self.in_pred.text().strip()
        o = self.in_obj.text().strip()
        if s and p and o:
            self.mm.memorize_fact(s, p, o, source="manual_ui")
            self.in_subj.clear()
            self.in_pred.clear()
            self.in_obj.clear()
            self._load_facts()

    def _delete_fact(self):
        row = self.table_facts.currentRow()
        if row >= 0:
            id_item = self.table_facts.item(row, 0)
            if id_item and id_item.text().isdigit():
                self.mm.delete_fact(int(id_item.text()))
                self._load_facts()

    # ── Subtab 2: Core Personality Traits ────────────────────────────────────
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

    # ── Subtab 3: Episodic Memories ──────────────────────────────────────────
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

        btn_add = QPushButton("📝 WRITE ENTRY")
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

    # ── Subtab 4: Personal Intelligence ──────────────────────────────────────
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
        self.in_prof_cat.addItems(["identity", "preferences", "environment", "projects", "habits", "general"])
        self.in_prof_cat.setStyleSheet(f"background: {C['bg_deep']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px;")

        self.in_prof_key = QLineEdit(); self.in_prof_key.setPlaceholderText("Key (e.g. music_preference)")
        self.in_prof_val = QLineEdit(); self.in_prof_val.setPlaceholderText("Value (e.g. Cyberpunk Synthwave)")
        for inp in (self.in_prof_key, self.in_prof_val):
            inp.setStyleSheet(f"background: {C['bg_deep']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px; padding: 3px 6px;")

        btn_save = QPushButton("💾 SAVE ATTRIBUTE")
        btn_save.setStyleSheet(f"background: {C['neon_cyan']}33; color: {C['neon_cyan']}; border: 1px solid {C['neon_cyan']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 9px; padding: 4px 10px;")
        btn_save.clicked.connect(self._upsert_profile)

        abl.addWidget(self.in_prof_cat)
        abl.addWidget(self.in_prof_key, 1)
        abl.addWidget(self.in_prof_val, 1)
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
        cat = self.in_prof_cat.currentText()
        k = self.in_prof_key.text().strip()
        v = self.in_prof_val.text().strip()
        if k and v:
            self.mm.set_user_attribute(k, v, category=cat, source="manual_ui")
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


# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================
# 2. IMAGE STUDIO TAB
# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────

class ImageGenWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, studio_mgr, kwargs):
        super().__init__()
        self.studio_mgr = studio_mgr
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.studio_mgr.generate_image(**self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class ImageUpscaleWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, studio_mgr, image_path, upscaler_model):
        super().__init__()
        self.studio_mgr = studio_mgr
        self.image_path = image_path
        self.upscaler_model = upscaler_model

    def run(self):
        try:
            res = self.studio_mgr.upscale_image(self.image_path, upscaler_model=self.upscaler_model)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class AgentStudioTab(QWidget):
    """Neural Image Studio with SDXL Checkpoints, LoRA, Upscaling, & RLHF Feedback."""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.sm = main_win.agent.studio_mgr
        self.current_img_path = None
        self.current_gen_id = None
        self.current_rating = 0
        self._gen_worker = None
        self._upscale_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header bar
        hdr = QHBoxLayout()
        title = QLabel("🎨 NEURAL IMAGE STUDIO")
        title.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['neon_cyan']};")
        hdr.addWidget(title)
        hdr.addStretch()

        self.btn_open_folder = QPushButton("📂 OPEN OUTPUTS")
        self.btn_open_folder.setFixedHeight(28)
        self.btn_open_folder.setFont(QFont(FONT_FAMILY, 8))
        self.btn_open_folder.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C['text_dim']};
                border: 1px solid {C['border']}; border-radius: 4px; padding: 0 10px;
            }}
            QPushButton:hover {{ border-color: {C['neon_blue']}; color: {C['text_bright']}; }}
        """)
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        hdr.addWidget(self.btn_open_folder)
        root.addLayout(hdr)

        # Main Splitter (Left: Controls, Right: Viewport + RLHF)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Controls Panel (Scrollable) ────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setStyleSheet("background: transparent; border: none;")

        left_widget = QWidget()
        ll = QVBoxLayout(left_widget)
        ll.setContentsMargins(0, 0, 10, 0)
        ll.setSpacing(8)

        # Model Selector
        ll.addWidget(QLabel("SDXL Checkpoint Model:"))
        self.combo_model = QComboBox()
        for k, v in MODEL_CATALOG.items():
            self.combo_model.addItem(f"{v['name']} ({k})", k)
        self.combo_model.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; padding: 4px 6px; font-family: {FONT_FAMILY};")
        ll.addWidget(self.combo_model)

        # LoRA Selector + Scale
        lora_row = QHBoxLayout()
        self.combo_lora = QComboBox()
        for k, v in LORA_CATALOG.items():
            self.combo_lora.addItem(v, k)
        self.combo_lora.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 4px 6px; font-family: {FONT_FAMILY};")
        lora_row.addWidget(self.combo_lora, 2)

        self.spin_lora_scale = QDoubleSpinBox()
        self.spin_lora_scale.setRange(0.0, 2.0)
        self.spin_lora_scale.setValue(0.8)
        self.spin_lora_scale.setSingleStep(0.05)
        self.spin_lora_scale.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_yellow']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY};")
        lora_row.addWidget(self.spin_lora_scale, 1)
        ll.addWidget(QLabel("LoRA Enhancement & Scale:"))
        ll.addLayout(lora_row)

        # Character Persona Association
        ll.addWidget(QLabel("Character Persona (Optional):"))
        self.combo_char = QComboBox()
        self.combo_char.addItem("None", "")
        self.combo_char.addItems(["Alpha", "Luci", "Eden", "Lacey"])
        self.combo_char.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 4px 6px; font-family: {FONT_FAMILY};")
        ll.addWidget(self.combo_char)

        # Positive Prompt
        ll.addWidget(QLabel("Positive Prompt:"))
        self.txt_prompt = QTextEdit()
        self.txt_prompt.setFixedHeight(75)
        self.txt_prompt.setPlaceholderText("Describe visual scene in detail: lighting, angle, subject, style, composition...")
        self.txt_prompt.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        ll.addWidget(self.txt_prompt)

        # Negative Prompt
        ll.addWidget(QLabel("Negative Prompt:"))
        self.txt_neg_prompt = QTextEdit()
        self.txt_neg_prompt.setFixedHeight(45)
        self.txt_neg_prompt.setPlainText(DEFAULT_NEGATIVE_PROMPT)
        self.txt_neg_prompt.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 10px;")
        ll.addWidget(self.txt_neg_prompt)

        # Parameters Row: Resolution, Steps, CFG
        params_row = QHBoxLayout()
        self.combo_res = QComboBox()
        self.combo_res.addItem("1024x1024 (Square)", (1024, 1024))
        self.combo_res.addItem("896x1152 (Portrait)", (896, 1152))
        self.combo_res.addItem("1152x896 (Landscape)", (1152, 896))
        self.combo_res.addItem("768x1024 (Tall)", (768, 1024))
        self.combo_res.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY};")
        params_row.addWidget(self.combo_res)

        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(15, 60)
        self.spin_steps.setValue(30)
        self.spin_steps.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY};")
        params_row.addWidget(QLabel("Steps:"))
        params_row.addWidget(self.spin_steps)

        self.spin_cfg = QDoubleSpinBox()
        self.spin_cfg.setRange(1.0, 15.0)
        self.spin_cfg.setValue(7.0)
        self.spin_cfg.setSingleStep(0.5)
        self.spin_cfg.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY};")
        params_row.addWidget(QLabel("CFG:"))
        params_row.addWidget(self.spin_cfg)
        ll.addLayout(params_row)

        # Upscaler selector
        ll.addWidget(QLabel("Super-Resolution Upscaler:"))
        self.combo_upscaler = QComboBox()
        for k, v in UPSCALER_CATALOG.items():
            self.combo_upscaler.addItem(v, k)
        self.combo_upscaler.setStyleSheet(f"background: {C['bg_card']}; color: {C['neon_green']}; border: 1px solid {C['border']}; padding: 4px 6px; font-family: {FONT_FAMILY};")
        ll.addWidget(self.combo_upscaler)

        # Action Buttons
        self.btn_generate = QPushButton("⚡ GENERATE IMAGE")
        self.btn_generate.setFixedHeight(38)
        self.btn_generate.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.btn_generate.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_cyan']}; color: #000;
                border: none; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #ffffff; }}
            QPushButton:disabled {{ background: {C['border']}; color: {C['text_dim']}; }}
        """)
        self.btn_generate.clicked.connect(self._run_generation)
        ll.addWidget(self.btn_generate)

        upscale_row = QHBoxLayout()
        self.btn_upscale = QPushButton("🔍 UPSCALE CURRENT")
        self.btn_upscale.setFixedHeight(30)
        self.btn_upscale.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        self.btn_upscale.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon_green']}22; color: {C['neon_green']};
                border: 1px solid {C['neon_green']}; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {C['neon_green']}; color: #000; }}
            QPushButton:disabled {{ background: transparent; color: {C['text_dim']}; border-color: {C['border']}; }}
        """)
        self.btn_upscale.clicked.connect(self._run_upscale)
        self.btn_upscale.setEnabled(False)
        upscale_row.addWidget(self.btn_upscale)

        ll.addLayout(upscale_row)

        # Recent Generations History
        ll.addWidget(QLabel("Recent Generation History:"))
        self.history_list = QListWidget()
        self.history_list.setFixedHeight(120)
        self.history_list.setStyleSheet(f"""
            QListWidget {{
                background: {C['bg_card']}; color: {C['text_bright']};
                border: 1px solid {C['border']}; border-radius: 4px; font-family: {FONT_FAMILY}; font-size: 10px;
            }}
            QListWidget::item:selected {{ background: {C['neon_blue']}44; color: #fff; }}
        """)
        self.history_list.itemClicked.connect(self._on_history_clicked)
        ll.addWidget(self.history_list)

        left_scroll.setWidget(left_widget)
        splitter.addWidget(left_scroll)

        # ── Right: Viewport & RLHF Feedback Panel ────────────────────────────
        right_panel = QFrame()
        right_panel.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px;")
        rl = QVBoxLayout(right_panel)
        rl.setContentsMargins(10, 10, 10, 10)
        rl.setSpacing(8)

        # Viewport Frame
        vp_frame = QFrame()
        vp_frame.setStyleSheet(f"background: {C['bg_dark']}; border: 1px solid {C['border']}; border-radius: 4px;")
        vpl = QVBoxLayout(vp_frame)
        vpl.setContentsMargins(4, 4, 4, 4)

        self.img_viewport = QLabel()
        self.img_viewport.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_viewport.setText("🎨 No image rendered yet.\nEnter a prompt and click GENERATE IMAGE.")
        self.img_viewport.setStyleSheet(f"color: {C['text_dim']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        vpl.addWidget(self.img_viewport)
        rl.addWidget(vp_frame, 1)

        # Meta info label
        self.lbl_meta = QLabel("Status: Idle")
        self.lbl_meta.setFont(QFont(FONT_FAMILY, 9))
        self.lbl_meta.setStyleSheet(f"color: {C['text_dim']};")
        self.lbl_meta.setWordWrap(True)
        rl.addWidget(self.lbl_meta)

        # RLHF Feedback Card
        fb_card = QFrame()
        fb_card.setStyleSheet(f"background: {C['bg_deep']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px;")
        fbl = QVBoxLayout(fb_card)
        fbl.setSpacing(6)

        stars_row = QHBoxLayout()
        stars_row.addWidget(QLabel("RLHF Star Rating:"))
        self.star_btns = []
        for i in range(1, 6):
            btn = QPushButton(f"★ {i}")
            btn.setFixedSize(42, 24)
            btn.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
            btn.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']}; border-radius: 3px;")
            btn.clicked.connect(lambda _, star=i: self._set_star_rating(star))
            stars_row.addWidget(btn)
            self.star_btns.append(btn)
        stars_row.addStretch()
        fbl.addLayout(stars_row)

        notes_row = QHBoxLayout()
        self.in_fb_notes = QLineEdit()
        self.in_fb_notes.setPlaceholderText("Feedback notes (e.g. good skin texture, weird fingers, great lighting)...")
        self.in_fb_notes.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_bright']}; border: 1px solid {C['border']}; font-family: {FONT_FAMILY}; font-size: 10px; padding: 3px;")
        notes_row.addWidget(self.in_fb_notes, 1)

        self.btn_submit_fb = QPushButton("SUBMIT RLHF")
        self.btn_submit_fb.setStyleSheet(f"background: {C['neon_blue']}33; color: {C['neon_blue']}; border: 1px solid {C['neon_blue']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 8px; padding: 4px 8px;")
        self.btn_submit_fb.clicked.connect(self._submit_feedback)
        notes_row.addWidget(self.btn_submit_fb)
        fbl.addLayout(notes_row)

        rl.addWidget(fb_card)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._load_history()

    def _open_output_folder(self):
        folder = ROOT_DIR / "outputs" / "generated_images"
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
        import subprocess
        subprocess.Popen(f'explorer "{folder}"', shell=True)

    def _load_history(self):
        self.history_list.clear()
        hist = self.sm.get_history(limit=30)
        for item in hist:
            gen_id = item.get("id")
            prompt_snip = item.get("prompt", "")[:35]
            time_str = str(item.get("timestamp", ""))[-8:]
            model = item.get("model_name", "")
            list_item = QListWidgetItem(f"#{gen_id} [{time_str}] [{model}] {prompt_snip}...")
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.history_list.addItem(list_item)

    def _on_history_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        img_p = data.get("image_path")
        self.current_gen_id = data.get("id")
        self.current_img_path = img_p
        if img_p and os.path.exists(img_p):
            pix = QPixmap(img_p)
            scaled = pix.scaled(self.img_viewport.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.img_viewport.setPixmap(scaled)
            self.lbl_meta.setText(f"File: {os.path.basename(img_p)} | Model: {data.get('model_name')} | Steps: {data.get('steps')} | Seed: {data.get('seed')}")
            self.btn_upscale.setEnabled(True)
        else:
            self.img_viewport.setText("Image file no longer found on disk.")
            self.btn_upscale.setEnabled(False)

    def _set_star_rating(self, rating: int):
        self.current_rating = rating
        for i, btn in enumerate(self.star_btns, start=1):
            if i <= rating:
                btn.setStyleSheet(f"background: {C['neon_yellow']}; color: #000; border: 1px solid {C['neon_yellow']}; font-weight: bold;")
            else:
                btn.setStyleSheet(f"background: {C['bg_card']}; color: {C['text_dim']}; border: 1px solid {C['border']};")

    def _submit_feedback(self):
        if not self.current_gen_id:
            self.lbl_meta.setText("Status: No image selected to review.")
            return
        notes = self.in_fb_notes.text().strip()
        self.sm.record_feedback(self.current_gen_id, rating=self.current_rating, feedback_notes=notes)
        self.lbl_meta.setText(f"Status: Feedback recorded (★ {self.current_rating}) for generation #{self.current_gen_id}.")
        self.in_fb_notes.clear()

    def _run_generation(self):
        p = self.txt_prompt.toPlainText().strip()
        if not p:
            self.lbl_meta.setText("Status: Please enter a prompt first.")
            return

        model_key = self.combo_model.currentData()
        lora_key = self.combo_lora.currentData()
        lora_scale = self.spin_lora_scale.value()
        char_name = self.combo_char.currentText() if self.combo_char.currentText() != "None" else ""
        neg = self.txt_neg_prompt.toPlainText().strip()
        res_tuple = self.combo_res.currentData()
        steps = self.spin_steps.value()
        cfg = self.spin_cfg.value()

        self.btn_generate.setEnabled(False)
        self.btn_generate.setText("⏳ RENDERING...")
        self.lbl_meta.setText("Status: Dispatching SDXL generation pipeline...")

        kwargs = {
            "prompt": p,
            "negative_prompt": neg,
            "model_name": model_key,
            "lora_name": lora_key,
            "lora_scale": lora_scale,
            "steps": steps,
            "cfg_scale": cfg,
            "width": res_tuple[0],
            "height": res_tuple[1],
            "character_name": char_name
        }

        self._gen_worker = ImageGenWorker(self.sm, kwargs)
        self._gen_worker.finished.connect(self._on_gen_finished)
        self._gen_worker.error.connect(self._on_gen_error)
        self._gen_worker.start()

    def _on_gen_finished(self, res: dict):
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("⚡ GENERATE IMAGE")
        if res.get("status") == "success":
            img_p = res.get("image_path")
            self.current_img_path = img_p
            self.current_gen_id = res.get("generation_id")
            if img_p and os.path.exists(img_p):
                pix = QPixmap(img_p)
                scaled = pix.scaled(self.img_viewport.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.img_viewport.setPixmap(scaled)
                self.btn_upscale.setEnabled(True)
            self.lbl_meta.setText(f"Generated: {os.path.basename(img_p)} in {res.get('time_taken', 0):.2f}s | Seed: {res.get('seed')}")
            self._load_history()
        else:
            err = res.get("error", "Unknown error")
            self.lbl_meta.setText(f"Generation error: {err}")

    def _on_gen_error(self, err_msg: str):
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("⚡ GENERATE IMAGE")
        self.lbl_meta.setText(f"Pipeline error: {err_msg}")

    def _run_upscale(self):
        if not self.current_img_path or not os.path.exists(self.current_img_path):
            self.lbl_meta.setText("Status: No image file to upscale.")
            return

        upscaler = self.combo_upscaler.currentData()
        self.btn_upscale.setEnabled(False)
        self.btn_upscale.setText("⏳ UPSCALING...")
        self.lbl_meta.setText(f"Status: Running {upscaler} neural super-resolution...")

        self._upscale_worker = ImageUpscaleWorker(self.sm, self.current_img_path, upscaler)
        self._upscale_worker.finished.connect(self._on_upscale_finished)
        self._upscale_worker.error.connect(self._on_upscale_error)
        self._upscale_worker.start()

    def _on_upscale_finished(self, res: dict):
        self.btn_upscale.setEnabled(True)
        self.btn_upscale.setText("🔍 UPSCALE CURRENT")
        if res.get("status") == "success":
            out_p = res.get("upscaled_path")
            self.current_img_path = out_p
            if out_p and os.path.exists(out_p):
                pix = QPixmap(out_p)
                scaled = pix.scaled(self.img_viewport.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.img_viewport.setPixmap(scaled)
            self.lbl_meta.setText(f"Upscaled: {os.path.basename(out_p)} in {res.get('time_taken', 0):.2f}s")
            self._load_history()
        else:
            self.lbl_meta.setText(f"Upscale error: {res.get('error', 'unknown')}")

    def _on_upscale_error(self, err: str):
        self.btn_upscale.setEnabled(True)
        self.btn_upscale.setText("🔍 UPSCALE CURRENT")
        self.lbl_meta.setText(f"Upscale error: {err}")


# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================
# 3. CHARACTERS TAB
# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────

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

        # ── Left: Character List Panel ───────────────────────────────────────
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

        # ── Right: Character Detail Form (Scrollable) ────────────────────────
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
        self.btn_activate = QPushButton("★ ACTIVATE PERSONA ★")
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
            display = f"★ [ACTIVE] {name}" if is_active else f"  {name}"
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


# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================
# 4. MONITOR TAB
# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────

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

        # ── Card 1: Live Hardware Gauges (CPU, RAM, Disk) ─────────────────────
        hw_card = QFrame()
        hw_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        hl = QVBoxLayout(hw_card)
        hl.setSpacing(8)

        hl.addWidget(QLabel("⚡ HOST RESOURCE CONSUMPTION"))

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

        # ── Card 2: Agent Engine Telemetry ───────────────────────────────────
        tele_card = QFrame()
        tele_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        tl = QGridLayout(tele_card)
        tl.setSpacing(10)

        self.tele_lbls = {}
        fields = [
            ("Active Backend:", "backend", "—"),
            ("Model Identifier:", "model", "—"),
            ("Active Persona:", "persona", "—"),
            ("Voice Engine:", "voice", "—"),
            ("Duplex Audio Mode:", "duplex", "—"),
            ("Active Display:", "display", "—"),
            ("Session Name:", "session", "—"),
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

        # ── Card 3: Direct Hardware Testing Tools ────────────────────────────
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

        self.btn_test_ocr = QPushButton("🖥 TEST SCREEN OCR")
        self.btn_test_ocr.setStyleSheet(f"background: {C['neon_green']}22; color: {C['neon_green']}; border: 1px solid {C['neon_green']}; padding: 6px 12px; font-family: {FONT_FAMILY}; font-weight: bold;")
        self.btn_test_ocr.clicked.connect(self._test_screen_ocr)
        t_row.addWidget(self.btn_test_ocr)

        t_row.addStretch()
        tol.addLayout(t_row)
        root.addWidget(tools_card)

        # ── Card 4: Modal Cloud Infrastructure & Deployments ────────────────
        modal_card = QFrame()
        modal_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 10px;")
        ml = QVBoxLayout(modal_card)
        ml.setSpacing(8)

        ml.addWidget(QLabel("☁️ MODAL CLOUD DEPLOYMENTS"))

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
            self.tele_lbls["backend"].setText("Modal vLLM (HuiHui-Qwen3-14B)")
            self.tele_lbls["model"].setText("Qwen/Qwen2.5-Coder-14B-Instruct")
        else:
            self.tele_lbls["backend"].setText("Google Gemini")
            self.tele_lbls["model"].setText(agent.model_name.replace("models/", ""))

        active_char = getattr(agent, "active_character", "Alpha")
        self.tele_lbls["persona"].setText(f"★ {active_char.upper()}")

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
