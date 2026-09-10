import modal

app = modal.App("test-vllm")
image = modal.Image.debian_slim().pip_install("vllm")

@app.function(image=image)
def test():
    import inspect
    from vllm.entrypoints.openai import api_server
    print(inspect.signature(api_server.build_app))

