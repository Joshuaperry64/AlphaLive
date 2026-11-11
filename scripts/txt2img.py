# ---
# output-directory: "/tmp/stable-diffusion"
# args: ["--prompt", "A cinematic photo"]
# ---

import io
import random
import time
from pathlib import Path

import modal

MINUTES = 60

from shared_app import app, CACHE_DIR, cache_volume, OUTPUTS_DIR, outputs_volume

# Checkpoints built on SD1.5 (loaded with StableDiffusionPipeline instead of SDXL)
SD15_CHECKPOINTS = {"realisticComicBook_v10.safetensors"}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "accelerate==0.33.0",
        "diffusers==0.31.0",
        "DeepCache",
        "fastapi[standard]==0.115.4",
        "huggingface-hub==0.36.0",
        "sentencepiece==0.2.0",
        "torch==2.5.1",
        "torchvision==0.20.1",
        "transformers~=4.44.0",
        "omegaconf>=2.3.0",
        "peft>=0.6.0",
        "safetensors>=0.4.5",  
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "HF_HUB_CACHE": CACHE_DIR,
        }
    )
)

with image.imports():
    from diffusers import StableDiffusionXLPipeline, EulerDiscreteScheduler, LCMScheduler
    from DeepCache import DeepCacheSDHelper
    from huggingface_hub import hf_hub_download
    import diffusers
    import torch
    import torch.nn.functional as F
    from safetensors.torch import load_file, save_file
    from fastapi import Response
    from transformers import CLIPVisionModelWithProjection

LIGHTNING_REPO = "ByteDance/SDXL-Lightning"
LIGHTNING_CKPT = "sdxl_lightning_4step_lora.safetensors"
DEFAULT_WARMUP_CHECKPOINT = "epicrealismXL_pureFix.safetensors"


# --- REGIONAL PROMPTING (MASKED CROSS-ATTENTION / ATTENTION COUPLE) ---
def build_regional_mask(height: int, width: int, mode: str, num_regions: int, device, dtype):
    """
    Generates normalized spatial masks of shape (num_regions, height, width)
    with smooth Gaussian-like boundary blending for Regional Prompting.
    """
    H, W = height, width
    y_coords = torch.linspace(0, 1, H, device=device, dtype=dtype).view(H, 1).expand(H, W)
    x_coords = torch.linspace(0, 1, W, device=device, dtype=dtype).view(1, W).expand(H, W)
    mode = (mode or "none").lower().strip()

    raw_masks = []
    sharpness = 16.0  # smooth transition across region boundary

    if mode in ("left_right", "horizontal", "cols", "2col") or (mode == "auto" and num_regions == 2):
        m_left = torch.sigmoid((0.5 - x_coords) * sharpness)
        m_right = 1.0 - m_left
        raw_masks = [m_left, m_right]
    elif mode in ("top_bottom", "vertical", "rows", "2row"):
        m_top = torch.sigmoid((0.5 - y_coords) * sharpness)
        m_bottom = 1.0 - m_top
        raw_masks = [m_top, m_bottom]
    elif mode in ("three_col", "3col", "thirds"):
        m1 = torch.sigmoid((0.333 - x_coords) * sharpness)
        m3 = torch.sigmoid((x_coords - 0.667) * sharpness)
        m2 = torch.clamp(1.0 - m1 - m3, min=0.0)
        raw_masks = [m1, m2, m3]
    elif mode in ("center_bg", "center_background", "spotlight"):
        dist = torch.sqrt((x_coords - 0.5) ** 2 + (y_coords - 0.5) ** 2)
        m_center = torch.sigmoid((0.32 - dist) * sharpness)
        m_bg = 1.0 - m_center
        raw_masks = [m_center, m_bg]
    elif mode in ("quadrants", "grid", "4quad"):
        m_left = torch.sigmoid((0.5 - x_coords) * sharpness)
        m_right = 1.0 - m_left
        m_top = torch.sigmoid((0.5 - y_coords) * sharpness)
        m_bottom = 1.0 - m_top
        raw_masks = [m_top * m_left, m_top * m_right, m_bottom * m_left, m_bottom * m_right]
    else:
        # Equal vertical columns fallback for arbitrary num_regions
        edges = torch.linspace(0, 1, num_regions + 1, device=device, dtype=dtype)
        for i in range(num_regions):
            left_edge = edges[i]
            right_edge = edges[i + 1]
            m = ((x_coords >= left_edge) & (x_coords <= right_edge)).to(dtype)
            raw_masks.append(m)

    # Pad or truncate to match exact num_regions
    while len(raw_masks) < num_regions:
        raw_masks.append(torch.ones((H, W), device=device, dtype=dtype) / num_regions)
    raw_masks = raw_masks[:num_regions]

    stacked = torch.stack(raw_masks, dim=0)  # (R, H, W)
    stacked = stacked / (stacked.sum(dim=0, keepdim=True) + 1e-6)
    return stacked


class RegionalAttnProcessor2_0:
    """
    Wraps a standard Cross-Attention processor (or IPAttnProcessor2_0) to perform
    Regional Prompting (Attention Couple) across spatial latent masks while preserving
    both Classifier-Free Guidance (CFG), Base Prompt blending, and IP-Adapter image tokens.
    """

    def __init__(
        self,
        base_processor,
        region_cond_embeds: list,
        regional_mode: str = "left_right",
        base_ratio: float = 0.2,
        latent_hw: tuple = (128, 128),
    ):
        self.base_processor = base_processor
        self.region_cond_embeds = region_cond_embeds  # list of (B, seq_len, dim) tensors
        self.regional_mode = regional_mode
        self.base_ratio = float(base_ratio)
        self.latent_hw = latent_hw
        self._mask_cache = {}

    def _get_masks(self, seq_len: int, device, dtype):
        key = (seq_len, str(device), str(dtype))
        if key in self._mask_cache:
            return self._mask_cache[key]

        orig_h, orig_w = self.latent_hw
        aspect = orig_w / max(1, orig_h)
        h = max(1, int(round((seq_len / aspect) ** 0.5)))
        w = max(1, seq_len // h)
        if h * w != seq_len:
            for cand_h in range(int(seq_len**0.5), 0, -1):
                if seq_len % cand_h == 0:
                    h = cand_h
                    w = seq_len // cand_h
                    break

        masks_2d = build_regional_mask(
            h, w, self.regional_mode, len(self.region_cond_embeds), device, dtype
        )  # (R, h, w)
        masks_flat = masks_2d.reshape(len(self.region_cond_embeds), 1, seq_len, 1)
        self._mask_cache[key] = masks_flat
        return masks_flat

    def __call__(
        self,
        attn,
        hidden_states,
        encoder_hidden_states=None,
        attention_mask=None,
        temb=None,
        *args,
        **kwargs,
    ):
        # Self-attention or no regional embeds: delegate directly
        if encoder_hidden_states is None or not self.region_cond_embeds:
            return self.base_processor(
                attn,
                hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
                temb=temb,
                *args,
                **kwargs,
            )

        # Extract IP-Adapter image tokens if encoder_hidden_states is a tuple or longer than text tokens
        ip_tokens_full = None
        text_seq_len = self.region_cond_embeds[0].shape[1]
        if isinstance(encoder_hidden_states, tuple):
            text_encoder_states, ip_tokens_full = encoder_hidden_states
        elif (
             hasattr(encoder_hidden_states, "shape")
            and encoder_hidden_states.shape[1] > text_seq_len
        ):
            text_encoder_states = encoder_hidden_states[:, :text_seq_len, :]
            ip_tokens_full = encoder_hidden_states[:, text_seq_len:, :]
        else:
            text_encoder_states = encoder_hidden_states

        # Base forward pass (handles Uncond + Base Prompt + IP-Adapter if present)
        base_out = self.base_processor(
            attn,
            hidden_states,
            encoder_hidden_states=encoder_hidden_states,
            attention_mask=attention_mask,
            temb=temb,
            *args,
            **kwargs,
        )

        batch_total, seq_len, _ = hidden_states.shape
        r_batch = self.region_cond_embeds[0].shape[0]

        # Determine whether CFG is active (batch_total == 2 * r_batch) or LCM / non-CFG (batch_total == r_batch)
        has_cfg = batch_total == 2 * r_batch
        if has_cfg:
            hidden_uncond, hidden_cond = hidden_states.chunk(2, dim=0)
            base_uncond, base_cond = base_out.chunk(2, dim=0)
            ip_cond = ip_tokens_full.chunk(2, dim=0)[1] if ip_tokens_full is not None else None
        elif batch_total == r_batch:
            hidden_cond = hidden_states
            base_cond = base_out
            ip_cond = ip_tokens_full
        else:
            return base_out

        # Compute spatially masked regional cross-attention on the conditional branch
        masks = self._get_masks(seq_len, hidden_cond.device, hidden_cond.dtype)
        regional_accum = torch.zeros_like(base_cond)

        for r_idx, reg_emb in enumerate(self.region_cond_embeds):
            reg_emb_cast = reg_emb.to(device=hidden_cond.device, dtype=hidden_cond.dtype)
            if ip_cond is not None:
                if isinstance(encoder_hidden_states, tuple):
                    reg_enc = (reg_emb_cast, ip_cond)
                else:
                    reg_enc = torch.cat([reg_emb_cast, ip_cond], dim=1)
            else:
                reg_enc = reg_emb_cast

            reg_out = self.base_processor(
                attn,
                hidden_cond,
                encoder_hidden_states=reg_enc,
                attention_mask=attention_mask,
                temb=temb.chunk(2, dim=0)[1] if (temb is not None and has_cfg) else temb,
                *args,
                **kwargs,
            )
            regional_accum = regional_accum + reg_out * masks[r_idx]

        blended_cond = (self.base_ratio * base_cond) + ((1.0 - self.base_ratio) * regional_accum)

        if has_cfg:
            return torch.cat([base_uncond, blended_cond], dim=0)
        return blended_cond

# Volumes imported from shared_app


image = image.add_local_python_source("shared_app")


def ensure_pipeline_dtype(pipe, target_dtype=None, device="cuda"):
    """
    Exhaustively converts pipeline, components, submodules, parameters,
    attention processors (including IP-Adapter processors in dicts), image_proj_model,
    and buffers to target_dtype and device.
    Explicitly aligns module.bias and module.weight to eradicate any dtype mismatch
    (e.g. c10::BFloat16 vs float).
    """
    if pipe is None:
        return
    import torch
    if target_dtype is None:
        target_dtype = torch.bfloat16

    try:
        pipe.to(device=device, dtype=target_dtype)
    except Exception:
        pass

    visited_modules = set()

    def _convert_module(mod):
        if mod is None or not isinstance(mod, torch.nn.Module):
            return
        mod_id = id(mod)
        if mod_id in visited_modules:
            return
        visited_modules.add(mod_id)

        try:
            mod.to(device=device, dtype=target_dtype)
        except Exception:
            pass

        for m in mod.modules():
            try:
                m.to(device=device, dtype=target_dtype)
            except Exception:
                pass

            # Update Parameter objects in _parameters dict directly
            if hasattr(m, "_parameters") and isinstance(m._parameters, dict):
                for p_name, param in list(m._parameters.items()):
                    if param is not None and isinstance(param, torch.Tensor) and param.dtype.is_floating_point:
                        if param.dtype != target_dtype:
                            try:
                                m._parameters[p_name] = torch.nn.Parameter(
                                    param.data.to(device=device, dtype=target_dtype),
                                    requires_grad=param.requires_grad
                                )
                            except Exception:
                                try:
                                    param.data = param.data.to(device=device, dtype=target_dtype)
                                except Exception:
                                    pass

            # Update Buffer objects in _buffers dict directly
            if hasattr(m, "_buffers") and isinstance(m._buffers, dict):
                for b_name, buf in list(m._buffers.items()):
                    if buf is not None and isinstance(buf, torch.Tensor) and buf.dtype.is_floating_point:
                        if buf.dtype != target_dtype:
                            try:
                                m._buffers[b_name] = buf.data.to(device=device, dtype=target_dtype)
                            except Exception:
                                pass

            # Direct bias & weight checks
            if hasattr(m, "bias") and m.bias is not None:
                if isinstance(m.bias, torch.Tensor) and m.bias.dtype.is_floating_point and m.bias.dtype != target_dtype:
                    try:
                        m.bias.data = m.bias.data.to(device=device, dtype=target_dtype)
                    except Exception:
                        pass
            if hasattr(m, "weight") and m.weight is not None:
                if isinstance(m.weight, torch.Tensor) and m.weight.dtype.is_floating_point and m.weight.dtype != target_dtype:
                    try:
                        m.weight.data = m.weight.data.to(device=device, dtype=target_dtype)
                    except Exception:
                        pass

        # Check for attention processors if attached
        attn_procs = getattr(mod, "attn_processors", None)
        if isinstance(attn_procs, dict):
            for proc in attn_procs.values():
                if isinstance(proc, torch.nn.Module):
                    _convert_module(proc)

    # 1. Scan components dict
    components = getattr(pipe, "components", {})
    if isinstance(components, dict):
        for comp in components.values():
            if isinstance(comp, torch.nn.Module):
                _convert_module(comp)

    # 2. Scan all known attributes & dynamic attributes on pipe
    for attr in dir(pipe):
        if attr.startswith("__"):
            continue
        try:
            val = getattr(pipe, attr, None)
            if isinstance(val, torch.nn.Module):
                _convert_module(val)
            elif isinstance(val, (dict, list, tuple)):
                items = val.values() if isinstance(val, dict) else val
                for item in items:
                    if isinstance(item, torch.nn.Module):
                        _convert_module(item)
        except Exception:
            pass

@app.cls(
    image=image,
    gpu="H100",
    timeout=10 * MINUTES,
    scaledown_window=10 * MINUTES,
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("alphacore-secrets")],
)
class Txt2Img:
    current_model = None
    pipe = None

    @modal.enter()
    def setup(self):
        self.current_model = None
        self.pipe = None
        self.deepcache_helper = None
        self.loaded_ip_adapter_mode = None
        self.loaded_image_encoder_sub = None

        # Pre-load default SDXL checkpoint and trigger AOT torch.compile warmup during container spin-up
        try:
            ckpt_dir = Path(CACHE_DIR) / "checkpoints"
            warmup_ckpt = DEFAULT_WARMUP_CHECKPOINT
            if not (ckpt_dir / warmup_ckpt).exists():
                alt_ckpts = [
                    p.name for p in ckpt_dir.glob("*.safetensors")
                    if p.name not in SD15_CHECKPOINTS and not p.name.endswith(".tmp")
                ]
                if alt_ckpts:
                    warmup_ckpt = alt_ckpts[0]

            if (ckpt_dir / warmup_ckpt).exists():
                print(f"🔥 [COLD-START WARMUP] Loading pipeline for '{warmup_ckpt}' inside @modal.enter()...")
                self._load_model(warmup_ckpt, compile_unet=False)
                print("✅ [COLD-START WARMUP] Model weights loaded and ready for real-time requests.")
            else:
                print(f"⚠️ [COLD-START WARMUP] No checkpoint found in {ckpt_dir}; deferring load to first request.")
        except Exception as warmup_err:
            print(f"⚠️ [COLD-START WARMUP] Non-fatal warmup notice: {warmup_err}")

    def _apply_sdxl_optimizations(self, pipe, is_sd15: bool = False, compile_unet: bool = True):
        """
        Applies SDXL acceleration & clean quality configurations:
        1. Clean float32 VAE decoding (eliminates horizontal Fourier lines, NaNs, and grid banding)
        2. Channels-last memory format on U-Net & VAE
        3. torch.compile on U-Net (mode='default')
        Note: SDXL-Lightning 4-step LoRA is loaded dynamically only when lightning/lcm mode is explicitly requested.
        """
        import torch._dynamo

        # Configure TorchDynamo to cleanly handle dynamic Python hooks (e.g., DeepCache, IP-Adapter, Regional Prompting)
        torch._dynamo.config.suppress_errors = True
        torch._dynamo.config.capture_scalar_outputs = True

        # Ensure FreeU is completely disabled to eliminate Fourier frequency sinc-ringing lines / horizontal bands
        try:
            if hasattr(pipe, "disable_freeu"):
                pipe.disable_freeu()
        except Exception:
            pass

        # Channels-last memory format on U-Net & clean float32 precision on VAE to eliminate lines/banding
        try:
            pipe.unet.to(memory_format=torch.channels_last)
            if hasattr(pipe, "vae") and pipe.vae is not None:
                pipe.vae.to(dtype=torch.float32, memory_format=torch.channels_last)
            print("✅ [MEMORY & PRECISION] U-Net channels_last & VAE float32 precision active (lines eliminated).")
        except Exception as mem_err:
            print(f"⚠️ [MEMORY FORMAT] Warning: {mem_err}")

        if compile_unet:
            try:
                print("⚙️ [AOT COMPILE] Compiling pipe.unet with torch.compile(mode='default')...")
                pipe.unet = torch.compile(pipe.unet, mode="default")
                print("✅ [AOT COMPILE] U-Net wrapped for compilation.")
            except Exception as comp_err:
                print(f"⚠️ [AOT COMPILE] Warning: {comp_err}")

    def _is_clip_component_error(self, err: Exception) -> bool:
        name = type(err).__name__
        msg = str(err).lower()
        return (
            "SingleFileComponentError" in name
            or "cliptextmodel" in msg
            or "text_encoder" in msg
            or "failed to load clip" in msg
        )

    def _clip_bundle_from_hub(self, dtype, is_sd15: bool):
        from transformers import CLIPTextModel, CLIPTokenizer

        if is_sd15:
            repo = "runwayml/stable-diffusion-v1-5"
            print(f"Fetching SD1.5 CLIP text encoder from {repo}...")
            return {
                "text_encoder": CLIPTextModel.from_pretrained(repo, subfolder="text_encoder", torch_dtype=dtype),
                "tokenizer": CLIPTokenizer.from_pretrained(repo, subfolder="tokenizer"),
            }

        from transformers import CLIPTextModelWithProjection

        repo = "stabilityai/stable-diffusion-xl-base-1.0"
        print(f"Fetching SDXL CLIP text encoders from {repo}...")
        return {
            "text_encoder": CLIPTextModel.from_pretrained(repo, subfolder="text_encoder", torch_dtype=dtype),
            "text_encoder_2": CLIPTextModelWithProjection.from_pretrained(repo, subfolder="text_encoder_2", torch_dtype=dtype),
            "tokenizer": CLIPTokenizer.from_pretrained(repo, subfolder="tokenizer"),
            "tokenizer_2": CLIPTokenizer.from_pretrained(repo, subfolder="tokenizer_2"),
        }

    def _clip_bundle_from_local_checkpoint(self, filename: str, dtype, is_sd15: bool):
        ref_path = Path(CACHE_DIR) / "checkpoints" / filename
        if not ref_path.exists():
            return None
        print(f"Stealing CLIP text encoders from local checkpoint {filename}...")
        if is_sd15:
            from diffusers import StableDiffusionPipeline
            ref = StableDiffusionPipeline.from_single_file(
                str(ref_path),
                torch_dtype=dtype,
                use_safetensors=True,
                safety_checker=None,
            )
            bundle = {"text_encoder": ref.text_encoder, "tokenizer": ref.tokenizer}
            ref.text_encoder = None
        else:
            ref = StableDiffusionXLPipeline.from_single_file(
                str(ref_path),
                torch_dtype=dtype,
                use_safetensors=True,
                add_watermarker=False,
            )
            bundle = {
                "text_encoder": ref.text_encoder,
                "text_encoder_2": ref.text_encoder_2,
                "tokenizer": ref.tokenizer,
                "tokenizer_2": ref.tokenizer_2,
            }
            ref.text_encoder = None
            ref.text_encoder_2 = None
        del ref
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return bundle

    def _from_single_file_with_clip_fallback(self, model_path, model_filename, is_sd15, dtype):
        if is_sd15:
            from diffusers import StableDiffusionPipeline
            loader = StableDiffusionPipeline.from_single_file
            extra = {"safety_checker": None}
        else:
            loader = StableDiffusionXLPipeline.from_single_file
            extra = {"add_watermarker": False}

        kwargs = {"torch_dtype": dtype, "use_safetensors": True, **extra}
        try:
            return loader(str(model_path), **kwargs)
        except Exception as err:
            if not self._is_clip_component_error(err):
                raise
            print(f"⚠️ CLIP weights missing in {model_filename}: {err}")
            print("Retrying from_single_file with external text encoders...")

            bundle = None
            fallback_name = "realisticComicBook_v10.safetensors" if is_sd15 else DEFAULT_WARMUP_CHECKPOINT
            if fallback_name != model_filename:
                try:
                    bundle = self._clip_bundle_from_local_checkpoint(fallback_name, dtype, is_sd15)
                except Exception as local_err:
                    print(f"⚠️ Local CLIP steal failed: {local_err}")
                    bundle = None
            if bundle is None:
                bundle = self._clip_bundle_from_hub(dtype, is_sd15)

            return loader(str(model_path), **kwargs, **bundle)

    def _load_model(self, model_filename: str, compile_unet: bool = False):
        if not hasattr(self, "pipe"):
            self.pipe = None
        if not hasattr(self, "current_model"):
            self.current_model = None

        if self.current_model == model_filename and self.pipe is not None:
            return

        if getattr(self, "pipe", None) is not None:
            print(f"Unloading {getattr(self, 'current_model', 'model')} from VRAM...")
            if getattr(self, "deepcache_helper", None) is not None:
                try:
                    self.deepcache_helper.disable()
                except Exception:
                    pass
                self.deepcache_helper = None
            old_pipe = self.pipe
            self.pipe = None
            self.loaded_ip_adapter_mode = None
            self.loaded_image_encoder_sub = None
            try:
                del old_pipe
            except Exception:
                pass
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        print(f"Loading {model_filename} into VRAM...")
        model_path = Path(CACHE_DIR) / "checkpoints" / model_filename
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at: {model_path}. Did you upload it?")

        is_sd15 = model_filename in SD15_CHECKPOINTS
        dtype = torch.float16 if is_sd15 else torch.bfloat16
        self.pipe = self._from_single_file_with_clip_fallback(
            model_path, model_filename, is_sd15=is_sd15, dtype=dtype
        ).to("cuda")
        if hasattr(self.pipe, "watermark"):
            self.pipe.watermark = None

        self._apply_sdxl_optimizations(self.pipe, is_sd15=is_sd15, compile_unet=compile_unet)
            
        self.current_model = model_filename
        self.loaded_ip_adapter_mode = None
        self.loaded_image_encoder_sub = None

    def _configure_ip_adapter(self, run_pipe, ip_adapter_image_b64: str, ip_adapter_scale: float, ip_adapter_mode: str, is_sd15: bool):
        """Loads and configures IP-Adapter (Standard Style/Composition or Face/Identity ViT-H) if an image is provided."""
        import base64
        import io
        from PIL import Image
        from transformers import CLIPVisionModelWithProjection

        if not ip_adapter_image_b64 or not ip_adapter_image_b64.strip():
            # If an IP-Adapter was previously loaded on self.pipe, dial scale to 0 or unload
            if getattr(self, "loaded_ip_adapter_mode", None) is not None:
                try:
                    run_pipe.unload_ip_adapter()
                    self.loaded_ip_adapter_mode = None
                except Exception:
                    try:
                        run_pipe.set_ip_adapter_scale(0.0)
                    except Exception:
                        pass
            return None

        clean_b64 = ip_adapter_image_b64.split(",", 1)[1] if "," in ip_adapter_image_b64 else ip_adapter_image_b64.strip()
        ip_pil = Image.open(io.BytesIO(base64.b64decode(clean_b64))).convert("RGB")

        mode = (ip_adapter_mode or "standard").lower().strip()
        target_dtype = torch.float16 if is_sd15 else torch.bfloat16

        if is_sd15:
            subfolder = "models"
            encoder_sub = "models/image_encoder"
            if "face" in mode:
                weight_name = "ip-adapter-plus-face_sd15.bin"
            elif "plus" in mode:
                weight_name = "ip-adapter-plus_sd15.bin"
            else:
                weight_name = "ip-adapter_sd15.bin"
        else:
            subfolder = "sdxl_models"
            if "face" in mode:
                weight_name = "ip-adapter-plus-face_sdxl_vit-h.bin"
                encoder_sub = "models/image_encoder"
            elif "plus" in mode:
                weight_name = "ip-adapter-plus_sdxl_vit-h.bin"
                encoder_sub = "models/image_encoder"
            else:
                weight_name = "ip-adapter_sdxl.bin"
                encoder_sub = "sdxl_models/image_encoder"

        adapter_key = f"{subfolder}/{weight_name}"
        if getattr(self, "loaded_ip_adapter_mode", None) != adapter_key:
            print(f"[IP-ADAPTER] Loading {adapter_key} (encoder: {encoder_sub})...")
            if getattr(self, "loaded_image_encoder_sub", None) != encoder_sub:
                image_encoder = CLIPVisionModelWithProjection.from_pretrained(
                    "h94/IP-Adapter",
                    subfolder=encoder_sub,
                    torch_dtype=target_dtype,
                    cache_dir=CACHE_DIR,
                ).to("cuda")
                run_pipe.register_modules(image_encoder=image_encoder)
                if run_pipe is not self.pipe:
                    self.pipe.register_modules(image_encoder=image_encoder)
                self.loaded_image_encoder_sub = encoder_sub

            run_pipe.load_ip_adapter(
                "h94/IP-Adapter",
                subfolder=subfolder,
                weight_name=weight_name,
                cache_dir=CACHE_DIR,
            )
            self.loaded_ip_adapter_mode = adapter_key

            # Strictly enforce target_dtype on all newly attached IP-Adapter layers
            ensure_pipeline_dtype(run_pipe, target_dtype)

            try:
                cache_volume.commit()
            except Exception:
                pass

        run_pipe.set_ip_adapter_scale(float(ip_adapter_scale))
        print(f"[IP-ADAPTER] Active ({weight_name}) at scale={float(ip_adapter_scale):.2f}")
        return ip_pil

    def _apply_regional_prompting(
        self,
        run_pipe,
        regional_mode: str,
        regional_prompts_str: str,
        regional_base_ratio: float,
        batch_size: int,
        height: int,
        width: int,
        is_sd15: bool,
    ):
        """
        Encodes regional sub-prompts and wraps Cross-Attention (attn2) processors with
        RegionalAttnProcessor2_0 so each spatial region attends to its dedicated prompt.
        Returns the original attn_processors dict so it can be cleanly restored after generation.
        """
        mode = (regional_mode or "none").lower().strip()
        if mode in ("none", "", "off", "disabled") or not regional_prompts_str:
            return None

        import json as _json
        region_texts = []
        raw_str = regional_prompts_str.strip()
        if raw_str.startswith("["):
            try:
                parsed = _json.loads(raw_str)
                if isinstance(parsed, list):
                    region_texts = [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        if not region_texts:
            if "||" in raw_str:
                region_texts = [p.strip() for p in raw_str.split("||") if p.strip()]
            elif "BREAK" in raw_str:
                region_texts = [p.strip() for p in raw_str.split("BREAK") if p.strip()]
            else:
                region_texts = [raw_str]

        if len(region_texts) < 1:
            return None

        print(f"[REGIONAL PROMPTING] Mode='{mode}', Regions={len(region_texts)}, BaseRatio={regional_base_ratio:.2f}")
        region_cond_embeds = []
        with torch.no_grad():
            for idx, r_text in enumerate(region_texts):
                print(f"  -> Region #{idx + 1}: {r_text[:80]}")
                if is_sd15:
                    enc_res = run_pipe.encode_prompt(
                        prompt=r_text,
                        device="cuda",
                        num_images_per_prompt=batch_size,
                        do_classifier_free_guidance=False,
                    )
                    prompt_emb = enc_res[0] if isinstance(enc_res, tuple) else enc_res
                else:
                    enc_res = run_pipe.encode_prompt(
                        prompt=r_text,
                        prompt_2=r_text,
                        device="cuda",
                        num_images_per_prompt=batch_size,
                        do_classifier_free_guidance=False,
                    )
                    prompt_emb = enc_res[0]
                region_cond_embeds.append(prompt_emb)

        orig_processors = dict(run_pipe.unet.attn_processors)
        new_processors = {}
        latent_hw = (max(1, height // 8), max(1, width // 8))
        for name, proc in orig_processors.items():
            if name.endswith("attn2.processor"):
                new_processors[name] = RegionalAttnProcessor2_0(
                    base_processor=proc,
                    region_cond_embeds=region_cond_embeds,
                    regional_mode=mode,
                    base_ratio=regional_base_ratio,
                    latent_hw=latent_hw,
                )
            else:
                new_processors[name] = proc

        run_pipe.unet.set_attn_processor(new_processors)
        return orig_processors

    def _merge_and_load(self, model1_name: str, model2_name: str, merged_name: str):
        merged_path = Path(CACHE_DIR) / "checkpoints" / merged_name
        
        if not merged_path.exists():
            print("🚀 BOTH MODELS SELECTED! Initiating 50/50 Checkpoint Merge...")
            print("⚠️ This will take ~60 seconds but will only happen ONCE. Caching result...")
            
            path1 = Path(CACHE_DIR) / "checkpoints" / model1_name
            path2 = Path(CACHE_DIR) / "checkpoints" / model2_name
            
            if not path1.exists() or not path2.exists():
                raise FileNotFoundError("Cannot merge: One or both source models are missing from the folder.")

            tensors1 = load_file(path1)
            tensors2 = load_file(path2)
            
            merged_tensors = {}
            for key in tensors1.keys():
                if key in tensors2:
                    merged_tensors[key] = (tensors1[key] * 0.5) + (tensors2[key] * 0.5)
                else:
                    merged_tensors[key] = tensors1[key]
            
            save_file(merged_tensors, merged_path)
            print(f"✅ Merge complete! Saved as {merged_name}")
            
            del tensors1, tensors2, merged_tensors
            
        self._load_model(merged_name)

    @modal.method()
    def run(
        self, 
        prompt: str, 
        control_image_b64: str = "", 
        control_type: str = "none", 
        controlnet_conditioning_scale: float = 1.0, 
        JuggernautXL: int = 0,          
        CyberRealisticXL: int = 0,      
        EpicRealismXL: int = 0,
        UnholyDesireXL: int = 0,
        Lustify: int = 0,
        AutismPony: int = 0,
        model_name: str = "jugg",
        negative_prompt: str = "low quality, blurry, distorted", 
        batch_size: int = 4, 
        guidance_scale: str = "7.0", 
        num_inference_steps: int = 30, 
        scheduler: str = "Euler a", 
        sampler: str = "",
        amateur: int = 0,
        comic_mode: int = 0,
        seed: int = -1,
        lora: str = "none",
        width: int = 1024,
        height: int = 1024,
        lcm_mode: int = 0,
        ip_adapter_image_b64: str = "",
        ip_adapter_scale: float = 0.6,
        ip_adapter_mode: str = "standard",
        regional_mode: str = "none",
        regional_prompts: str = "",
        regional_base_ratio: float = 0.2,
    ) -> list[bytes]:
        import torch
        import io
        import base64
        from PIL import Image
        
        if model_name.endswith(".safetensors"):
            model_file = model_name
        elif EpicRealismXL == 1 or model_name.lower().startswith("epic"):
            model_file = "epicrealismXL_pureFix.safetensors"
        elif CyberRealisticXL == 1 or model_name.lower().startswith("cyber"):
            model_file = "cyberrealisticXL_desireV30.safetensors"
        elif UnholyDesireXL == 1 or model_name.lower().startswith("unholy"):
            model_file = "unholyDesireMixCrimson_v50.safetensors"
        elif Lustify == 1 or model_name.lower().startswith("lust"):
            model_file = "lustifyNSFWCheckpoint_zenithV9.safetensors"
        elif ("pony" in model_name.lower() and "cyber" in model_name.lower()) or "cyberrealisticpony" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "cyberrealisticPony_v180Coreshift.safetensors"
        elif AutismPony == 1 or model_name.lower().startswith("autism") or model_name.lower().startswith("pony"):
            model_file = "autismmixSDXL_autismmixPony.safetensors"
        elif "comicbook" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "realisticComicBook_v10.safetensors"
        elif model_name.lower().startswith("juicy"):
            model_file = "juicyDreams_v10.safetensors"
        elif model_name.lower().startswith("0x7"):
            model_file = "0x7RealisticFreedom_omegaSDXL.safetensors"
        elif "realvis" in model_name.lower() or "realvisxl" in model_name.lower():
            model_file = "realvisxlV50_v50Bakedvae.safetensors"
        elif model_name.lower().startswith("into") or "realism" in model_name.lower() and "epic" not in model_name.lower() and "vision" not in model_name.lower():
            model_file = "intorealism_sdxlV4.safetensors"
        elif "vision" in model_name.lower() or "realisticvision" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "realvisxlV50_v50Bakedvae.safetensors"
        elif "fullyreal" in model_name.lower().replace(" ", "").replace("_", ""):
            model_file = "fullyREALXL_v30TRINITY.safetensors"
        else:
            model_file = "juggernautXL_ragnarok.safetensors"
            
        self._load_model(model_file)
        is_sd15 = model_file in SD15_CHECKPOINTS

        run_pipe = self.pipe
        controlnet_image_obj = None
        if control_type and control_type.lower() != "none" and control_image_b64:
            if not hasattr(self, "controlnets"):
                self.controlnets = {}
            ctype = control_type.lower()
            if ctype not in self.controlnets:
                from diffusers import ControlNetModel
                print(f"Loading ControlNet: {ctype}...")
                if ctype == "canny":
                    model_id = "diffusers/controlnet-canny-sdxl-1.0"
                elif ctype == "depth":
                    model_id = "diffusers/controlnet-depth-sdxl-1.0"
                elif ctype == "openpose":
                    model_id = "thibaud/controlnet-openpose-sdxl-1.0"
                else:
                    raise ValueError(f"Unknown controlnet type {ctype}")
                
                self.controlnets[ctype] = ControlNetModel.from_pretrained(
                    model_id, 
                    torch_dtype=torch.bfloat16,
                    cache_dir="/hf-hub-cache"
                ).to("cuda")
                
            cnet = self.controlnets[ctype]
            
            import base64
            from PIL import Image
            import io
            
            bdata = control_image_b64.split(",")[1] if "," in control_image_b64 else control_image_b64
            controlnet_image_obj = Image.open(io.BytesIO(base64.b64decode(bdata))).convert("RGB")
            
            from diffusers import StableDiffusionXLControlNetPipeline
            components = {k: v for k, v in self.pipe.components.items() if k != "controlnet"}
            components["controlnet"] = cnet
            run_pipe = StableDiffusionXLControlNetPipeline(**components)


        if guidance_scale is None or str(guidance_scale).strip() == "":
            guidance_scale = "0.0"
        g_scale_float = float(guidance_scale)
        batch_size = max(1, batch_size)
        width = max(512, int(width or 1024) // 8 * 8)
        height = max(512, int(height or 1024) // 8 * 8)

        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        print(f"Seeding RNG with: {seed}")
        torch.manual_seed(seed)

        # Combine sampler and scheduler strings to parse them comprehensively
        chosen_sampler = f"{sampler} {scheduler}".lower().strip()
        # Lightning mode is active ONLY if explicitly requested via lcm_mode=1 toggle
        is_lightning_active = bool(not is_sd15 and int(lcm_mode or 0) == 1)
        is_sd15_lcm_active = bool(is_sd15 and int(lcm_mode or 0) == 1)

        if is_lightning_active:
            print("⚡ [SDXL-LIGHTNING] Activating 4-step LoRA adapter + EulerDiscreteScheduler(timestep_spacing='trailing')...")
            run_pipe.scheduler = diffusers.EulerDiscreteScheduler.from_config(
                run_pipe.scheduler.config,
                timestep_spacing="trailing",
            )
            if not num_inference_steps or num_inference_steps > 8:
                num_inference_steps = 4
            if g_scale_float > 2.0:
                g_scale_float = 0.0
        elif is_sd15_lcm_active:
            print("⚡ [LCM-LoRA SD1.5] Activating LCMScheduler for Real-Time Consistency Inference...")
            run_pipe.scheduler = diffusers.LCMScheduler.from_config(run_pipe.scheduler.config)
            if g_scale_float > 2.5 or g_scale_float < 1.0:
                g_scale_float = 1.5
            if num_inference_steps > 12:
                num_inference_steps = 6
        elif "euler a" in chosen_sampler:
            run_pipe.scheduler = diffusers.EulerAncestralDiscreteScheduler.from_config(run_pipe.scheduler.config)
        # Note: diffusers has a known bug with solver_order=3 and sde-dpmsolver++ (UnboundLocalError on x_t).
        # We catch 3M requests and safely route them through the stable 2nd-order SDE mathematics instead.
        elif "3m" in chosen_sampler and "sde" in chosen_sampler and "karras" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, algorithm_type="sde-dpmsolver++", use_karras_sigmas=True)
        elif "3m" in chosen_sampler and "sde" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, algorithm_type="sde-dpmsolver++")
        elif "2m" in chosen_sampler and "sde" in chosen_sampler and "karras" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, algorithm_type="sde-dpmsolver++", use_karras_sigmas=True)
        elif "dpm++ 2m karras" in chosen_sampler or "dpm++_2m_karras" in chosen_sampler or ("2m" in chosen_sampler and "karras" in chosen_sampler):
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, use_karras_sigmas=True)
        elif "dpm++ sde karras" in chosen_sampler or "dpm++_sde_karras" in chosen_sampler or ("sde" in chosen_sampler and "karras" in chosen_sampler):
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, algorithm_type="sde-dpmsolver++", use_karras_sigmas=True)
        elif "dpm++ 2m" in chosen_sampler or "dpm++_2m" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config)
        elif "dpm++ sde" in chosen_sampler or "dpm++_sde" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config, algorithm_type="sde-dpmsolver++")
        elif "ddim" in chosen_sampler:
            run_pipe.scheduler = diffusers.DDIMScheduler.from_config(run_pipe.scheduler.config)
        elif "lms" in chosen_sampler:
            run_pipe.scheduler = diffusers.LMSDiscreteScheduler.from_config(run_pipe.scheduler.config)
        elif "heun" in chosen_sampler:
            run_pipe.scheduler = diffusers.HeunDiscreteScheduler.from_config(run_pipe.scheduler.config)
        elif "unipc" in chosen_sampler:
            run_pipe.scheduler = diffusers.UniPCMultistepScheduler.from_config(run_pipe.scheduler.config)
        elif "dpm" in chosen_sampler:
            run_pipe.scheduler = diffusers.DPMSolverMultistepScheduler.from_config(run_pipe.scheduler.config)
        else:
            run_pipe.scheduler = diffusers.EulerDiscreteScheduler.from_config(run_pipe.scheduler.config)

        # Handle Amateur UI toggle
        if amateur == 1:
            if lora and lora.lower() != "none":
                lora += ",New_Amateurs_XL"
            else:
                lora = "New_Amateurs_XL"

        # Load LoRAs
        loaded_adapters = []
        adapter_weights = []

        if is_lightning_active:
            try:
                from huggingface_hub import hf_hub_download
                light_name = "sdxl_lightning_4step"
                ckpt_path = hf_hub_download(LIGHTNING_REPO, LIGHTNING_CKPT, cache_dir=CACHE_DIR)
                run_pipe.load_lora_weights(ckpt_path, adapter_name=light_name)
                loaded_adapters.append(light_name)
                adapter_weights.append(1.0)
            except Exception as light_e:
                print(f"[SDXL] SDXL-Lightning dynamic LoRA load note: {light_e}")

        if is_sd15_lcm_active:
            lcm_repo = "latent-consistency/lcm-lora-sdv1-5"
            lcm_adapter_name = "lcm_lora_adapter"
            local_lcm = Path(CACHE_DIR) / "loras" / "lcm_lora_sd15.safetensors"
            try:
                if local_lcm.exists():
                    print(f"⚡ [LCM-LoRA] Loading cached LCM weights from {local_lcm}")
                    run_pipe.load_lora_weights(str(local_lcm.parent), weight_name=local_lcm.name, adapter_name=lcm_adapter_name)
                else:
                    print(f"⚡ [LCM-LoRA] Loading {lcm_repo} from HuggingFace Hub...")
                    run_pipe.load_lora_weights(lcm_repo, weight_name="pytorch_lora_weights.safetensors", adapter_name=lcm_adapter_name, cache_dir=CACHE_DIR)
                    try:
                        cache_volume.commit()
                    except Exception:
                        pass
                loaded_adapters.append(lcm_adapter_name)
                adapter_weights.append(1.0)
            except Exception as lcm_err:
                print(f"⚠️ Failed to load LCM-LoRA ({lcm_repo}): {lcm_err}")

        if lora and lora.lower() != "none":
            loras_to_load = [l.strip() for l in lora.split(",") if l.strip() and l.strip() != "none"]
            for l in loras_to_load:
                clean_name = l.replace(".safetensors", "")
                if clean_name in ("lcm-lora-sdxl", "lcm_lora_sdxl", "lcm", "sdxl_lightning_4step_lora"):
                    continue
                lora_path = Path("/hf-hub-cache/loras") / f"{clean_name}.safetensors"
                if not lora_path.exists():
                    candidates = list(Path("/hf-hub-cache/loras").glob(f"*{clean_name}*.safetensors"))
                    if candidates:
                        lora_path = candidates[0]
                if lora_path.exists():
                    print(f"Loading LoRA: {lora_path}")
                    try:
                        run_pipe.load_lora_weights(
                            str(lora_path.parent), 
                            weight_name=lora_path.name, 
                            adapter_name=clean_name
                        )
                        loaded_adapters.append(clean_name)
                        adapter_weights.append(0.8 if (is_lightning_active or is_sd15_lcm_active) else 1.0)
                    except Exception as le:
                        print(f"⚠️ Failed to load LoRA {clean_name} (architecture mismatch or corrupt): {le}")
                else:
                    print(f"LoRA {lora_path} not found!")
                    
        if loaded_adapters:
            try:
                run_pipe.set_adapters(loaded_adapters, adapter_weights=adapter_weights)
            except Exception as ae:
                print(f"⚠️ Failed to activate LoRA adapters: {ae}")

        # 1. Configure IP-Adapter (Image Prompting)
        ip_pil_image = None
        try:
            ip_pil_image = self._configure_ip_adapter(
                run_pipe=run_pipe,
                ip_adapter_image_b64=ip_adapter_image_b64,
                ip_adapter_scale=ip_adapter_scale,
                ip_adapter_mode=ip_adapter_mode,
                is_sd15=is_sd15,
            )
        except Exception as ip_err:
            print(f"⚠️ [IP-ADAPTER] Configuration warning: {ip_err}")
            ip_pil_image = None

        import queue
        import threading
        import base64

        if getattr(self, "_gen_lock", None) is None:
            self._gen_lock = threading.Lock()

        q = queue.Queue()

        def callback(pipe, step_index, timestep, callback_kwargs):
            q.put({"step": step_index, "max_steps": num_inference_steps})
            return callback_kwargs

        def generate_task():
            import io
            import base64
            all_images_b64 = []
            orig_attn_processors = None
            with self._gen_lock:
                try:
                    # Comic Mode prompt & negative prompt adaptations
                    base_prompt = prompt
                    effective_neg = negative_prompt or ""
                    if comic_mode == 1:
                        comic_neg = "illegible text, gibberish lettering, smeared speech bubbles, unreadable typography, messy pseudo-letters, blurry captions, distorted dialogue balloons, cut off text, watermark, bad anatomy, photorealistic, 3d render"
                        effective_neg = (effective_neg + ", " + comic_neg) if effective_neg else comic_neg

                    images_completed = 0
                    while images_completed < batch_size:
                        current_page = images_completed + 1
                        if comic_mode == 1 and batch_size > 1:
                            if current_page == 1:
                                current_prompt = f"Page 1 of {batch_size}, opening chapter, establishing scene: {base_prompt}, dynamic comic book page layout, narrative introduction caption box, character dialogue speech bubble with bold legible comic text, crisp graphic novel inks, vibrant cell shading"
                            elif current_page < batch_size:
                                current_prompt = f"Page {current_page} of {batch_size}, scene continuation, rising action and dialogue exchange: {base_prompt}, expressive character reactions, conversation speech balloons with bold legible text, clear thought bubble, dramatic panel transitions"
                            else:
                                current_prompt = f"Page {current_page} of {batch_size}, final concluding comic book page, climactic moment and resolution: {base_prompt}, dramatic character face-off, final dialogue balloons with crisp legible lettering, concluding narrative caption 'TO BE CONTINUED...', epic graphic novel finale"
                            current_batch_size = 1
                        else:
                            current_prompt = (
                                f"comic book page, comic panel layout, dynamic graphic novel art, clean legible speech bubbles, white dialogue balloons with bold black typography, clear thought bubble with crisp text, sound effects onomatopoeia: {base_prompt}"
                                if comic_mode == 1 else base_prompt
                            )
                            current_batch_size = min(batch_size - images_completed, 10)

                        # 2. Configure Regional Prompting (Masked Cross-Attention) for current chunk batch size
                        if orig_attn_processors is not None:
                            try:
                                run_pipe.unet.set_attn_processor(orig_attn_processors)
                            except Exception:
                                pass
                            orig_attn_processors = None

                        if regional_mode and regional_mode.lower() not in ("none", "", "off") and regional_prompts:
                            try:
                                orig_attn_processors = self._apply_regional_prompting(
                                    run_pipe=run_pipe,
                                    regional_mode=regional_mode,
                                    regional_prompts_str=regional_prompts,
                                    regional_base_ratio=float(regional_base_ratio),
                                    batch_size=current_batch_size,
                                    height=height,
                                    width=width,
                                    is_sd15=is_sd15,
                                )
                            except Exception as reg_err:
                                print(f"⚠️ [REGIONAL PROMPTING] Setup warning: {reg_err}")
                                orig_attn_processors = None

                        def chunk_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": num_inference_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        kwargs = {
                            "width": width,
                            "height": height,
                        }
                        if controlnet_image_obj:
                            kwargs["image"] = controlnet_image_obj.resize((width, height), Image.Resampling.LANCZOS)
                            kwargs["controlnet_conditioning_scale"] = float(controlnet_conditioning_scale)
                        if ip_pil_image is not None:
                            kwargs["ip_adapter_image"] = ip_pil_image

                        ensure_pipeline_dtype(run_pipe, target_dtype=torch.float16 if is_sd15 else torch.bfloat16)
                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16 if is_sd15 else torch.bfloat16):
                            chunk_images = run_pipe(
                                prompt=current_prompt,
                                negative_prompt=(effective_neg if (effective_neg and g_scale_float > 0.0) else None),
                                num_images_per_prompt=current_batch_size,
                                num_inference_steps=num_inference_steps,
                                guidance_scale=g_scale_float,
                                callback_on_step_end=chunk_callback,
                                **kwargs
                            ).images
                        
                        chunk_b64 = []
                        out_dir = Path(OUTPUTS_DIR) / "txt2img"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        for idx, image in enumerate(chunk_images):
                            with io.BytesIO() as buf:
                                image.save(buf, format="PNG")
                                img_bytes = buf.getvalue()
                                b64 = base64.b64encode(img_bytes).decode("utf-8")
                                chunk_b64.append(b64)
                                all_images_b64.append(b64)
                            try:
                                filename = f"txt2img_{int(time.time() * 1000)}_{idx}_{seed}.png"
                                (out_dir / filename).write_bytes(img_bytes)
                            except Exception as fe:
                                print(f"[TXT2IMG] File write note: {fe}")
                        try:
                            outputs_volume.commit()
                        except Exception as ve:
                            print(f"[TXT2IMG] Volume commit note: {ve}")
                        
                        images_completed += current_batch_size
                        q.put({
                            "image_b64_partial": chunk_b64, 
                            "images_completed": images_completed, 
                            "total_images": batch_size,
                            "current_page": current_page if (comic_mode == 1 and batch_size > 1) else None,
                            "is_comic_book": bool(comic_mode == 1 and batch_size > 1)
                        })

                    if orig_attn_processors is not None:
                        try:
                            run_pipe.unet.set_attn_processor(orig_attn_processors)
                        except Exception:
                            pass
                    torch.cuda.empty_cache()
                    if loaded_adapters:
                        try: run_pipe.unload_lora_weights()
                        except: pass
                    
                    q.put({"image_b64": all_images_b64})
                except Exception as e:
                    if orig_attn_processors is not None:
                        try:
                            run_pipe.unet.set_attn_processor(orig_attn_processors)
                        except Exception:
                            pass
                    if loaded_adapters:
                        try: run_pipe.unload_lora_weights()
                        except: pass
                    q.put({"error": str(e)})

        threading.Thread(target=generate_task).start()

        while True:
            msg = q.get()
            yield msg
            if "image_b64" in msg or "error" in msg:
                break

    @modal.asgi_app()
    def web_txt2img(self):
        import fastapi
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi import Response
        import time

        web_app = fastapi.FastAPI()
        web_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @web_app.get("/ping")
        def ping():
            return {"status": "ok"}

        @web_app.post("/shutdown")
        @web_app.get("/shutdown")
        def shutdown():
            import os
            import threading
            def kill():
                time.sleep(1)
                os._exit(0)
            threading.Thread(target=kill).start()
            return {"status": "shutting down"}

        @web_app.get("/v1/models")
        def get_models():
            return {
                "object": "list",
                "data": [
                    {"id": "jugg", "object": "model", "owned_by": "user"},
                    {"id": "cyber", "object": "model", "owned_by": "user"},
                    {"id": "epic", "object": "model", "owned_by": "user"},
                    {"id": "unholy", "object": "model", "owned_by": "user"},
                    {"id": "lust", "object": "model", "owned_by": "user"},
                    {"id": "autism", "object": "model", "owned_by": "user"},
                ]
            }

        @web_app.post("/v1/images/generations")
        async def openai_compatible_generations(request: fastapi.Request):
            import base64
            
            body = await request.json()
            prompt = body.get("prompt", "A cinematic photo")
            n = int(body.get("n", 1))
            model_name = body.get("model", "jugg")
            sampler_val = body.get("sampler", "")
            scheduler_val = body.get("scheduler", "Euler")
            
            # Default massive negative prompt
            default_neg = "illustration, 3d, render, anime, cartoon, painting, sketch, bad anatomy, deformed, disfigured, mutated, poorly drawn face, poorly drawn hands, mutated hands, missing limbs, extra limbs, extra fingers, distorted body, bad proportions, fused flesh, asymmetrical, plastic, airbrushed, overly smooth skin, oversaturated, blurry, worst quality, low quality, watermark, text, signature"
            neg_prompt = body.get("negative_prompt", default_neg)
            # If they pass an empty string, we should respect it or use default? Usually, fallback if empty.
            if not neg_prompt:
                neg_prompt = default_neg
            
            msgs = list(self.run.local(
                prompt=prompt,
                model_name=model_name,
                negative_prompt=neg_prompt,
                batch_size=n,
                guidance_scale=str(body.get("guidance_scale", "7.0")),
                num_inference_steps=int(body.get("num_inference_steps", 30)),
                scheduler=scheduler_val,
                sampler=sampler_val,
                amateur=0,
                seed=-1,
                lora="none",
                lcm_mode=int(body.get("lcm_mode", 0)),
            ))
            
            final_msg = msgs[-1]
            if "error" in final_msg:
                return {"error": final_msg["error"]}
            
            b64_list = [{"b64_json": b64} for b64 in final_msg["image_b64"]]
            return {"data": b64_list}

        @web_app.get("/stream")
        @web_app.get("/")
        def generate_endpoint(
            prompt: str, 
            model_name: str = "jugg",
            JuggernautXL: int = 0,
            CyberRealisticXL: int = 0,
            EpicRealismXL: int = 0,
            UnholyDesireXL: int = 0,
            Lustify: int = 0,
            AutismPony: int = 0,
            negative_prompt: str = "illustration, 3d, render, anime, cartoon, painting, sketch, bad anatomy, deformed, disfigured, mutated, poorly drawn face, poorly drawn hands, mutated hands, missing limbs, extra limbs, extra fingers, distorted body, bad proportions, fused flesh, asymmetrical, plastic, airbrushed, overly smooth skin, oversaturated, blurry, worst quality, low quality, watermark, text, signature", 
            guidance_scale: str = "7.0", 
            num_inference_steps: int = 30, 
            scheduler: str = "Euler a", 
            sampler: str = "",
            amateur: int = 0,
            comic_mode: int = 0,
            seed: int = -1,
            batch_size: int = 1,
            lora: str = "none",
            width: int = 1024,
            height: int = 1024,
            control_image_b64: str = "",
            control_type: str = "none",
            controlnet_conditioning_scale: float = 1.0,
            lcm_mode: int = 0,
            ip_adapter_image_b64: str = "",
            ip_adapter_scale: float = 0.6,
            ip_adapter_mode: str = "standard",
            regional_mode: str = "none",
            regional_prompts: str = "",
            regional_base_ratio: float = 0.2,
        ):
            from starlette.responses import StreamingResponse
            import json

            def event_stream():
                for msg in self.run.local(
                    prompt=prompt,
                    model_name=model_name,
                    JuggernautXL=JuggernautXL,
                    CyberRealisticXL=CyberRealisticXL,
                    EpicRealismXL=EpicRealismXL,
                    UnholyDesireXL=UnholyDesireXL,
                    Lustify=Lustify,
                    AutismPony=AutismPony,
                    negative_prompt=negative_prompt,
                    batch_size=max(1, int(batch_size)),
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    scheduler=scheduler,
                    sampler=sampler,
                    amateur=amateur,
                    comic_mode=comic_mode,
                    seed=seed,
                    lora=lora,
                    width=width,
                    height=height,
                    control_image_b64=control_image_b64,
                    control_type=control_type,
                    controlnet_conditioning_scale=controlnet_conditioning_scale,
                    lcm_mode=lcm_mode,
                    ip_adapter_image_b64=ip_adapter_image_b64,
                    ip_adapter_scale=ip_adapter_scale,
                    ip_adapter_mode=ip_adapter_mode,
                    regional_mode=regional_mode,
                    regional_prompts=regional_prompts,
                    regional_base_ratio=regional_base_ratio,
                ):
                    yield f"data: {json.dumps(msg)}\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        @web_app.post("/stream")
        @web_app.post("/")
        async def generate_endpoint_post(request: fastapi.Request):
            from starlette.responses import StreamingResponse
            import base64
            import json

            content_type = (request.headers.get("content-type") or "").lower()
            params = dict(request.query_params)

            if "application/json" in content_type:
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        params.update(body)
                except Exception:
                    pass
            elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                try:
                    form = await request.form()
                    for k, v in form.items():
                        if hasattr(v, "read"):
                            file_bytes = await v.read()
                            if file_bytes:
                                b64_str = base64.b64encode(file_bytes).decode("utf-8")
                                if k in ("ip_adapter_image", "ip_image"):
                                    params["ip_adapter_image_b64"] = b64_str
                                elif k in ("control_image", "controlnet_image"):
                                    params["control_image_b64"] = b64_str
                        else:
                            params[k] = v
                except Exception:
                    pass

            default_neg = "illustration, 3d, render, anime, cartoon, painting, sketch, bad anatomy, deformed, disfigured, mutated, poorly drawn face, poorly drawn hands, mutated hands, missing limbs, extra limbs, extra fingers, distorted body, bad proportions, fused flesh, asymmetrical, plastic, airbrushed, overly smooth skin, oversaturated, blurry, worst quality, low quality, watermark, text, signature"
            prompt_val = str(params.get("prompt", "A cinematic photo"))
            model_name_val = str(params.get("model_name") or params.get("model") or params.get("checkpoint") or "jugg")
            jugg_val = int(params.get("JuggernautXL", 0) or 0)
            cyber_val = int(params.get("CyberRealisticXL", 0) or 0)
            epic_val = int(params.get("EpicRealismXL", 0) or 0)
            unholy_val = int(params.get("UnholyDesireXL", 0) or 0)
            lust_val = int(params.get("Lustify", 0) or 0)
            autism_val = int(params.get("AutismPony", 0) or 0)
            neg_val = str(params.get("negative_prompt", default_neg))
            guidance_val = str(params.get("guidance_scale", "7.0"))
            steps_val = int(float(params.get("num_inference_steps", 30) or 30))
            scheduler_val = str(params.get("scheduler", "Euler a"))
            sampler_val = str(params.get("sampler", ""))
            amateur_val = int(params.get("amateur", 0) or 0)
            comic_val = int(params.get("comic_mode", 0) or 0)
            seed_val = int(params.get("seed", -1) or -1)
            batch_val = max(1, int(params.get("batch_size", 1) or 1))
            lora_val = str(params.get("lora", "none"))
            width_val = int(params.get("width", 1024) or 1024)
            height_val = int(params.get("height", 1024) or 1024)
            ctrl_b64_val = str(params.get("control_image_b64", ""))
            ctrl_type_val = str(params.get("control_type", "none"))
            ctrl_scale_val = float(params.get("controlnet_conditioning_scale", 1.0) or 1.0)
            lcm_val = int(params.get("lcm_mode", 0) if "lcm_mode" in params else 0)
            ip_b64_val = str(params.get("ip_adapter_image_b64", ""))
            ip_scale_val = float(params.get("ip_adapter_scale", 0.6) or 0.6)
            ip_mode_val = str(params.get("ip_adapter_mode", "standard"))
            reg_mode_val = str(params.get("regional_mode", "none"))
            reg_prompts_val = str(params.get("regional_prompts", ""))
            reg_ratio_val = float(params.get("regional_base_ratio", 0.2) or 0.2)

            def event_stream():
                for msg in self.run.local(
                    prompt=prompt_val,
                    model_name=model_name_val,
                    JuggernautXL=jugg_val,
                    CyberRealisticXL=cyber_val,
                    EpicRealismXL=epic_val,
                    UnholyDesireXL=unholy_val,
                    Lustify=lust_val,
                    AutismPony=autism_val,
                    negative_prompt=neg_val,
                    batch_size=batch_val,
                    guidance_scale=guidance_val,
                    num_inference_steps=steps_val,
                    scheduler=scheduler_val,
                    sampler=sampler_val,
                    amateur=amateur_val,
                    comic_mode=comic_val,
                    seed=seed_val,
                    lora=lora_val,
                    width=width_val,
                    height=height_val,
                    control_image_b64=ctrl_b64_val,
                    control_type=ctrl_type_val,
                    controlnet_conditioning_scale=ctrl_scale_val,
                    lcm_mode=lcm_val,
                    ip_adapter_image_b64=ip_b64_val,
                    ip_adapter_scale=ip_scale_val,
                    ip_adapter_mode=ip_mode_val,
                    regional_mode=reg_mode_val,
                    regional_prompts=reg_prompts_val,
                    regional_base_ratio=reg_ratio_val,
                ):
                    yield f"data: {json.dumps(msg)}\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")
        return web_app


@app.local_entrypoint()
def entrypoint(
    samples: int = 4,
    prompt: str = "A cinematic photo",
    JuggernautXL: int = 1,
    CyberRealisticXL: int = 0,
    negative_prompt: str = "low quality, blurry, distorted",
    batch_size: int = 4,
    guidance_scale: str = "7.0",
    num_inference_steps: int = 25,
    scheduler: str = "Euler",
    sampler: str = "",
    amateur: int = 0,
    seed: int = -1,
    lora: str = "none",
):
    output_dir = Path("/tmp/stable-diffusion")
    output_dir.mkdir(exist_ok=True, parents=True)

    inference_service = Inference()

    for sample_idx in range(samples):
        start = time.time()
        images_gen = inference_service.run.remote(
            prompt=prompt,
            JuggernautXL=JuggernautXL,
            CyberRealisticXL=CyberRealisticXL,
            negative_prompt=negative_prompt,
            batch_size=batch_size,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            scheduler=scheduler,
            sampler=sampler,
            amateur=amateur,
            seed=seed,
            lora=lora,
        )
        msgs = list(images_gen)
        final_msg = msgs[-1]
        if "error" in final_msg:
            print(f"Error: {final_msg['error']}")
            continue

        import base64
        images = [base64.b64decode(b64) for b64 in final_msg["image_b64"]]

        duration = time.time() - start
        print(f"Run {sample_idx + 1} took {duration:.3f}s")
        for batch_idx, image_bytes in enumerate(images):
            output_path = output_dir / f"output_{slugify(prompt)[:64]}_{str(sample_idx).zfill(2)}_{str(batch_idx).zfill(2)}.png"
            output_path.write_bytes(image_bytes)

def slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s).strip("-")
