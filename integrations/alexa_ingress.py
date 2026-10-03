# -*- coding: utf-8 -*-
"""
AlphaLive Alexa/Lambda Ingress Listener
Lightweight FastAPI server running in a background thread inside AlphaLive.
Receives desktop control payloads from the Alexa Lambda function via an external tunnel (Ngrok, Tailscale, Cloudflare, etc.).
Supported Actions:
- screenshot: Captures screen, compresses to JPEG, returns base64
- click: Moves to (x, y) and performs click
- type: Types text via keyboard emulation
- hotkey: Executes keyboard shortcuts
- move: Moves mouse cursor
- scroll: Scrolls up/down
- open_app: Launches applications or URLs
- vision_click: Uses local Google Gemini vision to ground an instruction on screen and click
"""

import base64
import ctypes
import io
import json
import logging
import os
import subprocess
import threading
import time
import webbrowser
from typing import List, Optional

import PIL.Image
import PIL.ImageDraw
import pyautogui
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("AlphaLive.Ingress")
logging.basicConfig(level=logging.INFO)

# Initialize FastAPI app
app = FastAPI(title="AlphaLive Ingress Listener", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Screen metrics
try:
    screen_w, screen_h = pyautogui.size()
except Exception:
    screen_w, screen_h = 1920, 1080


# --- Desktop Automation Controller ---
class DesktopAutomation:
    """Handles mouse, keyboard, and display capture operations."""

    @staticmethod
    def capture_screenshot(draw_cursor: bool = True, quality: int = 80, max_width: int = 1600) -> dict:
        """Captures screen, draws cursor indicator, resizes and encodes to base64."""
        img = None
        # Try mss for fast capture
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as err:
            logger.warning("MSS capture failed, falling back to pyautogui: %s", err)
            try:
                img = pyautogui.screenshot()
            except Exception as e2:
                logger.warning("pyautogui.screenshot failed: %s. Checking recent screenshots...", e2)
                # Fallback to most recent screenshot in user's Screenshots directory
                shots_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
                if os.path.exists(shots_dir):
                    pngs = [os.path.join(shots_dir, f) for f in os.listdir(shots_dir) if f.lower().endswith((".png", ".jpg"))]
                    if pngs:
                        pngs.sort(key=os.path.getmtime, reverse=True)
                        try:
                            img = PIL.Image.open(pngs[0]).convert("RGB")
                            logger.info("Loaded most recent screenshot from disk: %s", pngs[0])
                        except Exception:
                            pass
                if img is None:
                    img = PIL.Image.new("RGB", (screen_w or 1920, screen_h or 1080), (15, 23, 42))

        if draw_cursor:
            try:
                mx, my = pyautogui.position()
                draw = PIL.ImageDraw.Draw(img)
                r = 14
                draw.line((mx - r, my, mx + r, my), fill="red", width=3)
                draw.line((mx, my - r, mx, my + r), fill="red", width=3)
                draw.ellipse((mx - 3, my - 3, mx + 3, my + 3), fill="red")
            except Exception:
                pass

        orig_w, orig_h = img.size

        # Resize if width exceeds max_width to keep payload lightweight for Lambda
        if orig_w > max_width:
            scale = max_width / float(orig_w)
            new_h = int(orig_h * scale)
            img = img.resize((max_width, new_h), PIL.Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {
            "status": "success",
            "action": "screenshot",
            "width": orig_w,
            "height": orig_h,
            "encoded_width": img.width,
            "encoded_height": img.height,
            "format": "jpeg",
            "image_base64": b64_str,
            "timestamp": time.time()
        }

    @staticmethod
    def click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> dict:
        """Executes mouse click at specified coordinates using Win32 API."""
        u32 = ctypes.windll.user32
        cur_x, cur_y = pyautogui.position()
        tx = max(0, min(int(x), screen_w - 1)) if x is not None else cur_x
        ty = max(0, min(int(y), screen_h - 1)) if y is not None else cur_y

        u32.SetCursorPos(tx, ty)
        time.sleep(0.04)

        down_flag = 0x0008 if button == "right" else (0x0020 if button == "middle" else 0x0002)
        up_flag = 0x0010 if button == "right" else (0x0040 if button == "middle" else 0x0004)

        for i in range(clicks):
            u32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.05)
            u32.mouse_event(up_flag, 0, 0, 0, 0)
            if clicks > 1 and i < clicks - 1:
                time.sleep(0.08)

        return {
            "status": "success",
            "action": "click",
            "x": tx,
            "y": ty,
            "button": button,
            "clicks": clicks,
            "message": f"Clicked at ({tx}, {ty}) with {button} button"
        }

    @staticmethod
    def move_to(x: int, y: int) -> dict:
        tx = max(0, min(int(x), screen_w - 1))
        ty = max(0, min(int(y), screen_h - 1))
        ctypes.windll.user32.SetCursorPos(tx, ty)
        return {"status": "success", "action": "move", "x": tx, "y": ty}

    @staticmethod
    def type_text(text: str, press_enter: bool = False, clear_first: bool = False) -> dict:
        if clear_first:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("backspace")
            time.sleep(0.05)

        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            pyautogui.write(text, interval=0.01)

        time.sleep(0.05)
        if press_enter:
            pyautogui.press("enter")

        return {
            "status": "success",
            "action": "type",
            "chars_typed": len(text),
            "pressed_enter": press_enter,
            "message": f"Typed text ({len(text)} chars)"
        }

    @staticmethod
    def hotkey(keys: List[str]) -> dict:
        pyautogui.hotkey(*keys)
        return {"status": "success", "action": "hotkey", "keys": keys}

    @staticmethod
    def scroll(clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> dict:
        if x is not None and y is not None:
            DesktopAutomation.move_to(x, y)
            time.sleep(0.04)
        amount = clicks * 120 if abs(clicks) <= 20 else clicks
        pyautogui.scroll(amount)
        return {"status": "success", "action": "scroll", "clicks": clicks}

    @staticmethod
    def open_app(app_name: str) -> dict:
        """Opens common apps or websites."""
        clean = app_name.lower().strip()
        common_apps = {
            "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "code": "code",
            "vscode": "code",
            "notepad": "notepad.exe",
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "terminal": "powershell.exe",
            "powershell": "powershell.exe",
            "cmd": "cmd.exe",
            "explorer": "explorer.exe",
        }
        if clean in common_apps:
            subprocess.Popen(common_apps[clean], shell=True)
            return {"status": "success", "action": "open_app", "target": clean}
        elif clean.startswith("http://") or clean.startswith("https://"):
            webbrowser.open(clean)
            return {"status": "success", "action": "open_app", "target": clean}
        else:
            try:
                os.startfile(app_name)
                return {"status": "success", "action": "open_app", "target": app_name}
            except Exception as e:
                return {"status": "error", "message": f"Could not launch {app_name}: {e}"}


# --- Request Models ---
class ActionPayload(BaseModel):
    action: str  # 'screenshot', 'click', 'type', 'hotkey', 'move', 'scroll', 'open_app', 'status'
    x: Optional[int] = None
    y: Optional[int] = None
    button: Optional[str] = "left"
    clicks: Optional[int] = 1
    text: Optional[str] = None
    keys: Optional[List[str]] = None
    press_enter: Optional[bool] = False
    clear_first: Optional[bool] = False
    app_name: Optional[str] = None
    quality: Optional[int] = 80


class VisionClickPayload(BaseModel):
    instruction: str  # e.g. "click the Chrome icon on taskbar"


# --- API Routes ---
@app.get("/")
@app.get("/health")
def health():
    mx, my = pyautogui.position()
    return {
        "status": "online",
        "system": "AlphaLive Ingress Listener",
        "screen_resolution": f"{screen_w}x{screen_h}",
        "cursor_position": {"x": mx, "y": my},
        "time": time.time()
    }


@app.post("/api/action")
def execute_action(payload: ActionPayload):
    """Primary webhook endpoint invoked by Alexa Lambda function."""
    act = payload.action.lower()
    logger.info("Executing Ingress Action: %s", act)

    if act == "screenshot":
        return DesktopAutomation.capture_screenshot(quality=payload.quality or 80)
    elif act == "click":
        return DesktopAutomation.click(x=payload.x, y=payload.y, button=payload.button or "left", clicks=payload.clicks or 1)
    elif act == "type":
        if not payload.text:
            raise HTTPException(status_code=400, detail="Missing text for type action")
        return DesktopAutomation.type_text(payload.text, press_enter=payload.press_enter or False, clear_first=payload.clear_first or False)
    elif act == "hotkey":
        if not payload.keys:
            raise HTTPException(status_code=400, detail="Missing keys for hotkey action")
        return DesktopAutomation.hotkey(payload.keys)
    elif act == "move":
        if payload.x is None or payload.y is None:
            raise HTTPException(status_code=400, detail="Missing coordinates for move action")
        return DesktopAutomation.move_to(payload.x, payload.y)
    elif act == "scroll":
        return DesktopAutomation.scroll(clicks=payload.clicks or 3, x=payload.x, y=payload.y)
    elif act == "open_app":
        if not payload.app_name:
            raise HTTPException(status_code=400, detail="Missing app_name")
        return DesktopAutomation.open_app(payload.app_name)
    elif act == "status":
        return health()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {act}")


@app.post("/api/vision_click")
def vision_grounded_click(payload: VisionClickPayload):
    """
    Local Visual Grounding:
    Captures screenshot, passes to Google Gemini Flash using local config API key,
    identifies UI coordinate, and performs physical click on Windows desktop.
    """
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    api_key = None
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r") as f:
                cfg = json.load(f)
                api_key = cfg.get("Global", {}).get("ApiKey")
        except Exception:
            pass

    if not api_key:
        raise HTTPException(status_code=500, detail="Google Gemini API key not found in config.json")

    # Capture pristine screenshot without cursor drawing
    shot = DesktopAutomation.capture_screenshot(draw_cursor=False, quality=90, max_width=1920)
    img_bytes = base64.b64decode(shot["image_base64"])
    pil_img = PIL.Image.open(io.BytesIO(img_bytes))

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)

        prompt = (
            f"You are a computer vision UI grounder on a {screen_w}x{screen_h} desktop screen.\n"
            f"Target instruction: '{payload.instruction}'.\n"
            "Identify the center pixel coordinate of the UI element that corresponds to this target.\n"
            "Return ONLY a JSON object in this exact format: {\"x\": integer, \"y\": integer, \"element\": \"description\"}\n"
            "Do not include markdown fences, thoughts, or extra commentary."
        )

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[pil_img, prompt]
        )
        text = resp.text.strip()
        # Clean any markdown fences
        clean_json = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        target_x = int(data["x"])
        target_y = int(data["y"])

        click_res = DesktopAutomation.click(target_x, target_y, button="left", clicks=1)
        return {
            "status": "success",
            "instruction": payload.instruction,
            "grounded_target": data.get("element"),
            "target_coordinates": {"x": target_x, "y": target_y},
            "click_result": click_res
        }
    except Exception as e:
        logger.error("Vision click error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Server Runner Helper for Background Threads ---
_server_thread = None
_server_instance = None

def is_ingress_running() -> bool:
    global _server_thread
    return bool(_server_thread and _server_thread.is_alive())

def start_ingress_server_thread(host: str = "0.0.0.0", port: int = 8765):
    """Starts the FastAPI Ingress Listener in a background daemon thread."""
    global _server_thread, _server_instance
    if _server_thread and _server_thread.is_alive():
        logger.info("Ingress server thread already running.")
        return True

    def run_uvicorn():
        global _server_instance
        logger.info("[AlphaLive] Starting Ingress Webhook Server on http://%s:%d", host, port)
        config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
        _server_instance = uvicorn.Server(config)
        _server_instance.run()

    _server_thread = threading.Thread(target=run_uvicorn, name="AlphaLiveIngressServer", daemon=True)
    _server_thread.start()
    time.sleep(0.4)
    logger.info("[AlphaLive] Ingress Webhook Server thread active.")
    return True

def stop_ingress_server():
    """Stops the FastAPI Ingress Listener server cleanly."""
    global _server_instance, _server_thread
    if _server_instance:
        _server_instance.should_exit = True
    _server_thread = None
    logger.info("[AlphaLive] Ingress Webhook Server stopped.")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AlphaLive Ingress Listener Server")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()

    print(f"\n[AlphaLive] Starting Standalone Ingress Listener on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
