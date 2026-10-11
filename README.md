# Process roles

AlphaLive uses one implementation for each workstation role:

- **Normal GUI:** `start.bat`
- **Workplace 1 Overseer:** `start.bat --overseer --host 127.0.0.1`
- **Workplace 2 worker:** `start.bat --aster-worker`

`aster-worker/worker_main.py` is the sole Workplace 2 server and command dispatcher.
The desktop GUI is always a client and never hosts a hidden worker. Worker network
options such as `--host`, `--port`, and `--token` are forwarded to the isolated worker.

# ⚡ AlphaLive // Autonomous Desktop Agent Suite v4.0

AlphaLive is an advanced multimodal AI pair programmer and desktop automation agent.

---

## 🚀 Quick Start (New Workspace / Machine)

### 1. Automated Setup (One-Click)
Double-click `Setup.bat` or run:
```cmd
Setup.bat
```
*(or in PowerShell: `.\Setup.ps1`)*

This script automatically:
- Creates an isolated Python virtual environment (`.venv`)
- Installs all required libraries (`requirements.txt`)
- Sets up configuration files
- Generates a Windows desktop shortcut (`AlphaLive.lnk`)

---

### 2. Launching the Application
Double-click `start.bat` or run:
```cmd
start.bat
```
Or directly with Python:
```cmd
.venv\Scripts\python.exe main.py
```

---

## 🔑 Initial Configuration

1. **API Keys**: Open the **⚙️ SETTINGS** tab in the application to enter your Google Gemini API Key or Modal Token.
2. **Microphone**: Select your desired microphone input and sensitivity threshold in the **⚙️ SETTINGS** tab.
3. **Display**: Choose which monitor the agent receives visuals from and navigates on.

---

## 📁 Project Architecture

- `main.py` — Application entrypoint & bootstrapper
- `core/`
  - `alpha_agent.py` — Multimodal cognitive engine, tool execution, half-duplex voice listener & desktop controller
  - `session_manager.py` — Conversation session history manager
  - `modal_vllm.py` — Modal cloud inference bridge
- `ui/`
  - `agent_gui.py` — Main Cyberpunk interface, floating mini HUD, log terminal
  - `agent_tabs.py` — Structured SQL Memory Vault, SDXL Neural Studio, Character Persona Manager, Hardware Monitor
  - `overlays.py` — Fullscreen transparent coordinate grid & calibration overlays
- `memory/`
  - `memory_manager.py` — SQLite structured knowledge graph & personal intelligence
  - `character_manager.py` — Dynamic persona profiles & attributes
- `studio/`
  - `image_studio_manager.py` — Neural SDXL image generation & super-resolution upscaling
- `integrations/`
  - `alexa_ingress.py` — Local webhook bridge for external smart assistant triggers
  - `google_workspace.py` — Gmail, Google Calendar, Drive, and Tasks integration
