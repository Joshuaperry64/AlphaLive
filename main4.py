"""Standalone main4 client using a temporary T4-backed Modal endpoint."""

import os
import re
import subprocess
import sys


APP_NAME = "alphalive-temp-proxy"
PROXY_FILE = os.path.join(os.path.dirname(__file__), "tempmodalmode.py")


def websocket_endpoint(url):
    url = url.rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    return url if url.endswith("/ws") else url + "/ws"


def deploy_proxy():
    print("[main4] Deploying temporary T4 Modal endpoint...", flush=True)
    completed = subprocess.run(
        ["modal", "deploy", PROXY_FILE],
        cwd=os.path.dirname(PROXY_FILE),
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError("Modal deployment failed. See deployment output above.")
    urls = re.findall(r"https://[^\s\"']+\.modal\.run", output)
    if not urls:
        raise RuntimeError("Modal deployment succeeded but returned no endpoint URL.")
    endpoint = websocket_endpoint(urls[-1])
    print("[main4] Temporary endpoint deployed.", flush=True)
    return endpoint


def stop_proxy():
    print("[main4] Stopping temporary Modal app...", flush=True)
    subprocess.run(
        ["modal", "app", "stop", APP_NAME],
        cwd=os.path.dirname(PROXY_FILE),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def main():
    endpoint = os.environ.get("ALPHALIVE_MAIN4_WS_URL")
    if endpoint:
        endpoint = websocket_endpoint(endpoint)
    deployed_here = False
    if not endpoint:
        endpoint = deploy_proxy()
        deployed_here = True

    os.environ["ALPHALIVE_WS_URL"] = endpoint
    os.environ.setdefault("ALPHALIVE_ENGINE", "main3.py")

    try:
        # Reuse the stabilized desktop client without changing main3.py's defaults.
        from main3 import main as run_client
        import asyncio

        asyncio.run(run_client())
    finally:
        if deployed_here:
            stop_proxy()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        pass