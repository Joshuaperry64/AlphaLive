import io
import base64
from PIL import Image
import modal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared_app import app

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install(
        "controlnet-aux==0.0.9",
        "opencv-python-headless",
        "Pillow",
        "fastapi[standard]",
        "pydantic",
        "torch==2.5.1",
        "torchvision==0.20.1"
    )
    .add_local_python_source("shared_app")
)

class PreprocessRequest(BaseModel):
    image_b64: str
    processor_type: str  # 'canny', 'openpose', 'depth'

@app.cls(image=image, gpu="A10G")
class ControlNet:
    @modal.enter()
    def setup(self):
        self.processors = {}
        
    def _get_processor(self, ptype):
        if ptype == "openpose":
            if "openpose" not in self.processors:
                from controlnet_aux import OpenposeDetector
                self.processors["openpose"] = OpenposeDetector.from_pretrained("lllyasviel/ControlNet")
            return self.processors["openpose"]
        elif ptype == "depth":
            if "depth" not in self.processors:
                from controlnet_aux import MidasDetector
                self.processors["depth"] = MidasDetector.from_pretrained("lllyasviel/Annotators")
            return self.processors["depth"]
        return None

    @modal.method()
    def process(self, image_bytes: bytes, ptype: str) -> bytes:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        
        if ptype == "canny":
            import cv2
            import numpy as np
            img_np = np.array(img)
            edges = cv2.Canny(img_np, 100, 200)
            # Convert 1 channel to 3 channels for ControlNet
            img_out = Image.fromarray(edges).convert("RGB")
        else:
            processor = self._get_processor(ptype)
            if not processor:
                raise ValueError(f"Unknown processor type: {ptype}")
            img_out = processor(img)
            
        out_bytes = io.BytesIO()
        img_out.save(out_bytes, format="PNG")
        return out_bytes.getvalue()
        
    @modal.fastapi_endpoint(method="POST")
    def web_process(self, req: PreprocessRequest):
        import base64
        # Remove data URI prefix if present
        b64_data = req.image_b64
        if "," in b64_data:
            b64_data = b64_data.split(",")[1]
            
        image_data = base64.b64decode(b64_data)
        out_bytes = self.process.local(image_data, req.processor_type)
        out_b64 = base64.b64encode(out_bytes).decode('utf-8')
        return {"image_b64": f"data:image/png;base64,{out_b64}"}

