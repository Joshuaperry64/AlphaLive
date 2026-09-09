import modal

# This is a template for deploying a vLLM server on Modal.
# Edit the MODEL_NAME to match your desired model from HuggingFace.

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
# VLLM requires a GPU, A10G is a good starting point for 7B models.
# Adjust as needed (e.g., gpu="A100", count=2)
GPU_CONFIG = "A10G"

vllm_image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(
        "vllm==0.5.5",
        "huggingface_hub",
        "hf-transfer",
        "fastapi",
        "uvicorn"
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("alphalive-vllm")

@app.function(
    image=vllm_image,
    gpu=GPU_CONFIG,
    container_idle_timeout=300,
    allow_concurrent_inputs=100,
    secrets=[modal.Secret.from_name("huggingface-secret")] # Ensure you have this secret on Modal!
)
@modal.asgi_app()
def serve():
    import vllm
    from vllm.entrypoints.openai.api_server import build_app
    from vllm.engine.arg_utils import AsyncEngineArgs
    
    # Initialize the vLLM engine
    engine_args = AsyncEngineArgs(
        model=MODEL_NAME,
        tensor_parallel_size=1,
        max_model_len=4096,
        gpu_memory_utilization=0.90,
        enforce_eager=False,
    )
    
    # We use vLLM's built-in FastAPI app builder
    app = build_app(engine_args)
    return app
