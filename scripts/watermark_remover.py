import io
import os
import time
from pathlib import Path
from PIL import Image
import modal

from shared_app import app, CACHE_DIR, cache_volume

secrets = [modal.Secret.from_name("alphacore-secrets")]

wm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch", "torchvision", "Pillow", "huggingface_hub", "numpy", "fastapi")
    .add_local_python_source("shared_app")
)

@app.cls(
    image=wm_image,
    gpu="T4",
    volumes={CACHE_DIR: cache_volume},
    secrets=secrets,
    scaledown_window=300,
    timeout=180
)
class WatermarkRemover:
    @modal.enter()
    def load_model(self):
        import torch
        from huggingface_hub import hf_hub_download
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print("[WATERMARK REMOVER] Loading EngageApps/remove-watermarks-fast Swin2 model...")
        
        # Download or load model.ts from cached volume
        model_path = hf_hub_download(
            repo_id="EngageApps/remove-watermarks-fast",
            filename="model.ts",
            cache_dir=str(CACHE_DIR)
        )
        print(f"[WATERMARK REMOVER] Loading TorchScript model from {model_path}...")
        self.model = torch.jit.load(model_path, map_location=self.device)
        self.model.eval()
        print("[WATERMARK REMOVER] Dedicated watermark removal model successfully loaded on GPU!")

    @modal.method()
    def remove_watermark(self, image_bytes: bytes) -> bytes:
        """
        Removes watermarks and text overlays from an image without altering the person,
        face, hair, skin, lighting, or background structure.
        """
        import torch
        import torchvision.transforms as T
        
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        orig_width, orig_height = img.size
        
        # Convert to tensor [1, 3, H, W] in [0, 1] range
        img_tensor = T.ToTensor()(img).unsqueeze(0).to(self.device)
        
        # Inference with TorchScript pipeline
        with torch.no_grad():
            pred_t = self.model(img_tensor)
        
        # Convert back to PIL
        pred_img = T.ToPILImage()(pred_t.squeeze(0).cpu().clamp(0, 1))
        
        # Resize to original aspect ratio
        _, _, pipeline_size, _ = pred_t.shape
        if orig_width >= orig_height:
            out_w = min(orig_width, pipeline_size)
            out_h = int(orig_height * (out_w / orig_width))
        else:
            out_h = min(orig_height, pipeline_size)
            out_w = int(orig_width * (out_h / orig_height))
        
        pred_img = pred_img.resize((out_w, out_h), resample=Image.LANCZOS)
        
        out_buf = io.BytesIO()
        pred_img.save(out_buf, format="JPEG", quality=95)
        return out_buf.getvalue()

    @modal.fastapi_endpoint(method="POST")
    def web_clean(self, request: dict):
        import base64
        image_b64 = request.get("image", "")
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
        raw_bytes = base64.b64decode(image_b64)
        clean_bytes = self.remove_watermark(raw_bytes)
        return {"status": "success", "image_base64": base64.b64encode(clean_bytes).decode("utf-8")}
