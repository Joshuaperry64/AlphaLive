import re

with open('ui/agent_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace setting tab UI
search_ws_tab = """        # Multi-Workspace Group (Postponed Placeholder)
        grp_multi_ws = QGroupBox("🌐 MULTI-WORKSPACE & ASTER NETWORKING [COMING SOON]")
        grp_multi_ws.setStyleSheet(f"QGroupBox {{ color: #708caa; font-weight: bold; border: 1px dashed {C['border']}; border-radius: 6px; padding-top: 15px; margin-top: 6px; }}")
        ws_layout = QVBoxLayout(grp_multi_ws)
        ws_layout.setSpacing(6)
        lbl_ws_info = QLabel("⏳ [FEATURE POSTPONED // COMING SOON]\\nMulti-Workspace ASTER multiseat & remote network cockpit integration is currently postponed.")
        lbl_ws_info.setStyleSheet("color: #eab308; font-size: 8pt; font-family: Consolas;")
        lbl_ws_info.setWordWrap(True)
        ws_layout.addWidget(lbl_ws_info)

        row_ws_ph = QHBoxLayout()
        chk_ws_placeholder = QCheckBox("🌐 Multi-Workspace Mode (Postponed)")
        chk_ws_placeholder.setEnabled(False)
        chk_ws_placeholder.setStyleSheet("color: #4a5d73; font-weight: bold; font-family: Consolas;")
        row_ws_ph.addWidget(chk_ws_placeholder, 2)

        btn_launch_ws_ph = QPushButton("🚀 LAUNCH REMOTE COCKPIT [SOON]")
        btn_launch_ws_ph.setEnabled(False)
        btn_launch_ws_ph.setStyleSheet(f"background: #08111d; color: #4a5d73; border: 1px dashed {C['border']}; border-radius: 4px; padding: 4px 8px; font-family: Consolas; font-size: 10px; font-weight: bold;")
        row_ws_ph.addWidget(btn_launch_ws_ph, 1)
        ws_layout.addLayout(row_ws_ph)
        l_auto.addWidget(grp_multi_ws)"""

replace_ws_tab = """        # Multi-Workspace Group
        grp_multi_ws = QGroupBox("🌐 MULTI-WORKSPACE & ASTER NETWORKING")
        grp_multi_ws.setStyleSheet(f"QGroupBox {{ color: {C['text_bright']}; font-weight: bold; border: 1px solid {C['border']}; border-radius: 6px; padding-top: 15px; margin-top: 6px; }}")
        ws_layout = QVBoxLayout(grp_multi_ws)
        ws_layout.setSpacing(6)
        lbl_ws_info = QLabel("Enable Multi-Workspace Mode to start a local WebSocket server (ASTER multiseat & remote network).")
        lbl_ws_info.setStyleSheet("color: #708caa; font-size: 8pt; font-family: Consolas;")
        lbl_ws_info.setWordWrap(True)
        ws_layout.addWidget(lbl_ws_info)

        row_ws_ph = QHBoxLayout()
        self.chk_workspace_mode = QCheckBox("🌐 Multi-Workspace Mode")
        self.chk_workspace_mode.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: Consolas;")
        self.chk_workspace_mode.setChecked(getattr(self.agent, "workspace_mode", False))
        row_ws_ph.addWidget(self.chk_workspace_mode, 2)

        self.btn_launch_ws = QPushButton("🚀 LAUNCH REMOTE COCKPIT")
        self.btn_launch_ws.setStyleSheet(btn_base_style)
        self.btn_launch_ws.clicked.connect(self._launch_remote_cockpit)
        row_ws_ph.addWidget(self.btn_launch_ws, 1)
        ws_layout.addLayout(row_ws_ph)
        l_auto.addWidget(grp_multi_ws)"""

content = content.replace(search_ws_tab, replace_ws_tab)

# Update _save_automation_settings
search_save_auto = """            self.agent.unobserved_mode = self.chk_unobserved_mode.isChecked()
            self.agent.studio_mode = self.chk_studio_mode.isChecked()"""
replace_save_auto = """            self.agent.unobserved_mode = self.chk_unobserved_mode.isChecked()
            self.agent.studio_mode = self.chk_studio_mode.isChecked()
            self.agent.workspace_mode = self.chk_workspace_mode.isChecked()
            self._apply_workspace_mode()"""
content = content.replace(search_save_auto, replace_save_auto)

search_save_auto_cfg = """                cfg["Global"]["UnobservedMode"] = self.agent.unobserved_mode
                cfg["Global"]["StudioMode"] = self.agent.studio_mode"""
replace_save_auto_cfg = """                cfg["Global"]["UnobservedMode"] = self.agent.unobserved_mode
                cfg["Global"]["StudioMode"] = self.agent.studio_mode
                cfg["Global"]["WorkspaceMode"] = self.agent.workspace_mode"""
content = content.replace(search_save_auto_cfg, replace_save_auto_cfg)

# Update sidebar workspace button
search_sidebar_btn = """        self.btn_t_workspace = QPushButton("MULTI-WS: SOON")
        self.btn_t_workspace.setEnabled(False)
        self.btn_t_workspace.setFixedHeight(27)
        self.btn_t_workspace.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_t_workspace.setStyleSheet(f"background: transparent; color: #4b6079; border: 1px dashed {C['border']}; border-radius: 4px;")
        self.btn_t_workspace.setToolTip("Multi-Workspace Mode (ASTER Multiseat & LAN Remote Link) — Feature Postponed / Coming Soon")"""

replace_sidebar_btn = """        self.btn_t_workspace = QPushButton("MULTI-WS: OFF")
        self.btn_t_workspace.setCheckable(True)
        self.btn_t_workspace.setFixedHeight(27)
        self.btn_t_workspace.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_t_workspace.setToolTip("Multi-Workspace Mode (ASTER Multiseat & LAN Remote Link)")"""

content = content.replace(search_sidebar_btn, replace_sidebar_btn)

# Add click event for sidebar btn
search_clicks = """        self.btn_t_unobserved.clicked.connect(self._toggle_quick_unobserved)"""
replace_clicks = """        self.btn_t_unobserved.clicked.connect(self._toggle_quick_unobserved)
        self.btn_t_workspace.clicked.connect(self._toggle_quick_workspace)"""
content = content.replace(search_clicks, replace_clicks)

# Update _sync_toggles
search_sync_toggles = """        if getattr(self.agent, "unobserved_mode", False):
            self.btn_t_unobserved.setText("? PRIVACY: ON")
            self.btn_t_unobserved.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_t_unobserved.setChecked(True)
        else:
            self.btn_t_unobserved.setText("🕶 PRIVACY: OFF")
            self.btn_t_unobserved.setStyleSheet("color: #708caa;")
            self.btn_t_unobserved.setChecked(False)"""

replace_sync_toggles = """        if getattr(self.agent, "unobserved_mode", False):
            self.btn_t_unobserved.setText("? PRIVACY: ON")
            self.btn_t_unobserved.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_t_unobserved.setChecked(True)
        else:
            self.btn_t_unobserved.setText("🕶 PRIVACY: OFF")
            self.btn_t_unobserved.setStyleSheet("color: #708caa;")
            self.btn_t_unobserved.setChecked(False)

        if getattr(self.agent, "workspace_mode", False):
            self.btn_t_workspace.setText("MULTI-WS: ON")
            self.btn_t_workspace.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_t_workspace.setChecked(True)
        else:
            self.btn_t_workspace.setText("MULTI-WS: OFF")
            self.btn_t_workspace.setStyleSheet("color: #708caa;")
            self.btn_t_workspace.setChecked(False)"""

content = content.replace(search_sync_toggles, replace_sync_toggles)


with open('ui/agent_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
