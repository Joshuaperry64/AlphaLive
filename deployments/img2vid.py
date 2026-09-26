import io
import os
import time
import random
from pathlib import Path
import tempfile
import base64

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
        "ftfy",
        "sentencepiece",
        "protobuf",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HUB_CACHE": CACHE_DIR, "HF_HOME": CACHE_DIR})
)

from shared_app import app

with image.imports():
    import torch
    from diffusers import WanImageToVideoPipeline
    from diffusers.utils import export_to_video
    from PIL import Image

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)

MODEL_480P = "fdk6566/wan2.2_14b_i2v_480p_lightning_nsfw_diffusers"
# Assuming standard HuggingFace naming convention for 720p if requested
MODEL_720P = "fdk6566/wan2.2_14b_i2v_720p_lightning_nsfw_diffusers"

image = image.add_local_python_source("shared_app")
@app.cls(
    gpu="H100",  # 14B model requires H100
    timeout=60 * MINUTES,
    scaledown_window=60,
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
class Img2Vid:
    @modal.enter()
    def setup(self):
        self.current_res = None
        self.pipe = None
        
    def _load_model(self, resolution: str):
        if not hasattr(self, "pipe"):
            self.pipe = None
        if not hasattr(self, "current_res"):
            self.current_res = None

        if self.current_res == resolution and self.pipe is not None:
            return

        if getattr(self, "pipe", None) is not None:
            print(f"Unloading Wan {getattr(self, 'current_res', 'model')} from VRAM...")
            old_pipe = self.pipe
            self.pipe = None
            try:
                del old_pipe
            except Exception:
                pass
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        model_id = MODEL_720P if resolution == "720p" else MODEL_480P
        print(f"Loading Wan {resolution} I2V Model ({model_id}) into VRAM...")

        try:
            self.pipe = WanImageToVideoPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR
            )
            self.pipe.enable_model_cpu_offload()
            self.current_res = resolution
            print(f"✅ Wan I2V {resolution} loaded successfully!")
        except Exception as e:
            print(f"Failed to load {model_id}: {e}")
            raise

    @modal.method()
    def inference(
        self,
        image: bytes,
        prompt: str = "",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        resolution: str = "480p", # "480p" or "720p"
        num_frames: int = 81,
        guidance_scale: str = "5.0", # String bypasses Modal UI float bug
        num_inference_steps: int = 30,
        seed: int = -1,
        fps: int = 16,
    ) -> bytes:
        self._load_model(resolution)
        guidance_scale_f = float(guidance_scale)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        print(f"🎬 Generating I2V ({resolution}): '{prompt}' (Seed: {seed})")

        # Decode input image
        import io
        from PIL import Image
        
        input_image = Image.open(io.BytesIO(image)).convert("RGB")
        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        try:
            start_time = time.time()
            output = self.pipe(
                image=input_image,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_frames=num_frames,
                guidance_scale=guidance_scale_f,
                num_inference_steps=num_inference_steps,
                generator=generator,
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

            out_dir = OUTPUTS_DIR / "img2vid"
            out_dir.mkdir(parents=True, exist_ok=True)
            filename = f"vid_{int(time.time() * 1000)}_{seed}.mp4"
            (out_dir / filename).write_bytes(video_bytes)
            outputs_volume.commit()
            
            torch.cuda.empty_cache()
            return video_bytes
        except Exception as e:
            torch.cuda.empty_cache()
            raise Exception(f"Generation failed: {str(e)}")

    @modal.method(is_generator=True)
    def run_stream(
        self,
        image_b64: str,
        prompt: str = "",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        resolution: str = "480p", # "480p" or "720p"
        num_frames: int = 81,
        guidance_scale: float = 5.0,
        num_inference_steps: int = 30,
        seed: int = -1,
        fps: int = 16,
    ):
        self._load_model(resolution)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        print(f"🎬 Generating I2V Stream ({resolution}): '{prompt}' (Seed: {seed})")

        # Decode input image
        import io
        from PIL import Image
        import base64
        
        # Strip potential data URI prefix
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
            
        img_bytes = base64.b64decode(image_b64)
        input_image = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        import queue
        import threading

        q = queue.Queue()

        def callback(pipe, step_index, timestep, callback_kwargs):
            q.put({"step": step_index, "max_steps": num_inference_steps})
            return callback_kwargs

        def generate_task():
            try:
                start_time = time.time()
                
                output = self.pipe(
                    image=input_image,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
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

                out_dir = OUTPUTS_DIR / "img2vid"
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

    @modal.asgi_app()
    def web_img2vid(self):
        import fastapi
        from fastapi.middleware.cors import CORSMiddleware
        import base64

        web_app = fastapi.FastAPI(title="AlphaCore Img2Vid Wan API", version="1.0.0")
        web_app.add_middleware(
            CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
        )

        @web_app.post("/generate")
        async def generate_video(request: fastapi.Request):
            body = await request.json()
            image_b64 = body.get("image")
            if not image_b64:
                return {"error": "Missing 'image' parameter (base64 string)"}
                
            prompt = body.get("prompt", "")
            resolution = body.get("resolution", "480p")
            negative_prompt = body.get("negative_prompt", "low quality")
            num_frames = int(body.get("num_frames", 81))
            guidance_scale = float(body.get("guidance_scale", 5.0))
            num_inference_steps = int(body.get("num_inference_steps", 30))
            seed = int(body.get("seed", -1))
            fps = int(body.get("fps", 16))

            try:
                msgs = list(self.run_stream.local(
                    image_b64=image_b64, prompt=prompt, negative_prompt=negative_prompt, resolution=resolution,
                    num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                    seed=seed, fps=fps,
                ))
                final_msg = msgs[-1]
                if "error" in final_msg:
                    return {"error": final_msg["error"]}
                    
                return {"data": [{"b64_json": final_msg["video_b64"], "content_type": "video/mp4"}]}
            except Exception as e:
                return {"error": str(e)}

        @web_app.post("/stream")
        async def generate_stream(request: fastapi.Request):
            body = await request.json()
            image_b64 = body.get("image")
            if not image_b64:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=400, content={"error": "Missing image"})
                
            prompt = body.get("prompt", "")
            resolution = body.get("resolution", "480p")
            negative_prompt = body.get("negative_prompt", "low quality")
            num_frames = int(body.get("num_frames", 81))
            guidance_scale = float(body.get("guidance_scale", 5.0))
            num_inference_steps = int(body.get("num_inference_steps", 30))
            seed = int(body.get("seed", -1))
            fps = int(body.get("fps", 16))

            from fastapi.responses import StreamingResponse
            import json
            def event_stream():
                try:
                    for msg in self.run_stream.local(
                        image_b64=image_b64, prompt=prompt, negative_prompt=negative_prompt, resolution=resolution,
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
    gpu="L40S",
    timeout=60 * MINUTES,
    scaledown_window=60,
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
class Img2Vid_Eco(Img2Vid._get_user_cls()):
    """Economy tier endpoint for public/standard users. Cost-optimized on L40S with 60s scaledown."""
    pass
