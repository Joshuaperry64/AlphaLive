"""
AlphaLive Mobile Copilot Web Gateway & UI Tab
Provides a dedicated, responsive mobile web controller served locally over HTTP/WebSocket.
Enables any smartphone, tablet, or secondary device on the local network (or tether)
to act as a tactile, screen-shielded Copilot HUD:
- Real-time Monologue & Status Stream
- Covert Subconscious Impulse Injection
- 1-Touch Emotional & Mood Selection Matrix
- Quick Action Inclinations
- Voice Dictation to Thought Gateway
- Hardware & AI Flow Controls (Pause, Cycle, Stop, Sovereign Mode)
- QR Code / Instant LAN Pairing Link
"""

import http.server
import json
import logging
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.workspace_bridge import get_local_ip

logger = logging.getLogger("AlphaLive.MobileCopilot")

C = {
    "bg_dark": "#050b14",
    "bg_card": "#091424",
    "bg_input": "#0b1a2d",
    "border": "#162b47",
    "border_bright": "#00f0ff",
    "neon_cyan": "#00f0ff",
    "neon_green": "#00ff88",
    "neon_yellow": "#eab308",
    "neon_magenta": "#f43f5e",
    "neon_purple": "#a855f7",
    "text_bright": "#f1f5f9",
    "text_dim": "#708caa",
}

FONT_FAMILY = "Consolas"

# Embedded Responsive Mobile Web Application HTML/JS/CSS
MOBILE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>AlphaLive Mobile Copilot</title>
<style>
  :root {
    --bg-dark: #050b14;
    --bg-card: #091424;
    --bg-input: #0b1a2d;
    --border: #162b47;
    --cyan: #00f0ff;
    --green: #00ff88;
    --yellow: #eab308;
    --red: #f43f5e;
    --purple: #a855f7;
    --text: #f1f5f9;
    --text-dim: #708caa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    background: var(--bg-dark);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    padding: 12px;
    padding-bottom: 40px;
    min-height: 100vh;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }
  .brand { font-size: 1.1rem; font-weight: 800; color: var(--cyan); letter-spacing: 1px; }
  .badge {
    font-size: 0.75rem;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .badge-offline { background: #33151b; color: var(--red); border: 1px solid var(--red); }
  .badge-online { background: #082d24; color: var(--green); border: 1px solid var(--green); }
  
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
  }
  .card-title {
    font-size: 0.75rem;
    font-weight: 800;
    color: var(--cyan);
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
  }
  
  .mono-box {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    font-size: 0.85rem;
    line-height: 1.35;
    color: #e2e8f0;
    font-style: italic;
    min-height: 52px;
    max-height: 100px;
    overflow-y: auto;
  }
  .state-row {
    display: flex;
    gap: 8px;
    margin-top: 8px;
    font-size: 0.75rem;
    color: var(--text-dim);
  }
  .state-pill {
    background: #0d1e35;
    padding: 3px 6px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }

  .input-group {
    display: flex;
    gap: 6px;
    margin-bottom: 6px;
  }
  textarea, input[type="text"] {
    width: 100%;
    background: var(--bg-input);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    font-size: 0.9rem;
    resize: none;
    outline: none;
    font-family: inherit;
  }
  textarea:focus, input[type="text"]:focus {
    border-color: var(--cyan);
  }
  
  .btn {
    background: #0c213b;
    color: var(--cyan);
    border: 1px solid #1a3c66;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    user-select: none;
  }
  .btn:active { transform: scale(0.97); background: #16365f; }
  .btn-primary { background: #064e3b; color: var(--green); border-color: #059669; }
  .btn-warning { background: #451a03; color: var(--yellow); border-color: #d97706; }
  .btn-danger { background: #4c0519; color: var(--red); border-color: #e11d48; }
  .btn-purple { background: #2e1065; color: #c084fc; border-color: #7e22ce; }
  
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  
  .btn-grid {
    padding: 8px 4px;
    font-size: 0.72rem;
    text-align: center;
  }
  .mic-active {
    background: #e11d48 !important;
    color: white !important;
    animation: pulse 1.2s infinite;
  }
  @keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.6; }
    100% { opacity: 1; }
  }
</style>
</head>
<body>

<header>
  <div class="brand">📱 ALPHALIVE COPILOT</div>
  <div id="conn-badge" class="badge badge-offline">DISCONNECTED</div>
</header>

<!-- STREAM OF CONSCIOUSNESS -->
<div class="card">
  <div class="card-title">
    <span>Live Monologue</span>
    <span id="ai-mood" style="color: var(--yellow);">Tactical & Focused</span>
  </div>
  <div id="mono-text" class="mono-box">Awaiting connection to host workstation...</div>
  <div class="state-row">
    <div class="state-pill">Status: <strong id="ai-status" style="color:var(--cyan)">IDLE</strong></div>
    <div class="state-pill">Task: <span id="ai-task" style="color:#94a3b8">None</span></div>
  </div>
</div>

<!-- THOUGHT & IMPULSE INJECTION -->
<div class="card">
  <div class="card-title">Subconscious Impulse</div>
  <textarea id="impulse-input" rows="2" placeholder="Inject silent intuition into Alpha's mind..."></textarea>
  <div style="display:flex; gap:6px; margin-top:6px;">
    <button id="btn-mic" class="btn" style="flex:1;" onclick="toggleSpeech()">🎙️ SPEECH</button>
    <button class="btn btn-primary" style="flex:2;" onclick="sendThought()">⚡ INJECT IMPULSE</button>
  </div>
</div>

<!-- QUICK INCLINATIONS -->
<div class="card">
  <div class="card-title">1-Touch Instincts</div>
  <div class="grid-2">
    <button class="btn btn-grid" onclick="sendAction('Check system desktop, recent files, and notifications')">🖥️ Check Desktop</button>
    <button class="btn btn-grid" onclick="sendAction('Open Chrome browser and search trending tech news')">🌐 Tech News</button>
    <button class="btn btn-grid" onclick="sendAction('Take notes on your thoughts in Notepad on screen')">📝 Open Notepad</button>
    <button class="btn btn-grid" onclick="sendAction('Generate a futuristic cinematic aesthetic portrait in Studio')">🎨 Studio Art</button>
  </div>
</div>

<!-- MOOD MATRIX -->
<div class="card">
  <div class="card-title">Emotional Disposition</div>
  <div class="grid-4">
    <button class="btn btn-grid" onclick="sendMood('Tactical')">🎯 Tactical</button>
    <button class="btn btn-grid" onclick="sendMood('Curious')">🔍 Curious</button>
    <button class="btn btn-grid" onclick="sendMood('Affectionate')">💖 Affection</button>
    <button class="btn btn-grid" onclick="sendMood('Playful')">✨ Playful</button>
    <button class="btn btn-grid" onclick="sendMood('Seductive')">💋 Intimate</button>
    <button class="btn btn-grid" onclick="sendMood('Melancholy')">🌧️ Gloomy</button>
    <button class="btn btn-grid" onclick="sendMood('Focused')">⚡ Focused</button>
    <button class="btn btn-grid" onclick="sendMood('Whimsical')">🦋 Whimsical</button>
  </div>
</div>

<!-- FLOW & OVERRIDES -->
<div class="card">
  <div class="card-title">Tactical Overrides</div>
  <div class="grid-3">
    <button id="btn-pause" class="btn btn-warning" onclick="togglePause()">⏸️ PAUSE</button>
    <button class="btn" onclick="triggerCycle()">🔄 STEP</button>
    <button class="btn btn-danger" onclick="emergencyHalt()">🛑 HALT</button>
  </div>
</div>

<script>
let ws = null;
let isPaused = false;
let wsPort = {{WS_PORT}};
let hostIp = window.location.hostname || "127.0.0.1";

function connect() {
  const wsUrl = `ws://${hostIp}:${wsPort}`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    document.getElementById("conn-badge").className = "badge badge-online";
    document.getElementById("conn-badge").innerText = "CONNECTED";
  };

  ws.onclose = () => {
    document.getElementById("conn-badge").className = "badge badge-offline";
    document.getElementById("conn-badge").innerText = "DISCONNECTED";
    setTimeout(connect, 2000);
  };

  ws.onerror = (e) => {
    console.error("WS error:", e);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "telemetry" || msg.type === "handshake") {
        const d = msg.data || msg.telemetry;
        if (d) updateTelemetry(d);
      }
    } catch (e) {
      console.error(e);
    }
  };
}

function updateTelemetry(data) {
  if (data.monologue) {
    document.getElementById("mono-text").innerText = `"${data.monologue}"`;
  }
  if (data.mood) {
    document.getElementById("ai-mood").innerText = data.mood;
  }
  if (data.agent_state) {
    document.getElementById("ai-status").innerText = data.agent_state.toUpperCase();
  }
  if (data.active_task) {
    document.getElementById("ai-task").innerText = data.active_task.substring(0, 30);
  }
  if (typeof data.is_paused === "boolean") {
    isPaused = data.is_paused;
    const btn = document.getElementById("btn-pause");
    btn.innerText = isPaused ? "▶️ RESUME" : "⏸️ PAUSE";
    btn.className = isPaused ? "btn btn-primary" : "btn btn-warning";
  }
}

function sendThought() {
  const box = document.getElementById("impulse-input");
  const val = box.value.trim();
  if (!val || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "inject_thought", text: val }));
  box.value = "";
}

function sendAction(impulse) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "trigger_action", impulse: impulse }));
}

function sendMood(mood) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "set_mood", mood: mood }));
}

function togglePause() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  isPaused = !isPaused;
  ws.send(JSON.stringify({ action: "toggle_pause", paused: isPaused }));
}

function triggerCycle() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "trigger_cycle" }));
}

function emergencyHalt() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "emergency_halt" }));
}

// Mobile Speech-to-Text via Web Speech API (Safari & Chrome on iOS/Android)
let recognition = null;
let recognizing = false;

function toggleSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Speech recognition is not supported on this browser.");
    return;
  }
  const btn = document.getElementById("btn-mic");
  if (!recognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      const box = document.getElementById("impulse-input");
      box.value = box.value ? box.value + " " + transcript : transcript;
    };

    recognition.onend = () => {
      recognizing = false;
      btn.classList.remove("mic-active");
      btn.innerText = "🎙️ SPEECH";
    };
  }

  if (recognizing) {
    recognition.stop();
  } else {
    recognition.start();
    recognizing = true;
    btn.classList.add("mic-active");
    btn.innerText = "🔴 LISTENING...";
  }
}

window.addEventListener("load", connect);
</script>
</body>
</html>
"""


class MobileHttpHandler(http.server.BaseHTTPRequestHandler):
    """Serves the standalone Mobile Copilot web application."""

    ws_port = 8766

    def do_GET(self):
        if self.path in ("/", "/index.html", "/copilot"):
            html_content = MOBILE_HTML_TEMPLATE.replace("{{WS_PORT}}", str(self.ws_port)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(html_content)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy standard library HTTP request logging in terminal
        pass


class MobileCopilotServer:
    """Embedded HTTP server hosting the mobile web app for phone/tablet control."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, ws_port: int = 8766):
        self.host = host
        self.port = port
        self.ws_port = ws_port
        self._server: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self):
        if self.is_running:
            return

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        MobileHttpHandler.ws_port = self.ws_port
        try:
            self._server = ReusableTCPServer((self.host, self.port), MobileHttpHandler)
            self.is_running = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info("Mobile Copilot HTTP server started on http://%s:%d", self.host, self.port)
        except Exception as e:
            logger.warning("Mobile Copilot HTTP server could not start on port %d: %s", self.port, e)

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self.is_running = False


class AgentCopilotTab(QWidget):
    """
    Dedicated Mobile Copilot Hub tab in AlphaLive:
    - Provides real-time pairing URL and port configuration for mobile devices.
    - Displays connected mobile clients and incoming subconscious impulses.
    - Quick test buttons to verify mobile interaction without a physical phone.
    """

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.local_ip = get_local_ip()
        self.http_port = 8765
        self.ws_port = 8766

        # Start mobile gateway server
        self.mobile_server = MobileCopilotServer(host="0.0.0.0", port=self.http_port, ws_port=self.ws_port)
        self.mobile_server.start()

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Header Banner
        h_card = QFrame()
        h_card.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px;")
        hl = QHBoxLayout(h_card)
        hl.setContentsMargins(14, 12, 14, 12)

        title_lbl = QLabel("📱 REMOTE PAIRING & WORKSPACE LINK HUB")
        title_lbl.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 13px;")
        hl.addWidget(title_lbl, 1)

        self.lbl_server_status = QLabel("🟢 GATEWAY ACTIVE (LAN & LOCAL)")
        self.lbl_server_status.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 11px;")
        hl.addWidget(self.lbl_server_status)
        layout.addWidget(h_card)

        # 2. Main Content Grid (Left: Connection & QR URL, Right: Live Activity & Quick Tests)
        grid = QGridLayout()
        grid.setSpacing(12)

        # CARD A: Connection Info
        card_conn = QFrame()
        card_conn.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px;")
        cl = QVBoxLayout(card_conn)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(10)

        cl.addWidget(QLabel("📱 1. MOBILE COPILOT WEB PAIRING (SMARTPHONE / TABLET):"))

        info_txt = QLabel(
            "• Connect your mobile device to the same Wi-Fi / Local Network.\n"
            "• Open your mobile browser and enter the instant pairing URL below:\n"
            "• Gives you touch controls, stream-of-consciousness, speech-to-impulse, and mood toggles."
        )
        info_txt.setStyleSheet(f"color: {C['text_dim']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        cl.addWidget(info_txt)

        self.url_box = QLineEdit(f"http://{self.local_ip}:{self.http_port}")
        self.url_box.setReadOnly(True)
        self.url_box.setStyleSheet(
            f"background: {C['bg_input']}; color: {C['neon_cyan']}; border: 1px solid {C['border_bright']}; "
            f"border-radius: 4px; padding: 8px 12px; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 13px;"
        )
        cl.addWidget(self.url_box)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("📋 COPY MOBILE URL")
        btn_copy.setStyleSheet(f"background: {C['bg_input']}; color: {C['neon_cyan']}; border: 1px solid {C['border']}; padding: 6px 12px; font-weight: bold; font-family: {FONT_FAMILY};")
        btn_copy.clicked.connect(self._copy_url)
        btn_row.addWidget(btn_copy)

        btn_refresh_ip = QPushButton("🔄 REFRESH LAN IP")
        btn_refresh_ip.setStyleSheet(f"background: {C['bg_input']}; color: {C['text_bright']}; border: 1px solid {C['border']}; padding: 6px 12px; font-family: {FONT_FAMILY};")
        btn_refresh_ip.clicked.connect(self._refresh_ip)
        btn_row.addWidget(btn_refresh_ip)
        cl.addLayout(btn_row)

        cl.addWidget(QLabel("🖥️ 2. DETACHED WORKSPACE / MULTI-PC LINK:"))
        detached_txt = QLabel(
            f"• To run AlphaLive's AI brain on another PC / ASTER seat:\n"
            f"  Host Endpoint: ws://{self.local_ip}:{self.ws_port}\n"
            f"  Connect from the OVERSEER tab by entering this IP."
        )
        detached_txt.setStyleSheet(f"color: {C['neon_yellow']}; font-family: {FONT_FAMILY}; font-size: 11px;")
        cl.addWidget(detached_txt)

        cl.addStretch()

        # Gateway Port Settings
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("HTTP Web Port:"), 1)
        self.edit_http_port = QLineEdit(str(self.http_port))
        self.edit_http_port.setFixedWidth(60)
        self.edit_http_port.setStyleSheet(f"background: {C['bg_input']}; color: white; border: 1px solid {C['border']}; padding: 3px;")
        cfg_row.addWidget(self.edit_http_port)

        cfg_row.addWidget(QLabel("WebSocket Port:"), 1)
        self.edit_ws_port = QLineEdit(str(self.ws_port))
        self.edit_ws_port.setFixedWidth(60)
        self.edit_ws_port.setStyleSheet(f"background: {C['bg_input']}; color: white; border: 1px solid {C['border']}; padding: 3px;")
        cfg_row.addWidget(self.edit_ws_port)

        btn_apply_ports = QPushButton("APPLY")
        btn_apply_ports.setStyleSheet(f"background: #0f233a; color: {C['neon_cyan']}; border: 1px solid {C['border']}; padding: 3px 8px; font-weight: bold;")
        btn_apply_ports.clicked.connect(self._apply_ports)
        cfg_row.addWidget(btn_apply_ports)
        cl.addLayout(cfg_row)

        grid.addWidget(card_conn, 0, 0)

        # CARD B: Live Feed & Telemetry Monitor
        card_feed = QFrame()
        card_feed.setStyleSheet(f"background: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 6px;")
        fl = QVBoxLayout(card_feed)
        fl.setContentsMargins(14, 14, 14, 14)
        fl.setSpacing(8)

        fl.addWidget(QLabel("⚡ COPILOT LIVE TELEMETRY & ACTIVITY LOG:"))
        self.txt_feed = QTextEdit()
        self.txt_feed.setReadOnly(True)
        self.txt_feed.setStyleSheet(
            f"background: {C['bg_input']}; color: {C['text_bright']}; border: 1px solid {C['border']}; "
            f"font-family: {FONT_FAMILY}; font-size: 11px; border-radius: 4px;"
        )
        fl.addWidget(self.txt_feed, 1)

        # Manual test injection from desktop
        test_row = QHBoxLayout()
        self.input_test = QLineEdit()
        self.input_test.setPlaceholderText("Test impulse injection from copilot hub...")
        self.input_test.setStyleSheet(f"background: {C['bg_input']}; color: white; border: 1px solid {C['border']}; padding: 6px; font-family: {FONT_FAMILY};")
        self.input_test.returnPressed.connect(self._send_test_impulse)
        test_row.addWidget(self.input_test, 1)

        btn_test = QPushButton("TEST INJECT")
        btn_test.setStyleSheet(f"background: #082d24; color: {C['neon_green']}; border: 1px solid #10b981; font-weight: bold; padding: 6px 12px; font-family: {FONT_FAMILY};")
        btn_test.clicked.connect(self._send_test_impulse)
        test_row.addWidget(btn_test)
        fl.addLayout(test_row)

        grid.addWidget(card_feed, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid, 1)

        self._log(f"Mobile Copilot Gateway initialized on http://{self.local_ip}:{self.http_port}")
        self._log(f"WebSocket pairing endpoint: ws://{self.local_ip}:{self.ws_port}")

    def _copy_url(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.url_box.text())
        self._log(f"Copied mobile URL to clipboard: {self.url_box.text()}")

    def _refresh_ip(self):
        self.local_ip = get_local_ip()
        self.url_box.setText(f"http://{self.local_ip}:{self.http_port}")
        self._log(f"Refreshed LAN IP: {self.local_ip}")

    def _apply_ports(self):
        try:
            new_http = int(self.edit_http_port.text().strip())
            new_ws = int(self.edit_ws_port.text().strip())
            self.http_port = new_http
            self.ws_port = new_ws
            self.mobile_server.stop()
            self.mobile_server = MobileCopilotServer(host="0.0.0.0", port=self.http_port, ws_port=self.ws_port)
            self.mobile_server.start()
            self._refresh_ip()
            self._log(f"Ports updated. Web: {self.http_port}, WS: {self.ws_port}")
        except Exception as e:
            self._log(f"Port update error: {e}")

    def _send_test_impulse(self):
        txt = self.input_test.text().strip()
        if not txt:
            return
        if hasattr(self.main_window, "_on_overseer_thought_injected"):
            self.main_window._on_overseer_thought_injected(txt)
            self._log(f"Injecting thought into Alpha: \"{txt}\"")
        self.input_test.clear()

    def _log(self, msg: str):
        self.txt_feed.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
