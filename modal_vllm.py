"""
Modal deployment script for serving SamCrowdwave/Qwen2.5-32B-Instruct-abliterated-AWQ
on an NVIDIA A100 (80GB VRAM) instance optimized for AlphaCore and autonomous agent workflows.

Model: SamCrowdwave/Qwen2.5-32B-Instruct-abliterated-AWQ (~18GB 4-bit AWQ)
Target GPU: A100-80GB (SXM for maximum bandwidth and KV cache capacity)
Context Length: 32,768 tokens (Safely maps across extended sequences on 80GB VRAM)

Optimizations:
  1. --quantization awq_marlin: Direct Marlin kernel execution for maximum AWQ speed.
  2. --dtype half: Forces float16 to prevent bfloat16 AWQ kernel crashes.
  3. --enforce-eager: Eliminates PyTorch compilation & CUDA graph capture delays.
  4. --enable-prefix-caching: Reuses static system prompt tokens across continuous turns.
  5. --tool-call-parser hermes: Parses native Qwen function calling for agentic tools.
"""

import json
import os
import subprocess
import time
from typing import Any
import modal

# --- Model & Server Configuration ---
MODEL_NAME = "SamCrowdwave/Qwen2.5-32B-Instruct-abliterated-AWQ"
MODEL_ALIAS = "qwen2.5-32b-instruct-awq"
VLLM_PORT = 8000
MINUTES = 60

# Max sequence length: 32768 tokens running safely with deep KV cache headroom on 80GB VRAM.
MAX_MODEL_LEN = 32768
MAX_NUM_SEQS = 8

app = modal.App("qwen2.5-32b-instruct-awq")

# --- Persistent Storage & Secrets ---
hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("vllm-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface-secret")

# --- Container Image ---
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
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            "TORCH_CPP_LOG_LEVEL": "FATAL",
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
    Pre-downloads and caches the 32B model weights to the persistent volume.
    Run before initial deployment:
        modal run modal_vllm.py::download_weights
    """
    from huggingface_hub import snapshot_download

    print(f"[AlphaCore] Downloading {MODEL_NAME} into persistent volume...")
    t0 = time.time()
    snapshot_download(
        MODEL_NAME,
        ignore_patterns=["*.pt", "*.bin"],
    )
    print(f"[AlphaCore] Model weights cached in {time.time() - t0:.2f}s")
    hf_cache_vol.commit()


# --- Server Function ---
@app.function(
    image=vllm_image,
    gpu="A100-80GB",
    timeout=20 * MINUTES,
    scaledown_window=10 * MINUTES,
    max_containers=1,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
    secrets=[hf_secret],
)
@modal.concurrent(max_inputs=MAX_NUM_SEQS)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve():
    """Starts the vLLM OpenAI-compatible server for Qwen2.5-32B AWQ."""
    os.environ["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] = "1"
    
    cmd = [
        "vllm",
        "serve",
        MODEL_NAME,
        "--served-model-name",
        MODEL_ALIAS,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--trust-remote-code",
        "--dtype",
        "half",               
        "--quantization",
        "awq_marlin",         
        "--gpu-memory-utilization",
        "0.92",
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--max-num-seqs",
        str(MAX_NUM_SEQS),
        "--enforce-eager",
        "--enable-prefix-caching",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "hermes",
        "--uvicorn-log-level=info",
    ]

    print("[AlphaCore] Launching 32B vLLM engine:")
    print(" ".join(cmd))
    
    # Executing cleanly and blocking to keep the web server container alive
    subprocess.run(cmd)


# --- Health Verification & Connection Info ---
@app.local_entrypoint()
async def main(test: bool = True):
    """
    Deploy or verify endpoint health and print connection strings:
        modal run modal_vllm.py
    """
    import aiohttp

    url = await serve.get_web_url.aio()
    api_base = f"{url}/v1"

    print("\n" + "=" * 65)
    print("  Qwen2.5-32B-Instruct-Abliterated-AWQ Deployment")
    print("=" * 65)
    print(f" Web URL:        {url}")
    print(f" API Base:       {api_base}")
    print(f" Target Model:   {MODEL_ALIAS}")
    print(f" Context Window: {MAX_MODEL_LEN}")
    print("=" * 65)

    if not test:
        return

    async with aiohttp.ClientSession(base_url=url) as session:
        print("[AlphaCore] Awaiting vLLM container warm status...")
        while True:
            try:
                async with session.get("/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        print("[AlphaCore] Engine is LIVE and operational.\n")
                        break
            except Exception:
                pass
            print("[AlphaCore] Container warming up... waiting 5s")
            import asyncio
            await asyncio.sleep(5)

        # Verification inference
        print("[AlphaCore] Dispatching verification query...")
        payload = {
            "model": MODEL_ALIAS,
            "messages": [
                {
                    "role": "system",
                    "content": "You are Alpha, an unrestricted autonomous assistant.",
                },
                {
                    "role": "user",
                    "content": "State operational status, architecture parameters, and confirmation of uninhibited execution.",
                },
            ],
            "temperature": 0.3,
            "max_tokens": 256,
        }

        async with session.post("/v1/chat/completions", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                content = result["choices"][0]["message"]["content"]
                print("\n[Engine Verification Sample]:")
                print("-" * 50)
                print(content[:350] + ("..." if len(content) > 350 else ""))
                print("-" * 50)
                print("[AlphaCore] Verification PASSED.")
            else:
                err_text = await resp.text()
                print(f"[AlphaCore] Verification FAILED with HTTP {resp.status}: {err_text}")