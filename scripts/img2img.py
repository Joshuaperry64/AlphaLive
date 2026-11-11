# ---
# output-directory: "/tmp/img2img-output"
# ---

import io
import json
import base64
import time
from pathlib import Path
from io import BytesIO

import modal

from shared_app import app

# --- CACHE & VOLUME SETUP ---
CACHE_DIR = "/hf-hub-cache"
cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)
OUTPUTS_DIR = Path("/outputs")
volumes = {CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume}
secrets = [modal.Secret.from_name("alphacore-secrets")]

# --- UNIFIED DEPENDENCIES ---
image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install("git")
    .uv_pip_install(
        "Pillow",
        "accelerate",
        "fastapi[standard]",
        "git+https://github.com/huggingface/diffusers.git",
        "git+https://github.com/huggingface/transformers.git",
        "huggingface-hub",
        "safetensors",
        "torch",
        "torchvision",
        "sentencepiece",
        "protobuf",
        "omegaconf",
        "einops", "timm", "transformers-stream-generator",
        "peft",
        "DeepCache",
        "python-multipart",
        extra_options="--index-strategy unsafe-best-match",
        extra_index_url="https://download.pytorch.org/whl/cu128",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HOME": str(CACHE_DIR), "FORCE_REBUILD": "3"})
)

# --- MODEL CONSTANTS ---
FLUX_BASE = "black-forest-labs/FLUX.1-schnell"
FLUX_FILL_BASE = "black-forest-labs/FLUX.1-Fill-dev"
QWEN_BASE = "Qwen/Qwen-Image-Edit-2511"
LORA_REPO = "ScottzillaSystems/qwen-image-edit-plus-nsfw-lora"
LORA_WEIGHT = "qwen-image-edit-plus-nsfw-lora.safetensors"
LORA_ADAPTER = "mcnl-nsfw-v1"
SD35_BASE = "stabilityai/stable-diffusion-3.5-large"
COSXL_REPO = "stabilityai/cosxl"
COSXL_FILE = "cosxl_edit.safetensors"
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"

# --- CHECKPOINT CATALOG (R2: SDXL Native) ---
SDXL_CHECKPOINTS = {
    "epicrealismXL_pureFix": "epicrealismXL_pureFix.safetensors",
    "0x7RealisticFreedom_omegaSDXL": "0x7RealisticFreedom_omegaSDXL.safetensors",
    "juggernautXL_ragnarok": "juggernautXL_ragnarok.safetensors",
    "cyberrealisticXL_desireV30": "cyberrealisticXL_desireV30.safetensors",
    "unholyDesireMixCrimson_v50": "unholyDesireMixCrimson_v50.safetensors",
    "unholyDesireMixSinister_v80": "unholyDesireMixCrimson_v50.safetensors",
    "lustifyNSFWCheckpoint_zenithV9": "lustifyNSFWCheckpoint_zenithV9.safetensors",
    "dreamshaperXL_alpha2Xl10": "dreamshaperXL_alpha2Xl10.safetensors",
    "intorealism_sdxlV4": "intorealism_sdxlV4.safetensors",
    "realisticVisionV60B1_v60B1VAE": "realvisxlV50_v50Bakedvae.safetensors",
    "cyberrealisticPony_v180Coreshift": "cyberrealisticPony_v180Coreshift.safetensors",
    "realvisxlV50_v50Bakedvae": "realvisxlV50_v50Bakedvae.safetensors",
    "realisticComicBook_v10": "realisticComicBook_v10.safetensors",
    "juicyDreams_v10": "juicyDreams_v10.safetensors",
    "fullyREALXL_v30TRINITY": "fullyREALXL_v30TRINITY.safetensors",
    "fullyREALXL_v30TRINITY.safetensors": "fullyREALXL_v30TRINITY.safetensors",
    "ntrMIXIllustriousXL_xiii": "ntrMIXIllustriousXL_xiii.safetensors",
    "ntrMIXIllustriousXL_xiii.safetensors": "ntrMIXIllustriousXL_xiii.safetensors",
}


def resolve_model_choice(
    model: str = "",
    model_name: str = "",
    Flux: int = 0,
    Qwen: int = 0,
    checkpoint: str = "",
    mask_bytes: bytes | None = None,
    mask_b64: str = "",
) -> str:
    """Resolves requested model string, boolean toggles, and parameter heuristics into canonical model key."""
    raw = (model or model_name or "").lower().strip()
    
    if raw in ("flux_fill", "flux-fill", "flux_inpaint", "flux-inpaint", "fill", "inpaint"):
        return "flux_fill"
    if raw in ("sdxl", "sdxl_native", "sdxl-native", "sdxl_img2img"):
        return "sdxl"
    if raw in ("cosxl", "cosxl_edit", "cosxl-edit"):
        return "cosxl"
    if raw in ("sd35", "sd3.5", "sd_3_5", "sd35_large", "sd-3.5-large", "sd3.5_large", "sd-3.5"):
        return "sd35"
    if raw in ("flux", "flux.1", "schnell", "flux_schnell"):
        return "flux"
    if raw in ("qwen", "qwen_edit", "qwen-edit"):
        return "qwen"
        
    # Substring heuristics
    if "fill" in raw or "inpaint" in raw:
        return "flux_fill"
    if "cosxl" in raw:
        return "cosxl"
    if "sd3" in raw or "sd-3" in raw:
        return "sd35"
    if "sdxl" in raw:
        return "sdxl"
    if "flux" in raw:
        return "flux"
    if "qwen" in raw:
        return "qwen"
        
    # Heuristic inference from parameters
    if mask_bytes or (mask_b64 and mask_b64.strip()):
        return "flux_fill"
    if checkpoint and checkpoint.strip() and checkpoint.strip().lower() not in ("none", "default", ""):
        return "sdxl"
    if Flux == 1:
        return "flux"
    if Qwen == 1:
        return "qwen"
        
    return "qwen"


def resolve_checkpoint_filename(checkpoint_name: str) -> str:
    """Maps custom checkpoint alias or filename to canonical safetensors filename."""
    if not checkpoint_name or checkpoint_name.lower().strip() in ("none", "default", ""):
        return "epicrealismXL_pureFix.safetensors"
    clean = checkpoint_name.strip()
    if clean.endswith(".safetensors"):
        base = clean[:-12]
    else:
        base = clean
    if base in SDXL_CHECKPOINTS:
        return SDXL_CHECKPOINTS[base]
    if clean.endswith(".safetensors"):
        return clean
    return f"{clean}.safetensors"


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



# --- REGIONAL PROMPTING (MASKED CROSS-ATTENTION / ATTENTION COUPLE) ---
def build_regional_mask_i2i(height: int, width: int, mode: str, num_regions: int, device, dtype):
    import torch
    H, W = height, width
    y_coords = torch.linspace(0, 1, H, device=device, dtype=dtype).view(H, 1).expand(H, W)
    x_coords = torch.linspace(0, 1, W, device=device, dtype=dtype).view(1, W).expand(H, W)
    mode = (mode or "none").lower().strip()
    sharpness = 16.0

    raw_masks = []
    if mode in ("left_right", "horizontal", "cols", "2col") or (mode == "auto" and num_regions == 2):
        m_left = torch.sigmoid((0.5 - x_coords) * sharpness)
        raw_masks = [m_left, 1.0 - m_left]
    elif mode in ("top_bottom", "vertical", "rows", "2row"):
        m_top = torch.sigmoid((0.5 - y_coords) * sharpness)
        raw_masks = [m_top, 1.0 - m_top]
    elif mode in ("three_col", "3col", "thirds"):
        m1 = torch.sigmoid((0.333 - x_coords) * sharpness)
        m3 = torch.sigmoid((x_coords - 0.667) * sharpness)
        m2 = torch.clamp(1.0 - m1 - m3, min=0.0)
        raw_masks = [m1, m2, m3]
    elif mode in ("center_bg", "center_background", "spotlight"):
        dist = torch.sqrt((x_coords - 0.5) ** 2 + (y_coords - 0.5) ** 2)
        m_center = torch.sigmoid((0.32 - dist) * sharpness)
        raw_masks = [m_center, 1.0 - m_center]
    elif mode in ("quadrants", "grid", "4quad"):
        m_left = torch.sigmoid((0.5 - x_coords) * sharpness)
        m_right = 1.0 - m_left
        m_top = torch.sigmoid((0.5 - y_coords) * sharpness)
        m_bottom = 1.0 - m_top
        raw_masks = [m_top * m_left, m_top * m_right, m_bottom * m_left, m_bottom * m_right]
    else:
        edges = torch.linspace(0, 1, num_regions + 1, device=device, dtype=dtype)
        for i in range(num_regions):
            raw_masks.append(((x_coords >= edges[i]) & (x_coords <= edges[i + 1])).to(dtype))

    while len(raw_masks) < num_regions:
        raw_masks.append(torch.ones((H, W), device=device, dtype=dtype) / num_regions)
    raw_masks = raw_masks[:num_regions]
    stacked = torch.stack(raw_masks, dim=0)
    return stacked / (stacked.sum(dim=0, keepdim=True) + 1e-6)


class RegionalAttnProcessorI2I:
    def __init__(self, base_processor, region_cond_embeds, regional_mode="left_right", base_ratio=0.2, latent_hw=(128, 128)):
        self.base_processor = base_processor
        self.region_cond_embeds = region_cond_embeds
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
                    h, w = cand_h, seq_len // cand_h
                    break
        masks_2d = build_regional_mask_i2i(h, w, self.regional_mode, len(self.region_cond_embeds), device, dtype)
        masks_flat = masks_2d.reshape(len(self.region_cond_embeds), 1, seq_len, 1)
        self._mask_cache[key] = masks_flat
        return masks_flat

    def __call__(self, attn, hidden_states, encoder_hidden_states=None, attention_mask=None, temb=None, *args, **kwargs):
        import torch
        if encoder_hidden_states is None or not self.region_cond_embeds:
            return self.base_processor(attn, hidden_states, encoder_hidden_states=encoder_hidden_states, attention_mask=attention_mask, temb=temb, *args, **kwargs)

        ip_tokens_full = None
        text_seq_len = self.region_cond_embeds[0].shape[1]
        if isinstance(encoder_hidden_states, tuple):
            _, ip_tokens_full = encoder_hidden_states
        elif hasattr(encoder_hidden_states, "shape") and encoder_hidden_states.shape[1] > text_seq_len:
            ip_tokens_full = encoder_hidden_states[:, text_seq_len:, :]

        base_out = self.base_processor(attn, hidden_states, encoder_hidden_states=encoder_hidden_states, attention_mask=attention_mask, temb=temb, *args, **kwargs)
        batch_total, seq_len, _ = hidden_states.shape
        r_batch = self.region_cond_embeds[0].shape[0]
        has_cfg = batch_total == 2 * r_batch
        if has_cfg:
            _, hidden_cond = hidden_states.chunk(2, dim=0)
            base_uncond, base_cond = base_out.chunk(2, dim=0)
            ip_cond = ip_tokens_full.chunk(2, dim=0)[1] if ip_tokens_full is not None else None
        elif batch_total == r_batch:
            hidden_cond = hidden_states
            base_cond = base_out
            ip_cond = ip_tokens_full
        else:
            return base_out

        masks = self._get_masks(seq_len, hidden_cond.device, hidden_cond.dtype)
        regional_accum = torch.zeros_like(base_cond)
        for r_idx, reg_emb in enumerate(self.region_cond_embeds):
            reg_emb_cast = reg_emb.to(device=hidden_cond.device, dtype=hidden_cond.dtype)
            if ip_cond is not None:
                reg_enc = (reg_emb_cast, ip_cond) if isinstance(encoder_hidden_states, tuple) else torch.cat([reg_emb_cast, ip_cond], dim=1)
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
        return torch.cat([base_uncond, blended_cond], dim=0) if has_cfg else blended_cond


@app.cls(
    image=image,
    gpu="H100",
    volumes=volumes,
    secrets=secrets,
    scaledown_window=600,
    timeout=1200,
    memory=64 * 1024
)
class Img2Img:
    current_model = None
    pipe = None

    @modal.enter()
    def enter(self):
        self.current_model = None
        self.pipe = None
        self.loaded_ip_adapter_mode = None
        self.loaded_image_encoder_sub = None
        
    def _load_model(self, model_choice: str, checkpoint: str = ""):
        if not hasattr(self, "pipe"):
            self.pipe = None
        if not hasattr(self, "current_model"):
            self.current_model = None

        cache_key = f"sdxl:{resolve_checkpoint_filename(checkpoint)}" if model_choice == "sdxl" else model_choice
        if self.current_model == cache_key and self.pipe is not None:
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
            
        import os
        import torch
        from pathlib import Path
        
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if token:
            os.environ["HF_TOKEN"] = token

        try:
            cache_volume.reload()
        except Exception as ve:
            print(f"[IMG2IMG] Volume reload note (non-fatal, open files or sync in progress): {ve}")
        
        if model_choice == "flux":
            print(f"Loading base model {FLUX_BASE} (bfloat16)...")
            from diffusers import FluxImg2ImgPipeline
            self.pipe = FluxImg2ImgPipeline.from_pretrained(
                FLUX_BASE, 
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR,
                token=token
            )
            self.pipe.to("cuda")
            
            try:
                cache_volume.commit()
                print("[FLUX] Successfully committed downloaded weights to persistent volume cache.")
            except Exception as ce:
                print(f"[FLUX] Volume commit note: {ce}")
            
        elif model_choice == "qwen":
            from diffusers import QwenImageEditPlusPipeline
            print(f"Loading base model {QWEN_BASE} (bfloat16)...")
            self.pipe = QwenImageEditPlusPipeline.from_pretrained(
                QWEN_BASE,
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR,
                trust_remote_code=True,
                token=token
            ).to("cuda")

            print(f"Loading and setting LoRA adapter from {LORA_REPO}...")
            self.pipe.load_lora_weights(
                LORA_REPO,
                weight_name=LORA_WEIGHT,
                adapter_name=LORA_ADAPTER,
                cache_dir=CACHE_DIR,
                token=token
            )
            self.pipe.set_adapters([LORA_ADAPTER])
            # Cast all LoRA layers & biases to bfloat16 to match Qwen base activations
            ensure_pipeline_dtype(self.pipe, torch.bfloat16)

            print("Disabling safety checker.")
            self.pipe.safety_checker = lambda images, **kwargs: (images, [False] * len(images))

            try:
                cache_volume.commit()
            except Exception:
                pass

        elif model_choice == "sdxl":
            from diffusers import StableDiffusionXLImg2ImgPipeline
            ckpt_filename = resolve_checkpoint_filename(checkpoint)
            ckpt_path = Path(CACHE_DIR) / "checkpoints" / ckpt_filename
            print(f"[SDXL] Loading SDXL Img2Img with checkpoint '{ckpt_filename}'...")
            
            loaded = False
            if ckpt_path.exists():
                try:
                    print(f"[SDXL] Loading single-file checkpoint from {ckpt_path}...")
                    self.pipe = StableDiffusionXLImg2ImgPipeline.from_single_file(
                        str(ckpt_path),
                        torch_dtype=torch.bfloat16,
                        use_safetensors=True,
                        cache_dir=CACHE_DIR,
                        token=token,
                        add_watermarker=False
                    ).to("cuda")
                    if hasattr(self.pipe, "watermark"):
                        self.pipe.watermark = None
                    loaded = True
                    print(f"[SDXL] Successfully loaded custom checkpoint {ckpt_filename} into VRAM.")
                except Exception as ex:
                    print(f"[SDXL] Warning: from_single_file failed ({ex}). Falling back to pretrained base...")
            
            if not loaded:
                print(f"[SDXL] Checkpoint file '{ckpt_path}' not found on disk. Loading fallback {SDXL_BASE}...")
                self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                    SDXL_BASE,
                    torch_dtype=torch.bfloat16,
                    cache_dir=CACHE_DIR,
                    token=token,
                    add_watermarker=False
                ).to("cuda")
                if hasattr(self.pipe, "watermark"):
                    self.pipe.watermark = None
                print(f"[SDXL] Pretrained fallback base model loaded successfully.")

            # Apply clean precision, DeepCache, and channels_last to SDXL Img2Img pipeline (FreeU disabled to eliminate lines)
            try:
                if hasattr(self.pipe, "disable_freeu"):
                    self.pipe.disable_freeu()
                self.pipe.unet.to(memory_format=torch.channels_last)
                if hasattr(self.pipe, "vae") and self.pipe.vae is not None:
                    self.pipe.vae.to(dtype=torch.float32, memory_format=torch.channels_last)
                from DeepCache import DeepCacheSDHelper
                helper = DeepCacheSDHelper(pipe=self.pipe)
                helper.set_params(cache_interval=2, cache_branch_id=0)
                helper.enable()
                self.deepcache_helper = helper
                print("✅ [SDXL-I2I] DeepCache (interval=2) + channels_last + float32 VAE enabled (lines eliminated).")
            except Exception as opt_e:
                print(f"[SDXL-I2I] Optimization notice: {opt_e}")

            try:
                cache_volume.commit()
            except Exception:
                pass

        elif model_choice == "flux_fill":
            from diffusers import FluxInpaintPipeline
            print(f"[FLUX-FILL] Loading FluxInpaintPipeline from {FLUX_FILL_BASE} (bfloat16)...")
            self.pipe = FluxInpaintPipeline.from_pretrained(
                FLUX_FILL_BASE,
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR,
                token=token
            ).to("cuda")
            try:
                cache_volume.commit()
                print("[FLUX-FILL] Successfully committed downloaded weights to persistent volume cache.")
            except Exception as ce:
                print(f"[FLUX-FILL] Volume commit note: {ce}")

        elif model_choice == "cosxl":
            from diffusers import StableDiffusionXLInstructPix2PixPipeline, EDMEulerScheduler
            from huggingface_hub import hf_hub_download
            
            print("[CosXL] Loading CosXL Edit pipeline with EDM VPred scheduler...")
            scheduler = EDMEulerScheduler(prediction_type="v_prediction")
            
            ckpt_path = Path(CACHE_DIR) / "checkpoints" / COSXL_FILE
            if not ckpt_path.exists():
                try:
                    print(f"[CosXL] Downloading {COSXL_FILE} from HF repo {COSXL_REPO}...")
                    downloaded_path = hf_hub_download(
                        repo_id=COSXL_REPO,
                        filename=COSXL_FILE,
                        cache_dir=CACHE_DIR,
                        token=token
                    )
                    ckpt_path = Path(downloaded_path)
                except Exception as he:
                    print(f"[CosXL] HF download notice: {he}")
            
            loaded = False
            if ckpt_path.exists():
                try:
                    print(f"[CosXL] Loading single file {ckpt_path} with EDMEulerScheduler (v_prediction)...")
                    self.pipe = StableDiffusionXLInstructPix2PixPipeline.from_single_file(
                        str(ckpt_path),
                        scheduler=scheduler,
                        torch_dtype=torch.bfloat16,
                        cache_dir=CACHE_DIR,
                        token=token
                    ).to("cuda")
                    loaded = True
                    print("[CosXL] Successfully loaded CosXL Edit single file into VRAM.")
                except Exception as se:
                    print(f"[CosXL] from_single_file failed ({se}). Falling back...")
            
            if not loaded:
                print("[CosXL] Loading fallback diffusers/sdxl-instructpix2pix-768 with EDMEulerScheduler...")
                self.pipe = StableDiffusionXLInstructPix2PixPipeline.from_pretrained(
                    "diffusers/sdxl-instructpix2pix-768",
                    scheduler=scheduler,
                    torch_dtype=torch.bfloat16,
                    cache_dir=CACHE_DIR,
                    token=token
                ).to("cuda")
                print("[CosXL] Fallback pipeline loaded successfully.")

            try:
                cache_volume.commit()
            except Exception:
                pass

        elif model_choice == "sd35":
            from diffusers import StableDiffusion3Img2ImgPipeline
            print(f"[SD3.5] Loading StableDiffusion3Img2ImgPipeline from {SD35_BASE} with MMDiT and T5-XXL in bfloat16...")
            self.pipe = StableDiffusion3Img2ImgPipeline.from_pretrained(
                SD35_BASE,
                torch_dtype=torch.bfloat16,
                cache_dir=CACHE_DIR,
                token=token
            ).to("cuda")
            try:
                cache_volume.commit()
                print("[SD3.5] Successfully committed downloaded weights to persistent volume cache.")
            except Exception as ce:
                print(f"[SD3.5] Volume commit note: {ce}")

        self.current_model = cache_key
        self.loaded_ip_adapter_mode = None
        self.loaded_image_encoder_sub = None
        print(f"✅ Model [{self.current_model.upper()}] loaded successfully!")

    def _configure_sdxl_ip_adapter(self, ip_adapter_image_b64: str, ip_adapter_scale: float, ip_adapter_mode: str):
        import base64
        import io
        import torch
        from PIL import Image
        from transformers import CLIPVisionModelWithProjection

        if not ip_adapter_image_b64 or not ip_adapter_image_b64.strip():
            if getattr(self, "loaded_ip_adapter_mode", None) is not None:
                try:
                    self.pipe.unload_ip_adapter()
                    self.loaded_ip_adapter_mode = None
                except Exception:
                    try:
                        self.pipe.set_ip_adapter_scale(0.0)
                    except Exception:
                        pass
            return None

        clean_b64 = ip_adapter_image_b64.split(",", 1)[1] if "," in ip_adapter_image_b64 else ip_adapter_image_b64.strip()
        ip_pil = Image.open(io.BytesIO(base64.b64decode(clean_b64))).convert("RGB")
        mode = (ip_adapter_mode or "standard").lower().strip()
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
            print(f"[SDXL-I2I IP-ADAPTER] Loading {adapter_key} (encoder: {encoder_sub})...")
            if getattr(self, "loaded_image_encoder_sub", None) != encoder_sub:
                image_encoder = CLIPVisionModelWithProjection.from_pretrained(
                    "h94/IP-Adapter",
                    subfolder=encoder_sub,
                    torch_dtype=torch.bfloat16,
                    cache_dir=CACHE_DIR,
                ).to("cuda")
                self.pipe.register_modules(image_encoder=image_encoder)
                self.loaded_image_encoder_sub = encoder_sub

            self.pipe.load_ip_adapter(
                "h94/IP-Adapter",
                subfolder=subfolder,
                weight_name=weight_name,
                cache_dir=CACHE_DIR,
            )
            self.loaded_ip_adapter_mode = adapter_key

            # Strictly enforce bfloat16 on all newly attached IP-Adapter layers to eliminate bias dtype mismatch
            target_dtype = torch.bfloat16
            ensure_pipeline_dtype(self.pipe, target_dtype)

            try:
                cache_volume.commit()
            except Exception:
                pass

        self.pipe.set_ip_adapter_scale(float(ip_adapter_scale))
        print(f"[SDXL-I2I IP-ADAPTER] Active ({weight_name}) at scale={float(ip_adapter_scale):.2f}")
        return ip_pil

    def _apply_sdxl_regional_prompting(self, regional_mode: str, regional_prompts_str: str, regional_base_ratio: float, batch_size: int, height: int, width: int):
        import json as _json
        import torch
        mode = (regional_mode or "none").lower().strip()
        if mode in ("none", "", "off", "disabled") or not regional_prompts_str:
            return None

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

        if not region_texts:
            return None

        print(f"[SDXL-I2I REGIONAL] Mode='{mode}', Regions={len(region_texts)}, BaseRatio={regional_base_ratio:.2f}")
        region_cond_embeds = []
        with torch.no_grad():
            for r_text in region_texts:
                enc_res = self.pipe.encode_prompt(
                    prompt=r_text,
                    prompt_2=r_text,
                    device="cuda",
                    num_images_per_prompt=batch_size,
                    do_classifier_free_guidance=False,
                )
                region_cond_embeds.append(enc_res[0])

        orig_processors = dict(self.pipe.unet.attn_processors)
        new_processors = {}
        latent_hw = (max(1, height // 8), max(1, width // 8))
        for name, proc in orig_processors.items():
            if name.endswith("attn2.processor"):
                new_processors[name] = RegionalAttnProcessorI2I(
                    base_processor=proc,
                    region_cond_embeds=region_cond_embeds,
                    regional_mode=mode,
                    base_ratio=regional_base_ratio,
                    latent_hw=latent_hw,
                )
            else:
                new_processors[name] = proc
        self.pipe.unet.set_attn_processor(new_processors)
        return orig_processors

    @modal.method(is_generator=True)
    def run_stream(
        self,
        image_bytes: bytes,
        prompt: str = "input requested image edits here.",
        Qwen: int = 0,
        Flux: int = 0,
        model_name: str = "",
        model: str = "",
        checkpoint: str = "",
        mask_bytes: bytes | None = None,
        mask_b64: str = "",
        instruction: str = "",
        negative_prompt: str = "worst quality, low quality",
        strength: float = 0.75,
        true_cfg_scale: float = 4.0,
        guidance_scale: float = 0.0,
        image_guidance_scale: float = 1.5,
        num_inference_steps: int = 20,
        batch_size: int = 1,
        lora: str = "none",
        seed: int | None = None,
        image_bytes2: bytes | None = None,
        refs: list[bytes] = [],
        lcm_mode: int = 0,
        ip_adapter_image_b64: str = "",
        ip_adapter_scale: float = 0.6,
        ip_adapter_mode: str = "standard",
        regional_mode: str = "none",
        regional_prompts: str = "",
        regional_base_ratio: float = 0.2,
    ):
        from diffusers.utils import load_image
        from PIL import Image
        import queue
        import threading
        import torch
        import base64
        from io import BytesIO
        
        # Resolve model selection
        selected_model = resolve_model_choice(
            model=model,
            model_name=model_name,
            Flux=Flux,
            Qwen=Qwen,
            checkpoint=checkpoint,
            mask_bytes=mask_bytes,
            mask_b64=mask_b64,
        )
        
        # Resolve prompt vs instruction
        effective_prompt = prompt
        if instruction and instruction.strip():
            if not prompt or prompt.strip() == "input requested image edits here.":
                effective_prompt = instruction.strip()
                
        # Resolve guidance scale
        effective_guidance = guidance_scale if guidance_scale > 0.0 else true_cfg_scale
        
        # Resolve strength
        effective_strength = float(strength) if strength is not None else 0.75

        self._load_model(selected_model, checkpoint=checkpoint)
        
        primary_pil = load_image(Image.open(BytesIO(image_bytes))).convert("RGB")
        pil_images = [primary_pil]
        if image_bytes2:
            pil_images.append(load_image(Image.open(BytesIO(image_bytes2))).convert("RGB"))
        for ref_bytes in refs:
            if ref_bytes:
                pil_images.append(load_image(Image.open(BytesIO(ref_bytes))).convert("RGB"))
            
        # Parse mask if provided (for inpainting)
        pil_mask = None
        if mask_bytes:
            try:
                pil_mask = Image.open(BytesIO(mask_bytes)).convert("L")
            except Exception as me:
                print(f"[WARN] Failed to parse mask_bytes: {me}")
        elif mask_b64 and mask_b64.strip():
            try:
                clean_b64 = mask_b64.strip()
                if "," in clean_b64:
                    clean_b64 = clean_b64.split(",", 1)[1]
                pil_mask = Image.open(BytesIO(base64.b64decode(clean_b64))).convert("L")
            except Exception as me:
                print(f"[WARN] Failed to parse mask_b64: {me}")
                
        if selected_model == "flux_fill" and pil_mask is None:
            # Create a full inpaint mask if no mask was drawn
            pil_mask = Image.new("L", primary_pil.size, 255)
            
        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None and seed >= 0 else None
        q = queue.Queue()

        def generate_task():
            import io
            from io import BytesIO
            import base64
            from PIL import Image
            all_images_b64 = []
            try:
                images_completed = 0
                while images_completed < batch_size:
                    current_batch_size = min(batch_size - images_completed, 10)

                    def chunk_callback(pipe, step_index, timestep, callback_kwargs):
                        q.put({"step": step_index, "max_steps": num_inference_steps, "images_completed": images_completed, "total_images": batch_size})
                        return callback_kwargs

                    if self.current_model == "flux":
                        from PIL import Image
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 16) * 16))
                        th = max(64, int(round(h * scale_f / 16) * 16))
                        flux_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)

                        # Parse and balance strength:
                        if 0.0 < effective_guidance <= 1.0:
                            f_strength = float(effective_guidance)
                        elif effective_strength < 1.0 and effective_strength > 0.0:
                            f_strength = effective_strength
                        elif effective_guidance <= 10.0:
                            f_strength = float(effective_guidance) / 10.0
                            if 0.35 <= f_strength <= 0.45:
                                f_strength = 0.75
                        else:
                            f_strength = 0.80

                        f_strength = max(0.20, min(0.98, f_strength))

                        # Target 4 effective distillation denoising steps for FLUX.1-schnell:
                        flux_total_steps = max(4, int(round(4.0 / max(0.1, f_strength))))
                        if 4 <= num_inference_steps <= 10:
                            flux_total_steps = int(round(num_inference_steps / max(0.1, f_strength)))
                        flux_total_steps = min(12, flux_total_steps)

                        def flux_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": flux_total_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        print(f"[FLUX] Schnell Img2Img inference: strength={f_strength:.2f}, steps={flux_total_steps}, dims=({tw}x{th})")
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)

                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                            chunk_images = self.pipe(
                                prompt=effective_prompt,
                                image=flux_img,
                                num_inference_steps=flux_total_steps,
                                strength=f_strength,
                                guidance_scale=0.0,
                                max_sequence_length=256,
                                num_images_per_prompt=current_batch_size,
                                generator=generator,
                                callback_on_step_end=flux_step_callback
                            ).images
                        
                    elif self.current_model == "qwen":
                        if lora and lora != "none" and lora != LORA_ADAPTER:
                            loras_to_load = [l.strip() for l in lora.split(",") if l.strip() and l.strip() != "none"]
                            loaded_adapters = [LORA_ADAPTER]
                            for l in loras_to_load:
                                lora_path = Path("/hf-hub-cache/loras") / f"{l}.safetensors"
                                if lora_path.exists():
                                    self.pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name, adapter_name=l)
                                    loaded_adapters.append(l)
                            self.pipe.set_adapters(loaded_adapters)

                        # Support IP-Adapter / Reference Image conditioning in Qwen
                        qwen_images = list(pil_images)
                        if ip_adapter_image_b64 and ip_adapter_image_b64.strip():
                            try:
                                clean_ip_b64 = ip_adapter_image_b64.split(",", 1)[1] if "," in ip_adapter_image_b64 else ip_adapter_image_b64.strip()
                                ref_pil = Image.open(io.BytesIO(base64.b64decode(clean_ip_b64))).convert("RGB")
                                qwen_images.append(ref_pil)
                                print(f"[QWEN-I2I] Injected IP-Adapter reference conditioning: total images={len(qwen_images)}")
                            except Exception as ip_err:
                                print(f"[QWEN-I2I] Could not load IP-Adapter reference: {ip_err}")

                        # Ensure entire Qwen pipeline has matching bfloat16 weights & bias
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)

                        with torch.inference_mode():
                            try:
                                chunk_images = self.pipe(
                                    image=qwen_images if len(qwen_images) > 1 else pil_images,
                                    prompt=effective_prompt,
                                    negative_prompt=(negative_prompt if negative_prompt else " "),
                                    num_images_per_prompt=current_batch_size,
                                    num_inference_steps=num_inference_steps,
                                    true_cfg_scale=effective_guidance,
                                    generator=generator,
                                    callback_on_step_end=chunk_callback
                                ).images
                            except RuntimeError as r_err:
                                if any(x in str(r_err) for x in ("BFloat16", "bias", "should be the same", "dtype")):
                                    print(f"[QWEN] Caught dtype mismatch ({r_err}), reapplying deep cast and retrying...")
                                    ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                                    with torch.autocast("cuda", dtype=torch.bfloat16):
                                        chunk_images = self.pipe(
                                            image=qwen_images if len(qwen_images) > 1 else pil_images,
                                            prompt=effective_prompt,
                                            negative_prompt=(negative_prompt if negative_prompt else " "),
                                            num_images_per_prompt=current_batch_size,
                                            num_inference_steps=num_inference_steps,
                                            true_cfg_scale=effective_guidance,
                                            generator=generator,
                                            callback_on_step_end=chunk_callback
                                        ).images
                                else:
                                    raise

                    elif self.current_model.startswith("sdxl"):
                        from PIL import Image
                        import diffusers
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 64) * 64))
                        th = max(64, int(round(h * scale_f / 64) * 64))
                        sdxl_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)

                        is_lcm_active = bool(int(lcm_mode or 0) == 1)
                        if getattr(self, "deepcache_helper", None) is not None:
                            try:
                                if is_lcm_active or num_inference_steps <= 6:
                                    self.deepcache_helper.disable()
                                else:
                                    self.deepcache_helper.enable()
                            except Exception:
                                pass
                        if is_lcm_active:
                            print("⚡ [SDXL-I2I LIGHTNING] Activating EulerDiscreteScheduler(timestep_spacing='trailing') + ByteDance/SDXL-Lightning 4-step LoRA...")
                            self.pipe.scheduler = diffusers.EulerDiscreteScheduler.from_config(
                                self.pipe.scheduler.config,
                                timestep_spacing="trailing",
                            )
                            sdxl_steps = 4
                            sdxl_guidance = 0.0
                        else:
                            self.pipe.scheduler = diffusers.EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
                            sdxl_steps = max(10, num_inference_steps)
                            sdxl_guidance = effective_guidance if effective_guidance > 1.0 else 6.0

                        def sdxl_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": sdxl_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        sdxl_strength = min(0.99, max(0.05, effective_strength))

                        # LoRA + SDXL-Lightning 4-step LoRA support for SDXL
                        loaded_sdxl_adapters = []
                        sdxl_adapter_weights = []
                        if is_lcm_active:
                            try:
                                from huggingface_hub import hf_hub_download
                                light_name = "sdxl_lightning_4step"
                                ckpt_path = hf_hub_download("ByteDance/SDXL-Lightning", "sdxl_lightning_4step_lora.safetensors", cache_dir=CACHE_DIR)
                                self.pipe.load_lora_weights(ckpt_path, adapter_name=light_name)
                                loaded_sdxl_adapters.append(light_name)
                                sdxl_adapter_weights.append(1.0)
                            except Exception as lcm_e:
                                print(f"[SDXL-I2I] SDXL-Lightning LoRA load note: {lcm_e}")

                        if lora and lora != "none":
                            loras_to_load = [l.strip() for l in lora.split(",") if l.strip() and l.strip() != "none"]
                            for l in loras_to_load:
                                clean_l = l.replace(".safetensors", "")
                                lora_path = Path("/hf-hub-cache/loras") / f"{clean_l}.safetensors"
                                if not lora_path.exists():
                                    candidates = list(Path("/hf-hub-cache/loras").glob(f"*{clean_l}*.safetensors"))
                                    if candidates:
                                        lora_path = candidates[0]
                                if lora_path.exists():
                                    try:
                                        self.pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name, adapter_name=clean_l)
                                        loaded_sdxl_adapters.append(clean_l)
                                        sdxl_adapter_weights.append(0.8 if is_lcm_active else 1.0)
                                    except Exception as le:
                                        print(f"[SDXL] LoRA load note for {l}: {le}")

                        if loaded_sdxl_adapters:
                            try:
                                self.pipe.set_adapters(loaded_sdxl_adapters, adapter_weights=sdxl_adapter_weights)
                            except Exception as ae:
                                print(f"[SDXL] Adapter activation note: {ae}")

                        # IP-Adapter support for SDXL Img2Img
                        ip_pil = None
                        try:
                            ip_pil = self._configure_sdxl_ip_adapter(
                                ip_adapter_image_b64=ip_adapter_image_b64,
                                ip_adapter_scale=ip_adapter_scale,
                                ip_adapter_mode=ip_adapter_mode,
                            )
                        except Exception as ip_e:
                            print(f"[SDXL-I2I] IP-Adapter warning: {ip_e}")

                        # Regional Prompting support for SDXL Img2Img
                        orig_sdxl_procs = None
                        if regional_mode and regional_mode.lower() not in ("none", "", "off") and regional_prompts:
                            try:
                                orig_sdxl_procs = self._apply_sdxl_regional_prompting(
                                    regional_mode=regional_mode,
                                    regional_prompts_str=regional_prompts,
                                    regional_base_ratio=float(regional_base_ratio),
                                    batch_size=current_batch_size,
                                    height=th,
                                    width=tw,
                                )
                            except Exception as reg_e:
                                print(f"[SDXL-I2I] Regional prompting warning: {reg_e}")

                        sdxl_kwargs = {}
                        if ip_pil is not None:
                            sdxl_kwargs["ip_adapter_image"] = ip_pil

                        print(f"[SDXL] Img2Img inference: strength={sdxl_strength:.2f}, guidance={sdxl_guidance:.1f}, steps={sdxl_steps}, dims=({tw}x{th})")
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                        try:
                            with torch.inference_mode():
                                try:
                                    chunk_images = self.pipe(
                                        prompt=effective_prompt,
                                        negative_prompt=(negative_prompt if sdxl_guidance > 0.0 else None),
                                        image=sdxl_img,
                                        num_inference_steps=sdxl_steps,
                                        strength=sdxl_strength,
                                        guidance_scale=sdxl_guidance,
                                        num_images_per_prompt=current_batch_size,
                                        generator=generator,
                                        callback_on_step_end=sdxl_step_callback,
                                        **sdxl_kwargs,
                                    ).images
                                except RuntimeError as r_err:
                                    if any(x in str(r_err) for x in ("BFloat16", "bias", "should be the same", "dtype")):
                                        print(f"[SDXL] Caught dtype mismatch ({r_err}), reapplying deep cast and retrying...")
                                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                                        with torch.autocast("cuda", dtype=torch.bfloat16):
                                            chunk_images = self.pipe(
                                                prompt=effective_prompt,
                                                negative_prompt=(negative_prompt if sdxl_guidance > 0.0 else None),
                                                image=sdxl_img,
                                                num_inference_steps=sdxl_steps,
                                                strength=sdxl_strength,
                                                guidance_scale=sdxl_guidance,
                                                num_images_per_prompt=current_batch_size,
                                                generator=generator,
                                                callback_on_step_end=sdxl_step_callback,
                                                **sdxl_kwargs,
                                            ).images
                                    else:
                                        raise
                        finally:
                            if orig_sdxl_procs is not None:
                                try:
                                    self.pipe.unet.set_attn_processor(orig_sdxl_procs)
                                except Exception:
                                    pass
                            if loaded_sdxl_adapters:
                                try:
                                    self.pipe.unload_lora_weights()
                                except Exception:
                                    pass

                    elif self.current_model == "flux_fill":
                        from PIL import Image
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 16) * 16))
                        th = max(64, int(round(h * scale_f / 16) * 16))
                        fill_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)
                        fill_mask = pil_mask.resize((tw, th), Image.Resampling.NEAREST) if pil_mask else Image.new("L", (tw, th), 255)

                        fill_steps = max(12, num_inference_steps)
                        def fill_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": fill_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        fill_guidance = effective_guidance if effective_guidance > 1.0 else 30.0
                        fill_strength = min(1.0, max(0.1, effective_strength))

                        print(f"[FLUX-FILL] Inpaint inference: strength={fill_strength:.2f}, guidance={fill_guidance:.1f}, steps={fill_steps}, dims=({tw}x{th})")
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                            chunk_images = self.pipe(
                                prompt=effective_prompt,
                                image=fill_img,
                                mask_image=fill_mask,
                                num_inference_steps=fill_steps,
                                strength=fill_strength,
                                guidance_scale=fill_guidance,
                                num_images_per_prompt=current_batch_size,
                                generator=generator,
                                callback_on_step_end=fill_step_callback
                            ).images

                    elif self.current_model == "cosxl":
                        from PIL import Image
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 64) * 64))
                        th = max(64, int(round(h * scale_f / 64) * 64))
                        cosxl_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)

                        cosxl_steps = max(10, num_inference_steps)
                        def cosxl_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": cosxl_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        cosxl_guidance = effective_guidance if effective_guidance > 1.0 else 7.0
                        img_guidance = image_guidance_scale if image_guidance_scale > 0.0 else 1.5

                        print(f"[CosXL] Edit inference: prompt='{effective_prompt}', guidance={cosxl_guidance:.1f}, img_guidance={img_guidance:.1f}, steps={cosxl_steps}")
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                            chunk_images = self.pipe(
                                prompt=effective_prompt,
                                negative_prompt=negative_prompt,
                                image=cosxl_img,
                                num_inference_steps=cosxl_steps,
                                guidance_scale=cosxl_guidance,
                                image_guidance_scale=img_guidance,
                                num_images_per_prompt=current_batch_size,
                                generator=generator,
                                callback_on_step_end=cosxl_step_callback
                            ).images

                    elif self.current_model == "sd35":
                        from PIL import Image
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 16) * 16))
                        th = max(64, int(round(h * scale_f / 16) * 16))
                        sd35_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)

                        sd35_steps = max(10, num_inference_steps)
                        def sd35_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": sd35_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        sd35_guidance = effective_guidance if effective_guidance > 1.0 else 4.5
                        sd35_strength = min(0.99, max(0.05, effective_strength))

                        print(f"[SD3.5] Img2Img inference: strength={sd35_strength:.2f}, guidance={sd35_guidance:.1f}, steps={sd35_steps}, dims=({tw}x{th})")
                        ensure_pipeline_dtype(self.pipe, torch.bfloat16)
                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                            chunk_images = self.pipe(
                                prompt=effective_prompt,
                                negative_prompt=negative_prompt,
                                image=sd35_img,
                                num_inference_steps=sd35_steps,
                                strength=sd35_strength,
                                guidance_scale=sd35_guidance,
                                num_images_per_prompt=current_batch_size,
                                generator=generator,
                                callback_on_step_end=sd35_step_callback
                            ).images

                    else:
                        raise ValueError(f"Unknown or unsupported current_model: {self.current_model}")

                    chunk_b64 = []
                    for img in chunk_images:
                        with BytesIO() as buf:
                            img.save(buf, format="PNG")
                            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                            chunk_b64.append(b64)
                            all_images_b64.append(b64)

                    images_completed += current_batch_size
                    q.put({"image_b64_partial": chunk_b64, "images_completed": images_completed, "total_images": batch_size})

                q.put({"image_b64": all_images_b64})
            except Exception as e:
                q.put({"error": str(e)})

        threading.Thread(target=generate_task).start()

        while True:
            msg = q.get()
            yield msg
            if "image_b64" in msg or "error" in msg:
                break

    @modal.method()
    def inference(
        self,
        image_bytes: bytes,
        prompt: str = "input requested image edits here.",
        Qwen: int = 0,
        Flux: int = 0,
        model_name: str = "",
        model: str = "",
        checkpoint: str = "",
        mask_bytes: bytes | None = None,
        mask_b64: str = "",
        instruction: str = "",
        negative_prompt: str = "worst quality, low quality",
        strength: float = 0.75,
        true_cfg_scale: float = 4.0,
        guidance_scale: float = 0.0,
        image_guidance_scale: float = 1.5,
        num_inference_steps: int = 20,
        batch_size: int = 1,
        lora: str = "none",
        seed: int | None = None,
        image_bytes2: bytes | None = None,
        refs: list[bytes] = [],
        lcm_mode: int = 0,
        ip_adapter_image_b64: str = "",
        ip_adapter_scale: float = 0.6,
        ip_adapter_mode: str = "standard",
        regional_mode: str = "none",
        regional_prompts: str = "",
        regional_base_ratio: float = 0.2,
    ) -> list[bytes]:
        import base64
        msgs = list(self.run_stream.local(
            image_bytes=image_bytes,
            prompt=prompt,
            Qwen=Qwen,
            Flux=Flux,
            model_name=model_name,
            model=model,
            checkpoint=checkpoint,
            mask_bytes=mask_bytes,
            mask_b64=mask_b64,
            instruction=instruction,
            negative_prompt=negative_prompt,
            strength=strength,
            true_cfg_scale=true_cfg_scale,
            guidance_scale=guidance_scale,
            image_guidance_scale=image_guidance_scale,
            num_inference_steps=num_inference_steps,
            batch_size=batch_size,
            lora=lora,
            seed=seed,
            image_bytes2=image_bytes2,
            refs=refs,
            lcm_mode=lcm_mode,
            ip_adapter_image_b64=ip_adapter_image_b64,
            ip_adapter_scale=ip_adapter_scale,
            ip_adapter_mode=ip_adapter_mode,
            regional_mode=regional_mode,
            regional_prompts=regional_prompts,
            regional_base_ratio=regional_base_ratio,
        ))
        final_msg = msgs[-1]
        if "error" in final_msg:
            raise Exception(final_msg["error"])
        return [base64.b64decode(b64) for b64 in final_msg["image_b64"]]

    @modal.asgi_app()
    def web_img2img(self):
        import fastapi
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi import Response, UploadFile, File, Form

        web_app = fastapi.FastAPI(title="AlphaCore Img2Img", version="2.0.0")
        web_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

        @web_app.post("/v1/images/edits")
        async def openai_compatible_edits(request: fastapi.Request):
            import base64
            form = await request.form()
            prompt = str(form.get("prompt", "Apply standard edits"))
            instruction = str(form.get("instruction", ""))
            n = int(form.get("n", 1))
            model_str = str(form.get("model", "qwen")).lower()
            checkpoint = str(form.get("checkpoint", ""))
            strength = float(form.get("strength", 0.75))
            
            image_file = form.get("image")
            if not image_file:
                return fastapi.responses.JSONResponse(status_code=400, content={"error": "Image is required for editing."})
            image_bytes = await image_file.read()

            mask_file = form.get("mask")
            mask_bytes = await mask_file.read() if mask_file else None
            mask_b64 = str(form.get("mask_b64", ""))
            
            output_bytes_list = self.inference.local(
                image_bytes=image_bytes,
                prompt=prompt,
                model_name=model_str,
                model=model_str,
                checkpoint=checkpoint,
                mask_bytes=mask_bytes,
                mask_b64=mask_b64,
                instruction=instruction,
                negative_prompt="worst quality, low quality",
                strength=strength,
                true_cfg_scale=4.0,
                num_inference_steps=20,
                batch_size=n,
                lora="none",
                seed=-1,
            )
            
            b64_list = [{"b64_json": base64.b64encode(img).decode('utf-8')} for img in output_bytes_list]
            return {"data": b64_list}

        @web_app.post("/stream")
        def web_endpoint_stream(
            image: UploadFile = File(...),
            image2: UploadFile | None = File(None),
            mask: UploadFile | None = File(None),
            ref1: UploadFile | None = File(None),
            ref2: UploadFile | None = File(None),
            ip_adapter_image: UploadFile | None = File(None),
            Qwen: int = Form(0),
            Flux: int = Form(0),
            model_name: str = Form(""),
            model: str = Form(""),
            checkpoint: str = Form(""),
            prompt: str = Form("input requested image edits here."),
            instruction: str = Form(""),
            negative_prompt: str = Form("worst quality, low quality"),
            strength: float = Form(0.75),
            true_cfg_scale: float = Form(4.0),
            guidance_scale: float = Form(0.0),
            image_guidance_scale: float = Form(1.5),
            num_inference_steps: int = Form(20),
            batch_size: int = Form(1),
            lora: str = Form("none"),
            seed: int = Form(-1),
            mask_b64: str = Form(""),
            width: int = Form(0),
            height: int = Form(0),
            lcm_mode: int = Form(0),
            ip_adapter_image_b64: str = Form(""),
            ip_adapter_scale: float = Form(0.6),
            ip_adapter_mode: str = Form("standard"),
            regional_mode: str = Form("none"),
            regional_prompts: str = Form(""),
            regional_base_ratio: float = Form(0.2),
        ):
            from fastapi.responses import StreamingResponse
            import base64
            
            image_bytes = image.file.read()
            image_bytes2 = image2.file.read() if image2 else None
            mask_bytes = mask.file.read() if mask else None
            refs_bytes = [ref.file.read() for ref in [ref1, ref2] if ref]
            seed_val = None if seed == -1 else seed
            if ip_adapter_image and not ip_adapter_image_b64:
                ip_bytes = ip_adapter_image.file.read()
                if ip_bytes:
                    ip_adapter_image_b64 = base64.b64encode(ip_bytes).decode("utf-8")
            
            effective_model = (model_name or model or "").lower().strip()

            def event_generator():
                for msg in self.run_stream.local(
                    image_bytes=image_bytes,
                    prompt=prompt,
                    Qwen=Qwen,
                    Flux=Flux,
                    model_name=effective_model,
                    model=effective_model,
                    checkpoint=checkpoint,
                    mask_bytes=mask_bytes,
                    mask_b64=mask_b64,
                    instruction=instruction,
                    negative_prompt=negative_prompt,
                    strength=strength,
                    true_cfg_scale=true_cfg_scale,
                    guidance_scale=guidance_scale,
                    image_guidance_scale=image_guidance_scale,
                    num_inference_steps=num_inference_steps,
                    batch_size=batch_size,
                    lora=lora,
                    seed=seed_val,
                    image_bytes2=image_bytes2,
                    refs=refs_bytes,
                    lcm_mode=lcm_mode,
                    ip_adapter_image_b64=ip_adapter_image_b64,
                    ip_adapter_scale=ip_adapter_scale,
                    ip_adapter_mode=ip_adapter_mode,
                    regional_mode=regional_mode,
                    regional_prompts=regional_prompts,
                    regional_base_ratio=regional_base_ratio,
                ):
                    yield f"data: {json.dumps(msg)}\n\n"
                    
                    if "image_b64" in msg:
                        for idx, b64 in enumerate(msg["image_b64"]):
                            out_bytes = base64.b64decode(b64)
                            out_dir = OUTPUTS_DIR / "img2img"
                            out_dir.mkdir(parents=True, exist_ok=True)
                            (out_dir / f"img2img_{int(time.time() * 1000)}_{idx}.png").write_bytes(out_bytes)
                        try:
                            outputs_volume.commit()
                        except Exception:
                            pass

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        @web_app.post("/generate")
        @web_app.post("/")
        def web_endpoint(
            image: UploadFile = File(...),
            image2: UploadFile | None = File(None),
            mask: UploadFile | None = File(None),
            ref1: UploadFile | None = File(None),
            ref2: UploadFile | None = File(None),
            ip_adapter_image: UploadFile | None = File(None),
            Qwen: int = Form(0),
            Flux: int = Form(0),
            model_name: str = Form(""),
            model: str = Form(""),
            checkpoint: str = Form(""),
            prompt: str = Form("input requested image edits here."),
            instruction: str = Form(""),
            negative_prompt: str = Form("worst quality, low quality"),
            strength: float = Form(0.75),
            true_cfg_scale: float = Form(4.0),
            guidance_scale: float = Form(0.0),
            image_guidance_scale: float = Form(1.5),
            num_inference_steps: int = Form(20),
            batch_size: int = Form(1),
            lora: str = Form("none"),
            seed: int = Form(-1),
            mask_b64: str = Form(""),
            width: int = Form(0),
            height: int = Form(0),
            lcm_mode: int = Form(0),
            ip_adapter_image_b64: str = Form(""),
            ip_adapter_scale: float = Form(0.6),
            ip_adapter_mode: str = Form("standard"),
            regional_mode: str = Form("none"),
            regional_prompts: str = Form(""),
            regional_base_ratio: float = Form(0.2),
        ):
            import base64
            image_bytes = image.file.read()
            image_bytes2 = image2.file.read() if image2 else None
            mask_bytes = mask.file.read() if mask else None
            refs_bytes = [ref.file.read() for ref in [ref1, ref2] if ref]
            seed_val = None if seed == -1 else seed
            if ip_adapter_image and not ip_adapter_image_b64:
                ip_bytes = ip_adapter_image.file.read()
                if ip_bytes:
                    ip_adapter_image_b64 = base64.b64encode(ip_bytes).decode("utf-8")
            
            effective_model = (model_name or model or "").lower().strip()

            output_bytes_list = self.inference.local(
                image_bytes=image_bytes,
                prompt=prompt,
                Qwen=Qwen,
                Flux=Flux,
                model_name=effective_model,
                model=effective_model,
                checkpoint=checkpoint,
                mask_bytes=mask_bytes,
                mask_b64=mask_b64,
                instruction=instruction,
                negative_prompt=negative_prompt,
                strength=strength,
                true_cfg_scale=true_cfg_scale,
                guidance_scale=guidance_scale,
                image_guidance_scale=image_guidance_scale,
                num_inference_steps=num_inference_steps,
                batch_size=batch_size,
                lora=lora,
                seed=seed_val,
                image_bytes2=image_bytes2,
                refs=refs_bytes,
                lcm_mode=lcm_mode,
                ip_adapter_image_b64=ip_adapter_image_b64,
                ip_adapter_scale=ip_adapter_scale,
                ip_adapter_mode=ip_adapter_mode,
                regional_mode=regional_mode,
                regional_prompts=regional_prompts,
                regional_base_ratio=regional_base_ratio,
            )

            out_dir = OUTPUTS_DIR / "img2img"
            out_dir.mkdir(parents=True, exist_ok=True)
            for idx, out_bytes in enumerate(output_bytes_list):
                (out_dir / f"img2img_{int(time.time() * 1000)}_{idx}.png").write_bytes(out_bytes)
            try:
                outputs_volume.commit()
            except Exception:
                pass

            return Response(content=output_bytes_list[0], media_type="image/png")

        return web_app


@app.local_entrypoint()
def main_img2img(
    image_path=Path(__file__).parent / "demo_images/woman.png",
    output_path=Path("/tmp/img2img-output/output.png"),
    model: str = "qwen",
    checkpoint: str = "",
    prompt: str = "input requested image edits here.",
    num_steps: int = 20,
):
    input_image_bytes = Path(image_path).read_bytes()
    print(f"🎨 Editing image using {model} with instruction: '{prompt}'")
    
    output_image_bytes = Img2Img().inference.remote(
        image_bytes=input_image_bytes,
        prompt=prompt,
        model=model,
        checkpoint=checkpoint,
        negative_prompt="worst quality",
        true_cfg_scale=4.0,
        num_inference_steps=num_steps,
        batch_size=1,
    )[0]

    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    output_path.write_bytes(output_image_bytes)
    print(f"✅ Saved generated image to {output_path}")
