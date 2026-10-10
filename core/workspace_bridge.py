"""
AlphaLive // Multi-Workspace Remote Overseer Bridge
Provides local network & ASTER multiseat pairing between:
- Host Workstation (Workplace 2 / AI Desktop): Runs the AI agent, executes desktop actions, streams internal telemetry.
- Remote Overseer Client (Workplace 1 / Josh's Desktop): Runs the touch-friendly Overseer Control Panel,
  diverts microphone speech, and injects subconscious thoughts/moods over WebSocket.

Zero-latency loopback support for IBIK ASTER on 127.0.0.1, or LAN IP for multi-PC setups.
"""

import asyncio
import json
import logging
import socket
import threading
import time
from typing import Callable, Optional, Set
import websockets

logger = logging.getLogger("AlphaLive.WorkspaceBridge")


def get_local_ip() -> str:
    """Detect primary local IPv4 address on the LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class WorkspaceServer:
    """
    WebSocket Server running on the Host (AI Workstation / Workplace 2).
    Receives covert thought injections, mood changes, and flow commands from Josh's Remote Overseer.
    Broadcasts live stream-of-consciousness monologue and telemetry to connected Overseer clients.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8766):
        self.host = host
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.on_command: Optional[Callable[[str, dict], None]] = None
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._latest_telemetry: dict = {
            "agent_state": "idle",
            "mood": "Tactical & Focused",
            "is_paused": False,
            "monologue": "Workstation initialized. Standing by.",
            "active_task": "",
        }

    def start(self):
        """Start the WebSocket server in a dedicated background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="OverseerBridgeServer", daemon=True)
        self._thread.start()
        time.sleep(0.3)
        print(f"[WorkspaceBridge] Server active on ws://{self.host}:{self.port} (LAN: {get_local_ip()}:{self.port})", flush=True)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_server())
        self._loop.run_forever()

    async def _start_server(self):
        while self._running:
            try:
                self._server = await websockets.serve(self._handle_client, self.host, self.port)
                print(f"[WorkspaceBridge] Server active on ws://{self.host}:{self.port} (LAN: {get_local_ip()}:{self.port})", flush=True)
                break
            except OSError as e:
                print(f"[WorkspaceBridge] Port {self.port} in use ({e}). Retrying in 2.0s...", flush=True)
                await asyncio.sleep(2.0)

    async def _handle_client(self, websocket):
        self.clients.add(websocket)
        peer = getattr(websocket, "remote_address", "client")
        print(f"[WorkspaceBridge] Overseer client connected from {peer}", flush=True)

        # Send initial handshake with current AI state
        try:
            handshake = {
                "type": "handshake",
                "status": "connected",
                "telemetry": self._latest_telemetry,
                "timestamp": time.time(),
            }
            await websocket.send(json.dumps(handshake))
        except Exception:
            pass

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    action = data.get("action")
                    if action and self.on_command:
                        self.on_command(action, data)
                except Exception as e:
                    print(f"[WorkspaceBridge] Error processing message from client: {e}", flush=True)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"[WorkspaceBridge] Overseer client disconnected: {peer}", flush=True)

    def broadcast_telemetry(self, data: dict):
        """Broadcast live AI state/monologue to all connected Overseer HUDs."""
        self._latest_telemetry.update(data)
        if not self._running or not self._loop or not self.clients:
            return

        payload = json.dumps({
            "type": "telemetry",
            "data": self._latest_telemetry,
            "timestamp": time.time(),
        })

        async def _broadcast():
            to_remove = set()
            for ws in list(self.clients):
                try:
                    await ws.send(payload)
                except Exception:
                    to_remove.add(ws)
            self.clients.difference_update(to_remove)

        asyncio.run_coroutine_threadsafe(_broadcast(), self._loop)

    def stop(self):
        """Shut down the server cleanly."""
        self._running = False
        if self._server and self._loop:
            self._server.close()
            self._loop.call_soon_threadsafe(self._loop.stop)


class WorkspaceClient:
    """
    WebSocket Client running on Josh's seat (Workplace 1).
    Connects to the Host (ws://127.0.0.1:8766 for ASTER, or ws://192.168.x.x:8766).
    Transmits user thought injections, microphone speech, mood commands, and flow controls.
    Receives live monologue telemetry from the remote AI.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self.host = host
        self.port = port
        self.on_connection_change: Optional[Callable[[bool, str], None]] = None
        self.on_telemetry: Optional[Callable[[dict], None]] = None
        self._websocket = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False

    def connect(self, host: Optional[str] = None, port: Optional[int] = None):
        """Start client background connection thread."""
        if host:
            self.host = host
        if port:
            self.port = port

        if self._running:
            self.disconnect()

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="OverseerBridgeClient", daemon=True)
        self._thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._maintain_connection())

    async def _maintain_connection(self):
        uri = f"ws://{self.host}:{self.port}"
        while self._running:
            try:
                if self.on_connection_change:
                    self.on_connection_change(False, f"Connecting to {uri}...")

                async with websockets.connect(uri, ping_interval=15, ping_timeout=10) as ws:
                    self._websocket = ws
                    self._connected = True
                    print(f"[WorkspaceClient] Connected to AI Workstation at {uri}", flush=True)
                    if self.on_connection_change:
                        self.on_connection_change(True, f"LINKED // {self.host}:{self.port}")

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            if msg_type in ("telemetry", "handshake"):
                                telem = data.get("data") or data.get("telemetry") or {}
                                if self.on_telemetry:
                                    self.on_telemetry(telem)
                        except Exception as e:
                            print(f"[WorkspaceClient] Telemetry parse error: {e}", flush=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                self._connected = False
                self._websocket = None
                if self.on_connection_change:
                    self.on_connection_change(False, f"Offline: {e}")
                print(f"[WorkspaceClient] Connection to {uri} failed: {e}. Retrying in 2.5s...", flush=True)
                try:
                    await asyncio.sleep(2.5)
                except asyncio.CancelledError:
                    break

    def send_command(self, action: str, **kwargs):
        """Thread-safe dispatch of a command to the AI Workstation."""
        if not self._connected or not self._websocket or not self._loop:
            print(f"[WorkspaceClient] Warning: Cannot send '{action}'; not connected.", flush=True)
            return

        payload = json.dumps({"action": action, **kwargs})

        async def _send():
            try:
                await self._websocket.send(payload)
            except Exception as e:
                print(f"[WorkspaceClient] Failed to send '{action}': {e}", flush=True)

        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def send_thought(self, text: str):
        self.send_command("inject_thought", text=text)

    def send_mood(self, mood: str):
        self.send_command("set_mood", mood=mood)

    def send_action(self, action_impulse: str):
        self.send_command("trigger_action", impulse=action_impulse)

    def send_pause(self, paused: bool):
        self.send_command("toggle_pause", paused=paused)

    def send_halt(self):
        self.send_command("emergency_halt")

    def send_voice(self, text: str):
        self.send_command("voice_input", text=text)

    def send_cycle(self):
        self.send_command("trigger_cycle")

    def send_task(self, goal: str):
        self.send_command("run_task", goal=goal)

    def send_restart_worker(self):
        self.send_command("restart_worker")

    def disconnect(self):
        self._running = False
        self._connected = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
