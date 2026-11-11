"""
voice_cloner.py - RVC v2 Voice Cloning Backend
Modal GPU pipeline for training, refining, and managing voice profiles.
"""

import os
import sys
import json
import subprocess
import shutil
import tempfile
import io
import modal
from pathlib import Path

# ─────────────────────────────────────────────
# Modal Infrastructure & Image Definition
# ─────────────────────────────────────────────

volume = modal.Volume.from_name("rvc-models-volume", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "wget", "build-essential")
    .run_commands("git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git /rvc")
    .run_commands("cd /rvc && git checkout 9f2f0559e6932c10c48642d404e7d2e771d9db43")
    .workdir("/rvc")
    .run_commands("python -m pip install 'pip<24.1'")
    .pip_install("torch==2.1.2", "torchaudio==2.1.2", "torchvision==0.16.2", index_url="https://download.pytorch.org/whl/cu121")
    .run_commands("cd /rvc && pip install -r requirements.txt")
    .pip_install("gitpython", "soundfile")
    .run_commands(
        "wget -q https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt -P /rvc/assets/hubert/",
        "wget -q https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt -P /rvc/assets/rmvpe/",
        "wget -q https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/pretrained_v2/f0G48k.pth -P /rvc/assets/pretrained_v2/",
        "wget -q https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/pretrained_v2/f0D48k.pth -P /rvc/assets/pretrained_v2/"
    )
    .add_local_python_source("shared_app")
)

storage_image = (
    modal.Image.debian_slim(python_version="3.10")
    .add_local_python_source("shared_app")
)

# Ensure the /rvc directory is in Python path for RVC modules and import shared_app
sys.path.insert(0, "/rvc")
try:
    from shared_app import app
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from shared_app import app

# ─────────────────────────────────────────────
# Core Inference Helper
# ─────────────────────────────────────────────

def _execute_rvc_inference(profile_name: str, audio_bytes: bytes, pitch_shift: int = 0) -> dict:
    """
    Core RVC file-to-file voice conversion.
    Accepts raw audio bytes (wav/mp3), returns converted wav bytes.
    """
    try:
        volume.reload()
    except Exception:
        pass

    sys.path.insert(0, "/rvc")

    import soundfile as sf
    from configs.config import Config
    from infer.modules.vc.modules import VC

    model_dir = Path(f"/mnt/rvc_data/models/{profile_name}")
    pth_files = list(model_dir.glob("*.pth")) if model_dir.exists() else []

    # Broad search across volume if not in standard directory
    if not pth_files:
        base = Path("/mnt/rvc_data")
        if base.exists():
            for f in base.rglob("*.pth"):
                if profile_name.lower() in f.stem.lower() or profile_name.lower() in str(f.parent).lower():
                    pth_files.append(f)
                    break

    if not pth_files:
        return {
            "status": "error",
            "message": f"No trained model found for profile '{profile_name}'. Please train this profile first."
        }

    config = Config()
    vc_engine = VC(config)
    vc_engine.get_vc(str(pth_files[0]), 0.5, 0.33)

    # Write input audio to disk for processing
    audio_io = io.BytesIO(audio_bytes)
    audio_data, in_sr = sf.read(audio_io)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        sf.write(tf.name, audio_data, in_sr)
        input_path = tf.name

    index_files = list(model_dir.glob("*.index")) if model_dir.exists() else []
    if not index_files:
        index_files = list(Path(f"/rvc/logs/{profile_name}").rglob("*.index"))
    index_path = str(index_files[0]) if index_files else ""

    try:
        _, wav_opt = vc_engine.vc_single(
            0, input_path, pitch_shift, None,
            "rmvpe", index_path, None,
            0.75, 3, 0, 0.25, 0.33
        )

        if wav_opt is None:
            return {"status": "error", "message": "Inference returned no output."}

        out_sr, out_data = wav_opt
        out_io = io.BytesIO()
        sf.write(out_io, out_data, out_sr, format="WAV")
        return {"status": "success", "audio_bytes": out_io.getvalue(), "sample_rate": out_sr}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        Path(input_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Storage & Model Management Class
# ─────────────────────────────────────────────

@app.cls(image=storage_image, timeout=300, volumes={"/mnt/rvc_data": volume})
class VoiceCloner_Storage:
    @modal.method()
    def upload_audio_file(self, profile_name: str, filename: str, file_bytes: bytes):
        """Uploads a single audio file to the Modal volume for training."""
        dataset_dir = Path(f"/mnt/rvc_data/datasets/{profile_name}")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        with open(dataset_dir / filename, "wb") as f:
            f.write(file_bytes)
        volume.commit()

    @modal.method()
    def list_volume_contents(self) -> dict:
        """Lists everything stored in the Modal persistent volume."""
        try:
            volume.reload()
        except Exception:
            pass

        tree = {}
        base = Path("/mnt/rvc_data")
        if not base.exists():
            return {"error": "Volume mount not found"}
        for f in sorted(base.rglob("*")):
            rel = str(f.relative_to(base))
            tree[rel] = {"is_dir": f.is_dir(), "size_kb": round(f.stat().st_size / 1024, 1) if f.is_file() else 0}
        return tree

    @modal.method()
    def download_model_assets(self, profile_name: str) -> dict:
        """Returns trained model .pth and .index files as bytes."""
        try:
            volume.reload()
        except Exception:
            pass

        files = {}
        base = Path("/mnt/rvc_data")
        if base.exists():
            for f in base.rglob("*"):
                if f.is_file() and f.suffix in (".pth", ".index"):
                    if profile_name.lower() in f.stem.lower() or profile_name.lower() in str(f.parent).lower():
                        with open(f, "rb") as fp:
                            files[f.name] = fp.read()

        if not files:
            listing = [str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()] if base.exists() else []
            return {
                "status": "error",
                "message": f"No model files found for '{profile_name}' anywhere on volume.",
                "volume_contents": listing
            }

        return {"status": "success", "files": files}


# ─────────────────────────────────────────────
# GPU Inference & Training Classes
# ─────────────────────────────────────────────

@app.cls(image=image, gpu="A10G", timeout=3600, volumes={"/mnt/rvc_data": volume})
class VoiceCloner:
    @modal.method()
    def infer_audio_modal(self, profile_name: str, audio_bytes: bytes, pitch_shift: int = 0) -> dict:
        """Architect tier voice conversion on A10G GPU."""
        return _execute_rvc_inference(profile_name, audio_bytes, pitch_shift)

    @modal.method()
    def process_audio_samples(self, profile_name: str):
        """RVC v2 Training Pipeline — runs on Modal A10G GPU."""
        try:
            volume.reload()
        except Exception:
            pass

        dataset_dir = f"/mnt/rvc_data/datasets/{profile_name}"
        if not os.path.exists(dataset_dir):
            return {"status": "error", "message": f"Dataset directory not found for '{profile_name}'"}

        audio_files = []
        for ext in ["*.mp3", "*.m4a", "*.wav"]:
            audio_files.extend(list(Path(dataset_dir).rglob(ext)))
        
        print(f"[*] Found {len(audio_files)} audio file(s).")
        if not audio_files:
            return {"status": "error", "message": "No audio files found in the dataset directory."}

        total_seconds = 0.0
        for f in audio_files:
            try:
                cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(f)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                total_seconds += float(res.stdout.strip())
            except Exception:
                pass
            
        if total_seconds < 60:
            target_epochs = 200
        elif total_seconds < 180:
            target_epochs = 150
        elif total_seconds < 600:
            target_epochs = 100
        else:
            target_epochs = 50
        
        save_epoch = min(50, max(10, target_epochs // 2))
        print(f"[*] Total duration: {total_seconds:.2f}s | Target Epochs: {target_epochs}")

        exp_dir = f"/rvc/logs/{profile_name}"
        os.makedirs(exp_dir, exist_ok=True)

        logs = "[*] Preprocessing audio (resample to 48k)...\n"
        try:
            res1 = subprocess.run(
                ["python", "infer/modules/train/preprocess.py", dataset_dir, "48000", "2", exp_dir, "False", "3.0"],
                check=True, capture_output=True, text=True
            )
            logs += f"[*] preprocess.py stdout:\n{res1.stdout}\n"
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": f"Preprocess failed:\n{e.stderr}", "logs": logs}

        logs += "[*] Extracting pitch (RMVPE) and HuBERT features...\n"
        try:
            res2 = subprocess.run(
                ["python", "infer/modules/train/extract/extract_f0_print.py", exp_dir, "2", "rmvpe"],
                check=True, capture_output=True, text=True
            )
            logs += f"[*] extract_f0 stdout:\n{res2.stdout}\n"
        
            res3 = subprocess.run(
                ["python", "infer/modules/train/extract_feature_print.py", "cuda:0", "1", "0", "0", exp_dir, "v2", "True"],
                check=True, capture_output=True, text=True
            )
            logs += f"[*] extract_feature stdout:\n{res3.stdout}\n"
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": f"Feature extraction failed:\n{e.stderr}", "logs": logs}
        
        logs += "[*] Generating filelist.txt for training...\n"
        try:
            opt = []
            gt_wavs_dir = f"{exp_dir}/0_gt_wavs"
            co256_dir = f"{exp_dir}/3_feature768"
            f0_dir = f"{exp_dir}/2a_f0"
            f0nsf_dir = f"{exp_dir}/2b-f0bak"
        
            for npy_file in os.listdir(co256_dir):
                name = npy_file.split(".")[0]
                if os.path.exists(f"{gt_wavs_dir}/{name}.wav") and os.path.exists(f"{f0_dir}/{name}.wav.npy") and os.path.exists(f"{f0nsf_dir}/{name}.wav.npy"):
                    line = f"{gt_wavs_dir}/{name}.wav|{co256_dir}/{name}.npy|{f0_dir}/{name}.wav.npy|{f0nsf_dir}/{name}.wav.npy|0"
                    opt.append(line)
        
            with open(f"{exp_dir}/filelist.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(opt))
            
            os.makedirs(f"{exp_dir}/mute", exist_ok=True)
            with open(f"{exp_dir}/mute/filelist.txt", "w", encoding="utf-8") as f:
                pass
            
            logs += f"[*] Generated filelist with {len(opt)} valid samples.\n"
        except Exception as e:
            return {"status": "error", "message": f"Filelist generation failed:\n{e}", "logs": logs}

        logs += f"[*] Starting RVC v2 model training ({target_epochs} epochs)...\n"
        try:
            shutil.copy("/rvc/configs/v2/48k.json", f"{exp_dir}/config.json")
            res = subprocess.run([
                "python", "infer/modules/train/train.py",
                "-e", profile_name,
                "-sr", "48k",
                "-f0", "1",
                "-bs", "4",
                "-te", str(target_epochs),
                "-se", str(save_epoch),
                "-pg", "/rvc/assets/pretrained_v2/f0G48k.pth",
                "-pd", "/rvc/assets/pretrained_v2/f0D48k.pth",
                "-l", "0",
                "-c", "0",
                "-sw", "1",
                "-v", "v2"
            ], capture_output=True, text=True)
        
            logs += f"[*] train.py stdout:\n{res.stdout}\n"
            if res.stderr:
                logs += f"[!] train.py stderr:\n{res.stderr}\n"
            
            if res.returncode != 0:
                return {"status": "error", "message": "Model training failed.", "logs": logs}
            
        except Exception as e:
            return {"status": "error", "message": f"Model training crash: {e}", "logs": logs}

        print("[*] Building FAISS retrieval index...")
        try:
            subprocess.run(
                ["python", "infer/modules/train/train_index.py", profile_name, "v2"],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"[!] Index build warning: {e.stderr}")

        dest_dir = Path(f"/mnt/rvc_data/models/{profile_name}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved = []

        for f in Path("/rvc").rglob("*"):
            if f.is_file() and f.suffix in [".pth", ".index"]:
                if profile_name.lower() in f.stem.lower() or profile_name.lower() in str(f.parent).lower():
                    if "pretrained" not in str(f).lower() and "rmvpe" not in str(f).lower() and "hubert" not in str(f).lower():
                        target = dest_dir / f.name
                        if not target.exists():
                            shutil.copy(str(f), str(target))
                            saved.append(f.name)
                            logs += f"[*] Saved artifact: {f.name}\n"

        volume.commit()
        logs += f"[*] Training complete. Persisted {len(saved)} artifact(s).\n"
        return {"status": "success", "processed_files": len(audio_files), "logs": logs}
