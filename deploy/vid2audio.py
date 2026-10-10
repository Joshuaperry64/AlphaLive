"""
Video-to-Audio (V2A) Foley Synthesis Service on Modal
Powered by MMAudio (hkchengrex/MMAudio) - 44.1kHz Synchronized Video-Conditioned Audio Generation.
Supports Architect (L40S) & Economy (T4) Tiers, SSE real-time streaming, and muxed composite MP4 export.
"""

import io
import os
import time
import json
import base64
import random
import tempfile
from pathlib import Path
from typing import Optional

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
    .run_commands(
        "git clone --depth 1 https://github.com/hkchengrex/MMAudio.git /opt/mmaudio",
        "pip install --upgrade pip",
        "pip install -e /opt/mmaudio",
    )
    .uv_pip_install(
        "torch>=2.5.1",
        "torchaudio>=2.5.1",
        "torchvision>=0.20.1",
        "fastapi[standard]>=0.115.4",
        "huggingface-hub>=0.36.0",
        "numpy<2",
        "tqdm",
        "pydantic>=2.0",
    )
    .env({
        "HF_HUB_CACHE": CACHE_DIR,
        "HF_HOME": CACHE_DIR,
        "MMAUDIO_CACHE": CACHE_DIR,
        "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9;9.0",
    })
)

from shared_app import app

with image.imports():
    import torch
    import torchaudio
    from mmaudio.eval_utils import (
        ModelConfig, all_model_cfg, generate, load_video, make_video, setup_eval_logging
    )
    from mmaudio.model.flow_matching import FlowMatching
    from mmaudio.model.networks import MMAudio, get_my_mmaudio
    from mmaudio.model.utils.features_utils import FeaturesUtils

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)

image = image.add_local_python_source("shared_app")


@app.cls(
    image=image,
    gpu="L40S",  # Architect Tier: L40S high-performance node
    timeout=60 * MINUTES,
    scaledown_window=60,
    max_containers=1,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
class Vid2Audio:
    @modal.enter()
    def setup(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16
        self.current_variant = None
        self.net = None
        self.feature_utils = None
        self.model_cfg = None

        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

        print(f"[Vid2Audio] Initializing MMAudio engine on {self.device}...")
        self._load_model("large_44k_v2")

    def _load_model(self, variant: str):
        if self.current_variant == variant and self.net is not None:
            return

        if variant not in all_model_cfg:
            variant = "large_44k_v2"

        print(f"[Vid2Audio] Loading model variant: {variant}")
        self.model_cfg: ModelConfig = all_model_cfg[variant]
        self.model_cfg.download_if_needed()

        self.net = get_my_mmaudio(self.model_cfg.model_name).to(self.device, self.dtype).eval()
        self.net.load_weights(torch.load(self.model_cfg.model_path, map_location=self.device, weights_only=True))

        self.feature_utils = FeaturesUtils(
            tod_vae_ckpt=self.model_cfg.vae_path,
            synchformer_ckpt=self.model_cfg.synchformer_ckpt,
            enable_conditions=True,
            mode=self.model_cfg.mode,
            bigvgan_vocoder_ckpt=self.model_cfg.bigvgan_16k_path,
            need_vae_encoder=False
        ).to(self.device, self.dtype).eval()

        self.current_variant = variant
        print(f"[Vid2Audio] Successfully loaded {variant} into VRAM.")

    @modal.method()
    def run_stream(
        self,
        video_b64: str,
        prompt: str = "",
        negative_prompt: str = "low quality, muffled, noise, distorted, static",
        duration: float = 8.0,
        num_steps: int = 25,
        cfg_strength: float = 4.5,
        variant: str = "large_44k_v2",
        seed: int = -1,
        return_video: bool = True
    ):
        """
        Processes video frames and generates synchronized audio using MMAudio.
        Yields step progress updates and final synthesized audio + composite video.
        """
        yield {"step": 0, "max_steps": num_steps, "status": "Initializing neural pipeline"}

        if seed < 0:
            seed = random.randint(0, 2**31 - 1)

        rng = torch.Generator(device=self.device)
        rng.manual_seed(seed)

        self._load_model(variant)
        seq_cfg = self.model_cfg.seq_cfg

        # Save base64 video to temporary file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
            tmp_in_path = Path(tmp_in.name)
            video_bytes = base64.b64decode(video_b64)
            tmp_in.write(video_bytes)

        output_dir = Path(tempfile.mkdtemp())

        try:
            yield {"step": 1, "max_steps": num_steps, "status": "Extracting temporal video features"}

            # Load video frames and visual sync embeddings
            video_info = load_video(tmp_in_path, duration)
            clip_frames = video_info.clip_frames.unsqueeze(0)
            sync_frames = video_info.sync_frames.unsqueeze(0)
            target_duration = video_info.duration_sec

            seq_cfg.duration = target_duration
            self.net.update_seq_lengths(seq_cfg.latent_seq_len, seq_cfg.clip_seq_len, seq_cfg.sync_seq_len)

            yield {"step": 5, "max_steps": num_steps, "status": "Diffusing synchronized audio"}

            fm = FlowMatching(min_sigma=0, inference_mode="euler", num_steps=num_steps)

            # Generate audio tensor
            audios = generate(
                clip_frames,
                sync_frames,
                [prompt],
                negative_text=[negative_prompt],
                feature_utils=self.feature_utils,
                net=self.net,
                fm=fm,
                rng=rng,
                cfg_strength=cfg_strength
            )

            audio = audios.float().cpu()[0]
            audio_save_path = output_dir / "generated_audio.wav"
            torchaudio.save(audio_save_path, audio, seq_cfg.sampling_rate)

            with open(audio_save_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            video_out_b64 = None
            if return_video:
                yield {"step": num_steps - 2, "max_steps": num_steps, "status": "Muxing synchronized composite video"}
                video_save_path = output_dir / "composite_video.mp4"
                make_video(video_info, video_save_path, audio, sampling_rate=seq_cfg.sampling_rate)
                with open(video_save_path, "rb") as f:
                    video_out_b64 = base64.b64encode(f.read()).decode("utf-8")

            yield {
                "step": num_steps,
                "max_steps": num_steps,
                "status": "Complete",
                "audio_b64": audio_b64,
                "video_b64": video_out_b64,
                "duration": target_duration,
                "sample_rate": seq_cfg.sampling_rate,
                "seed": seed,
                "variant": variant
            }

        except Exception as e:
            yield {"error": str(e)}
        finally:
            if tmp_in_path.exists():
                tmp_in_path.unlink()
            for p in output_dir.glob("*"):
                try:
                    p.unlink()
                except:
                    pass
            try:
                output_dir.rmdir()
            except:
                pass

    @modal.method()
    def generate(
        self,
        video_b64: str,
        prompt: str = "",
        negative_prompt: str = "low quality, muffled, noise, distorted",
        duration: float = 8.0,
        num_steps: int = 25,
        cfg_strength: float = 4.5,
        variant: str = "large_44k_v2",
        seed: int = -1,
        return_video: bool = True
    ) -> dict:
        """Non-streaming remote execution method for monolithic deployment integration."""
        msgs = list(self.run_stream.local(
            video_b64=video_b64,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            num_steps=num_steps,
            cfg_strength=cfg_strength,
            variant=variant,
            seed=seed,
            return_video=return_video,
        ))
        final_msg = msgs[-1]
        if "error" in final_msg:
            raise RuntimeError(final_msg["error"])
        return final_msg

    @modal.asgi_app()
    def web(self):
        import fastapi
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse, JSONResponse

        web_app = FastAPI(title="AlphaCore Vid2Audio Service")
        web_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @web_app.get("/health")
        def health():
            return {
                "status": "online",
                "engine": "MMAudio 44.1kHz",
                "device": getattr(self, "device", "cuda"),
                "variant": getattr(self, "current_variant", "large_44k_v2")
            }

        @web_app.post("/")
        @web_app.post("/generate")
        async def generate_post(request: fastapi.Request):
            body = await request.json()
            video_b64 = body.get("video") or body.get("video_b64")
            if not video_b64:
                return JSONResponse(status_code=400, content={"error": "Missing 'video' (base64) parameter"})

            prompt = body.get("prompt", "")
            negative_prompt = body.get("negative_prompt", "low quality, muffled, noise, distorted")
            duration = float(body.get("duration", 8.0))
            num_steps = int(body.get("num_steps", 25))
            cfg_strength = float(body.get("cfg_strength", 4.5))
            variant = body.get("variant", "large_44k_v2")
            seed = int(body.get("seed", -1))
            return_video = bool(body.get("return_video", True))

            try:
                msgs = list(self.run_stream.local(
                    video_b64=video_b64,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    duration=duration,
                    num_steps=num_steps,
                    cfg_strength=cfg_strength,
                    variant=variant,
                    seed=seed,
                    return_video=return_video,
                ))
                final_msg = msgs[-1]
                if "error" in final_msg:
                    return JSONResponse(status_code=500, content={"error": final_msg["error"]})
                return final_msg
            except Exception as e:
                return JSONResponse(status_code=500, content={"error": str(e)})

        @web_app.post("/stream")
        async def generate_stream(request: fastapi.Request):
            body = await request.json()
            video_b64 = body.get("video") or body.get("video_b64")
            if not video_b64:
                return JSONResponse(status_code=400, content={"error": "Missing 'video' parameter"})

            prompt = body.get("prompt", "")
            negative_prompt = body.get("negative_prompt", "low quality, muffled, noise, distorted")
            duration = float(body.get("duration", 8.0))
            num_steps = int(body.get("num_steps", 25))
            cfg_strength = float(body.get("cfg_strength", 4.5))
            variant = body.get("variant", "large_44k_v2")
            seed = int(body.get("seed", -1))
            return_video = bool(body.get("return_video", True))

            def event_stream():
                try:
                    for msg in self.run_stream.local(
                        video_b64=video_b64,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        duration=duration,
                        num_steps=num_steps,
                        cfg_strength=cfg_strength,
                        variant=variant,
                        seed=seed,
                        return_video=return_video,
                    ):
                        yield ": " + " " * 4096 + "\n"
                        yield f"data: {json.dumps(msg)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        return web_app

