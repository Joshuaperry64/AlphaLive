import modal

app = modal.App("test-vllm")
image = modal.Image.debian_slim().pip_install("vllm")

@app.function(image=image)
def test():
    import vllm.entrypoints.openai.api_server as api_server
    import inspect
    print(dir(api_server))

