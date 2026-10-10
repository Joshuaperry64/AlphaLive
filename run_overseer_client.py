"""
AlphaLive // Standalone Remote Overseer Cockpit
Dedicated client designed for Workplace 1 (Josh's Desktop) when operating in Multi-Workspace mode (IBIK ASTER or LAN).
- Connects over WebSocket to the AI Workstation (Workplace 2 / Host).
- Captures voice locally on Workplace 1 and diverts spoken thoughts to the AI's subconscious queue.
- Excluded from screen captures via WDA_EXCLUDEFROMCAPTURE.
- Controls AI mood, inclinations, pause/resume, and emergency halt remotely.
"""

import argparse
import os
import sys
import time

# Ensure project path is accessible
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PyQt6.QtWidgets import QApplication
from core.workspace_bridge import WorkspaceClient
from ui.overseer_dashboard import EnhancedOverseerDashboard


def main():
    parser = argparse.ArgumentParser(description="AlphaLive Remote Overseer Client (Workplace 1)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Target AI Workstation Host/IP (default: 127.0.0.1 for ASTER)")
    parser.add_argument("--port", type=int, default=8766, help="Target AI Workstation Port (default: 8766)")
    parser.add_argument("--no-mic", action="store_true", help="Disable local microphone listener on Workplace 1")
    args = parser.parse_args()

    print("=" * 60)
    print(" ALPHALIVE // ENHANCED OVERSEER COCKPIT (REMOTE)")
    print(f" Connecting to AI Workstation at ws://{args.host}:{args.port}")
    print("=" * 60)

    app = QApplication.instance() or QApplication(sys.argv)

    # Initialize Remote Bridge Client
    client = WorkspaceClient(host=args.host, port=args.port)

    # Instantiate Enhanced Overseer Dashboard
    panel = EnhancedOverseerDashboard(remote_client=client)
    panel.show()

    # Automatically connect to host
    panel.remote_client.connect(host=args.host, port=args.port)

    # Optional local microphone listener for Workplace 1
    voice_listener = None
    if not args.no_mic:
        try:
            from core.alpha_agent import VoiceListener
            def _on_speech(text: str):
                panel.on_voice_received(text)

            voice_listener = VoiceListener(
                on_speech_callback=_on_speech,
                is_busy_fn=lambda: False,
                duplex_mode="half"
            )
            voice_listener.start()
            print("[Remote Overseer] Local microphone active on Workplace 1. Voice diverted to subconscious box.", flush=True)
        except Exception as e:
            print(f"[Remote Overseer] Local microphone not available: {e}. Touch/text input active.", flush=True)

    def _cleanup():
        if voice_listener:
            voice_listener.stop()
        if client:
            client.disconnect()

    app.aboutToQuit.connect(_cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
