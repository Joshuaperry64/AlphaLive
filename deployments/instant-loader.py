import modal
import os
import requests
import time

app = modal.App("instant-loader")
cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)

image = modal.Image.debian_slim(python_version="3.12").pip_install("requests", "tqdm")

LORAS = {
    "epiCRealismHelper.safetensors": "118945",
    "cunny.safetensors": "286911",
    "FlatTop.safetensors": "1109661",
    "BJ.safetensors": "1312598",
    "Cowgirl.safetensors": "472474",
    "Missionary.safetensors": "144818",
    "SpyCam.safetensors": "545059",
}

CHECKPOINTS = {
    "0x7RealisticFreedom_omegaSDXL.safetensors": "1461059",
    "juggernautXL_ragnarok.safetensors": "1759168",
    "cyberrealisticXL_desireV30.safetensors": "2765942",
    "unholyDesireMixSinister_v80.safetensors": "2824082",
    "dreamshaperXL_alpha2Xl10.safetensors": "128713",
    "lustifyNSFWCheckpoint_zenithV9.safetensors": "3112728",
    "epicrealismXL_pureFix.safetensors": "2514955",
}

def get_civitai_secrets():
    secrets = []
    try: secrets.append(modal.Secret.from_name("civitai-secret"))
    except: pass
    return secrets

@app.function(image=image, volumes={"/hf-hub-cache": cache_volume}, secrets=get_civitai_secrets(), timeout=3600)
def sync_assets():
    from tqdm import tqdm
    api_key = os.environ.get("CIVITAI_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    # Ensure directories exist
    os.makedirs("/hf-hub-cache/checkpoints", exist_ok=True)
    os.makedirs("/hf-hub-cache/loras", exist_ok=True)
    
    def download_file(version_id, dest_path, category):
        print(f"[{category.upper()}] Checking {os.path.basename(dest_path)}...")
        if os.path.exists(dest_path):
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            if size_mb > 1.0: # Check if it's not a corrupted 0kb file
                print(f"  -> Already exists ({size_mb:.2f} MB). Skipping.")
                return
        
        print(f"  -> Missing! Fetching metadata for Version ID {version_id}...")
        meta_url = f"https://civitai.com/api/v1/model-versions/{version_id}"
        meta = requests.get(meta_url, headers=headers, timeout=30)
        
        if meta.status_code != 200:
            print(f"  -> ERROR: CivitAI API returned {meta.status_code}: {meta.text}")
            return
            
        files = meta.json().get("files", [])
        primary = next((f for f in files if f.get("primary", False)), files[0] if files else None)
        
        if not primary:
            print(f"  -> ERROR: No downloadable files found for {version_id}")
            return
            
        download_url = primary["downloadUrl"]
        if api_key:
            download_url += f"&token={api_key}" if "?" in download_url else f"?token={api_key}"
            
        print(f"  -> Downloading from CivitAI ({primary.get('sizeKB', 0)/1024:.2f} MB)...")
        
        with requests.get(download_url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            with open(dest_path + ".tmp", 'wb') as f, tqdm(
                desc=os.path.basename(dest_path),
                total=total_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
                    
        os.rename(dest_path + ".tmp", dest_path)
        print(f"  -> Successfully saved to {dest_path}")
        cache_volume.commit() # Commit to remote volume after each successful download
        time.sleep(1) # Small delay to respect API rate limits

    print("========================================")
    print("SYNCING LORAS")
    print("========================================")
    for filename, version_id in LORAS.items():
        download_file(version_id, f"/hf-hub-cache/loras/{filename}", "LORA")
        
    print("\n========================================")
    print("SYNCING CHECKPOINTS")
    print("========================================")
    for filename, version_id in CHECKPOINTS.items():
        download_file(version_id, f"/hf-hub-cache/checkpoints/{filename}", "CHECKPOINT")
        
    print("\nSYNC COMPLETE! ALL ASSETS LOADED IN VOLUME.")

@app.local_entrypoint()
def main():
    print("Starting Instant Loader to sync Volume...")
    sync_assets.remote()
