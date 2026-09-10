import modal

app = modal.App("test-vllm")
image = modal.Image.debian_slim().pip_install("vllm")

@app.function(image=image)
def test():
    from vllm.entrypoints.openai import api_server
    print(dir(api_server))

