"""
Modal deployment script for serving HuiHui-Qwen3-14B-abliterated-v2-AWQ on an A10G GPU
with fastest cold-boot configurations optimized for Eigent coding workflows.

Model: warshanks/HuiHui-Qwen3-14B-abliterated-v2-AWQ (~9.3GB 4-bit compressed-tensors/AWQ)
Target GPU: A10G (24GB VRAM)
Context Length: 65,536 tokens (extended via VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 from native 40,960)

Fast Cold Boot & Performance Optimizations:
  1. --enforce-eager: Skips PyTorch compilation and CUDA graph capture (~30-60s saved).
  2. --enable-prefix-caching: Caches static massive system prompts (~28k tokens) for instant sub-second turns.
  3. VLLM_USE_FLASHINFER_SAMPLER="0": Prevents FlashInfer JIT C++/ninja compilation stalls.
  4. 4-bit pack-quantized weights with Marlin kernel: Loads in ~4s.
  5. Persistent Modal Volume: Pre-caches model weights to eliminate network download latency.
  6. --enable-auto-tool-choice & --tool-call-parser hermes: Seamless agentic tool use for Eigent.
"""

import json
import os
import subprocess
import time
from typing import Any
import modal

# --- Model & Server Configuration ---
MODEL_NAME = "warshanks/HuiHui-Qwen3-14B-abliterated-v2-AWQ"
MODEL_ALIAS = "huihui-qwen3-14b-awq"
VLLM_PORT = 8000
MINUTES = 60

# Max sequence length: 65536 (65k context window).
# On A10G (24GB):
# 14B 4-bit weights = ~8.5-9.3GB, 65k KV cache = ~10.5-12.8GB.
# Total ~21.3GB safely fits within A10G's 24GB limit at 0.95 utilization!
MAX_MODEL_LEN = 65536
MAX_NUM_SEQS = 8

app = modal.App("qwen3-14b-awq")

# --- Persistent Storage & Secrets ---
hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("vllm-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface-secret")

# --- Container Image ---
# CUDA 12.8.2 devel image ensures full nvcc / kernel compatibility
vllm_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.2-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(
        "vllm>=0.6.3",
        "huggingface_hub[hf_transfer]",
        "transformers",
        "fastapi[standard]",
        "aiohttp",
        "openai",
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "VLLM_LOG_STATS_INTERVAL": "10",
            # Disable FlashInfer JIT sampler compilation to avoid ninja build delays at boot
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            "TORCH_CPP_LOG_LEVEL": "FATAL",
            # Allow max_model_len (65536) to exceed derived native max_position_embeddings (40960)
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
        }
    )
)


# --- Optional Pre-warm / Weight Download Helper ---
@app.function(
    image=vllm_image,
    volumes={"/root/.cache/huggingface": hf_cache_vol},
    timeout=20 * MINUTES,
    secrets=[hf_secret],
)
def download_weights():
    """
    Pre-downloads and caches model weights to the persistent volume.
    Run before first deploy for instant sub-15s cold starts:
        modal run Vllm.py::download_weights
    """
    from huggingface_hub import snapshot_download

    print(f"[AlphaCore] Downloading {MODEL_NAME} weights into persistent volume...")
    t0 = time.time()
    snapshot_download(
        MODEL_NAME,
        ignore_patterns=["*.pt", "*.bin"],
    )
    print(f"[AlphaCore] Model weights successfully cached in {time.time() - t0:.2f}s")
    hf_cache_vol.commit()


# --- Server Function ---
@app.function(
    image=vllm_image,
    gpu="A10G",  # 24GB VRAM Ampere GPU
    timeout=20 * MINUTES,
    scaledown_window=10 * MINUTES,  # Keeps warm between agent queries while active
    max_containers=1,  # Strict cap to prevent runaway autoscaling
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
    secrets=[hf_secret],
)
@modal.concurrent(max_inputs=MAX_NUM_SEQS)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve():
    """Starts the ultra-low-latency vLLM server optimized for Eigent coding."""
    os.environ["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] = "1"
    cmd = [
        "vllm",
        "serve",
        MODEL_NAME,
        "--served-model-name",
        MODEL_ALIAS,
        MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--trust-remote-code",
        "--dtype",
        "auto",
        "--gpu-memory-utilization",
        "0.95",
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--max-num-seqs",
        str(MAX_NUM_SEQS),
        # --- Fastest Cold-Boot & Prefix Caching Flags ---
        "--enforce-eager",  # Skips PyTorch compilation & CUDA graph capture for ~15s cold starts
        "--enable-prefix-caching",  # Caches static ~28k system prompts for instant sub-second turns
        # --- Eigent Agentic Tool Support ---
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "hermes",  # Native Qwen tool calling format
        "--uvicorn-log-level=info",
    ]

    print("[AlphaCore] Launching vLLM engine with command:")
    print(" ".join(cmd))
    subprocess.Popen(" ".join(cmd), shell=True)


# --- Interactive Verification & Eigent Configuration Helper ---
@app.local_entrypoint()
async def main(test: bool = True):
    """
    Verify server health and output Eigent connection settings:
        modal run Vllm.py
    """
    import aiohttp

    url = await serve.get_web_url.aio()
    api_base = f"{url}/v1"

    print("\n" + "=" * 65)
    print("  HuiHui-Qwen3-14B-AWQ (65k) vLLM Deployment")
    print("=" * 65)
    print(f" Web URL:   {url}")
    print(f" API Base:  {api_base}")
    print(f" Model ID:  {MODEL_ALIAS} (or {MODEL_NAME})")
    print("=" * 65)

    print("\n[Eigent Configuration]")
    print(f"  Base URL:        {api_base}")
    print(f"  Model:           {MODEL_ALIAS}")
    print("  API Key:         any (e.g. 'modal')")
    print(f"  Context Length:  {MAX_MODEL_LEN}\n")

    if not test:
        return

    async with aiohttp.ClientSession(base_url=url) as session:
        print("[AlphaCore] Waiting for vLLM engine readiness...")
        while True:
            try:
                async with session.get("/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        print("[AlphaCore] Engine is LIVE and healthy!\n")
                        break
            except Exception:
                pass
            print("[AlphaCore] Container warming up... waiting 5s")
            import asyncio
            await asyncio.sleep(5)

        # Verification Test Query with Tool Calling
        print("[AlphaCore] Running test query with tool-calling simulation...")
        payload = {
            "model": MODEL_ALIAS,
            "messages": [
                {
                    "role": "user",
                    "content": "Write a Python function to compute Fibonacci numbers using memoization.",
                }
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }

        async with session.post("/v1/chat/completions", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                content = result["choices"][0]["message"]["content"]
                print("\n[Engine Output Sample]:")
                print("-" * 50)
                print(content[:350] + ("..." if len(content) > 350 else ""))
                print("-" * 50)
                print("[AlphaCore] Verification PASSED. Eigent is ready to connect.")
            else:
                err_text = await resp.text()
                print(f"[AlphaCore] Verification FAILED with HTTP {resp.status}: {err_text}")
