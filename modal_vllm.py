import modal
import os
import subprocess

# We will sync your HuggingFace Bucket into a Modal Volume so vLLM can load it instantly
BUCKET_ID = "Joshuaperry64/Gemma"
CACHE_DIR = "/models"
LOCAL_MODEL_PATH = f"{CACHE_DIR}/Gemma"

GPU_CONFIG = "A10G"

# 1. Create a persistent Volume to store the synced bucket files
model_volume = modal.Volume.from_name("alphalive-gemma-volume", create_if_missing=True)

vllm_image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(
        "vllm",
        "huggingface_hub",
        "hf-xet",
        "fastapi",
        "uvicorn"
    )
    # Install the new Hugging Face CLI (required for hf buckets sync)
    .apt_install("curl")
    .run_commands("curl -LsSf https://hf.co/cli/install.sh | bash -s")
    .env({
        "HF_XET_HIGH_PERFORMANCE": "1",
        "HF_HOME": CACHE_DIR
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
@modal.asgi_app()
def serve():
    import vllm
    from vllm.entrypoints.openai.api_server import build_app
    from vllm.engine.arg_utils import AsyncEngineArgs
    
    # 2. Sync the HF Bucket to the Modal Volume before starting vLLM.
    #    (This only downloads files that are missing or changed, so it's instant after the first run)
    print(f"Syncing HF Bucket {BUCKET_ID} to {LOCAL_MODEL_PATH}...")
    subprocess.run(["hf", "buckets", "sync", BUCKET_ID, LOCAL_MODEL_PATH], check=True)
    print("Sync complete!")
    
    # 3. Initialize vLLM pointing directly to the downloaded files in the Volume
    engine_args = AsyncEngineArgs(
        model=LOCAL_MODEL_PATH,
        tensor_parallel_size=1,
        max_model_len=4096,
        gpu_memory_utilization=0.90,
        enforce_eager=False,
    )
    
    app = build_app(engine_args)
    return app
