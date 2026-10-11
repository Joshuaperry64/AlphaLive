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
import os
import secrets
import socket
import threading
import time
from typing import Callable, Optional, Set
import websockets

logger = logging.getLogger("AlphaLive.WorkspaceBridge")

PROTOCOL_VERSION = 2
_EVENT_TELEMETRY_KEYS = {"monologue", "memory_event"}


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


def resolve_bridge_token(override: Optional[str] = None) -> str:
    """Resolve the Overseer bridge shared-secret token.

    Priority: explicit argument -> ALPHALIVE_BRIDGE_TOKEN env -> config.json 'BridgeToken'.
    Returns '' when no token is configured (authentication then remains disabled).
    """
    if override:
        return str(override).strip()
    env = os.getenv("ALPHALIVE_BRIDGE_TOKEN", "").strip()
    if env:
        return env
    try:
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
        )
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                return str(json.load(f).get("Global", {}).get("BridgeToken", "") or "").strip()
    except Exception:
        pass
    return ""


class WorkspaceServer:
    """
    WebSocket Server running on the Host (AI Workstation / Workplace 2).
    Receives covert thought injections, mood changes, and flow commands from Josh's Remote Overseer.
    Broadcasts live stream-of-consciousness monologue and telemetry to connected Overseer clients.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8766, token: Optional[str] = None):
        self.host = host
        self.port = port
        self.token = resolve_bridge_token(token)
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.on_command: Optional[Callable[[str, dict], None]] = None
        # Fired with the new authenticated-Overseer count on every change.
        self.on_overseer_change: Optional[Callable[[int], None]] = None
        # Monotonic timestamp of the last authenticated Overseer contact.
        self.last_presence: float = 0.0
        self._presence_lock = threading.Lock()
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._telemetry_sequence = 0
        self._latest_telemetry: dict = {
            "agent_state": "idle",
            "mood": "Tactical & Focused",
            "is_paused": False,
            "active_task": "",
            "is_connected": False,
            "identity_mode": False,
            "autonomous_mode": False,
            "unobserved_mode": False,
            "pacing": 30,
            "max_steps": 3,
        }

    def start(self):
        """Start the WebSocket server in a dedicated background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="OverseerBridgeServer", daemon=True)
        self._thread.start()
        time.sleep(0.3)
        if not self.token and self.host not in ("127.0.0.1", "localhost", "::1"):
            print(
                f"[WorkspaceBridge] WARNING: server bound to {self.host} WITHOUT an auth token. "
                f"Anyone on the LAN can send desktop-control commands. Set 'BridgeToken' in config.json "
                f"or ALPHALIVE_BRIDGE_TOKEN to enable authentication.",
                flush=True,
            )
        print(f"[WorkspaceBridge] Server active on ws://{self.host}:{self.port} (LAN: {get_local_ip()}:{self.port})", flush=True)

    def overseer_count(self) -> int:
        """Number of authenticated Overseer clients currently attached."""
        with self._presence_lock:
            return len(self.clients)

    def has_overseer(self) -> bool:
        """True while at least one authenticated Overseer cockpit is connected.

        Also refreshes the presence timestamp so callers can implement grace windows.
        """
        with self._presence_lock:
            present = len(self.clients) > 0
            if present:
                self.last_presence = time.monotonic()
            return present

    def seconds_since_presence(self) -> float:
        """Seconds since the last authenticated Overseer contact (inf if never)."""
        with self._presence_lock:
            if not self.last_presence:
                return float("inf")
            return time.monotonic() - self.last_presence

    def _notify_presence(self):
        """Notify listeners with the current authenticated-Overseer count."""
        count = self.overseer_count()
        if self.on_overseer_change:
            try:
                self.on_overseer_change(count)
            except Exception:
                pass

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_server())
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _start_server(self):
        while self._running:
            try:
                self._server = await websockets.serve(
                    self._handle_client, self.host, self.port,
                    ping_interval=20, ping_timeout=20,
                )
                print(f"[WorkspaceBridge] Server active on ws://{self.host}:{self.port} (LAN: {get_local_ip()}:{self.port})", flush=True)
                break
            except OSError as e:
                print(f"[WorkspaceBridge] Port {self.port} in use ({e}). Retrying in 2.0s...", flush=True)
                await asyncio.sleep(2.0)

    async def _handle_client(self, websocket):
        peer = getattr(websocket, "remote_address", "client")

        # Shared-secret authentication gate (enforced only when a token is configured).
        if self.token:
            authenticated = False
            try:
                first = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(first)
                authenticated = (
                    data.get("type") == "auth"
                    and secrets.compare_digest(str(data.get("token", "")), self.token)
                )
            except Exception:
                authenticated = False

            if not authenticated:
                print(f"[WorkspaceBridge] Rejected unauthenticated Overseer client from {peer}", flush=True)
                try:
                    await websocket.send(json.dumps({"type": "error", "status": "unauthorized"}))
                    await websocket.close()
                except Exception:
                    pass
                return

            print(f"[WorkspaceBridge] Overseer client authenticated from {peer}", flush=True)
        else:
            print(f"[WorkspaceBridge] Overseer client connected from {peer} (no auth token configured)", flush=True)

        # Only authenticated Overseers count toward presence, which drives the fail-closed
        # autonomy gate on the Worker node (no Overseer => the node must not self-drive).
        with self._presence_lock:
            self.clients.add(websocket)
            self.last_presence = time.monotonic()
        self._notify_presence()

        # Send initial handshake with current AI state
        try:
            handshake = {
                "type": "handshake",
                "status": "connected",
                "protocol_version": PROTOCOL_VERSION,
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
                    # Any traffic from an authenticated client refreshes the presence clock.
                    with self._presence_lock:
                        self.last_presence = time.monotonic()
                    if action in ("heartbeat", "ping", "keepalive"):
                        continue
                    if action and self.on_command:
                        self.on_command(action, data)
                        request_id = data.get("request_id")
                        if request_id:
                            await websocket.send(json.dumps({
                                "type": "command_result",
                                "request_id": request_id,
                                "action": action,
                                "status": "accepted",
                                "timestamp": time.time(),
                            }))
                except Exception as e:
                    print(f"[WorkspaceBridge] Error processing message from client: {e}", flush=True)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with self._presence_lock:
                self.clients.discard(websocket)
            self._notify_presence()
            print(f"[WorkspaceBridge] Overseer client disconnected: {peer}", flush=True)

    def broadcast_telemetry(self, data: dict):
        """Broadcast live AI state/monologue to all connected Overseer HUDs."""
        # State is retained for reconnect handshakes; transient events are sent once.
        self._latest_telemetry.update({
            key: value for key, value in data.items() if key not in _EVENT_TELEMETRY_KEYS
        })
        self._telemetry_sequence += 1
        if not self._running or not self._loop or not self.clients:
            return

        payload = json.dumps({
            "type": "telemetry",
            "data": data,
            "sequence": self._telemetry_sequence,
            "timestamp": time.time(),
        })

        async def _broadcast():
            to_remove = set()
            with self._presence_lock:
                targets = list(self.clients)
            for ws in targets:
                try:
                    await ws.send(payload)
                except Exception:
                    to_remove.add(ws)
            if to_remove:
                with self._presence_lock:
                    self.clients.difference_update(to_remove)
                self._notify_presence()

        try:
            asyncio.run_coroutine_threadsafe(_broadcast(), self._loop)
        except Exception:
            # The event loop may not be running yet during startup bind retries.
            pass

    def stop(self):
        """Shut down the server cleanly."""
        self._running = False
        if self._loop and self._loop.is_running():
            async def _shutdown():
                with self._presence_lock:
                    clients = list(self.clients)
                if clients:
                    await asyncio.gather(*(ws.close() for ws in clients), return_exceptions=True)
                if self._server:
                    self._server.close()
                    await self._server.wait_closed()

            try:
                fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
                fut.result(timeout=3.0)
            except Exception:
                pass
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=3.0)


class WorkspaceClient:
    """
    WebSocket Client running on Josh's seat (Workplace 1).
    Connects to the Host (ws://127.0.0.1:8766 for ASTER, or ws://192.168.x.x:8766).
    Transmits user thought injections, microphone speech, mood commands, and flow controls.
    Receives live monologue telemetry from the remote AI.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8766, token: Optional[str] = None):
        self.host = host
        self.port = port
        self.token = resolve_bridge_token(token)
        self.on_connection_change: Optional[Callable[[bool, str], None]] = None
        self.on_telemetry: Optional[Callable[[dict], None]] = None
        self.on_command_result: Optional[Callable[[dict], None]] = None
        self._connection_listeners = []
        self._telemetry_listeners = []
        self._command_result_listeners = []
        self._websocket = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the bridge is authenticated and ready for commands."""
        return self._connected

    def add_connection_listener(self, callback: Callable[[bool, str], None]):
        if callback not in self._connection_listeners:
            self._connection_listeners.append(callback)

    def add_telemetry_listener(self, callback: Callable[[dict], None]):
        if callback not in self._telemetry_listeners:
            self._telemetry_listeners.append(callback)

    def add_command_result_listener(self, callback: Callable[[dict], None]):
        if callback not in self._command_result_listeners:
            self._command_result_listeners.append(callback)

    def _emit_connection(self, connected: bool, message: str):
        callbacks = ([self.on_connection_change] if self.on_connection_change else []) + list(self._connection_listeners)
        for callback in callbacks:
            try:
                callback(connected, message)
            except Exception:
                logger.exception("Workspace connection listener failed")

    def _emit_telemetry(self, telemetry: dict):
        callbacks = ([self.on_telemetry] if self.on_telemetry else []) + list(self._telemetry_listeners)
        for callback in callbacks:
            try:
                callback(telemetry)
            except Exception:
                logger.exception("Workspace telemetry listener failed")

    def _emit_command_result(self, result: dict):
        callbacks = ([self.on_command_result] if self.on_command_result else []) + list(self._command_result_listeners)
        for callback in callbacks:
            try:
                callback(result)
            except Exception:
                logger.exception("Workspace command-result listener failed")

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
        try:
            self._loop.run_until_complete(self._maintain_connection())
        finally:
            self._loop.close()

    async def _maintain_connection(self):
        uri = f"ws://{self.host}:{self.port}"
        while self._running:
            try:
                self._emit_connection(False, f"Connecting to {uri}...")

                async with websockets.connect(uri, ping_interval=15, ping_timeout=10) as ws:
                    self._websocket = ws
                    if self.token:
                        await ws.send(json.dumps({"type": "auth", "token": self.token}))

                    # The server handshake is the authentication boundary. Never expose a
                    # ready state until it arrives successfully.
                    first_raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    first = json.loads(first_raw)
                    if first.get("type") == "error":
                        status = first.get("status", "unknown")
                        self._emit_connection(False, f"Authentication failed: {status}")
                        raise PermissionError(status)
                    if first.get("type") != "handshake" or first.get("status") != "connected":
                        raise ConnectionError("Invalid server handshake")

                    self._connected = True
                    print(f"[WorkspaceClient] Authenticated with AI Workstation at {uri}", flush=True)
                    self._emit_connection(True, f"AUTHENTICATED // {self.host}:{self.port}")
                    self._emit_telemetry(first.get("telemetry") or {})

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            if msg_type in ("telemetry", "handshake"):
                                telem = data.get("data") or data.get("telemetry") or {}
                                self._emit_telemetry(telem)
                            elif msg_type == "command_result":
                                self._emit_command_result(data)
                            elif msg_type == "error":
                                print(f"[WorkspaceClient] Server rejected connection: {data.get('status', 'unknown')}", flush=True)
                                self._connected = False
                        except Exception as e:
                            print(f"[WorkspaceClient] Telemetry parse error: {e}", flush=True)

                # Clean server-side close: back off before reconnecting to avoid a hot loop.
                if self._running:
                    self._connected = False
                    self._websocket = None
                    self._emit_connection(False, "Disconnected. Retrying in 2.5s...")
                    await asyncio.sleep(2.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                self._connected = False
                self._websocket = None
                self._emit_connection(False, f"Offline: {e}")
                print(f"[WorkspaceClient] Connection to {uri} failed: {e}. Retrying in 2.5s...", flush=True)
                try:
                    await asyncio.sleep(2.5)
                except asyncio.CancelledError:
                    break

    def send_command(self, action: str, **kwargs):
        """Thread-safe dispatch of a command to the AI Workstation."""
        if not self._connected or not self._websocket or not self._loop:
            print(f"[WorkspaceClient] Warning: Cannot send '{action}'; not connected.", flush=True)
            return False

        request_id = secrets.token_hex(8)
        payload = json.dumps({
            "action": action,
            "request_id": request_id,
            "protocol_version": PROTOCOL_VERSION,
            **kwargs,
        })

        async def _send():
            try:
                await self._websocket.send(payload)
            except Exception as e:
                print(f"[WorkspaceClient] Failed to send '{action}': {e}", flush=True)

        asyncio.run_coroutine_threadsafe(_send(), self._loop)
        return True

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

    def send_pacing(self, delay_seconds: int):
        self.send_command("set_pacing", delay_seconds=int(delay_seconds))

    def send_max_steps(self, max_steps: int):
        self.send_command("set_max_steps", max_steps=int(max_steps))

    def send_start_agent(self, identity_mode: bool = True, autonomous_mode: bool = False, unobserved_mode: bool = False):
        self.send_command("start_agent", identity_mode=identity_mode, autonomous_mode=autonomous_mode, unobserved_mode=unobserved_mode)

    def send_stop_agent(self):
        self.send_command("stop_agent")

    def send_sync_modes(self, identity_mode: bool, autonomous_mode: bool, unobserved_mode: bool):
        self.send_command("set_modes", identity_mode=identity_mode, autonomous_mode=autonomous_mode, unobserved_mode=unobserved_mode)

    def disconnect(self):
        self._running = False
        self._connected = False
        if self._websocket and self._loop:
            try:
                # Block briefly so the close handshake actually reaches the Host before
                # we stop the loop -- otherwise the Host keeps seeing us as present.
                fut = asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)
                fut.result(timeout=2.0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            try:
                self._thread.join(timeout=3.0)
            except Exception:
                pass
        self._thread = None
        self._websocket = None
        self._loop = None
