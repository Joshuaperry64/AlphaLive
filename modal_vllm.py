import modal
import os
import subprocess

MODEL_ID = "DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED"
CACHE_DIR = "/models"
LOCAL_MODEL_PATH = f"{CACHE_DIR}/Qwen3.5-9B"

GPU_CONFIG = "L40S"

# 1. Create a persistent Volume to store the downloaded model files
model_volume = modal.Volume.from_name("alphalive-qwen-volume", create_if_missing=True)

vllm_image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(
        "vllm",
        "huggingface_hub",
        "fastapi",
        "uvicorn"
    )
    .run_commands(
        "ln -s /usr/local/lib/python3.10/site-packages/nvidia/cuda_nvcc/bin/nvcc /usr/local/bin/nvcc || true",
        "mkdir -p /usr/local/cuda/bin && ln -s /usr/local/lib/python3.10/site-packages/nvidia/cuda_nvcc/bin/nvcc /usr/local/cuda/bin/nvcc || true"
    )
    .env({
        "HF_HOME": CACHE_DIR,
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
        "CUDA_HOME": "/usr/local/cuda"
    })
)

app = modal.App("alphalive-vllm-bucket")

@app.function(
    image=vllm_image,
    gpu=GPU_CONFIG,
    scaledown_window=300,
    volumes={CACHE_DIR: model_volume}, 
    secrets=[modal.Secret.from_name("huggingface-secret")] # Ensure your HF token is in this Modal secret!
)
@modal.concurrent(max_inputs=100)
@modal.web_server(8000, startup_timeout=300)
def serve():
    import subprocess
    from huggingface_hub import snapshot_download
    
    # 2. Download / cache the model to the persistent volume
    print(f"Verifying/downloading model {MODEL_ID} to {LOCAL_MODEL_PATH}...")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=LOCAL_MODEL_PATH,
        local_dir_use_symlinks=False,
    )
    model_volume.commit()
    print("Model snapshot ready!")
    
    # 3. Start the vLLM OpenAI-compatible server using the official CLI
    cmd = [
        "vllm", "serve", LOCAL_MODEL_PATH,
        "--served-model-name", MODEL_ID,
        "--host", "0.0.0.0",
        "--port", "8000",
        "--tensor-parallel-size", "1",
        "--max-model-len", "4096",
        "--gpu-memory-utilization", "0.90",
        "--trust-remote-code"
    ]
    
    print("Starting vLLM server...")
    subprocess.run(cmd, check=True)

