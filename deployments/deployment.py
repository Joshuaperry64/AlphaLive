"""
AlphaLive — Modal Deployment
=============================================================================
Unified single-tier production API for AlphaLive core services:
- Checkpoints & LoRA sync / volume management (web_loader)
- Neural Upscaler (upscaler)
- Image Generation (txt2img, img2img)
- Video Generation (txt2vid, img2vid)

Shared Modal app defined in shared_app.py:
    App name:        alphalive-aio-backend
    ASGI function:   alphalive_api

Deploy:
    cd deployments
    modal deploy deployment.py

Run Asset Loader:
    modal run instant-loader.py

Stop:
    modal app stop alphalive-aio-backend
"""

import base64
import time
import os
from pathlib import Path

import modal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# ─── Shared Modal app + volumes ──────────────────────────────────────────────
from shared_app import app, CACHE_DIR, cache_volume

# ─── Worker modules (live inside deployments/) ──────────────────────────────
import upscaler

if modal.is_local():
    import txt2img
    import img2img
    import txt2vid
    import img2vid
    import upscaler

# ─── Model catalogs ──────────────────────────────────────────────────────────
WEBSITE_CHECKPOINTS = {
    "0x7RealisticFreedom_omegaSDXL.safetensors":   "1461059",
    "juggernautXL_ragnarok.safetensors":            "1759168",
    "cyberrealisticXL_desireV30.safetensors":       "2765942",
    "unholyDesireMixSinister_v80.safetensors":      "2824082",
    "dreamshaperXL_alpha2Xl10.safetensors":         "128713",
    "lustifyNSFWCheckpoint_zenithV9.safetensors":   "3112728",
    "epicrealismXL_pureFix.safetensors":            "2514955",
}

WEBSITE_LORAS = {
    "epiCRealismHelper.safetensors": "118945",
    "cunny.safetensors":             "286911",
    "FlatTop.safetensors":           "1109661",
    "BJ.safetensors":                "1312598",
    "Cowgirl.safetensors":           "472474",
    "Missionary.safetensors":        "144818",
    "SpyCam.safetensors":            "545059",
    "detailifier.safetensors":       "623945",
}

# ─── Secrets helper ──────────────────────────────────────────────────────────
def _get_secrets():
    secrets = []
    for name in ("civitai-secret", "huggingface-secret"):
        try:
            secrets.append(modal.Secret.from_name(name))
        except Exception:
            pass
    return secrets

# ─── Model sync background job ───────────────────────────────────────────────
_sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("requests", "tqdm", "fastapi[standard]", "pydantic", "Pillow", "numpy")
    .add_local_python_source("shared_app", "upscaler")
)

@app.function(
    image=_sync_image,
    volumes={CACHE_DIR: cache_volume},
    secrets=_get_secrets(),
    timeout=3600,
)
def sync_website_models(force: bool = False):
    """
    Scans the hf-hub-cache volume for all configured checkpoints and LoRAs.
    Downloads any that are missing or empty directly from CivitAI.
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
        print(f"[SYNC] Volume reload note (non-fatal): {ve}")

    summary = {
        "checkpoints": {"already_present": [], "downloaded": [], "failed": []},
        "loras":       {"already_present": [], "downloaded": [], "failed": []},
    }

    def process_item(filename, version_id, target_dir, category_key):
        label = "CHECKPOINT" if category_key == "checkpoints" else "LORA"
        dest  = target_dir / filename

        if not force and dest.exists() and dest.stat().st_size > 1_048_576:
            mb = dest.stat().st_size / 1_048_576
            print(f"[{label}] {filename} already present ({mb:.1f} MB). Skipping.")
            summary[category_key]["already_present"].append({"file": filename, "size_mb": round(mb, 2)})
            return

        # Check alias variants
        if not force:
            stem = filename.replace(".safetensors", "")
            for existing in target_dir.glob(f"{stem}*.safetensors"):
                if existing.is_file() and existing != dest and not existing.name.endswith(".tmp"):
                    mb = existing.stat().st_size / 1_048_576
                    if mb > 1.0:
                        print(f"[{label}] Variant found: {existing.name} — linking to {filename}")
                        try:
                            os.link(str(existing), str(dest))
                        except Exception:
                            try:
                                os.symlink(str(existing), str(dest))
                            except Exception:
                                import shutil
                                shutil.copyfile(str(existing), str(dest))
                        cache_volume.commit()
                        summary[category_key]["already_present"].append({"file": filename, "size_mb": round(mb, 2)})
                        return

        # Remove stale tmp
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        print(f"[{label}] Fetching {filename} from CivitAI (version {version_id})…")
        try:
            meta = requests.get(
                f"https://civitai.com/api/v1/model-versions/{version_id}",
                headers=headers, timeout=30
            )
            if meta.status_code != 200:
                raise RuntimeError(f"CivitAI API {meta.status_code}")
            files   = meta.json().get("files", [])
            primary = next((f for f in files if f.get("primary")), files[0] if files else None)
            if not primary or "downloadUrl" not in primary:
                raise RuntimeError("No downloadable file in version metadata")

            dl_url = primary["downloadUrl"]
            if api_key:
                dl_url += ("&" if "?" in dl_url else "?") + f"token={api_key}"

            mb_expected = primary.get("sizeKB", 0) / 1024
            print(f"  -> Downloading {filename} ({mb_expected:.1f} MB)…")

            with requests.get(dl_url, headers=headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                with open(tmp, "wb") as fh, tqdm(
                    desc=filename, total=total, unit="iB", unit_scale=True, unit_divisor=1024
                ) as bar:
                    for chunk in r.iter_content(chunk_size=65536):
                        fh.write(chunk)
                        bar.update(len(chunk))

            tmp.rename(dest)
            cache_volume.commit()
            mb_actual = dest.stat().st_size / 1_048_576
            print(f"  -> Saved {dest} ({mb_actual:.1f} MB)")
            summary[category_key]["downloaded"].append({"file": filename, "size_mb": round(mb_actual, 2)})

        except Exception as exc:
            print(f"  -> FAILED {filename}: {exc}")
            summary[category_key]["failed"].append({"file": filename, "error": str(exc)})

    print("=" * 60)
    print("ALPHALIVE: SYNCING CHECKPOINTS")
    print("=" * 60)
    for fn, vid in WEBSITE_CHECKPOINTS.items():
        process_item(fn, vid, ckpt_dir, "checkpoints")

    print("\n" + "=" * 60)
    print("ALPHALIVE: SYNCING LORAS")
    print("=" * 60)
    for fn, vid in WEBSITE_LORAS.items():
        process_item(fn, vid, lora_dir, "loras")

    # Clean orphaned tmp files
    for stale in list(ckpt_dir.glob("*.tmp")) + list(lora_dir.glob("*.tmp")):
        try:
            stale.unlink()
            print(f"[CLEANUP] Removed stale temp: {stale.name}")
        except Exception:
            pass

    cache_volume.commit()
    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)
    return summary


# ─── FastAPI app factory ──────────────────────────────────────────────────────
def create_api() -> FastAPI:
    api = FastAPI(title="AlphaLive API")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ────────────────────────────────────────────────────────────────
    @api.get("/")
    def health():
        return {"status": "AlphaLive API Online", "timestamp": time.time()}

    # ── Model sync ────────────────────────────────────────────────────────────
    @api.post("/api/assets/sync")
    async def api_sync_models(force: bool = False):
        try:
            call = sync_website_models.spawn(force=force)
            return {
                "status":   "sync_initiated",
                "call_id":  call.object_id,
                "message":  "Model sync initiated in background.",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Upscaler ──────────────────────────────────────────────────────────────
    @api.get("/api/upscale/status")
    def api_upscale_status():
        return {
            "status":   "online",
            "engine":   "Real-ESRGAN / Neural Super-Resolution",
            "hardware": "Modal A10G",
            "models": [
                {"id": "realesrgan-x4plus", "name": "RealESRGAN x4+",  "category": "Photo Realism", "scale": 4},
                {"id": "realesrgan-anime",  "name": "RealESRGAN Anime", "category": "2D / Line Art", "scale": 4},
                {"id": "ultrasharp-4x",     "name": "4x UltraSharp",   "category": "Crisp Textures", "scale": 4},
                {"id": "dsp-fast",          "name": "Fast DSP",         "category": "Instant Resampling", "scale": 4},
            ],
            "supported_scales": [2, 4, 8],
            "timestamp": time.time(),
        }

    @api.post("/api/upscale")
    async def api_upscale(req: upscaler.UpscaleRequest):
        try:
            return await upscaler.Upscaler().upscale_image.remote.aio(
                image_b64=req.image_b64,
                scale=req.scale,
                model_name=req.model_name,
                denoise=req.denoise,
                sharpen=req.sharpen,
                face_enhance=req.face_enhance,
                output_format=req.output_format,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Image generation (txt2img) ────────────────────────────────────────────
    @api.post("/api/generate/txt2img")
    async def api_txt2img(body: dict):
        try:
            images: list[bytes] = await txt2img.Txt2Img().run.remote.aio(**body)
            return {"images": [base64.b64encode(b).decode() for b in images]}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Image-to-image ────────────────────────────────────────────────────────
    @api.post("/api/generate/img2img")
    async def api_img2img(body: dict):
        try:
            result = await img2img.Img2Img().run.remote.aio(**body)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Text-to-video ─────────────────────────────────────────────────────────
    @api.post("/api/generate/txt2vid")
    async def api_txt2vid(body: dict):
        try:
            result = await txt2vid.Txt2Vid().run.remote.aio(**body)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Image-to-video ────────────────────────────────────────────────────────
    @api.post("/api/generate/img2vid")
    async def api_img2vid(body: dict):
        try:
            result = await img2vid.Img2Vid().run.remote.aio(**body)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return api


_web_app = create_api()


# ─── Modal ASGI endpoint ──────────────────────────────────────────────────────
_router_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "pydantic", "requests", "Pillow", "numpy")
    .add_local_python_source("shared_app", "upscaler",
                             "txt2img", "img2img", "txt2vid", "img2vid")
)

@app.function(image=_router_image)
@modal.asgi_app()
def alphalive_api():
    """Primary AlphaLive production endpoint."""
    return _web_app


# ─── Local entrypoint: trigger model sync ────────────────────────────────────
@app.local_entrypoint()
def scan_and_download(force: bool = False):
    """
    Run locally:
        modal run deployment.py
        modal run deployment.py --force
    """
    print("🚀 Triggering remote volume sync for all checkpoints and LoRAs…")
    result = sync_website_models.remote(force=force)
    import json
    print("\n✅ Sync complete!")
    print(json.dumps(result, indent=2))
