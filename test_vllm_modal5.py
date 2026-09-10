import modal

app = modal.App("test-vllm")
image = modal.Image.debian_slim().pip_install("vllm")

@app.function(image=image)
def test():
    from vllm.entrypoints.openai.api_server import build_app
    class MockArgs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        
        def __getattr__(self, item):
            return None

    args = MockArgs(
        model="gpt2",
        tensor_parallel_size=1,
        max_model_len=128,
        gpu_memory_utilization=0.90,
        enforce_eager=False,
    )
    
    app = build_app(args)
    print("SUCCESS")
