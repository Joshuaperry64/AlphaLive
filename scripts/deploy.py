"""
deploy.py - Unified All-in-One Deployment Gateway for AlphaLive Backend
Modal Application: alphalive-backend

Capabilities:
  1. Media Generation Suite:
     - Txt2Img (SDXL on H100 with real-time step streaming)
     - Img2Img (Flux, SD3.5, Qwen-Image-Edit, SDXL on H100/L40S)
     - Txt2Vid (AnimateDiff SDXL on H100/L40S)
     - Img2Vid (Wan2.2 Lightning on H100/L40S)
     - Upscaler (RealESRGAN x4plus, 4x-UltraSharp, RealESRGAN Anime on H100/L40S)
     - Vid2Audio (MMAudio 44.1kHz on L40S)
     - OmniGen (Unified multi-modal image generation and editing on H100)
     - Preprocessors (ControlNet Canny, OpenPose, Depth on A10G)
     - WatermarkRemover (Fast Swin2 watermark removal on T4)
     - VoiceCloner (RVC v2 voice conversion and dataset training on A10G)
  2. Inference & Conversational Engines:
     - Qwen2.5-32B AWQ vLLM (OpenAI-compatible LLM on A100-80GB)
     - Orpheus TTS vLLM + SNAC (24kHz Neural Audio Codec on L4)
     - Cognitive Core vLLM (Lightweight OpenAI-compatible LLM on L4/T4)
  3. AssetSync Engine:
     - Downloads and verifies SDXL checkpoints, LoRAs, Qwen weights, and Orpheus/SNAC weights.

Usage:
  - Download and cache all models (Checkpoints, LoRAs, Qwen2.5-32B, Orpheus TTS) into volumes:
      modal run scripts/deploy.py
      modal run scripts/deploy.py --force
      modal run scripts/deploy.py --no-check-updates
  - Target specific categories:
      modal run scripts/deploy.py --media-only
      modal run scripts/deploy.py --qwen-only
      modal run scripts/deploy.py --orpheus-only
  - Deploy the entire backend:
      modal deploy scripts/deploy.py
"""

import os
import io
import time
import json
import base64
from typing import Optional, Dict, Any, List
from pathlib import Path

import modal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 1. Central App & Shared Storage
from shared_app import app, CACHE_DIR, cache_volume, OUTPUTS_DIR, outputs_volume

# 2. Worker modules - Register all endpoint scripts on the unified Modal App
import upscaler
import vid2audio

try:
    import txt2img
    import img2img
    import txt2vid
    import img2vid
    import omnigen
    import preprocessors
    import voice_cloner
    import watermark_remover
    import vllm_qwen
    import orpheus_tts
    import vllm_t4
except Exception as _mod_err:
    if modal.is_local():
        print(f"[DEPLOYMENT NOTE] Worker module import warning: {_mod_err}")

# --- CATALOGS: Checkpoints & LoRAs on /hf-hub-cache (Shared with AlphaCoreNexus) ---
WEBSITE_CHECKPOINTS = {
    "0x7RealisticFreedom_omegaSDXL.safetensors": "1461059",
    "juggernautXL_ragnarok.safetensors": "1759168",
    "cyberrealisticXL_desireV30.safetensors": "2765942",
    "unholyDesireMixCrimson_v50.safetensors": "2200584",
    "dreamshaperXL_alpha2Xl10.safetensors": "303662",
    "lustifyNSFWCheckpoint_zenithV9.safetensors": "3112728",
    "epicrealismXL_pureFix.safetensors": "2514955",
    "intorealism_sdxlV4.safetensors": "2650268",
    "cyberrealisticPony_v180Coreshift.safetensors": "2884631",
    "realvisxlV50_v50Bakedvae.safetensors": "798204",
    "realisticComicBook_v10.safetensors": "271085",
    "juicyDreams_v10.safetensors": "3381025",
    "ntrMIXIllustriousXL_xiii.safetensors": "1166878",
}

WEBSITE_LORAS = {
    "epiCRealismHelper.safetensors": "1051156",
    "cunny.safetensors": "286911",
    "FlatTop.safetensors": "1109661",
    "BJ.safetensors": "1312598",
    "Cowgirl.safetensors": "472474",
    "Missionary.safetensors": "144818",
    "SpyCam.safetensors": "545059",
    "detailifier.safetensors": "623945",
    "lezcunbkv2.safetensors": "252053",
}

def _get_secrets():
    secrets = []
    try:
        secrets.append(modal.Secret.from_name("civitai-secret"))
    except Exception:
        pass
    try:
        secrets.append(modal.Secret.from_name("huggingface-secret"))
    except Exception:
        pass
    return secrets

sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests",
        "tqdm",
        "fastapi[standard]",
        "pydantic",
        "Pillow",
        "numpy",
        "huggingface_hub[hf_transfer]",
    )
    .add_local_python_source("shared_app", "upscaler", "vid2audio")
)

hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)

@app.cls(
    image=sync_image,
    volumes={
        CACHE_DIR: cache_volume,
        "/root/.cache/huggingface": hf_cache_vol,
    },
    secrets=_get_secrets(),
    timeout=3600
)
class AssetSync:
    @modal.method()
    def sync_website_models(self, force: bool = False, check_updates: bool = True):
        """
        Scans the hf-hub-cache volume for all SDXL checkpoints and LoRAs.
        If any asset is missing or empty, downloads it directly from CivitAI.
        """
        import requests
        from tqdm import tqdm

        api_key = os.environ.get("CIVITAI_API_KEY", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        ckpt_dir = Path(CACHE_DIR) / "checkpoints"
        lora_dir = Path(CACHE_DIR) / "loras"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        lora_dir.mkdir(parents=True, exist_ok=True)

        try:
            cache_volume.reload()
        except Exception as ve:
            print(f"[DEPLOYMENT] Volume reload note (non-fatal): {ve}")

        summary = {
            "checkpoints": {"already_present": [], "downloaded": [], "updated": [], "failed": []},
            "loras": {"already_present": [], "downloaded": [], "updated": [], "failed": []},
        }

        manifest_path = Path(CACHE_DIR) / "models_manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as mf:
                    manifest = json.load(mf)
            except Exception as me:
                print(f"[MANIFEST] Read note: {me}")

        def save_manifest_entry(fname, vid, vname="", size_mb=0.0):
            manifest[fname] = {
                "version_id": str(vid),
                "name": vname,
                "size_mb": round(size_mb, 2) if size_mb else None,
                "updated_at": time.time()
            }
            try:
                with open(manifest_path, "w", encoding="utf-8") as mf:
                    json.dump(manifest, mf, indent=2)
                cache_volume.commit()
            except Exception as me:
                print(f"[MANIFEST] Save note: {me}")

        version_cache = {}

        def fetch_version_meta(v_id):
            if v_id in version_cache:
                return version_cache[v_id]
            try:
                res = requests.get(f"https://civitai.com/api/v1/model-versions/{v_id}", headers=headers, timeout=25)
                if res.status_code == 200:
                    data = res.json()
                    version_cache[v_id] = data
                    return data
            except Exception as e:
                print(f"  [API] Failed fetching version {v_id}: {e}")
            return None

        def check_for_upstream_update(current_version_id, category_name, filename):
            """Checks CivitAI parent model for newer versions with matching architecture."""
            try:
                # If we have an on-volume recorded version for this file, use it as baseline
                manifest_entry = manifest.get(filename, {})
                if isinstance(manifest_entry, dict):
                    effective_curr_vid = str(manifest_entry.get("version_id", current_version_id))
                else:
                    effective_curr_vid = str(manifest_entry)

                v_data = fetch_version_meta(effective_curr_vid)
                if not v_data:
                    v_data = fetch_version_meta(current_version_id)
                if not v_data:
                    return None
                model_id = v_data.get("modelId")
                curr_base = (v_data.get("baseModel") or "SDXL").strip().lower()
                curr_created = v_data.get("createdAt")

                if not model_id:
                    return None

                m_res = requests.get(f"https://civitai.com/api/v1/models/{model_id}", headers=headers, timeout=25)
                if m_res.status_code != 200:
                    return None

                m_data = m_res.json()
                all_versions = m_data.get("modelVersions", [])
                candidates = []
                for v in all_versions:
                    v_id_str = str(v.get("id"))
                    # If this version matches currently installed/recorded version, skip
                    if v_id_str == str(effective_curr_vid):
                        continue

                    # Must have published status
                    if v.get("status") and v.get("status").lower() not in ("published", "active"):
                        continue

                    # Must have downloadable files
                    v_files = v.get("files", [])
                    if not any(f.get("downloadUrl") for f in v_files):
                        continue

                    v_base = (v.get("baseModel") or "").strip().lower()
                    # Architecture family consistency check:
                    if "sdxl" in curr_base and "sdxl" not in v_base:
                        continue
                    if "pony" in curr_base and "pony" not in v_base:
                        continue
                    if "noob" in curr_base and "noob" not in v_base:
                        continue
                    if "illustrious" in curr_base and "illustrious" not in v_base:
                        continue
                    if "1.5" in curr_base and "1.5" not in v_base:
                        continue

                    v_created = v.get("createdAt")
                    # Compare release timestamp if present
                    if v_created and curr_created and v_created > curr_created:
                        candidates.append(v)

                if candidates:
                    # Sort candidates so the newest version by createdAt is selected
                    candidates.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
                    newest = candidates[0]
                    return {
                        "newer_version_id": str(newest.get("id")),
                        "newer_version_name": newest.get("name"),
                        "newer_created_at": newest.get("createdAt"),
                        "current_version_id": str(effective_curr_vid),
                        "current_version_name": v_data.get("name"),
                        "model_title": m_data.get("name"),
                        "filename": filename,
                        "category": category_name
                    }
            except Exception as check_err:
                print(f"  [UPDATE CHECK] Note for {filename}: {check_err}")
            return None

        def process_item(filename, version_id, target_dir, category_key):
            dest_path = target_dir / filename
            category_name = "CHECKPOINT" if category_key == "checkpoints" else "LORA"
            effective_version_id = version_id
            is_an_update = False
            update_meta = None

            # Check for upstream newer versions if update checking is active
            if check_updates:
                update_info = check_for_upstream_update(version_id, category_name, filename)
                if update_info:
                    print(f"🔔 [UPDATE DETECTED] {category_name} '{filename}' ({update_info['model_title']}):")
                    print(f"    Current: {update_info['current_version_name']} (ID: {update_info['current_version_id']})")
                    print(f"    Newer:   {update_info['newer_version_name']} (ID: {update_info['newer_version_id']} - Released: {update_info['newer_created_at']})")
                    effective_version_id = update_info["newer_version_id"]
                    is_an_update = True
                    update_meta = update_info

            # If not an update, check if current file already exists and is healthy
            if not is_an_update and not force and dest_path.exists():
                size_mb = dest_path.stat().st_size / (1024 * 1024)
                min_valid_mb = 10.0 if category_key == "checkpoints" else 1.0
                if size_mb > min_valid_mb:
                    print(f"[{category_name}] {filename} exists ({size_mb:.2f} MB, version {manifest.get(filename, {}).get('version_id', version_id)}). Skipping.")
                    if filename not in manifest:
                        save_manifest_entry(filename, version_id, size_mb=size_mb)
                    summary[category_key]["already_present"].append({"file": filename, "size_mb": round(size_mb, 2)})
                    return

            # Check for existing variants/aliases only if not updating
            if not is_an_update and not force:
                stem = filename.replace(".safetensors", "")
                for existing in target_dir.glob(f"{stem}*.safetensors"):
                    if existing.is_file() and existing != dest_path and not existing.name.endswith(".tmp"):
                        size_mb = existing.stat().st_size / (1024 * 1024)
                        if size_mb > (10.0 if category_key == "checkpoints" else 1.0):
                            print(f"[{category_name}] Found existing variant {existing.name} ({size_mb:.2f} MB) for {filename}. Linking...")
                            try:
                                os.link(str(existing), str(dest_path))
                            except Exception:
                                try:
                                    os.symlink(str(existing), str(dest_path))
                                except Exception:
                                    import shutil
                                    shutil.copyfile(str(existing), str(dest_path))
                            cache_volume.commit()
                            save_manifest_entry(filename, version_id, size_mb=size_mb)
                            summary[category_key]["already_present"].append({"file": filename, "size_mb": round(size_mb, 2)})
                            return

            # Clean stale tmp file if any
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

            action_label = f"UPDATING {filename} to version {effective_version_id}" if is_an_update else f"Missing {filename}! Fetching metadata (ID: {effective_version_id})"
            print(f"[{category_name}] {action_label} from CivitAI...")
            try:
                meta_data = fetch_version_meta(effective_version_id)
                if not meta_data:
                    err = f"CivitAI API could not retrieve metadata for ID {effective_version_id}."
                    print(f"  -> ERROR: {err}")
                    summary[category_key]["failed"].append({"file": filename, "error": err})
                    return

                files = meta_data.get("files", [])
                primary = next((f for f in files if f.get("primary", False)), files[0] if files else None)
                if not primary or "downloadUrl" not in primary:
                    err = "No downloadable file found in version metadata"
                    print(f"  -> ERROR: {err}")
                    summary[category_key]["failed"].append({"file": filename, "error": err})
                    return

                dl_url = primary["downloadUrl"]
                if api_key:
                    dl_url += f"&token={api_key}" if "?" in dl_url else f"?token={api_key}"

                expected_mb = primary.get("sizeKB", 0) / 1024
                print(f"  -> Downloading {filename} ({expected_mb:.2f} MB)...")

                with requests.get(dl_url, headers=headers, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get("content-length", 0))

                    with open(tmp_path, "wb") as f, tqdm(
                        desc=filename,
                        total=total_size,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as bar:
                        for chunk in r.iter_content(chunk_size=16 * 1024 * 1024):
                            f.write(chunk)
                            bar.update(len(chunk))

                tmp_size_mb = tmp_path.stat().st_size / (1024 * 1024)
                min_mb = 10.0 if category_key == "checkpoints" else 1.0
                if tmp_size_mb < min_mb:
                    tmp_path.unlink(missing_ok=True)
                    err = f"Downloaded file size too small ({tmp_size_mb:.2f} MB), potentially corrupt or HTML error response."
                    print(f"  -> ERROR: {err}")
                    summary[category_key]["failed"].append({"file": filename, "error": err})
                    return

                # Atomic replacement
                tmp_path.replace(dest_path)
                cache_volume.commit()
                actual_mb = dest_path.stat().st_size / (1024 * 1024)
                print(f"  -> [SAVED] {dest_path} ({actual_mb:.2f} MB)")

                v_name = update_meta.get("newer_version_name", "") if update_meta else meta_data.get("name", "")
                save_manifest_entry(filename, effective_version_id, v_name, size_mb=actual_mb)

                if is_an_update:
                    summary[category_key]["updated"].append({
                        "file": filename,
                        "size_mb": round(actual_mb, 2),
                        "new_version_id": effective_version_id,
                        "new_version_name": update_meta.get("newer_version_name") if update_meta else None
                    })
                else:
                    summary[category_key]["downloaded"].append({"file": filename, "size_mb": round(actual_mb, 2)})

            except Exception as exc:
                print(f"  -> FAILED downloading {filename}: {exc}")
                summary[category_key]["failed"].append({"file": filename, "error": str(exc)})

        print("=" * 60)
        print("ALPHALIVE: SCANNING & SYNCING CHECKPOINTS...")
        print("=" * 60)
        # Purge obsolete checkpoints if present to reclaim volume storage
        for obsolete_fn in ["unholyDesireMixSinister_v80.safetensors", "realisticVisionV60B1_v60B1VAE.safetensors"]:
            obsolete_file = ckpt_dir / obsolete_fn
            if obsolete_file.exists():
                try:
                    obsolete_file.unlink()
                    print(f"[AssetSync] ♻️ Replaced/purged obsolete {obsolete_fn}")
                except Exception as e:
                    print(f"[AssetSync] Note purging obsolete checkpoint {obsolete_fn}: {e}")

        for fn, vid in WEBSITE_CHECKPOINTS.items():
            process_item(fn, vid, ckpt_dir, "checkpoints")

        print("\n" + "=" * 60)
        print("ALPHALIVE: SCANNING & SYNCING LORAS...")
        print("=" * 60)
        for fn, vid in WEBSITE_LORAS.items():
            process_item(fn, vid, lora_dir, "loras")

        # Provide friendly alias licking_lesbians.safetensors pointing to lezcunbkv2.safetensors
        lez_file = lora_dir / "lezcunbkv2.safetensors"
        lez_alias = lora_dir / "licking_lesbians.safetensors"
        if lez_file.exists() and not lez_alias.exists():
            try:
                os.link(str(lez_file), str(lez_alias))
            except Exception:
                try:
                    os.symlink(str(lez_file), str(lez_alias))
                except Exception:
                    pass

        for tmp_file in list(ckpt_dir.glob("*.tmp")) + list(lora_dir.glob("*.tmp")):
            try:
                tmp_file.unlink()
            except Exception:
                pass

        cache_volume.commit()
        print("\n" + "=" * 60)
        print("ALPHALIVE SYNC COMPLETED")
        print("=" * 60)
        return summary

    @modal.method()
    def download_qwen_weights(self):
        """Downloads and caches Qwen 32B weights to the shared Hugging Face volume."""
        from huggingface_hub import snapshot_download

        model_name = "SamCrowdwave/Qwen2.5-32B-Instruct-abliterated-AWQ"
        print(f"[AssetSync] Downloading {model_name} into persistent volume...")
        started_at = time.time()
        snapshot_download(model_name, ignore_patterns=["*.pt", "*.bin"])
        print(f"[AssetSync] Qwen weights cached in {time.time() - started_at:.2f}s")
        hf_cache_vol.commit()

    @modal.method()
    def download_orpheus_weights(self):
        """Downloads and caches Orpheus and SNAC weights to the shared Hugging Face volume."""
        from huggingface_hub import snapshot_download

        model_names = (
            "canopylabs/orpheus-3b-0.1-ft",
            "hubertsiuzdak/snac_24khz",
        )
        started_at = time.time()
        for model_name in model_names:
            print(f"[AssetSync] Downloading {model_name} into persistent volume...")
            snapshot_download(model_name, ignore_patterns=["*.pt", "*.bin"])
        print(f"[AssetSync] Orpheus and SNAC weights cached in {time.time() - started_at:.2f}s")
        hf_cache_vol.commit()

    @modal.method()
    def download_all_weights(self, force: bool = False, check_updates: bool = True):
        """One-stop method to download CivitAI checkpoints/LoRAs, Qwen LLM, and Orpheus TTS weights."""
        summary = self.sync_website_models.local(force=force, check_updates=check_updates)
        self.download_qwen_weights.local()
        self.download_orpheus_weights.local()
        return summary

# --- PYDANTIC SCHEMAS ---
class Vid2AudioRequest(BaseModel):
    video: Optional[str] = None
    video_b64: Optional[str] = None
    prompt: str = ""
    negative_prompt: str = "low quality, muffled, noise, distorted"
    duration: float = 8.0
    num_steps: int = 25
    cfg_strength: float = 4.5
    variant: str = "large_44k_v2"
    seed: int = -1
    return_video: bool = True

class Txt2ImgRequest(BaseModel):
    prompt: str = "A cinematic photo"
    model_name: str = "0x7RealisticFreedom_omegaSDXL.safetensors"
    negative_prompt: str = "low quality, blurry, distorted"
    batch_size: int = 1
    guidance_scale: float = 7.0
    num_inference_steps: int = 25
    seed: int = -1
    lora: str = "none"

class Img2ImgRequest(BaseModel):
    image_b64: str
    prompt: str = ""
    model: str = "qwen"
    checkpoint: str = ""
    strength: float = 0.75
    num_steps: int = 20
    guidance_scale: float = 7.0
    seed: int = -1
    lora: str = "none"

class Txt2VidRequest(BaseModel):
    prompt: str = "A cinematic scene"
    model: str = "epic"
    negative_prompt: str = "low quality, blurry, distorted"
    height: int = 1024
    width: int = 1024
    num_frames: int = 16
    guidance_scale: float = 7.5
    steps: int = 25
    seed: int = -1
    fps: int = 8

class Img2VidRequest(BaseModel):
    image_b64: str
    prompt: str = ""
    negative_prompt: str = "low quality, blurry, distorted"
    num_frames: int = 81
    fps: int = 16
    seed: int = -1

class OmniGenRequest(BaseModel):
    prompt: str
    input_images: Optional[List[str]] = None
    height: int = 1024
    width: int = 1024
    num_inference_steps: int = 30
    guidance_scale: float = 2.5
    seed: int = -1

class PreprocessRequest(BaseModel):
    image_b64: str
    processor_type: str = "canny"

class WatermarkRemoveRequest(BaseModel):
    image_b64: str

class VoiceCloneInferRequest(BaseModel):
    profile_name: str
    audio_b64: str
    pitch_shift: int = 0

# --- API ROUTER FACTORY ---
def create_alphalive_api() -> FastAPI:
    app_instance = FastAPI(title="AlphaLive Unified Backend")

    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app_instance.get("/")
    def home():
        return {
            "status": "AlphaLive Unified Backend Online",
            "app": "alphalive-backend",
            "engines": [
                "Txt2Img", "Img2Img", "Txt2Vid", "Img2Vid",
                "Upscaler", "Vid2Audio", "OmniGen", "Preprocessors",
                "VoiceCloner", "WatermarkRemover", "Qwen2.5-32B",
                "OrpheusTTS", "CognitiveCore-T4"
            ],
            "timestamp": time.time()
        }

    @app_instance.get("/health")
    def health():
        return {
            "status": "online",
            "engines": [
                "Txt2Img", "Img2Img", "Txt2Vid", "Img2Vid",
                "Upscaler", "Vid2Audio", "OmniGen", "Preprocessors",
                "VoiceCloner", "WatermarkRemover", "Qwen2.5-32B",
                "OrpheusTTS", "CognitiveCore-T4"
            ]
        }

    # --- NEURAL UPSCALER ---
    @app_instance.get("/api/upscale/status")
    def api_upscale_status():
        return {
            "status": "online",
            "engine": "Real-ESRGAN / Neural Super-Resolution Pipeline",
            "models": [
                {"id": "realesrgan-x4plus", "name": "RealESRGAN x4plus", "category": "Photo Realism", "scale": 4},
                {"id": "realesrgan-anime", "name": "RealESRGAN Anime 6B", "category": "2D / Line Art", "scale": 4},
                {"id": "ultrasharp-4x", "name": "4x UltraSharp", "category": "Crisp Textures", "scale": 4},
                {"id": "dsp-fast", "name": "Fast Adaptive DSP", "category": "Instant Resampling", "scale": 4}
            ],
            "supported_scales": [2, 4, 8],
            "timestamp": time.time()
        }

    @app_instance.post("/api/upscale")
    async def api_upscale(req: upscaler.UpscaleRequest):
        try:
            res = await upscaler.Upscaler().upscale_image.remote.aio(**req.model_dump())
            return res
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- VID2AUDIO ---
    @app_instance.post("/api/vid2audio/generate")
    async def api_generate_vid2audio(req: Vid2AudioRequest):
        try:
            video_input = req.video or req.video_b64
            if not video_input:
                raise HTTPException(status_code=400, detail="Missing 'video' (base64) parameter")
            result = await vid2audio.Vid2Audio().generate.remote.aio(
                video_b64=video_input,
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                duration=req.duration,
                num_steps=req.num_steps,
                cfg_strength=req.cfg_strength,
                variant=req.variant,
                seed=req.seed,
                return_video=req.return_video
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- TXT2IMG ---
    @app_instance.post("/api/txt2img/generate")
    async def api_generate_txt2img(req: Txt2ImgRequest):
        try:
            import txt2img
            msgs = list(await txt2img.Txt2Img().run.remote.aio(
                prompt=req.prompt,
                model_name=req.model_name,
                negative_prompt=req.negative_prompt,
                batch_size=req.batch_size,
                guidance_scale=str(req.guidance_scale),
                num_inference_steps=req.num_inference_steps,
                seed=req.seed,
                lora=req.lora
            ))
            final_msg = msgs[-1] if msgs else {}
            if "error" in final_msg:
                raise HTTPException(status_code=500, detail=str(final_msg["error"]))
            return final_msg
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- IMG2IMG ---
    @app_instance.post("/api/img2img/generate")
    async def api_generate_img2img(req: Img2ImgRequest):
        try:
            import img2img
            raw_img = req.image_b64
            if "," in raw_img:
                raw_img = raw_img.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_img)
            res_bytes = await img2img.Img2Img().inference.remote.aio(
                image_bytes=img_bytes,
                prompt=req.prompt,
                model=req.model,
                checkpoint=req.checkpoint,
                strength=req.strength,
                num_steps=req.num_steps,
                guidance_scale=req.guidance_scale,
                seed=req.seed,
                lora=req.lora
            )
            b64_out = base64.b64encode(res_bytes).decode("utf-8")
            return {"status": "success", "image_b64": b64_out}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- TXT2VID ---
    @app_instance.post("/api/txt2vid/generate")
    async def api_generate_txt2vid(req: Txt2VidRequest):
        try:
            import txt2vid
            video_bytes = await txt2vid.Txt2Vid().inference.remote.aio(
                prompt=req.prompt,
                model=req.model,
                negative_prompt=req.negative_prompt,
                height=req.height,
                width=req.width,
                num_frames=req.num_frames,
                guidance_scale=req.guidance_scale,
                steps=req.steps,
                seed=req.seed,
                fps=req.fps
            )
            b64_vid = base64.b64encode(video_bytes).decode("utf-8")
            return {"status": "success", "video_b64": b64_vid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- IMG2VID ---
    @app_instance.post("/api/img2vid/generate")
    async def api_generate_img2vid(req: Img2VidRequest):
        try:
            import img2vid
            raw_img = req.image_b64
            if "," in raw_img:
                raw_img = raw_img.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_img)
            video_bytes = await img2vid.Img2Vid().inference.remote.aio(
                image_bytes=img_bytes,
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                num_frames=req.num_frames,
                fps=req.fps,
                seed=req.seed
            )
            b64_vid = base64.b64encode(video_bytes).decode("utf-8")
            return {"status": "success", "video_b64": b64_vid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- OMNIGEN ---
    @app_instance.post("/api/omnigen/generate")
    async def api_generate_omnigen(req: OmniGenRequest):
        try:
            import omnigen
            output_bytes_list = await omnigen.OmniGen().inference.remote.aio(
                prompt=req.prompt,
                input_images=req.input_images,
                height=req.height,
                width=req.width,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
                seed=req.seed
            )
            b64_images = [base64.b64encode(b).decode("utf-8") for b in output_bytes_list]
            return {"status": "success", "images_b64": b64_images}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- PREPROCESSORS (CONTROLNET) ---
    @app_instance.post("/api/preprocess")
    async def api_preprocess(req: PreprocessRequest):
        try:
            import preprocessors
            b64_data = req.image_b64
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(b64_data)
            processed_bytes = await preprocessors.ControlNet().process.remote.aio(raw_bytes, req.processor_type)
            out_b64 = base64.b64encode(processed_bytes).decode("utf-8")
            return {"status": "success", "image_b64": f"data:image/png;base64,{out_b64}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- WATERMARK REMOVER ---
    @app_instance.post("/api/watermark/remove")
    async def api_remove_watermark(req: WatermarkRemoveRequest):
        try:
            import watermark_remover
            raw_img = req.image_b64
            if "," in raw_img:
                raw_img = raw_img.split(",", 1)[1]
            in_bytes = base64.b64decode(raw_img)
            clean_bytes = await watermark_remover.WatermarkRemover().remove_watermark.remote.aio(in_bytes)
            out_b64 = base64.b64encode(clean_bytes).decode("utf-8")
            return {"status": "success", "image_b64": out_b64}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- VOICE CLONER ---
    @app_instance.post("/api/voice_clone/infer")
    async def api_voice_clone_infer(req: VoiceCloneInferRequest):
        try:
            import voice_cloner
            raw_audio = req.audio_b64
            if "," in raw_audio:
                raw_audio = raw_audio.split(",", 1)[1]
            in_bytes = base64.b64decode(raw_audio)
            res = await voice_cloner.VoiceCloner().infer_audio_modal.remote.aio(
                profile_name=req.profile_name,
                audio_bytes=in_bytes,
                pitch_shift=req.pitch_shift
            )
            return res
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app_instance.get("/api/voice_clone/contents")
    async def api_voice_clone_contents():
        try:
            import voice_cloner
            res = await voice_cloner.VoiceCloner_Storage().list_volume_contents.remote.aio()
            return res
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- ASSETS SYNC TRIGGERS ---
    @app_instance.post("/api/assets/sync")
    async def api_sync_assets(force: bool = False, check_updates: bool = True):
        try:
            call = AssetSync().sync_website_models.spawn(force=force, check_updates=check_updates)
            return {
                "status": "sync_initiated",
                "call_id": call.object_id,
                "message": "Model scan and download initiated in background on Modal volume."
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app_instance.post("/api/assets/sync/qwen")
    async def api_sync_qwen():
        try:
            call = AssetSync().download_qwen_weights.spawn()
            return {"status": "sync_initiated", "call_id": call.object_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app_instance.post("/api/assets/sync/orpheus")
    async def api_sync_orpheus():
        try:
            call = AssetSync().download_orpheus_weights.spawn()
            return {"status": "sync_initiated", "call_id": call.object_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app_instance

web_app = create_alphalive_api()

router_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "pydantic", "requests", "Pillow", "numpy")
    .add_local_python_source(
        "shared_app",
        "upscaler",
        "vid2audio",
        "txt2img",
        "img2img",
        "txt2vid",
        "img2vid",
        "omnigen",
        "preprocessors",
        "voice_cloner",
        "watermark_remover",
        "vllm_qwen",
        "orpheus_tts",
        "vllm_t4",
    )
)

@app.function(image=router_image, volumes={CACHE_DIR: cache_volume}, scaledown_window=120, secrets=_get_secrets())
@modal.asgi_app()
def AlphaLive_Main_API():
    """Universal Main API for AlphaLive Backend."""
    return web_app

@app.local_entrypoint()
def scan_and_download(
    force: bool = False,
    check_updates: bool = True,
    qwen_only: bool = False,
    orpheus_only: bool = False,
    media_only: bool = False,
):
    """
    Run locally via:
        modal run scripts/deploy.py               # Downloads ALL weights (Checkpoints, LoRAs, Qwen, Orpheus)
        modal run scripts/deploy.py --force       # Forces re-download of all weights
        modal run scripts/deploy.py --media-only  # Only syncs CivitAI SDXL checkpoints and LoRAs
        modal run scripts/deploy.py --qwen-only   # Only downloads Qwen2.5-32B weights
        modal run scripts/deploy.py --orpheus-only# Only downloads Orpheus & SNAC weights
    """
    if qwen_only:
        print("🚀 Downloading Qwen2.5-32B weights into shared volume...")
        AssetSync().download_qwen_weights.remote()
        result = {"status": "qwen_weights_downloaded"}
    elif orpheus_only:
        print("🚀 Downloading Orpheus & SNAC weights into shared volume...")
        AssetSync().download_orpheus_weights.remote()
        result = {"status": "orpheus_weights_downloaded"}
    elif media_only:
        print("🚀 Triggering remote volume scan & download for AlphaLive checkpoints and LoRAs only...")
        result = AssetSync().sync_website_models.remote(force=force, check_updates=check_updates)
    else:
        print("🚀 [DEFAULT] Triggering full weights download (Checkpoints, LoRAs, Qwen, Orpheus)...")
        result = AssetSync().download_all_weights.remote(force=force, check_updates=check_updates)

    print("\n✅ Operation completed!")
    print(json.dumps(result, indent=2))
