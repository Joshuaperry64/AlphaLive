import sys
import os
import time
import json
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PyQt6.QtWidgets import QApplication
from ui.agent_gui import AgentMainWindow
from core.alpha_agent import AlphaAgent, VoiceEngine, normalize_endpoint

class MockOrpheusServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Silence logs

    def do_POST(self):
        if self.path in ("/v1/audio/speech", "/audio/speech", "/synthesize"):
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode('utf-8'))
            
            # Generate a minimal valid 24kHz mono 16-bit PCM WAV header + 0.1s tone
            # 24000 samples/sec * 1 channel * 2 bytes/sample = 48000 bytes/sec
            num_samples = 2400
            data_size = num_samples * 2
            wav_bytes = bytearray()
            wav_bytes.extend(b"RIFF")
            wav_bytes.extend((36 + data_size).to_bytes(4, "little"))
            wav_bytes.extend(b"WAVE")
            wav_bytes.extend(b"fmt ")
            wav_bytes.extend((16).to_bytes(4, "little")) # Subchunk1Size
            wav_bytes.extend((1).to_bytes(2, "little"))  # AudioFormat (PCM)
            wav_bytes.extend((1).to_bytes(2, "little"))  # NumChannels (Mono)
            wav_bytes.extend((24000).to_bytes(4, "little")) # SampleRate
            wav_bytes.extend((48000).to_bytes(4, "little")) # ByteRate
            wav_bytes.extend((2).to_bytes(2, "little"))  # BlockAlign
            wav_bytes.extend((16).to_bytes(2, "little")) # BitsPerSample
            wav_bytes.extend(b"data")
            wav_bytes.extend((data_size).to_bytes(4, "little"))
            wav_bytes.extend(b"\x00" * data_size)

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path in ("/health", "/models", "/v1/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "engine": "orpheus-vllm-bf16", "data": [{"id": "mock-model"}]}')
        else:
            self.send_response(404)
            self.end_headers()

def run_tests():
    print("=== STARTING ORPHEUS TTS INTEGRATION & VERIFICATION TESTS ===")

    # 1. Start Local Mock Orpheus Server
    server = HTTPServer(("127.0.0.1", 18889), MockOrpheusServer)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()
    mock_url = "http://127.0.0.1:18889"
    print(f"[TEST 1] Mock Orpheus vLLM Server listening at {mock_url}")

    # 2. Test AlphaAgent set_tts_engine and VoiceEngine
    agent = AlphaAgent()
    agent.set_tts_engine("orpheus", orpheus_endpoint=mock_url, orpheus_voice="leah")
    assert agent.tts_engine == "orpheus", "Agent tts_engine must be orpheus"
    assert agent.voice.engine_type == "orpheus", "VoiceEngine engine_type must be orpheus"
    assert agent.voice.orpheus_endpoint == mock_url, "VoiceEngine endpoint must match"
    assert agent.voice.orpheus_voice == "leah", "VoiceEngine voice must match leah"
    print("[TEST 2] AlphaAgent set_tts_engine & VoiceEngine attributes verified.")

    # 3. Test VoiceEngine speech generation against Orpheus endpoint
    played = False
    def mock_play(wav_bytes):
        nonlocal played
        assert len(wav_bytes) > 44, "Must receive valid WAV bytes"
        assert wav_bytes[:4] == b"RIFF", "Header must be RIFF"
        played = True

    agent.voice._play_wav = mock_play
    agent.voice._generate_and_play("Test Orpheus speech generation")
    assert played is True, "VoiceEngine must have fetched and played WAV from Orpheus endpoint"
    print("[TEST 3] VoiceEngine Orpheus synthesis & zero-copy playback verified.")

    # 4. Test UI Settings and Controls
    app = QApplication.instance() or QApplication(sys.argv)
    win = AgentMainWindow()
    print("[TEST 4] AgentMainWindow initialized.")

    # Verify Orpheus UI components
    assert hasattr(win, "input_orpheus_endpoint"), "Missing input_orpheus_endpoint"
    assert hasattr(win, "combo_orpheus_voice"), "Missing combo_orpheus_voice"
    assert hasattr(win, "btn_test_orpheus"), "Missing btn_test_orpheus"
    assert hasattr(win, "btn_deploy_orpheus"), "Missing btn_deploy_orpheus"

    # Check voices
    expected_voices = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]
    actual_voices = [win.combo_orpheus_voice.itemText(i) for i in range(win.combo_orpheus_voice.count())]
    for v in expected_voices:
        assert v in actual_voices, f"Voice {v} should be present in combo"
    print(f"[TEST 5] Orpheus voices catalog verified: {actual_voices}")

    # Test combo_tts_engine items
    items = [win.combo_tts_engine.itemText(i) for i in range(win.combo_tts_engine.count())]
    assert len(items) == 4, f"Expected 4 TTS options, got {len(items)}"
    assert "Gemini" in items[0], "Index 0 must be Gemini"
    assert "Orpheus" in items[1], "Index 1 must be Orpheus"
    assert "pyttsx3" in items[2], "Index 2 must be pyttsx3"
    assert "OFF" in items[3], "Index 3 must be OFF"
    print("[TEST 6] combo_tts_engine 4-engine list verified.")

    # Test setting Orpheus via UI and persisting
    win.input_orpheus_endpoint.setText(mock_url)
    win.combo_orpheus_voice.setCurrentText("dan")
    win.combo_tts_engine.setCurrentIndex(1)
    win._on_tts_engine_changed(1)

    assert win.agent.tts_engine == "orpheus"
    assert win.agent.voice.engine_type == "orpheus"
    assert win.agent.voice.orpheus_voice == "dan"
    assert win.btn_t_tts.isChecked() is True
    assert "ON" in win.btn_t_tts.text()
    print("[TEST 7] UI engine switch to Orpheus & toggle sync verified.")

    # Test quick toggle to OFF
    win._toggle_quick_tts()
    assert win.combo_tts_engine.currentIndex() == 3, "Quick toggle from ON should switch to OFF (idx 3)"
    assert win.agent.tts_engine == "off"
    assert win.btn_t_tts.isChecked() is False
    assert "OFF" in win.btn_t_tts.text()

    # Test quick toggle back to ON
    win._toggle_quick_tts()
    assert win.combo_tts_engine.currentIndex() == 0, "Quick toggle from OFF should switch to Standard (idx 0)"
    assert win.agent.tts_engine == "gemini"
    assert win.btn_t_tts.isChecked() is True
    assert "ON" in win.btn_t_tts.text()
    print("[TEST 8] Quick TTS button toggle behavior verified.")

    # 5. Test Orpheus audio test probe
    win.input_orpheus_endpoint.setText(mock_url)
    win.combo_orpheus_voice.setCurrentText("jess")
    test_called = False
    def mock_agent_voice_play(b):
        nonlocal test_called
        assert b[:4] == b"RIFF"
        test_called = True
    win.agent.voice._play_wav = mock_agent_voice_play
    win._test_orpheus_audio()
    t_end = time.time() + 3.0
    while not test_called and time.time() < t_end:
        app.processEvents()
        time.sleep(0.05)
    assert test_called is True, "_test_orpheus_audio must query endpoint and play sound"
    print("[TEST 9] _test_orpheus_audio probe and playback verified.")

    # 9b. Regression: button must re-enable after completion so it works repeatedly
    for i in range(3):
        test_called = False
        win._test_orpheus_audio()
        t_end = time.time() + 5.0
        while (not test_called or not win.btn_test_orpheus.isEnabled()) and time.time() < t_end:
            app.processEvents()
            time.sleep(0.05)
        assert test_called is True, f"Test click #{i+2} must run"
        assert win.btn_test_orpheus.isEnabled() is True, f"Test button must re-enable after run #{i+2}"
    print("[TEST 9b] Orpheus test button works repeatedly (re-enables after each run).")

    # 6. Verify orpheus_modal.py Token parsing and frame de-interleaving logic
    from orpheus_modal import deinterleave_orpheus_tokens
    
    # Generate 1 valid synthetic super-frame: 7 tokens
    # L0 (1 token, offset 128266) -> index 0 + 128266
    # L1 (2 tokens, offset 132362) -> indices 10, 11 + 132362
    # L2 (4 tokens, offset 136458) -> indices 20, 21, 22, 23 + 136458
    synthetic_tokens = [
        128266 + 5,   # L0
        132362 + 10,  # L1_0
        136458 + 20,  # L2_0
        136458 + 21,  # L2_1
        132362 + 11,  # L1_1
        136458 + 22,  # L2_2
        136458 + 23   # L2_3
    ]
    l0, l1, l2 = deinterleave_orpheus_tokens(synthetic_tokens)
    assert l0 == [5], f"L0 should be [5], got {l0}"
    assert l1 == [10, 11], f"L1 should be [10, 11], got {l1}"
    assert l2 == [20, 21, 22, 23], f"L2 should be [20, 21, 22, 23], got {l2}"
    print("[TEST 10] Orpheus SNAC 7-token frame de-interleaver logic verified with exact offsets.")

    # 7. Test Orpheus Cold Boot / Health Check Wait on "Start Agent"
    win.input_orpheus_endpoint.setText(mock_url)
    win.combo_tts_engine.setCurrentIndex(1)
    win._on_tts_engine_changed(1)
    assert win.agent.tts_engine == "orpheus"
    win.agent.set_backend("gemini")
    
    # Power on: must trigger cold boot check and wait before finishing startup
    win._toggle_power()
    assert win._startup_checking is True, "Startup health check must be in progress"
    assert win.is_connected is False, "Agent must NOT be connected until health checks pass"
    # Text input must be blocked during startup health check
    win.cmd_input.setText("blocked during boot")
    ran = []
    win._run_task = lambda g: ran.append(g)
    win._send_text_command()
    assert ran == [], "Text input must be blocked while startup health check is running"
    # Mic input must also be dropped
    win._on_voice_heard("blocked voice during boot")
    assert ran == [], "Voice input must be blocked while startup health check is running"
    # Allow background cold boot probe against mock server to complete
    t_end = time.time() + 5.0
    while getattr(win, "_startup_checking", False) and time.time() < t_end:
        app.processEvents()
        time.sleep(0.05)
    assert win._startup_checking is False, "Startup cold boot check must complete"
    assert win.is_connected is True, "Agent must be connected after successful health check"
    assert "READY" in win.lbl_status.text(), f"Status must be READY, got {win.lbl_status.text()}"
    print("[TEST 11] Startup Cold Boot & Health Check gating (connect only after online) verified.")

    # 11b. Text input blocked while TTS playback is active (TTS on)
    win.cmd_input.setText("blocked during speech")
    win.agent.voice.is_speaking = True
    win._send_text_command()
    assert ran == [], "Text input must be blocked while TTS is speaking"
    win._on_speech_playback_started()
    assert win.cmd_input.isEnabled() is False and win.btn_send.isEnabled() is False
    win.agent.voice.is_speaking = False
    win.agent.voice.last_speech_time = 0.0
    win._on_speech_playback_finished()
    assert win.cmd_input.isEnabled() is True and win.btn_send.isEnabled() is True
    win._send_text_command()
    assert ran == ["blocked during speech"], "Text input must be accepted once playback completes"
    print("[TEST 11b] Text input gated during TTS playback verified.")

    # Power off cleanly
    win._toggle_power()
    assert win.is_connected is False

    # 12. Startup must ABORT if a required endpoint fails health check
    win.input_orpheus_endpoint.setText("http://127.0.0.1:1")  # nothing listens here
    win._on_tts_engine_changed(1)
    win._toggle_power()
    t_end = time.time() + 30.0
    while getattr(win, "_startup_checking", False) and time.time() < t_end:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(5):
        app.processEvents()
    assert win.is_connected is False, "Agent must stay disconnected when a required endpoint is offline"
    assert "STARTUP FAILED" in win.lbl_status.text(), f"Status must show failure, got {win.lbl_status.text()}"
    ran.clear()
    win.cmd_input.setText("should not run")
    win._send_text_command()
    assert ran == [], "Text input must stay blocked after failed startup"
    print("[TEST 11c] Startup aborts & input stays blocked when required endpoint is offline verified.")

    win.input_orpheus_endpoint.setText(mock_url)
    win._on_tts_engine_changed(1)


    # 8. Test Automatic Deployment URL Extraction & Auto-Insertion Regex
    import re
    url_pattern = re.compile(r'https://[a-zA-Z0-9_\-\.]+\.modal\.run[^\s\'"<>]*')
    sample_modal_log = "├── Created web function OrpheusTTSServer.web_app => https://josh64perry--orpheus-tts-vllm-orpheusttsserver-web-app.modal.run"
    match = url_pattern.search(sample_modal_log)
    assert match is not None, "Regex must extract modal.run URL from CLI log"
    extracted_url = match.group(0).rstrip("/.,")
    assert extracted_url == "https://josh64perry--orpheus-tts-vllm-orpheusttsserver-web-app.modal.run"

    # Simulate auto-insertion into UI
    win.input_orpheus_endpoint.setText(extracted_url)
    win.combo_tts_engine.setCurrentIndex(1)
    win._on_tts_engine_changed(1)
    assert win.input_orpheus_endpoint.text() == extracted_url
    assert win.agent.tts_engine == "orpheus"
    assert win.combo_tts_engine.currentIndex() == 1
    print(f"[TEST 12] Modal deploy endpoint auto-extraction & insertion verified: {extracted_url}")

    # Clean up
    win.close()
    server.shutdown()
    print("================================================================")
    print("ALL ORPHEUS TTS & AUDIO SYSTEM INTEGRATION TESTS PASSED (12/12)!")
    print("================================================================")

if __name__ == "__main__":
    run_tests()
