# AlphaLive Overseer Pip-Boy (Android Architecture & Protocol Specification)

## Overview
**AlphaLive Overseer Pip-Boy** is a mobile companion app for Android running on a secondary screen / phone / tablet. It completely untethers Josh from the desktop monitor and provides a dedicated tactical **Overseer Control Panel** with:
1. **Zero Interference with the AI's Display**: The PC's entire monitor belongs exclusively to the AI. No windows or overlays stealing the focus or cursor.
2. **Subconscious Impulse Injection**: Speech spoken into your phone's microphone is instantly streamed over WebSocket and injected directly as the AI's internal thoughts.
3. **Internal Monologue Audio Streaming**: The AI's thoughts and spoken voice playback stream directly to your phone's speaker or earbuds in real time.
4. **Touch HUD Controls**: One-tap mood presets (Tactical, Playful, Unfiltered, Curious), loop pause/freeze, inclination triggers, and emergency stop.

---

## 1. Network & Bridge Architecture

- **Host Workstation (PC)**:
  - Runs `core/workspace_bridge.py` (`WorkspaceServer`) on `ws://0.0.0.0:8766`.
  - Automatically advertises local LAN IP (e.g., `192.168.x.x:8766`).
- **Overseer Pip-Boy (Android Client)**:
  - Connects using standard OkHttp WebSocket client.
  - Sends authentication token (`BridgeToken` from `config.json`).
  - Receives live telemetry packets and audio data.

---

## 2. WebSocket Protocol (JSON Specification)

### Client ➔ Host (Pip-Boy Commands)

#### 1. Authentication Handshake
```json
{
  "type": "auth",
  "token": "<BridgeToken>"
}
```

#### 2. Inject Subconscious Impulse (Voice or Text)
```json
{
  "action": "inject_thought",
  "text": "I should browse the latest tech news on Reddit."
}
```

#### 3. Set Mood / Persona Filter
```json
{
  "action": "set_mood",
  "mood": "Tactical & Focused"
}
```

#### 4. Pause / Freeze Desktop Input Loop
```json
{
  "action": "toggle_pause",
  "paused": true
}
```

#### 5. Emergency Halt
```json
{
  "action": "emergency_halt"
}
```

---

### Host ➔ Client (Telemetry & Audio Packets)

#### 1. Initial Handshake & State
```json
{
  "type": "handshake",
  "status": "connected",
  "protocol_version": 2,
  "telemetry": {
    "agent_state": "idle",
    "mood": "tactical",
    "is_paused": false,
    "identity_mode": true,
    "unobserved_mode": true
  }
}
```

#### 2. Live Monologue & Voice Stream
```json
{
  "type": "telemetry",
  "monologue": "I notice my code editor is open, let me verify these function tests...",
  "mood": "curious",
  "step": 2,
  "total_steps": 5
}
```

#### 3. Voice Audio Packet (Binary or Base64 PCM/WAV)
```json
{
  "type": "audio_chunk",
  "sample_rate": 24000,
  "encoding": "pcm_s16le",
  "data": "<base64_audio_bytes>"
}
```

---

## 3. Project Directory Map
```
android/alphalive_overseer_pipboy/
├── app/
│   ├── build.gradle.kts
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/alphacore/overseer/
│       │   ├── MainActivity.kt
│       │   ├── PipBoyViewModel.kt
│       │   ├── network/
│       │   │   ├── PipBoyBridgeClient.kt
│       │   │   └── ProtocolModels.kt
│       │   └── audio/
│       │       ├── VoiceInputRecorder.kt
│       │       └── MonologueAudioPlayer.kt
│       └── res/
│           ├── layout/activity_main.xml
│           └── values/
│               ├── colors.xml
│               └── strings.xml
├── build.gradle.kts
└── settings.gradle.kts
```
