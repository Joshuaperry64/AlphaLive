import modal

app = modal.App("test-vllm")
image = modal.Image.debian_slim().pip_install("vllm")

@app.function(image=image)
def test():
    import vllm.entrypoints.openai as openai
    print(dir(openai))
    import vllm.entrypoints.launcher_args as launcher_args
    print(dir(launcher_args)) if hasattr(launcher_args, '__name__') else print("No launcher_args")
    
