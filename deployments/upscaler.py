import io
import os
import time
import base64
import math
from pathlib import Path
import modal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np

from shared_app import app, CACHE_DIR, cache_volume, OUTPUTS_DIR, outputs_volume

UPSCALERS_DIR = Path(CACHE_DIR) / "upscalers"

# CNN Model definitions and URLs
UPSCALER_MODELS = {
    "realesrgan-x4plus": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "scale": 4,
        "num_block": 23,
        "filename": "RealESRGAN_x4plus.pth",
        "name": "RealESRGAN x4plus (Photorealistic)"
    },
    "realesrgan-anime": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "scale": 4,
        "num_block": 6,
        "filename": "RealESRGAN_x4plus_anime_6B.pth",
        "name": "RealESRGAN x4plus Anime (Lineart & 2D)"
    },
    "ultrasharp-4x": {
        "url": "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x-UltraSharp.pth",
        "scale": 4,
        "num_block": 23,
        "filename": "4x-UltraSharp.pth",
        "name": "4x UltraSharp (Ultra-Crisp Textures)"
    },
    "tile-creative": {
        "type": "diffusion",
        "name": "SDXL ControlNet Tile (Creative Diffusion)",
        "scale": 4
    },
    "controlnet-tile": {
        "type": "diffusion",
        "name": "SDXL ControlNet Tile (Creative Diffusion)",
        "scale": 4
    },
    "dsp-fast": {
        "type": "dsp",
        "name": "Fast Adaptive DSP (Lanczos)",
        "scale": 4
    }
}

# ControlNet Tile models mapping
CONTROLNET_TILE_MODELS = {
    "xinsir": "xinsir/controlnet-tile-sdxl-1.0",
    "xinsir-tile": "xinsir/controlnet-tile-sdxl-1.0",
    "xinsir/controlnet-tile-sdxl-1.0": "xinsir/controlnet-tile-sdxl-1.0",
    "thibaud": "thibaud/controlnet-sd21-tile-sdxl",
    "thibaud-tile": "thibaud/controlnet-sd21-tile-sdxl",
    "thibaud/controlnet-sd21-tile-sdxl": "thibaud/controlnet-sd21-tile-sdxl",
    "default": "xinsir/controlnet-tile-sdxl-1.0"
}

# Modal image with PyTorch, Diffusers, Transformers, Accelerate, Safetensors
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install(
        "opencv-python-headless",
        "Pillow",
        "fastapi[standard]",
        "pydantic",
        "torch==2.5.1",
        "torchvision==0.20.1",
        "requests",
        "numpy",
        "accelerate>=0.33.0",
        "diffusers>=0.31.0",
        "transformers~=4.44.0",
        "safetensors>=0.4.5",
        "huggingface-hub>=0.25.0",
        "sentencepiece>=0.2.0",
        "peft>=0.6.0",
        "omegaconf>=2.3.0",
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "HF_HUB_CACHE": CACHE_DIR,
        }
    )
    .add_local_python_source("shared_app")
)

volumes = {CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume}
secrets = [modal.Secret.from_name("huggingface-secret")]


# --- PURE PYTORCH RRDBNet ARCHITECTURE ---
def create_rrdbnet_classes():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ResidualDenseBlock_5C(nn.Module):
        def __init__(self, nf=64, gc=32, bias=True):
            super().__init__()
            self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1, bias=bias)
            self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1, bias=bias)
            self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1, bias=bias)
            self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1, bias=bias)
            self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1, bias=bias)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, nf, gc=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock_5C(nf, gc)
            self.rdb2 = ResidualDenseBlock_5C(nf, gc)
            self.rdb3 = ResidualDenseBlock_5C(nf, gc)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
            super().__init__()
            self.scale = scale
            self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            feat = self.conv_first(x)
            body_feat = self.conv_body(self.body(feat))
            feat = feat + body_feat
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode='nearest')))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode='nearest')))
            out = self.conv_last(self.lrelu(self.conv_hr(feat)))
            return out

    return RRDBNet


# --- TILE CHUNKING & COSINE-FEATHERED BLENDING HELPERS ---
def compute_tile_slices_uniform(length: int, tile_len: int, min_overlap: int):
    """
    Computes symmetric, uniform tile start/end slices along a 1D dimension.
    Returns a list of tuples: (start, end, left_overlap_px, right_overlap_px).
    """
    if length <= tile_len:
        return [(0, length, 0, 0)]

    safe_min_ov = min(min_overlap, tile_len // 2)
    max_stride = max(1, tile_len - safe_min_ov)
    num_tiles = int(math.ceil((length - tile_len) / max_stride)) + 1
    num_steps = num_tiles - 1
    step_size = (length - tile_len) / num_steps

    starts = [int(round(i * step_size)) for i in range(num_tiles)]
    slices = []
    for i in range(num_tiles):
        s = starts[i]
        e = s + tile_len
        left_ov = max(0, starts[i - 1] + tile_len - s) if i > 0 else 0
        right_ov = max(0, e - starts[i + 1]) if i < num_tiles - 1 else 0
        slices.append((s, e, left_ov, right_ov))
    return slices


def create_cosine_weight_matrix(
    th: int,
    tw: int,
    top_ov: int,
    bottom_ov: int,
    left_ov: int,
    right_ov: int
) -> np.ndarray:
    """
    Constructs a 2D cosine-feathered weight matrix for a tile.
    Edges with active neighbor overlaps ramp from 0 to 1 with a C^1 continuous cosine curve:
      w(t) = 0.5 * (1 - cos(pi * (t + 0.5) / overlap))
    Edges on canvas borders remain at 1.0 (flat), eliminating boundary darkening.
    The sum of complementary cosine ramps across neighboring tiles is identically 1.0.
    """
    wy = np.ones(th, dtype=np.float32)
    if top_ov > 0 and top_ov <= th:
        idx = np.arange(top_ov, dtype=np.float32)
        wy[:top_ov] = 0.5 * (1.0 - np.cos(np.pi * (idx + 0.5) / top_ov))
    if bottom_ov > 0 and bottom_ov <= th:
        idx = np.arange(bottom_ov, dtype=np.float32)
        bottom_ramp = 0.5 * (1.0 - np.cos(np.pi * (bottom_ov - 1 - idx + 0.5) / bottom_ov))
        wy[-bottom_ov:] = np.minimum(wy[-bottom_ov:], bottom_ramp)

    wx = np.ones(tw, dtype=np.float32)
    if left_ov > 0 and left_ov <= tw:
        idx = np.arange(left_ov, dtype=np.float32)
        wx[:left_ov] = 0.5 * (1.0 - np.cos(np.pi * (idx + 0.5) / left_ov))
    if right_ov > 0 and right_ov <= tw:
        idx = np.arange(right_ov, dtype=np.float32)
        right_ramp = 0.5 * (1.0 - np.cos(np.pi * (right_ov - 1 - idx + 0.5) / right_ov))
        wx[-right_ov:] = np.minimum(wx[-right_ov:], right_ramp)

    w2d = np.outer(wy, wx).astype(np.float32)
    return np.maximum(w2d, 1e-4)


class UpscaleRequest(BaseModel):
    image_b64: str
    scale: int = 4
    model_name: str = "realesrgan-x4plus"
    denoise: float = 0.0
    sharpen: float = 0.3
    face_enhance: bool = False
    output_format: str = "png"
    # Creative Tile Diffusion Parameters
    mode: str = "standard"  # "standard" | "tile_creative"
    tile_size: int = 1024   # 512, 768, 1024
    tile_overlap: float = 0.25 # overlap percentage / ratio (0.05 to 0.50)
    creativity: float = 0.35 # denoise strength (0.05 to 0.95)
    denoise_strength: float = 0.35 # alias for creativity
    prompt: str = ""
    negative_prompt: str = ""
    controlnet_scale: float = 1.0
    controlnet_model: str = "xinsir/controlnet-tile-sdxl-1.0"
    base_checkpoint: str = "stabilityai/stable-diffusion-xl-base-1.0"
    num_inference_steps: int = 25
    guidance_scale: float = 6.0
    seed: int = -1


@app.cls(
    image=image,
    gpu="H100",
    volumes=volumes,
    secrets=secrets,
    scaledown_window=600,
    timeout=1200
)
class Upscaler:
    @modal.enter()
    def setup(self):
        self.loaded_models = {}
        self.loaded_diffusion_pipes = {}
        self.RRDBNet = create_rrdbnet_classes()

    def _ensure_weights(self, model_key: str) -> Path:
        import requests
        try:
            cache_volume.reload()
        except Exception as ve:
            print(f"[UPSCALER] Volume reload note (non-fatal): {ve}")
        UPSCALERS_DIR.mkdir(parents=True, exist_ok=True)

        meta = UPSCALER_MODELS.get(model_key, UPSCALER_MODELS["realesrgan-x4plus"])
        if "filename" not in meta or "url" not in meta:
            meta = UPSCALER_MODELS["realesrgan-x4plus"]
        dest = UPSCALERS_DIR / meta["filename"]

        if not dest.exists() or dest.stat().st_size < 1000000:
            print(f"[UPSCALER] Downloading weights for {model_key} from {meta['url']}...")
            try:
                with requests.get(meta["url"], stream=True, timeout=120) as r:
                    r.raise_for_status()
                    tmp_dest = dest.with_suffix(".tmp")
                    with open(tmp_dest, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            f.write(chunk)
                    tmp_dest.rename(dest)
                print(f"[UPSCALER] Successfully saved {dest.name} ({dest.stat().st_size / 1024 / 1024:.2f} MB)")
                cache_volume.commit()
            except Exception as e:
                print(f"[UPSCALER ERROR] Failed to download {meta['url']}: {e}")
                if dest.exists():
                    dest.unlink()
                raise e
        return dest

    def _get_model(self, model_key: str):
        import torch
        if model_key in self.loaded_models:
            return self.loaded_models[model_key]

        meta = UPSCALER_MODELS.get(model_key, UPSCALER_MODELS["realesrgan-x4plus"])
        if "filename" not in meta:
            meta = UPSCALER_MODELS["realesrgan-x4plus"]
        weights_path = self._ensure_weights(model_key if "filename" in UPSCALER_MODELS.get(model_key, {}) else "realesrgan-x4plus")

        num_block = meta.get("num_block", 23)
        scale = meta.get("scale", 4)
        model = self.RRDBNet(num_in_ch=3, num_out_ch=3, scale=scale, num_feat=64, num_block=num_block, num_grow_ch=32)

        loadnet = torch.load(str(weights_path), map_location=torch.device('cpu'), weights_only=False)
        keyname = 'params_ema' if 'params_ema' in loadnet else ('params' if 'params' in loadnet else None)
        state_dict = loadnet[keyname] if keyname is not None else loadnet

        cleaned = {}
        for k, v in state_dict.items():
            cleaned[k.replace('module.', '').replace('model.', '')] = v

        model.load_state_dict(cleaned, strict=False)
        model.eval()
        model = model.to("cuda")

        self.loaded_models[model_key] = model
        print(f"[UPSCALER] Loaded RRDBNet {model_key} onto CUDA.")
        return model

    def _predict_tiled(self, model, tensor, tile_size=512, tile_pad=16, scale=4):
        import torch
        batch, channel, height, width = tensor.shape
        device = "cuda"

        if height <= tile_size and width <= tile_size:
            with torch.no_grad():
                return model(tensor.to(device))

        output_h = height * scale
        output_w = width * scale
        output = torch.zeros((batch, channel, output_h, output_w), device=device)

        stride = tile_size - 2 * tile_pad
        h_steps = (height + stride - 1) // stride
        w_steps = (width + stride - 1) // stride

        for h_idx in range(h_steps):
            for w_idx in range(w_steps):
                top = h_idx * stride
                left = w_idx * stride

                top_pad = max(0, top - tile_pad)
                left_pad = max(0, left - tile_pad)
                bottom_pad = min(height, top + stride + tile_pad)
                right_pad = min(width, left + stride + tile_pad)

                tile = tensor[:, :, top_pad:bottom_pad, left_pad:right_pad].to(device)
                with torch.no_grad():
                    out_tile = model(tile)

                out_top = top * scale
                out_left = left * scale
                out_bottom = min(output_h, (top + stride) * scale)
                out_right = min(output_w, (left + stride) * scale)

                tile_top = (top - top_pad) * scale
                tile_left = (left - left_pad) * scale
                tile_bottom = tile_top + (out_bottom - out_top)
                tile_right = tile_left + (out_right - out_left)

                output[:, :, out_top:out_bottom, out_left:out_right] = out_tile[:, :, tile_top:tile_bottom, tile_left:tile_right]

        return output

    def _run_rrdbnet_upscale(self, input_img, scale: int = 4, model_name: str = "realesrgan-x4plus"):
        import torch
        import numpy as np
        from PIL import Image

        orig_w, orig_h = input_img.size
        target_w = orig_w * scale
        target_h = orig_h * scale

        if model_name == "dsp-fast" or model_name not in UPSCALER_MODELS or "filename" not in UPSCALER_MODELS.get(model_name, {}):
            return input_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

        try:
            model = self._get_model(model_name)
            img_np = np.array(input_img).astype(np.float32) / 255.0
            tensor = torch.from_numpy(np.transpose(img_np, (2, 0, 1))).unsqueeze(0)

            with torch.no_grad():
                out_tensor = self._predict_tiled(model, tensor, tile_size=512, scale=4)

            out_arr = out_tensor.data.squeeze(0).float().cpu().clamp_(0, 1).numpy()
            out_arr = np.transpose(out_arr, (1, 2, 0))
            out_arr = (out_arr * 255.0).round().astype(np.uint8)
            result_img = Image.fromarray(out_arr)

            if scale != 4:
                result_img = result_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)
            return result_img
        except Exception as e:
            print(f"[UPSCALER FALLBACK] RRDBNet inference failed: {e}. Using Lanczos.")
            return input_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

    def _get_diffusion_pipeline(
        self,
        controlnet_model_id: str = "xinsir/controlnet-tile-sdxl-1.0",
        base_checkpoint: str = "stabilityai/stable-diffusion-xl-base-1.0"
    ):
        pipe_key = f"{controlnet_model_id}::{base_checkpoint}"
        if pipe_key in self.loaded_diffusion_pipes:
            return self.loaded_diffusion_pipes[pipe_key]

        import torch
        from diffusers import (
            ControlNetModel,
            StableDiffusionXLControlNetImg2ImgPipeline,
            DPMSolverMultistepScheduler
        )

        print(f"[UPSCALER] Initializing SDXL ControlNet Tile ({controlnet_model_id})...")
        try:
            cache_volume.reload()
        except Exception as ve:
            print(f"[UPSCALER] Volume reload note (non-fatal): {ve}")

        cnet = ControlNetModel.from_pretrained(
            controlnet_model_id,
            torch_dtype=torch.bfloat16,
            cache_dir=str(CACHE_DIR),
            use_safetensors=True
        ).to("cuda")

        print(f"[UPSCALER] Initializing SDXL base model ({base_checkpoint})...")
        ckpt_path = Path(CACHE_DIR) / "checkpoints" / base_checkpoint
        if not ckpt_path.exists() and not base_checkpoint.endswith(".safetensors"):
            cand = Path(CACHE_DIR) / "checkpoints" / f"{base_checkpoint}.safetensors"
            if cand.exists():
                ckpt_path = cand

        if ckpt_path.exists():
            print(f"[UPSCALER] Loading SDXL base from single file: {ckpt_path}")
            pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_single_file(
                str(ckpt_path),
                controlnet=cnet,
                torch_dtype=torch.bfloat16,
                cache_dir=str(CACHE_DIR),
                use_safetensors=True
            )
        else:
            repo_id = base_checkpoint if "/" in base_checkpoint else "stabilityai/stable-diffusion-xl-base-1.0"
            print(f"[UPSCALER] Loading SDXL base from Hugging Face: {repo_id}")
            pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
                repo_id,
                controlnet=cnet,
                torch_dtype=torch.bfloat16,
                cache_dir=str(CACHE_DIR),
                use_safetensors=True
            )

        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            use_karras_sigmas=True,
            algorithm_type="sde-dpmsolver++"
        )
        pipe = pipe.to("cuda")

        try:
            pipe.enable_vae_tiling()
        except Exception:
            pass

        self.loaded_diffusion_pipes[pipe_key] = pipe
        print(f"[UPSCALER] SDXL ControlNet Tile pipeline loaded and ready.")
        return pipe

    def _tile_creative_upscale(
        self,
        input_img,
        scale: int = 4,
        tile_size: int = 1024,
        tile_overlap: float = 0.25,
        creativity: float = 0.35,
        prompt: str = "",
        negative_prompt: str = "",
        controlnet_scale: float = 1.0,
        controlnet_model: str = "xinsir/controlnet-tile-sdxl-1.0",
        base_checkpoint: str = "stabilityai/stable-diffusion-xl-base-1.0",
        num_inference_steps: int = 25,
        guidance_scale: float = 6.0,
        seed: int = -1,
        pre_model_name: str = "realesrgan-x4plus"
    ):
        import torch
        import numpy as np
        from PIL import Image

        orig_w, orig_h = input_img.size
        target_w = orig_w * scale
        target_h = orig_h * scale

        print(f"[UPSCALER TILE] Starting Tile Creative Upscaling ({scale}x: {orig_w}x{orig_h} -> {target_w}x{target_h})")

        # 1. Base pre-upscale stage (RRDBNet neural model or Lanczos)
        if pre_model_name in UPSCALER_MODELS and "filename" in UPSCALER_MODELS[pre_model_name]:
            base_highres = self._run_rrdbnet_upscale(input_img, scale=scale, model_name=pre_model_name)
        else:
            base_highres = input_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

        # 2. Determine effective tile size & overlap
        t_size = max(256, (int(tile_size) // 64) * 64)
        if target_w < t_size or target_h < t_size:
            t_size = max(256, (min(target_w, target_h) // 64) * 64)

        # Handle percentage (e.g. 25 -> 0.25) or ratio (0.25)
        overlap_ratio = float(tile_overlap)
        if overlap_ratio > 1.0:
            overlap_ratio = overlap_ratio / 100.0
        overlap_ratio = max(0.05, min(0.50, overlap_ratio))
        min_overlap_px = max(16, int(t_size * overlap_ratio))

        # Handle creativity percentage (e.g. 35 -> 0.35) or ratio (0.35)
        denoise_str = float(creativity)
        if denoise_str > 1.0:
            denoise_str = denoise_str / 100.0
        denoise_str = max(0.05, min(0.95, denoise_str))

        # 3. Compute uniform tile grid slices
        y_slices = compute_tile_slices_uniform(target_h, t_size, min_overlap_px)
        x_slices = compute_tile_slices_uniform(target_w, t_size, min_overlap_px)
        total_tiles = len(y_slices) * len(x_slices)

        print(f"[UPSCALER TILE] Grid layout: {len(x_slices)} cols x {len(y_slices)} rows = {total_tiles} tiles (tile_size={t_size}, overlap_ratio={overlap_ratio:.2f}, denoise={denoise_str:.2f})")

        # 4. Resolve ControlNet and Base Checkpoint
        cnet_id = CONTROLNET_TILE_MODELS.get(controlnet_model, controlnet_model)

        # 5. Load pipeline
        try:
            pipe = self._get_diffusion_pipeline(controlnet_model_id=cnet_id, base_checkpoint=base_checkpoint)
        except Exception as e:
            print(f"[UPSCALER ERROR] Failed to load SDXL ControlNet Tile pipeline: {e}. Fallback to pre-upscaled image.")
            return base_highres

        # 6. Seeding
        if seed < 0:
            seed = int(time.time() * 1000) % (2**32 - 1)
        generator = torch.Generator(device="cuda").manual_seed(seed)

        prompt_str = (prompt or "").strip()
        if not prompt_str:
            prompt_str = "high quality, ultra sharp, 8k uhd, detailed masterpiece, fine textures, photorealistic"
        neg_prompt_str = (negative_prompt or "").strip()
        if not neg_prompt_str:
            neg_prompt_str = "blur, blurry, lowres, distortion, artifacts, noise, pixelated, ugly, deformed"

        accum_canvas = np.zeros((target_h, target_w, 3), dtype=np.float32)
        weight_canvas = np.zeros((target_h, target_w), dtype=np.float32)

        tile_count = 0
        for (y1, y2, top_ov, btm_ov) in y_slices:
            for (x1, x2, left_ov, rgt_ov) in x_slices:
                tile_count += 1
                crop_w = x2 - x1
                crop_h = y2 - y1
                tile_crop = base_highres.crop((x1, y1, x2, y2))

                need_resize = (crop_w != t_size or crop_h != t_size)
                if need_resize:
                    diff_in = tile_crop.resize((t_size, t_size), Image.Resampling.LANCZOS)
                else:
                    diff_in = tile_crop

                try:
                    with torch.inference_mode():
                        try:
                            diff_out = pipe(
                                prompt=prompt_str,
                                negative_prompt=neg_prompt_str,
                                image=diff_in,
                                control_image=diff_in,
                                strength=denoise_str,
                                guidance_scale=float(guidance_scale),
                                num_inference_steps=int(num_inference_steps),
                                controlnet_conditioning_scale=float(controlnet_scale),
                                generator=generator
                            ).images[0]
                        except TypeError:
                            diff_out = pipe(
                                prompt=prompt_str,
                                negative_prompt=neg_prompt_str,
                                image=diff_in,
                                strength=denoise_str,
                                guidance_scale=float(guidance_scale),
                                num_inference_steps=int(num_inference_steps),
                                generator=generator
                            ).images[0]
                except Exception as e:
                    print(f"[UPSCALER WARN] Diffusion inference failed for tile {tile_count}/{total_tiles}: {e}. Retaining base tile.")
                    diff_out = diff_in

                if need_resize:
                    diff_out = diff_out.resize((crop_w, crop_h), Image.Resampling.LANCZOS)

                tile_out_np = np.array(diff_out).astype(np.float32)

                # Compute 2D cosine weight matrix
                w_matrix = create_cosine_weight_matrix(
                    th=crop_h,
                    tw=crop_w,
                    top_ov=top_ov,
                    bottom_ov=btm_ov,
                    left_ov=left_ov,
                    right_ov=rgt_ov
                )

                accum_canvas[y1:y2, x1:x2] += tile_out_np * w_matrix[:, :, None]
                weight_canvas[y1:y2, x1:x2] += w_matrix

        # 7. Normalize blended canvas
        blended_np = accum_canvas / np.maximum(weight_canvas[:, :, None], 1e-6)
        blended_np = np.clip(blended_np, 0, 255).round().astype(np.uint8)
        return Image.fromarray(blended_np)

    @modal.method()
    def upscale_image(
        self,
        image_b64: str,
        scale: int = 4,
        model_name: str = "realesrgan-x4plus",
        denoise: float = 0.0,
        sharpen: float = 0.3,
        face_enhance: bool = False,
        output_format: str = "png",
        mode: str = "standard",
        tile_size: int = 1024,
        tile_overlap: float = 0.25,
        creativity: float = 0.35,
        denoise_strength: float = 0.35,
        prompt: str = "",
        negative_prompt: str = "",
        controlnet_scale: float = 1.0,
        controlnet_model: str = "xinsir/controlnet-tile-sdxl-1.0",
        base_checkpoint: str = "stabilityai/stable-diffusion-xl-base-1.0",
        num_inference_steps: int = 25,
        guidance_scale: float = 6.0,
        seed: int = -1,
        **kwargs
    ) -> dict:
        import io
        import base64
        import time
        from PIL import Image, ImageFilter, ImageEnhance
        t0 = time.time()

        # Clean base64 input
        raw_b64 = image_b64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",")[1]

        image_data = base64.b64decode(raw_b64)
        input_img = Image.open(io.BytesIO(image_data)).convert("RGB")
        orig_w, orig_h = input_img.size

        # Validate scale
        if scale not in [2, 4, 8]:
            scale = 4

        target_w = orig_w * scale
        target_h = orig_h * scale

        effective_creativity = creativity
        if denoise_strength != 0.35 and creativity == 0.35:
            effective_creativity = denoise_strength

        is_tile_creative = (
            mode == "tile_creative"
            or model_name in ["tile-creative", "controlnet-tile", "tile_creative", "sdxl-tile", "controlnet-tile-sdxl"]
        )

        try:
            if is_tile_creative:
                # Stage 1 + Stage 2: Pre-upscale + SDXL ControlNet Tile diffusion pass
                pre_model = model_name if model_name in UPSCALER_MODELS and "filename" in UPSCALER_MODELS[model_name] else "realesrgan-x4plus"
                result_img = self._tile_creative_upscale(
                    input_img=input_img,
                    scale=scale,
                    tile_size=tile_size,
                    tile_overlap=tile_overlap,
                    creativity=effective_creativity,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    controlnet_scale=controlnet_scale,
                    controlnet_model=controlnet_model,
                    base_checkpoint=base_checkpoint,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    seed=seed,
                    pre_model_name=pre_model
                )
            elif model_name != "dsp-fast" and model_name in UPSCALER_MODELS:
                # Pure PyTorch RRDBNet neural upscale (4x native)
                result_img = self._run_rrdbnet_upscale(input_img, scale=scale, model_name=model_name)
            else:
                # Fast Lanczos DSP Super-Resolution
                result_img = input_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"[UPSCALER FALLBACK] Upscale pipeline error: {e}. Executing adaptive DSP upsample...")
            result_img = input_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

        # Apply post-processing enhancements
        if denoise > 0.05:
            result_img = result_img.filter(ImageFilter.MedianFilter(size=3))

        if sharpen > 0.05:
            enhancer = ImageEnhance.Sharpness(result_img)
            result_img = enhancer.enhance(1.0 + float(sharpen) * 1.5)

        if face_enhance:
            contrast = ImageEnhance.Contrast(result_img)
            result_img = contrast.enhance(1.04)
            color = ImageEnhance.Color(result_img)
            result_img = color.enhance(1.03)

        # Export result
        out_buf = io.BytesIO()
        fmt = "JPEG" if output_format.lower() in ["jpg", "jpeg"] else "PNG"
        mime = "image/jpeg" if fmt == "JPEG" else "image/png"

        if fmt == "JPEG":
            result_img.save(out_buf, format=fmt, quality=95, optimize=True)
        else:
            result_img.save(out_buf, format=fmt, compress_level=4)

        out_b64 = base64.b64encode(out_buf.getvalue()).decode("utf-8")
        elapsed = round(time.time() - t0, 3)

        reported_model = f"SDXL ControlNet Tile ({controlnet_model})" if is_tile_creative else model_name

        # Optionally commit to outputs volume
        try:
            out_dir = Path(OUTPUTS_DIR) / "upscaler"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"upscale_{int(time.time() * 1000)}_{scale}x.{fmt.lower()}"
            out_file.write_bytes(out_buf.getvalue())
            outputs_volume.commit()
        except Exception:
            pass

        return {
            "status": "success",
            "image_b64": f"data:{mime};base64,{out_b64}",
            "original_width": orig_w,
            "original_height": orig_h,
            "upscaled_width": result_img.width,
            "upscaled_height": result_img.height,
            "scale": scale,
            "model": reported_model,
            "mode": "tile_creative" if is_tile_creative else "standard",
            "tile_size": tile_size if is_tile_creative else None,
            "tile_overlap": tile_overlap if is_tile_creative else None,
            "creativity": effective_creativity if is_tile_creative else None,
            "seed": seed if is_tile_creative else None,
            "elapsed_time_s": elapsed
        }

    @modal.fastapi_endpoint(method="POST")
    def web_upscale(self, req: UpscaleRequest):
        effective_creativity = req.creativity if req.creativity is not None else req.denoise_strength
        return self.upscale_image.local(
            image_b64=req.image_b64,
            scale=req.scale,
            model_name=req.model_name,
            denoise=req.denoise,
            sharpen=req.sharpen,
            face_enhance=req.face_enhance,
            output_format=req.output_format,
            mode=req.mode,
            tile_size=req.tile_size,
            tile_overlap=req.tile_overlap,
            creativity=effective_creativity,
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            controlnet_scale=req.controlnet_scale,
            controlnet_model=req.controlnet_model,
            base_checkpoint=req.base_checkpoint,
            num_inference_steps=req.num_inference_steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed
        )

    @modal.fastapi_endpoint(method="POST")
    def tile_creative(self, req: UpscaleRequest):
        req.mode = "tile_creative"
        return self.web_upscale(req)

    @modal.fastapi_endpoint(method="GET")
    def status(self):
        return {
            "status": "online",
            "modes": ["standard", "tile_creative"],
            "cnn_models": list(UPSCALER_MODELS.keys()),
            "controlnet_tile_models": list(CONTROLNET_TILE_MODELS.keys()),
            "supported_scales": [2, 4, 8],
            "default_tile_size": 1024,
            "default_tile_overlap": 0.25
        }


@app.cls(
    image=image,
    gpu="L40S",
    volumes=volumes,
    secrets=secrets,
    scaledown_window=60,
    max_containers=1,
    timeout=1200
)
class Upscaler_Eco(Upscaler._get_user_cls()):
    """Economy tier endpoint for public/standard users. Cost-optimized on L40S with 60s scaledown."""
    pass
