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
secrets = [modal.Secret.from_name("huggingface-secret")]

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
    "unholyDesireMixSinister_v80": "unholyDesireMixSinister_v80.safetensors",
    "lustifyNSFWCheckpoint_zenithV9": "lustifyNSFWCheckpoint_zenithV9.safetensors",
    "dreamshaperXL_alpha2Xl10": "dreamshaperXL_alpha2Xl10.safetensors",
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
    def __init__(self):
        self.current_model = None
        self.pipe = None

    @modal.enter()
    def enter(self):
        self.current_model = None
        self.pipe = None
        
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
                        token=token
                    ).to("cuda")
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
                    token=token
                ).to("cuda")
                print(f"[SDXL] Pretrained fallback base model loaded successfully.")

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
        print(f"✅ Model [{self.current_model.upper()}] loaded successfully!")

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

                        chunk_images = self.pipe(
                            image=pil_images,
                            prompt=effective_prompt,
                            negative_prompt=negative_prompt,
                            num_images_per_prompt=current_batch_size,
                            num_inference_steps=num_inference_steps,
                            true_cfg_scale=effective_guidance,
                            generator=generator,
                            callback_on_step_end=chunk_callback
                        ).images

                    elif self.current_model.startswith("sdxl"):
                        from PIL import Image
                        w, h = pil_images[0].size
                        scale_f = min(1.0, 1024.0 / max(w, h))
                        tw = max(64, int(round(w * scale_f / 64) * 64))
                        th = max(64, int(round(h * scale_f / 64) * 64))
                        sdxl_img = pil_images[0].resize((tw, th), Image.Resampling.LANCZOS)

                        sdxl_steps = max(10, num_inference_steps)
                        def sdxl_step_callback(pipe, step_index, timestep, callback_kwargs):
                            q.put({"step": step_index, "max_steps": sdxl_steps, "images_completed": images_completed, "total_images": batch_size})
                            return callback_kwargs

                        sdxl_guidance = effective_guidance if effective_guidance > 1.0 else 6.0
                        sdxl_strength = min(0.99, max(0.05, effective_strength))

                        # LoRA support for SDXL
                        if lora and lora != "none":
                            loras_to_load = [l.strip() for l in lora.split(",") if l.strip() and l.strip() != "none"]
                            for l in loras_to_load:
                                lora_path = Path("/hf-hub-cache/loras") / f"{l}.safetensors"
                                if lora_path.exists():
                                    try:
                                        self.pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name, adapter_name=l)
                                    except Exception as le:
                                        print(f"[SDXL] LoRA load note for {l}: {le}")

                        print(f"[SDXL] Img2Img inference: strength={sdxl_strength:.2f}, guidance={sdxl_guidance:.1f}, steps={sdxl_steps}, dims=({tw}x{th})")
                        chunk_images = self.pipe(
                            prompt=effective_prompt,
                            negative_prompt=negative_prompt,
                            image=sdxl_img,
                            num_inference_steps=sdxl_steps,
                            strength=sdxl_strength,
                            guidance_scale=sdxl_guidance,
                            num_images_per_prompt=current_batch_size,
                            generator=generator,
                            callback_on_step_end=sdxl_step_callback
                        ).images

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
        ):
            from fastapi.responses import StreamingResponse
            
            image_bytes = image.file.read()
            image_bytes2 = image2.file.read() if image2 else None
            mask_bytes = mask.file.read() if mask else None
            refs_bytes = [ref.file.read() for ref in [ref1, ref2] if ref]
            seed_val = None if seed == -1 else seed
            
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
        ):
            image_bytes = image.file.read()
            image_bytes2 = image2.file.read() if image2 else None
            mask_bytes = mask.file.read() if mask else None
            refs_bytes = [ref.file.read() for ref in [ref1, ref2] if ref]
            seed_val = None if seed == -1 else seed
            
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


@app.cls(
    image=image,
    gpu="L40S",
    volumes=volumes,
    secrets=secrets,
    scaledown_window=60,
    max_containers=1,
    timeout=1200,
    memory=48 * 1024
)
class Img2Img_Eco(Img2Img._get_user_cls()):
    """Economy tier endpoint for public/standard users. Cost-optimized on L40S with 60s scaledown."""
    pass


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
