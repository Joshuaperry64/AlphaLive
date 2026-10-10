"""
deploy.py - Unified All-in-One Deployment Gateway for AlphaLive Backend
Modal Application: alphalive-backend

Capabilities:
  1. Media Generation Suite:
     - Txt2Img (SDXL on H100 with real-time step streaming)
     - Img2Img (Flux, SD3.5, Qwen-Image-Edit on L40S)
     - Txt2Vid (AnimateDiff SDXL on L40S)
     - Img2Vid (Wan2.2 Lightning on L40S)
     - Upscaler (RealESRGAN x4plus, 4x-UltraSharp, RealESRGAN Anime on A10G)
     - Vid2Audio (MMAudio 44.1kHz on L40S)
  2. Inference & Conversational Engines:
     - Qwen2.5-32B AWQ vLLM (OpenAI-compatible LLM on A100)
     - Orpheus TTS vLLM + SNAC (24kHz Neural Audio Codec on L4)
  3. AssetSync Engine:
     - Downloads and verifies all required SDXL Checkpoints & LoRAs on Modal Volume.

Usage:
  - Download all models into volume:
      modal run deploy/deploy.py
      modal run deploy/deploy.py --force
      modal run deploy/deploy.py --no-check-updates
  - Deploy the entire backend:
      modal deploy deploy/deploy.py
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

# 2. Worker modules
import upscaler
import vid2audio

if modal.is_local():
    import txt2img
    import img2img
    import txt2vid
    import img2vid
    import vllm_qwen
    import orpheus_tts

# --- CATALOGS: Checkpoints & LoRAs on /hf-hub-cache ---
WEBSITE_CHECKPOINTS = {
    "0x7RealisticFreedom_omegaSDXL.safetensors": "1461059",
    "juggernautXL_ragnarok.safetensors": "1759168",
    "cyberrealisticXL_desireV30.safetensors": "2765942",
    "unholyDesireMixSinister_v80.safetensors": "2824082",
    "dreamshaperXL_alpha2Xl10.safetensors": "128713",
    "lustifyNSFWCheckpoint_zenithV9.safetensors": "3112728",
    "epicrealismXL_pureFix.safetensors": "2514955",
    "intorealism_sdxlV4.safetensors": "2650268",
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
    .pip_install("requests", "tqdm", "fastapi[standard]", "pydantic", "Pillow", "numpy")
    .add_local_python_source("shared_app", "upscaler", "vid2audio")
)

@app.cls(
    image=sync_image,
    volumes={CACHE_DIR: cache_volume},
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
            print(f"[DEPLOYMENT] Volume reload note: {ve}")

        summary = {
            "checkpoints": {"already_present": [], "downloaded": [], "updated": [], "failed": []},
            "loras": {"already_present": [], "downloaded": [], "updated": [], "failed": []},
        }

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
            try:
                v_data = fetch_version_meta(current_version_id)
                if not v_data:
                    return None
                model_id = v_data.get("modelId")
                curr_base = (v_data.get("baseModel") or "SDXL").strip().upper()
                curr_created = v_data.get("createdAt")

                if not model_id:
                    return None

                m_res = requests.get(f"https://civitai.com/api/v1/models/{model_id}", headers=headers, timeout=25)
                if m_res.status_code != 200:
                    return None

                m_data = m_res.json()
                all_versions = m_data.get("modelVersions", [])
                for v in all_versions:
                    v_base = (v.get("baseModel") or "").strip().upper()
                    if "SDXL" in curr_base and "SDXL" not in v_base:
                        continue
                    if str(v.get("id")) != str(current_version_id):
                        v_created = v.get("createdAt")
                        if v_created and curr_created and v_created > curr_created:
                            return {
                                "newer_version_id": str(v.get("id")),
                                "newer_version_name": v.get("name"),
                                "newer_created_at": v_created,
                                "current_version_id": str(current_version_id),
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

            if check_updates:
                update_info = check_for_upstream_update(version_id, category_name, filename)
                if update_info:
                    print(f"🔔 [UPDATE DETECTED] {category_name} '{filename}' ({update_info['model_title']}):")
                    effective_version_id = update_info["newer_version_id"]
                    is_an_update = True

            if not is_an_update and not force and dest_path.exists():
                size_mb = dest_path.stat().st_size / (1024 * 1024)
                if size_mb > 1.0:
                    print(f"[{category_name}] {filename} exists ({size_mb:.2f} MB). Skipping.")
                    summary[category_key]["already_present"].append({"file": filename, "size_mb": round(size_mb, 2)})
                    return

            if is_an_update and dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass

            # Check variants/aliases
            if not is_an_update and not force:
                stem = filename.replace(".safetensors", "")
                for existing in target_dir.glob(f"{stem}*.safetensors"):
                    if existing.is_file() and existing != dest_path and not existing.name.endswith(".tmp"):
                        size_mb = existing.stat().st_size / (1024 * 1024)
                        if size_mb > 1.0:
                            print(f"[{category_name}] Found existing variant {existing.name} for {filename}.")
                            try:
                                os.link(str(existing), str(dest_path))
                            except Exception:
                                try:
                                    os.symlink(str(existing), str(dest_path))
                                except Exception:
                                    import shutil
                                    shutil.copyfile(str(existing), str(dest_path))
                            cache_volume.commit()
                            summary[category_key]["already_present"].append({"file": filename, "size_mb": round(size_mb, 2)})
                            return

            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

            print(f"[{category_name}] Downloading {filename} (ID: {effective_version_id}) from CivitAI...")
            try:
                meta_data = fetch_version_meta(effective_version_id)
                if not meta_data:
                    err = f"CivitAI API could not retrieve metadata for ID {effective_version_id}."
                    summary[category_key]["failed"].append({"file": filename, "error": err})
                    return

                files = meta_data.get("files", [])
                primary = next((f for f in files if f.get("primary", False)), files[0] if files else None)
                if not primary or "downloadUrl" not in primary:
                    err = "No downloadable file found in version metadata"
                    summary[category_key]["failed"].append({"file": filename, "error": err})
                    return

                download_url = primary["downloadUrl"]
                if api_key:
                    delim = "&" if "?" in download_url else "?"
                    download_url = f"{download_url}{delim}token={api_key}"

                with requests.get(download_url, headers=headers, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    total_bytes = int(r.headers.get("content-length", 0))
                    with open(tmp_path, "wb") as f, tqdm(
                        desc=filename,
                        total=total_bytes,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as bar:
                        for chunk in r.iter_content(chunk_size=16 * 1024 * 1024):
                            size = f.write(chunk)
                            bar.update(size)

                tmp_path.replace(dest_path)
                cache_volume.commit()
                file_mb = dest_path.stat().st_size / (1024 * 1024)
                print(f"✓ [{category_name}] Saved {filename} ({file_mb:.2f} MB).")
                summary[category_key]["downloaded"].append({"file": filename, "size_mb": round(file_mb, 2)})
            except Exception as exc:
                print(f"  -> FAILED downloading {filename}: {exc}")
                summary[category_key]["failed"].append({"file": filename, "error": str(exc)})

        print("=" * 60)
        print("ALPHALIVE: SCANNING & SYNCING CHECKPOINTS...")
        print("=" * 60)
        for fn, vid in WEBSITE_CHECKPOINTS.items():
            process_item(fn, vid, ckpt_dir, "checkpoints")

        print("\n" + "=" * 60)
        print("ALPHALIVE: SCANNING & SYNCING LORAS...")
        print("=" * 60)
        for fn, vid in WEBSITE_LORAS.items():
            process_item(fn, vid, lora_dir, "loras")

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
            "timestamp": time.time()
        }

    @app_instance.get("/health")
    def health():
        return {
            "status": "online",
            "engines": ["Txt2Img", "Img2Img", "Txt2Vid", "Img2Vid", "Upscaler", "Vid2Audio", "Qwen2.5-32B", "OrpheusTTS"]
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

    # --- ASSETS SYNC TRIGGER ---
    @app_instance.post("/api/assets/sync")
    async def api_sync_assets(force: bool = False):
        try:
            call = AssetSync().sync_website_models.spawn(force=force)
            return {
                "status": "sync_initiated",
                "call_id": call.object_id,
                "message": "Model scan and download initiated in background on Modal volume."
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app_instance

web_app = create_alphalive_api()

router_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "pydantic", "requests", "Pillow", "numpy")
    .add_local_python_source("shared_app", "upscaler", "vid2audio")
)

@app.function(image=router_image, volumes={CACHE_DIR: cache_volume}, scaledown_window=120, secrets=_get_secrets())
@modal.asgi_app()
def AlphaLive_Main_API():
    """Universal Main API for AlphaLive Backend."""
    return web_app

@app.local_entrypoint()
def scan_and_download(force: bool = False, check_updates: bool = True):
    """
    Run locally via:
        modal run deploy/deploy.py
        modal run deploy/deploy.py --force
        modal run deploy/deploy.py --no-check-updates
    """
    print("🚀 Triggering remote volume scan & download for AlphaLive checkpoints and LoRAs...")
    result = AssetSync().sync_website_models.remote(force=force, check_updates=check_updates)
    print("\n✅ Sync run completed!")
    print(json.dumps(result, indent=2))
