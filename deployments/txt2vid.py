# ---
# output-directory: "/tmp/txt2vid-output"
# args: ["--prompt", "A cinematic video of a majestic dragon flying over a sunset ocean"]
# ---

# Text-to-Video Generator on Modal (AnimateDiff SDXL Pipeline)
# Powered by Modal L40S GPUs and Hugging Face Diffusers AnimateDiffSDXLPipeline

import io
import os
import time
import random
from pathlib import Path
import tempfile

import modal

MINUTES = 60
CACHE_DIR = "/hf-hub-cache"
OUTPUTS_DIR = Path("/outputs")

cuda_version = "12.4.1"
tag = f"{cuda_version}-devel-ubuntu22.04"

image = (
    modal.Image.from_registry(f"nvidia/cuda:{tag}", add_python="3.12")
    .entrypoint([])
    .apt_install("git", "ffmpeg", "libgl1-mesa-glx", "libglib2.0-0", "libsm6", "libxrender1", "libxext6")
    .uv_pip_install(
        "accelerate>=0.33.0",
        "fastapi[standard]>=0.115.4",
        "huggingface-hub>=0.36.0",
        "torch>=2.5.1",
        "torchvision>=0.20.1",
        "diffusers",
        "transformers>=4.48.0",
        "safetensors>=0.4.5",
        "imageio[ffmpeg]",
        "imageio-ffmpeg",
        "numpy<2",
        "peft>=0.6.0",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HUB_CACHE": CACHE_DIR, "HF_HOME": CACHE_DIR})
)

from shared_app import app

with image.imports():
    import torch
    from diffusers import AnimateDiffSDXLPipeline, MotionAdapter, EulerDiscreteScheduler
    from diffusers.utils import export_to_video
    from PIL import Image

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)

MOTION_ADAPTER_ID = "guoyww/animatediff-motion-adapter-sdxl-beta"

image = image.add_local_python_source("shared_app")
@app.cls(
    gpu="L40S",
    timeout=60 * MINUTES,
    scaledown_window=60,
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
class Txt2Vid:
    @modal.enter()
    def setup(self):
        self.current_model = None
        self.pipe = None
        
        print(f"🚀 Loading AnimateDiff SDXL Motion Adapter ({MOTION_ADAPTER_ID})...")
        self.adapter = MotionAdapter.from_pretrained(
            MOTION_ADAPTER_ID, 
            torch_dtype=torch.float16, 
            cache_dir=CACHE_DIR
        )

    def _load_model(self, model_filename: str):
        if not hasattr(self, "pipe"):
            self.pipe = None
        if not hasattr(self, "current_model"):
            self.current_model = None

        if self.current_model == model_filename and self.pipe is not None:
            return

        if getattr(self, "pipe", None) is not None:
            print(f"Unloading {getattr(self, 'current_model', 'model')} from VRAM...")
            old_pipe = self.pipe
            self.pipe = None
            try:
                del old_pipe
            except Exception:
                pass
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        print(f"Loading {model_filename} into AnimateDiff SDXL Pipeline...")
        model_path = Path(CACHE_DIR) / "checkpoints" / model_filename
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at: {model_path}. Did you upload it to /hf-hub-cache/checkpoints?")

        self.pipe = AnimateDiffSDXLPipeline.from_single_file(
            str(model_path),
            motion_adapter=self.adapter,
            torch_dtype=torch.float16,
            use_safetensors=True,
        )
        
        # --- ADD THIS EXPLICIT CAST ---
        self.pipe.to(dtype=torch.float16)
        
        self.pipe.scheduler = EulerDiscreteScheduler.from_config(self.pipe.scheduler.config, timestep_spacing="linspace", beta_schedule="linear")
        
        self.pipe.vae.enable_slicing()  # replaces deprecated enable_vae_slicing()
        
        # Note: Since you are using an L40S with 48GB VRAM, you don't strictly need CPU offloading. 
        # If you still get device placement errors, replace the line below with: self.pipe.to("cuda")
        self.pipe.enable_model_cpu_offload() 
        
        self.current_model = model_filename
        print(f"✅ AnimateDiff SDXL loaded successfully with {model_filename}!")

    @modal.method(is_generator=True)
    def run_stream(
        self,
        prompt: str,
        model_name: str = "epic",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        height: int = 1024,
        width: int = 1024,
        num_frames: int = 16,
        guidance_scale: float = 7.5,
        num_inference_steps: int = 25,
        seed: int = -1,
        fps: int = 8,
    ):
        # Resolve model filename
        if model_name.endswith(".safetensors"):
            model_file = model_name
        elif model_name.lower().startswith("epic"):
            model_file = "epicrealismXL_pureFix.safetensors"
        elif model_name.lower().startswith("cyber"):
            model_file = "cyberrealisticXL_desireV30.safetensors"
        elif model_name.lower().startswith("unholy"):
            model_file = "unholyDesireMixSinister_v80.safetensors"
        elif model_name.lower().startswith("lust"):
            model_file = "lustifyNSFWCheckpoint_zenithV9.safetensors"
        elif model_name.lower().startswith("autism") or model_name.lower().startswith("pony"):
            model_file = "autismmixSDXL_autismmixPony.safetensors"
        elif model_name.lower().startswith("0x7"):
            model_file = "0x7RealisticFreedom_omegaSDXL.safetensors"
        else:
            model_file = "juggernautXL_ragnarok.safetensors"

        self._load_model(model_file)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        print(f"🎬 Generating SDXL Video: '{prompt}' (Model: {model_file})")

        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        import queue
        import threading
        import base64

        q = queue.Queue()

        def callback(pipe, step_index, timestep, callback_kwargs):
            q.put({"step": step_index, "max_steps": num_inference_steps})
            return callback_kwargs

        def generate_task():
            try:
                start_time = time.time()
                output = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    num_frames=num_frames,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    generator=generator,
                    callback_on_step_end=callback
                ).frames[0]
                duration = time.time() - start_time
                print(f"✅ Video generation finished in {duration:.2f}s!")

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    import numpy as np
                    import imageio
                    video_frames = [np.array(img) for img in output]
                    imageio.mimwrite(
                        tmp_path, 
                        video_frames, 
                        fps=fps, 
                        format="FFMPEG", 
                        codec="h264", 
                        pixelformat="yuv420p", 
                        macro_block_size=2
                    )
                    video_bytes = Path(tmp_path).read_bytes()
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

                out_dir = OUTPUTS_DIR / "txt2vid"
                out_dir.mkdir(parents=True, exist_ok=True)
                filename = f"vid_{int(time.time() * 1000)}_{seed}.mp4"
                (out_dir / filename).write_bytes(video_bytes)
                outputs_volume.commit()
                
                b64_video = base64.b64encode(video_bytes).decode("utf-8")
                
                torch.cuda.empty_cache()
                q.put({"video_b64": b64_video})
            except Exception as e:
                torch.cuda.empty_cache()
                q.put({"error": str(e)})

        threading.Thread(target=generate_task).start()

        while True:
            msg = q.get()
            yield msg
            if "video_b64" in msg or "error" in msg:
                break

    @modal.method()
    def inference(
        self,
        prompt: str,
        model_name: str = "epic",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        height: int = 1024,
        width: int = 1024,
        num_frames: int = 16,
        guidance_scale: float = 7.5,
        num_inference_steps: int = 25,
        seed: int = -1,
        fps: int = 8,
    ) -> bytes:
        import base64
        msgs = list(self.run_stream.local(
            prompt=prompt, model_name=model_name, negative_prompt=negative_prompt, height=height, width=width,
            num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
            seed=seed, fps=fps
        ))
        final_msg = msgs[-1]
        if "error" in final_msg:
            raise Exception(final_msg["error"])
        return base64.b64decode(final_msg["video_b64"])

    @modal.asgi_app()
    def web_txt2vid(self):
        import fastapi
        from fastapi.middleware.cors import CORSMiddleware
        import base64

        web_app = fastapi.FastAPI(title="AlphaCore AnimateDiff SDXL API", version="1.0.0")
        web_app.add_middleware(
            CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
        )

        @web_app.post("/generate")
        async def generate_video(request: fastapi.Request):
            body = await request.json()
            prompt = body.get("prompt", "A cinematic video")
            model_name = body.get("model", "epic")
            negative_prompt = body.get("negative_prompt", "low quality")
            height = int(body.get("height", 1024))
            width = int(body.get("width", 1024))
            num_frames = int(body.get("num_frames", 16))
            guidance_scale = float(body.get("guidance_scale", 7.5))
            num_inference_steps = int(body.get("num_inference_steps", 25))
            seed = int(body.get("seed", -1))
            fps = int(body.get("fps", 8))

            video_bytes = self.inference.local(
                prompt=prompt, model_name=model_name, negative_prompt=negative_prompt, height=height, width=width,
                num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                seed=seed, fps=fps,
            )
            return {"data": [{"b64_json": base64.b64encode(video_bytes).decode("utf-8"), "content_type": "video/mp4"}]}

        @web_app.get("/stream")
        @web_app.get("/")
        def generate_endpoint(
            prompt: str, model_name: str = "epic", negative_prompt: str = "low quality", height: int = 1024, width: int = 1024,
            num_frames: int = 16, guidance_scale: float = 7.5, num_inference_steps: int = 25, seed: int = -1, fps: int = 8,
        ):
            from fastapi.responses import StreamingResponse
            import json
            def event_stream():
                try:
                    for msg in self.run_stream.local(
                        prompt=prompt, model_name=model_name, negative_prompt=negative_prompt, height=height, width=width,
                        num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                        seed=seed, fps=fps,
                    ):
                        yield ": " + " " * 4096 + "\n"
                        yield f"data: {json.dumps(msg)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return StreamingResponse(event_stream(), media_type="text/event-stream")

        return web_app


@app.cls(
    gpu="A10G",
    timeout=60 * MINUTES,
    scaledown_window=60,
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
class Txt2Vid_Eco(Txt2Vid._get_user_cls()):
    """Economy tier endpoint for public/standard users. Cost-optimized on A10G with 60s scaledown."""
    pass


@app.local_entrypoint()
def main_txt2vid(
    prompt: str = "A highly detailed cinematic scene",
    model: str = "epic",
    negative_prompt: str = "low quality, blurry, distorted, static, jittery",
    height: int = 1024, width: int = 1024, num_frames: int = 16,
    guidance_scale: float = 7.5, steps: int = 25, seed: int = -1, fps: int = 8,
    output: str = "/tmp/txt2vid-output/output.mp4",
):
    output_path = Path(output)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    print(f"🎬 Requesting video generation from Modal...")
    video_bytes = Model().inference.remote(
        prompt=prompt, model_name=model, negative_prompt=negative_prompt, height=height, width=width,
        num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=steps, seed=seed, fps=fps,
    )
    output_path.write_bytes(video_bytes)
    print(f"✅ Saved generated MP4 video to {output_path}")
