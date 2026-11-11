import io
import os
import time
import random
from pathlib import Path
import tempfile
import base64
import sys

import modal

MINUTES = 60
CACHE_DIR = "/hf-hub-cache"
OUTPUTS_DIR = Path("/outputs")

cuda_version = "12.4.1"
tag = f"{cuda_version}-devel-ubuntu22.04"

# Hard-mount shared_app.py directly into the root directory where this script executes
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

image = image.add_local_python_source("shared_app")

with image.imports():
    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, UniPCMultistepScheduler
    from diffusers.utils import export_to_video
    from PIL import Image

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)

# Wan 2.2 14B MoE supports both 480p and 720p dynamically from the same checkpoint via height/width + flow_shift
MODEL_ID = "fdk6566/wan2.2_14b_i2v_480p_lightning_nsfw_diffusers"

ANTI_MUTATION_NEG = (
    "worst quality, low quality, bad quality, JPEG compression residue, ugly, incomplete, "
    "bad anatomy, deformed, disfigured, mutated, misshapen limbs, extra limbs, three legs, "
    "extra fingers, fused fingers, poorly drawn hands, poorly drawn faces, melted face, "
    "blurred details, overexposed, static, still picture, watermark, subtitles, text"
)

@app.cls(
    image=image,
    gpu="H100",  # Architect Tier: NVIDIA H100 (80GB HBM3, native sm_90 kernels)
    timeout=60 * MINUTES,
    scaledown_window=2,  # Shut down immediately after generation (2s idle, Modal minimum)
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("alphacore-secrets")],
)
class Img2Vid:
    @modal.enter()
    def setup(self):
        self.pipe = None

    def _load_model(self, resolution: str = "480p"):
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, UniPCMultistepScheduler

        if getattr(self, "pipe", None) is None:
            print(f"Loading Wan 2.2 14B I2V Model ({MODEL_ID}) with FP32 VAE...")
            vae = AutoencoderKLWan.from_pretrained(
                MODEL_ID,
                subfolder="vae",
                torch_dtype=torch.float32,
                cache_dir=CACHE_DIR,
            )
            self.pipe = WanImageToVideoPipeline.from_pretrained(
                MODEL_ID,
                vae=vae,
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR,
            )
            # Wan 2.2 MoE has two 14B transformers (56GB) + UMT5-XXL (11GB) + FP32 VAE;
            # sequential CPU offload switches only once at boundary_ratio and leaves >50GB free for 720p latents.
            self.pipe.enable_model_cpu_offload()
            print(f"✅ Wan 2.2 14B I2V loaded successfully!")

        # Adjust scheduler flow_shift for 720p (5.0) vs 480p (3.0)
        flow_shift = 5.0 if resolution == "720p" else 3.0
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(
            self.pipe.scheduler.config,
            flow_shift=flow_shift,
        )

    def _prepare_i2v_inputs(
        self,
        input_image,
        prompt: str,
        negative_prompt: str,
        resolution: str,
        guidance_scale: float,
        num_inference_steps: int,
        nsfw_mode: bool,
    ):
        import math
        from PIL import Image

        # Preserve exact aspect ratio of the input image (preventing 16:9 horizontal squash/mutation)
        max_area = (720 * 1280) if resolution == "720p" else (480 * 832)
        aspect_ratio = input_image.height / max(1, input_image.width)
        t_ref = self.pipe.transformer if self.pipe.transformer is not None else self.pipe.transformer_2
        mod_value = self.pipe.vae_scale_factor_spatial * t_ref.config.patch_size[1]
        height = max(mod_value, int(round(math.sqrt(max_area * aspect_ratio))) // mod_value * mod_value)
        width = max(mod_value, int(round(math.sqrt(max_area / aspect_ratio))) // mod_value * mod_value)
        resized_image = input_image.resize((width, height), Image.Resampling.LANCZOS)

        # Normalize steps for Lightning-distilled Wan 2.2 (designed for 6-12 steps; >20 steps over-burns latents)
        steps = int(num_inference_steps)
        if steps >= 60:
            steps = 12
        elif steps >= 40:
            steps = 8
        elif steps > 16:
            steps = 6
        steps = max(4, min(16, steps))

        # Build conditioned prompt & anti-mutation negative prompt
        clean_prompt = (prompt or "").strip()
        quality_suffix = "high quality, photorealistic, anatomically accurate, natural proportions, smooth fluid motion, detailed skin texture"
        if nsfw_mode:
            nsfw_prefix = "uncensored, nsfw, explicit, anatomically correct, keeping the exact same person and facial features, "
            if "uncensored" not in clean_prompt.lower() and "nsfw" not in clean_prompt.lower():
                clean_prompt = f"{nsfw_prefix}{clean_prompt}, {quality_suffix}"
            else:
                clean_prompt = f"{clean_prompt}, {quality_suffix}"
            neg = f"{negative_prompt}, {ANTI_MUTATION_NEG}" if negative_prompt else ANTI_MUTATION_NEG
            # Lightning distilled weights have CFG baked in; CFG=1.0 prevents latent burn/deformity
            cfg = 1.0 if guidance_scale >= 3.0 else max(1.0, min(2.0, float(guidance_scale)))
        else:
            clean_prompt = f"{clean_prompt}, {quality_suffix}"
            sfw_guard = "nsfw, nude, naked, explicit, uncensored, nipples, genitalia"
            base_neg = f"{negative_prompt}, {ANTI_MUTATION_NEG}" if negative_prompt else ANTI_MUTATION_NEG
            neg = f"{sfw_guard}, {base_neg}"
            # Low CFG (1.5) activates negative prompt SFW guard without over-burning Lightning weights
            cfg = 1.5 if guidance_scale >= 3.0 else max(1.0, min(2.0, float(guidance_scale)))

        return resized_image, width, height, clean_prompt, neg, cfg, steps

    @modal.method()
    def inference(
        self,
        image: bytes,
        prompt: str = "",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        resolution: str = "480p", # "480p" or "720p"
        num_frames: int = 81,
        guidance_scale: float = 1.0,
        num_inference_steps: int = 8,
        seed: int = -1,
        fps: int = 16,
        nsfw_mode: int = 0,
    ) -> bytes:
        self._load_model(resolution)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)

        import io
        from PIL import Image
        
        input_image = Image.open(io.BytesIO(image)).convert("RGB")
        resized_image, width, height, cond_prompt, cond_neg, cfg, steps = self._prepare_i2v_inputs(
            input_image, prompt, negative_prompt, resolution, guidance_scale, num_inference_steps, bool(nsfw_mode)
        )
        print(f"🎬 Generating I2V ({resolution} -> {width}x{height}, steps={steps}, cfg={cfg}, nsfw={bool(nsfw_mode)}): '{cond_prompt}' (Seed: {seed})")
        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        try:
            start_time = time.time()
            output = self.pipe(
                image=resized_image,
                prompt=cond_prompt,
                negative_prompt=cond_neg,
                height=height,
                width=width,
                num_frames=num_frames,
                guidance_scale=cfg,
                num_inference_steps=steps,
                generator=generator,
            ).frames[0]
            
            duration = time.time() - start_time
            print(f"✅ Video generation finished in {duration:.2f}s!")

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                import numpy as np
                import imageio
                video_frames = []
                for img in output:
                    arr = np.array(img)
                    if arr.dtype != np.uint8:
                        arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
                    video_frames.append(arr)
                imageio.mimwrite(
                    tmp_path, 
                    video_frames, 
                    fps=fps, 
                    format="FFMPEG", 
                    codec="h264", 
                    pixelformat="yuv420p", 
                    macro_block_size=2,
                    output_params=["-movflags", "+faststart", "-profile:v", "main"]
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
        guidance_scale: float = 1.0,
        num_inference_steps: int = 8,
        seed: int = -1,
        fps: int = 16,
        nsfw_mode: int = 0,
    ):
        self._load_model(resolution)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)

        # Decode input image
        import io
        from PIL import Image
        import base64
        
        # Strip potential data URI prefix
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
            
        img_bytes = base64.b64decode(image_b64)
        input_image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        resized_image, width, height, cond_prompt, cond_neg, cfg, steps = self._prepare_i2v_inputs(
            input_image, prompt, negative_prompt, resolution, guidance_scale, num_inference_steps, bool(nsfw_mode)
        )
        print(f"🎬 Generating I2V Stream ({resolution} -> {width}x{height}, steps={steps}, cfg={cfg}, nsfw={bool(nsfw_mode)}): '{cond_prompt}' (Seed: {seed})")

        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        import queue
        import threading

        q = queue.Queue()

        def callback(pipe, step_index, timestep, callback_kwargs):
            q.put({"step": step_index, "max_steps": steps})
            return callback_kwargs

        def generate_task():
            try:
                start_time = time.time()
                
                output = self.pipe(
                    image=resized_image,
                    prompt=cond_prompt,
                    negative_prompt=cond_neg,
                    height=height,
                    width=width,
                    num_frames=num_frames,
                    guidance_scale=cfg,
                    num_inference_steps=steps,
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
                    video_frames = []
                    for img in output:
                        arr = np.array(img)
                        if arr.dtype != np.uint8:
                            arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
                        video_frames.append(arr)
                    imageio.mimwrite(
                        tmp_path, 
                        video_frames, 
                        fps=fps, 
                        format="FFMPEG", 
                        codec="h264", 
                        pixelformat="yuv420p", 
                        macro_block_size=2,
                        output_params=["-movflags", "+faststart", "-profile:v", "main"]
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
            guidance_scale = float(body.get("guidance_scale", 1.0))
            num_inference_steps = int(body.get("num_inference_steps", 8))
            seed = int(body.get("seed", -1))
            fps = int(body.get("fps", 16))
            nsfw_mode = int(body.get("nsfw_mode", 0))

            try:
                msgs = list(self.run_stream.local(
                    image_b64=image_b64, prompt=prompt, negative_prompt=negative_prompt, resolution=resolution,
                    num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                    seed=seed, fps=fps, nsfw_mode=nsfw_mode,
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
            guidance_scale = float(body.get("guidance_scale", 1.0))
            num_inference_steps = int(body.get("num_inference_steps", 8))
            seed = int(body.get("seed", -1))
            fps = int(body.get("fps", 16))
            nsfw_mode = int(body.get("nsfw_mode", 0))

            from fastapi.responses import StreamingResponse
            import json
            def event_stream():
                try:
                    for msg in self.run_stream.local(
                        image_b64=image_b64, prompt=prompt, negative_prompt=negative_prompt, resolution=resolution,
                        num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                        seed=seed, fps=fps, nsfw_mode=nsfw_mode,
                    ):
                        yield ": " + " " * 4096 + "\n\n"
                        yield f"data: {json.dumps(msg)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        return web_app

