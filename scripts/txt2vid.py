# ---
# output-directory: "/tmp/txt2vid-output"
# args: ["--prompt", "A cinematic video of a majestic dragon flying over a sunset ocean"]
# ---

# Text-to-Video Generator on Modal (AnimateDiff SDXL Pipeline)
# Powered by Modal GPUs and Hugging Face Diffusers AnimateDiffSDXLPipeline

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
        "diffusers==0.31.0",
        "transformers~=4.44.0",
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
    from diffusers import AnimateDiffSDXLPipeline, StableDiffusionXLPipeline, MotionAdapter, DDIMScheduler, EulerDiscreteScheduler
    from diffusers.utils import export_to_video
    from PIL import Image

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)

MOTION_ADAPTER_ID = "guoyww/animatediff-motion-adapter-sdxl-beta"

ANTI_MUTATION_NEG = (
    "worst quality, low quality, bad anatomy, bad hands, deformed, mutated, extra limbs, "
    "missing limbs, disfigured, fused fingers, extra fingers, malformed limbs, melted face, "
    "poorly drawn face, poorly drawn hands, blurry, distorted, ugly, watermark, text, signature, static, jittery"
)

image = image.add_local_python_source("shared_app")
@app.cls(
    image=image,
    gpu="H100",  # Architect Tier: NVIDIA H100 (80GB HBM3, native sm_90 kernels, zero JIT stall)
    timeout=60 * MINUTES,
    scaledown_window=2,  # Shut down immediately after generation (2s idle, Modal minimum)
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("alphacore-secrets")],
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
        import torch
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
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        print(f"Loading {model_filename} into SDXL base pipeline...")
        model_path = Path(CACHE_DIR) / "checkpoints" / model_filename
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at: {model_path}. Did you upload it to /hf-hub-cache/checkpoints?")

        try:
            xl_pipe = StableDiffusionXLPipeline.from_single_file(
                str(model_path),
                torch_dtype=torch.float16,
                use_safetensors=True,
                add_watermarker=False,
            )
            print(f"Assembling AnimateDiffSDXLPipeline with MotionAdapter ({MOTION_ADAPTER_ID})...")
            self.pipe = AnimateDiffSDXLPipeline(
                vae=xl_pipe.vae,
                text_encoder=xl_pipe.text_encoder,
                text_encoder_2=xl_pipe.text_encoder_2,
                tokenizer=xl_pipe.tokenizer,
                tokenizer_2=xl_pipe.tokenizer_2,
                unet=xl_pipe.unet,
                motion_adapter=self.adapter,
                scheduler=xl_pipe.scheduler,
            )
            del xl_pipe
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"SDXL component load encountered {e}; attempting fallback...")
            self.pipe = AnimateDiffSDXLPipeline.from_single_file(
                str(model_path),
                motion_adapter=self.adapter,
                torch_dtype=torch.float16,
                use_safetensors=True,
            )
        
        # Move entire pipeline directly to GPU in float16 and override upcast_vae so the ENTIRE VAE
        # is upcast to float32 during decoding (preventing Half/Float mismatch between mid_block and up_blocks)
        self.pipe.to("cuda", dtype=torch.float16)
        self.pipe.vae.config.force_upcast = True
        self.pipe.upcast_vae = lambda: self.pipe.vae.to(dtype=torch.float32)
        
        self.pipe.scheduler = DDIMScheduler.from_config(
            self.pipe.scheduler.config,
            timestep_spacing="linspace",
            beta_schedule="linear",
            clip_sample=False,
            steps_offset=1,
        )
        
        self.pipe.vae.enable_slicing()
        self.pipe.vae.enable_tiling()
        
        self._install_long_video_context(context_length=16, context_stride=12)
        
        self.current_model = model_filename
        print(f"✅ AnimateDiff SDXL loaded successfully with {model_filename}!")

    def _install_long_video_context(self, context_length: int = 16, context_stride: int = 12):
        """
        Enables multi-window Sliding-Window Context + FreeNoise latent rescheduling on AnimateDiffSDXLPipeline
        so videos up to 80+ frames (10+ seconds) can be generated without exceeding the 32-frame positional
        embedding limit or causing VRAM spikes / character drift.
        """
        import torch
        from diffusers.utils.torch_utils import randn_tensor

        orig_unet_forward = self.pipe.unet.forward
        step_counter = {"count": 0}

        def _get_windows(num_frames: int, call_idx: int) -> list[int]:
            shift = (call_idx * 4) % context_stride
            starts = [0]
            first_interior = shift if shift > 0 else context_stride
            for s in range(first_interior, num_frames - context_length, context_stride):
                starts.append(s)
            final_start = num_frames - context_length
            if starts[-1] != final_start:
                if final_start > starts[-1] + context_stride:
                    starts.append(max(0, final_start - (context_stride // 2)))
                starts.append(final_start)
            return starts

        def sliding_window_unet_forward(sample, timestep, encoder_hidden_states, *args, **kwargs):
            total_frames = sample.shape[2]
            if total_frames <= context_length:
                return orig_unet_forward(sample, timestep, encoder_hidden_states, *args, **kwargs)

            call_idx = step_counter["count"]
            step_counter["count"] += 1
            window_starts = _get_windows(total_frames, call_idx)

            batch_cfg = sample.shape[0]
            ehs_5d = encoder_hidden_states.view(batch_cfg, total_frames, *encoder_hidden_states.shape[1:])

            # Pyramid tent weights [1, 2, ..., 8, 8, ..., 2, 1] for seamless temporal overlap blending
            half = context_length // 2
            pyramid = list(range(1, half + 1)) + list(range(half, 0, -1))
            w_tensor = torch.tensor(pyramid, device=sample.device, dtype=sample.dtype).view(1, 1, context_length, 1, 1)

            pred_sum = torch.zeros_like(sample)
            weight_sum = torch.zeros((1, 1, total_frames, 1, 1), device=sample.device, dtype=sample.dtype)
            return_dict = kwargs.get("return_dict", True)
            last_out = None

            for start in window_starts:
                end = start + context_length
                sub_sample = sample[:, :, start:end, :, :]
                sub_ehs = ehs_5d[:, start:end].reshape(batch_cfg * context_length, *encoder_hidden_states.shape[1:])

                out = orig_unet_forward(sub_sample, timestep, encoder_hidden_states=sub_ehs, *args, **kwargs)
                last_out = out
                sub_pred = out[0] if not return_dict else out.sample

                pred_sum[:, :, start:end, :, :] += sub_pred * w_tensor
                weight_sum[:, :, start:end, :, :] += w_tensor

            blended = pred_sum / weight_sum.clamp(min=1e-6)
            if not return_dict:
                return (blended,)
            return type(last_out)(sample=blended)

        self.pipe.unet.forward = sliding_window_unet_forward

        orig_prepare_latents = self.pipe.prepare_latents

        def freenoise_prepare_latents(
            batch_size, num_channels_latents, num_frames, height, width, dtype, device, generator, latents=None
        ):
            step_counter["count"] = 0
            if num_frames <= context_length or latents is not None:
                return orig_prepare_latents(
                    batch_size, num_channels_latents, num_frames, height, width, dtype, device, generator, latents
                )

            shape = (
                batch_size,
                num_channels_latents,
                num_frames,
                height // self.pipe.vae_scale_factor,
                width // self.pipe.vae_scale_factor,
            )
            latents = randn_tensor(shape, generator=generator, device=device, dtype=dtype)

            # FreeNoise shuffle_context: reschedule initial 16-frame noise block across longer durations
            # so background and subject identity remain locked across all 10 seconds
            cpu_gen = torch.Generator(device="cpu").manual_seed(int(generator.initial_seed()) if generator is not None else 42)
            for i in range(context_length, num_frames, context_stride):
                window_start = max(0, i - context_length)
                window_end = min(num_frames, window_start + context_stride)
                window_length = window_end - window_start
                if window_length <= 0:
                    break
                indices = torch.arange(window_start, window_end, dtype=torch.long)
                shuffled_indices = indices[torch.randperm(window_length, generator=cpu_gen)]
                current_start = i
                current_end = min(num_frames, current_start + window_length)
                prefix_len = current_end - current_start
                latents[:, :, current_start:current_end] = latents[:, :, shuffled_indices[:prefix_len].to(device)]

            latents = latents * self.pipe.scheduler.init_noise_sigma
            return latents

        self.pipe.prepare_latents = freenoise_prepare_latents

    @modal.method(is_generator=True)
    def run_stream(
        self,
        prompt: str = "A cinematic video of a majestic dragon flying over a sunset ocean",
        model_name: str = "epic",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        height: int = 1024,
        width: int = 1024,
        num_frames: int = 16,
        guidance_scale: float = 7.5,
        num_inference_steps: int = 25,
        seed: int = -1,
        fps: int = 8,
        duration: int = 0,
        nsfw_mode: int = 0,
        lora: str = "none",
    ):
        import torch

        # If duration (in seconds, up to 10s) is specified, map 1 second -> 8 native AnimateDiff frames
        if duration and duration > 0:
            num_frames = int(round(float(duration) * 8))
        num_frames = max(8, min(80, int(num_frames)))

        # Resolve model filename
        if model_name.endswith(".safetensors"):
            model_file = model_name
        elif model_name.lower().startswith("epic"):
            model_file = "epicrealismXL_pureFix.safetensors"
        elif model_name.lower().startswith("cyber"):
            model_file = "cyberrealisticXL_desireV30.safetensors"
        elif model_name.lower().startswith("unholy"):
            model_file = "unholyDesireMixCrimson_v50.safetensors"
        elif model_name.lower().startswith("lust"):
            model_file = "lustifyNSFWCheckpoint_zenithV9.safetensors"
        elif ("pony" in model_name.lower() and "cyber" in model_name.lower()) or "cyberrealisticpony" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "cyberrealisticPony_v180Coreshift.safetensors"
        elif model_name.lower().startswith("autism") or model_name.lower().startswith("pony"):
            model_file = "autismmixSDXL_autismmixPony.safetensors"
        elif model_name.lower().startswith("0x7"):
            model_file = "0x7RealisticFreedom_omegaSDXL.safetensors"
        elif model_name.lower().startswith("dream"):
            model_file = "dreamshaperXL_alpha2Xl10.safetensors"
        elif model_name.lower().startswith("juicy"):
            model_file = "juicyDreams_v10.safetensors"
        elif "realvis" in model_name.lower() or "realvisxl" in model_name.lower():
            model_file = "realvisxlV50_v50Bakedvae.safetensors"
        elif model_name.lower().startswith("into") or "realism" in model_name.lower() and "epic" not in model_name.lower() and "vision" not in model_name.lower():
            model_file = "intorealism_sdxlV4.safetensors"
        elif "vision" in model_name.lower() or "realisticvision" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "realvisxlV50_v50Bakedvae.safetensors"
        else:
            model_file = "juggernautXL_ragnarok.safetensors"

        # In NSFW Mode, automatically promote default SFW checkpoint to Lustify Zenith NSFW checkpoint
        if int(nsfw_mode) == 1 and model_file == "epicrealismXL_pureFix.safetensors":
            lustify_path = Path(CACHE_DIR) / "checkpoints" / "lustifyNSFWCheckpoint_zenithV9.safetensors"
            if lustify_path.exists():
                model_file = "lustifyNSFWCheckpoint_zenithV9.safetensors"

        self._load_model(model_file)

        # Load any requested SDXL LoRAs
        try:
            self.pipe.unload_lora_weights()
        except Exception:
            pass

        if lora and lora.lower() != "none":
            lora_list = [l.strip() for l in lora.split(",") if l.strip() and l.strip().lower() != "none"]
            loaded_adapters = []
            for idx, lora_item in enumerate(lora_list):
                lora_file = lora_item if lora_item.endswith(".safetensors") else f"{lora_item}.safetensors"
                lora_path = Path(CACHE_DIR) / "loras" / lora_file
                if lora_path.exists():
                    adapter_name = f"lora_{idx}"
                    try:
                        self.pipe.load_lora_weights(str(lora_path), adapter_name=adapter_name)
                        loaded_adapters.append(adapter_name)
                        print(f"💉 Loaded Video LoRA: {lora_file}")
                    except Exception as le:
                        print(f"⚠️ Could not load LoRA {lora_file}: {le}")
            if loaded_adapters:
                weights = [0.8 / len(loaded_adapters)] * len(loaded_adapters)
                self.pipe.set_adapters(loaded_adapters, adapter_weights=weights)

        # Condition prompt & anti-mutation negative prompt
        clean_prompt = (prompt or "").strip()
        is_pony = "pony" in model_file.lower() or "autism" in model_file.lower()
        if is_pony and "score_9" not in clean_prompt.lower():
            clean_prompt = f"score_9, score_8_up, score_7_up, {clean_prompt}"

        quality_suffix = "masterpiece, best quality, photorealistic, anatomically correct, natural body proportions, detailed skin texture, smooth fluid motion"
        if int(nsfw_mode) == 1:
            if "nsfw" not in clean_prompt.lower() and "uncensored" not in clean_prompt.lower():
                clean_prompt = f"nsfw, uncensored, explicit, {clean_prompt}, {quality_suffix}"
            else:
                clean_prompt = f"{clean_prompt}, {quality_suffix}"
            cond_neg = f"{negative_prompt}, {ANTI_MUTATION_NEG}" if negative_prompt else ANTI_MUTATION_NEG
            if is_pony:
                cond_neg = f"score_4, score_5, score_6, source_pony, {cond_neg}"
        else:
            clean_prompt = f"{clean_prompt}, {quality_suffix}"
            sfw_guard = "nsfw, nude, naked, explicit, uncensored"
            base_neg = f"{negative_prompt}, {ANTI_MUTATION_NEG}" if negative_prompt else ANTI_MUTATION_NEG
            cond_neg = f"{sfw_guard}, {base_neg}"

        # Ensure CFG is high enough for AnimateDiff SDXL linear beta schedule (>= 7.0 prevents mushy/deformed anatomy)
        effective_cfg = max(7.0, float(guidance_scale)) if abs(float(guidance_scale) - 5.0) < 0.1 else float(guidance_scale)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        print(f"🎬 Generating SDXL Video (nsfw={bool(nsfw_mode)}, cfg={effective_cfg}): '{clean_prompt}' (Model: {model_file})")

        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        import queue
        import threading
        import base64
        import traceback

        q = queue.Queue()

        def callback(pipe, step_index, timestep, callback_kwargs):
            q.put({"step": step_index, "max_steps": num_inference_steps})
            return callback_kwargs

        def generate_task():
            try:
                start_time = time.time()
                # Guarantee VAE starts in float16 on CUDA even if a prior request was canceled mid-decode
                self.pipe.vae.to(device="cuda", dtype=torch.float16)
                output = self.pipe(
                    prompt=clean_prompt,
                    negative_prompt=cond_neg,
                    width=width,
                    height=height,
                    num_frames=num_frames,
                    guidance_scale=effective_cfg,
                    num_inference_steps=num_inference_steps,
                    generator=generator,
                    callback_on_step_end=callback
                ).frames[0]
                gen_elapsed = time.time() - start_time
                print(f"✅ Video generation ({num_frames} frames / {num_frames / 8.0:.1f}s) finished in {gen_elapsed:.2f}s!")

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

                    # AnimateDiff native temporal cadence is 8 FPS (16 frames = 2s ... 80 frames = 10s).
                    # If target playback fps > 8, interpolate to smooth target fps while preserving true duration.
                    base_fps = 8
                    target_fps = max(8, int(fps))
                    ff_params = ["-movflags", "+faststart", "-profile:v", "main"]
                    if target_fps > base_fps:
                        ff_params = [
                            "-vf", f"framerate=fps={target_fps}:interp_start=0:interp_end=255:scene=100",
                            "-r", str(target_fps),
                        ] + ff_params

                    imageio.mimwrite(
                        tmp_path, 
                        video_frames, 
                        fps=base_fps, 
                        format="FFMPEG", 
                        codec="h264", 
                        pixelformat="yuv420p", 
                        macro_block_size=2,
                        output_params=ff_params
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
                traceback.print_exc()
                try:
                    self.pipe.vae.to(device="cuda", dtype=torch.float16)
                except Exception:
                    pass
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
        prompt: str = "A cinematic video of a majestic dragon flying over a sunset ocean",
        model_name: str = "epic",
        negative_prompt: str = "bad quality, worse quality, artifacts, watermark",
        height: int = 1024,
        width: int = 1024,
        num_frames: int = 16,
        guidance_scale: float = 7.5,
        num_inference_steps: int = 25,
        seed: int = -1,
        fps: int = 8,
        duration: int = 0,
        nsfw_mode: int = 0,
        lora: str = "none",
    ) -> bytes:
        import base64
        msgs = list(self.run_stream.local(
            prompt=prompt, model_name=model_name, negative_prompt=negative_prompt, height=height, width=width,
            num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
            seed=seed, fps=fps, duration=duration, nsfw_mode=nsfw_mode, lora=lora
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
            duration = int(body.get("duration", 0))
            nsfw_mode = int(body.get("nsfw_mode", 0))
            lora = str(body.get("lora", "none"))

            video_bytes = self.inference.local(
                prompt=prompt, model_name=model_name, negative_prompt=negative_prompt, height=height, width=width,
                num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                seed=seed, fps=fps, duration=duration, nsfw_mode=nsfw_mode, lora=lora,
            )
            return {"data": [{"b64_json": base64.b64encode(video_bytes).decode("utf-8"), "content_type": "video/mp4"}]}

        @web_app.get("/stream")
        @web_app.get("/")
        def generate_endpoint(
            prompt: str, model_name: str = "epic", model: str = None, negative_prompt: str = "low quality", height: int = 1024, width: int = 1024,
            num_frames: int = 16, guidance_scale: float = 7.5, num_inference_steps: int = 25, seed: int = -1, fps: int = 8, duration: int = 0,
            nsfw_mode: int = 0, lora: str = "none",
        ):
            from fastapi.responses import StreamingResponse
            import json
            selected_model = model or model_name
            def event_stream():
                try:
                    for msg in self.run_stream.local(
                        prompt=prompt, model_name=selected_model, negative_prompt=negative_prompt, height=height, width=width,
                        num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=num_inference_steps,
                        seed=seed, fps=fps, duration=duration, nsfw_mode=nsfw_mode, lora=lora,
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


@app.local_entrypoint()
def main_txt2vid(
    prompt: str = "A highly detailed cinematic scene",
    model: str = "epic",
    negative_prompt: str = "low quality, blurry, distorted, static, jittery",
    height: int = 1024, width: int = 1024, num_frames: int = 16,
    guidance_scale: float = 7.5, steps: int = 25, seed: int = -1, fps: int = 8, duration: int = 0,
    nsfw_mode: int = 0, lora: str = "none",
    output: str = "/tmp/txt2vid-output/output.mp4",
):
    output_path = Path(output)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    print(f"🎬 Requesting video generation from Modal...")
    video_bytes = Txt2Vid().inference.remote(
        prompt=prompt, model_name=model, negative_prompt=negative_prompt, height=height, width=width,
        num_frames=num_frames, guidance_scale=guidance_scale, num_inference_steps=steps, seed=seed, fps=fps,
        duration=duration, nsfw_mode=nsfw_mode, lora=lora,
    )
    output_path.write_bytes(video_bytes)
    print(f"✅ Saved generated MP4 video to {output_path}")
