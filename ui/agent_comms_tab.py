import json
import time
from datetime import datetime
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
import ssl
import certifi

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QFrame, QSplitter, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

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

# MQTT Default Config (Matching AlphaComms)
MQTT_BROKER_HOST = "4610d74c0f544c1da5ff299057ce2551.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USERNAME = "Alpha"
MQTT_PASSWORD = "Secretpassword1"

TOPIC_UPLINK = "gateway/uplink"
TOPIC_DOWNLINK = "gateway/downlink"

class MqttWorker(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    message_received = pyqtSignal(str, str) # topic, payload

    def __init__(self):
        super().__init__()
        if mqtt is not None:
            self.client = mqtt.Client(client_id="AlphaLive_Server", protocol=mqtt.MQTTv311)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            self.client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLSv1_2)
        else:
            self.client = None
        
    def connect_broker(self):
        if not self.client:
            print("[MQTT] paho-mqtt not installed; comms broker unavailable.")
            return
        try:
            self.client.connect(MQTT_BROKER_HOST, MQTT_PORT, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[MQTT Error] {e}")

    def disconnect_broker(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def publish(self, topic, payload):
        if self.client:
            self.client.publish(topic, payload, qos=1)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.client.subscribe(TOPIC_UPLINK, qos=1)
            self.connected.emit()
        else:
            print(f"[MQTT] Connect failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.disconnected.emit()

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode('utf-8')
        self.message_received.emit(msg.topic, payload)


class AgentCommsTab(QWidget):
    """
    Integrates AlphaComms (Wearable/Remote Rig) via MQTT into AlphaLive UI.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window # Reference to AlphaAgent GUI
        self.mqtt_worker = MqttWorker()
        self.mqtt_worker.connected.connect(self.on_mqtt_connected)
        self.mqtt_worker.disconnected.connect(self.on_mqtt_disconnected)
        self.mqtt_worker.message_received.connect(self.on_mqtt_message)
        
        # We also need a way to intercept responses from AlphaLive to pipe to Downlink.
        # We will attach to a signal if possible, or monkey-patch the TTS method for now.
        self._hook_alpha_responses()

        self.init_ui()
        
    def _hook_alpha_responses(self):
        """We need to know when AlphaLive generates a response so we can send it to the wearable."""
        if hasattr(self.main_window, 'signals'):
            self.main_window.signals.log_message.connect(self._intercepted_log)
            
    def _intercepted_log(self, text, color):
        if text.startswith("[Alpha]:"):
            msg = text.replace("[Alpha]:", "").strip()
            self.mqtt_worker.publish(TOPIC_DOWNLINK, msg)
            self.log(f"DOWNLINK TX (AUTO): {msg}", C['neon_magenta'])
        elif text.startswith("[Alpha Continued]:"):
            msg = text.replace("[Alpha Continued]:", "").strip()
            self.mqtt_worker.publish(TOPIC_DOWNLINK, msg)
            self.log(f"DOWNLINK TX (AUTO): {msg}", C['neon_magenta'])

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. Header / Status
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {C['bg_card']}; border: 1px solid {C['border']}; border-radius: 5px;")
        header_layout = QHBoxLayout(header_frame)
        
        title_lbl = QLabel("?? ALPHA COMMS : WEARABLE UPLINK")
        title_lbl.setStyleSheet(f"color: {C['neon_cyan']}; font-weight: bold; font-size: 14px; border: none;")
        
        self.status_lbl = QLabel("STATUS: OFFLINE")
        self.status_lbl.setStyleSheet(f"color: {C['neon_red']}; font-weight: bold; border: none;")
        
        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setStyleSheet(f"background-color: {C['border']}; color: {C['text_bright']}; padding: 5px 15px;")
        self.btn_connect.clicked.connect(self.toggle_connection)
        
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.status_lbl)
        header_layout.addWidget(self.btn_connect)
        layout.addWidget(header_frame)

        # 2. Main Splitter (Logs vs Manual Control)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # -- Log Area
        log_group = QGroupBox("LIVE TELEMETRY")
        log_group.setStyleSheet(f"color: {C['neon_blue']}; font-weight: bold;")
        log_layout = QVBoxLayout(log_group)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(f"background-color: {C['bg_deep']}; color: {C['text_bright']}; font-family: Consolas; border: 1px solid {C['border']};")
        log_layout.addWidget(self.log_area)
        splitter.addWidget(log_group)

        # -- Downlink Control
        ctrl_group = QGroupBox("DOWNLINK TRANSMISSION")
        ctrl_group.setStyleSheet(f"color: {C['neon_purple']}; font-weight: bold;")
        ctrl_layout = QHBoxLayout(ctrl_group)
        
        self.input_msg = QLineEdit()
        self.input_msg.setPlaceholderText("Enter manual message to broadcast to rig...")
        self.input_msg.setStyleSheet(f"background-color: {C['bg_deep']}; color: {C['text_bright']}; padding: 5px; border: 1px solid {C['border']};")
        self.input_msg.returnPressed.connect(self.send_downlink)
        
        self.btn_send = QPushButton("SEND TO RIG")
        self.btn_send.setStyleSheet(f"background-color: {C['border']}; color: {C['neon_cyan']}; padding: 5px 15px; font-weight: bold;")
        self.btn_send.clicked.connect(self.send_downlink)

        ctrl_layout.addWidget(self.input_msg)
        ctrl_layout.addWidget(self.btn_send)
        splitter.addWidget(ctrl_group)

        splitter.setSizes([400, 100])
        layout.addWidget(splitter)

    def log(self, text, color=C['text_dim']):
        ts = datetime.now().strftime("%H:%M:%S")
        html = f"<span style='color:{C['text_dim']};'>[{ts}]</span> <span style='color:{color};'>{text}</span>"
        self.log_area.append(html)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def toggle_connection(self):
        if self.btn_connect.text() == "CONNECT":
            self.log("Initializing MQTT connection to Rig...", C['neon_yellow'])
            self.mqtt_worker.connect_broker()
        else:
            self.log("Severing MQTT connection.", C['neon_yellow'])
            self.mqtt_worker.disconnect_broker()

    def on_mqtt_connected(self):
        self.status_lbl.setText("STATUS: ONLINE")
        self.status_lbl.setStyleSheet(f"color: {C['neon_green']}; font-weight: bold; border: none;")
        self.btn_connect.setText("DISCONNECT")
        self.log(f"Connected to Cloud Broker. Listening on {TOPIC_UPLINK}", C['neon_green'])

    def on_mqtt_disconnected(self):
        self.status_lbl.setText("STATUS: OFFLINE")
        self.status_lbl.setStyleSheet(f"color: {C['neon_red']}; font-weight: bold; border: none;")
        self.btn_connect.setText("CONNECT")
        self.log("Disconnected from Cloud Broker.", C['neon_red'])

    def on_mqtt_message(self, topic, payload):
        self.log(f"UPLINK RCV: {payload}", C['neon_blue'])
        if hasattr(self.main_window, '_run_task'):
            self.log("Routing to Alpha Core...", C['neon_magenta'])
            self.main_window._append_log(f"[UPLINK] {payload}", C["neon_cyan"])
            self.main_window._run_task(payload)

    def send_downlink(self):
        msg = self.input_msg.text().strip()
        if not msg: return
        self.mqtt_worker.publish(TOPIC_DOWNLINK, msg)
        self.log(f"DOWNLINK TX: {msg}", C['neon_purple'])
        self.input_msg.clear()
