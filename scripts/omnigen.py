# ---
# output-directory: "/tmp/omnigen-output"
# ---

import base64
import inspect
import io
import json
import os
import queue
import random
import re
import sys
import threading
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import modal

# Ensure scripts directory is in sys.path for local resolution of shared_app
scripts_dir = Path(__file__).parent.resolve()
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

try:
    from shared_app import app, CACHE_DIR, OUTPUTS_DIR, cache_volume, outputs_volume
except ImportError:
    from scripts.shared_app import app, CACHE_DIR, OUTPUTS_DIR, cache_volume, outputs_volume

# Normalize directory references
CACHE_DIR_STR = str(CACHE_DIR)
OUTPUTS_PATH = Path(OUTPUTS_DIR)

# --- CONTAINER IMAGE DEFINITION ---
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libsm6", "libxext6")
    .pip_install(
        "torch>=2.3.0",
        "torchvision",
        index_url="https://download.pytorch.org/whl/cu124",
    )
    .uv_pip_install(
        "accelerate>=0.33.0",
        "diffusers>=0.31.0",
        "einops",
        "fastapi[standard]",
        "huggingface-hub",
        "pillow",
        "python-multipart",
        "requests",
        "safetensors",
        "timm",
        "transformers>=4.45.0",
    )
    .run_commands(
        "pip install OmniGen || pip install git+https://github.com/VectorSpaceLab/OmniGen.git"
    )
    .env({
        "HF_HUB_ENABLE_HF_TRANSFER": "0",
        "HF_HOME": CACHE_DIR_STR,
        "TRANSFORMERS_CACHE": CACHE_DIR_STR,
    })
)

image = image.add_local_python_source("shared_app")


# --- IMAGE PROCESSING UTILITIES ---

def load_and_convert_image(item):
    """
    Converts various input formats (PIL Image, bytes, UploadFile, data URI, base64, URL, path)
    into a standard RGB PIL Image.
    """
    if item is None:
        return None

    from PIL import Image

    if isinstance(item, Image.Image):
        return item.convert("RGB")

    if isinstance(item, bytes):
        if len(item) == 0:
            return None
        try:
            return Image.open(BytesIO(item)).convert("RGB")
        except Exception:
            return None

    # FastAPI UploadFile or file-like object
    if hasattr(item, "file"):
        try:
            raw_bytes = item.file.read()
            if len(raw_bytes) == 0:
                return None
            return Image.open(BytesIO(raw_bytes)).convert("RGB")
        except Exception:
            return None

    if hasattr(item, "read"):
        try:
            raw_bytes = item.read()
            if len(raw_bytes) == 0:
                return None
            return Image.open(BytesIO(raw_bytes)).convert("RGB")
        except Exception:
            return None

    if isinstance(item, str):
        s = item.strip()
        if not s:
            return None

        # HTTP / HTTPS URL
        if s.startswith("http://") or s.startswith("https://"):
            try:
                import requests
                resp = requests.get(s, timeout=30)
                resp.raise_for_status()
                return Image.open(BytesIO(resp.content)).convert("RGB")
            except Exception:
                try:
                    req = urllib.request.Request(s, headers={"User-Agent": "AlphaCore-OmniGen/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as u:
                        return Image.open(BytesIO(u.read())).convert("RGB")
                except Exception:
                    return None

        # Data URL format: data:image/...;base64,...
        if s.startswith("data:image"):
            match = re.match(r"^data:image/[^;]+;base64,(.+)$", s, re.DOTALL)
            if match:
                s = match.group(1)

        # Raw base64 string
        try:
            decoded = base64.b64decode(s)
            return Image.open(BytesIO(decoded)).convert("RGB")
        except Exception:
            pass

        # Local filesystem path
        try:
            p = Path(s)
            if p.exists() and p.is_file():
                return Image.open(p).convert("RGB")
        except Exception:
            pass

    return None


def pil_to_bytes(pil_img, format="PNG") -> bytes:
    """Encodes a PIL Image into bytes."""
    with BytesIO() as buf:
        pil_img.save(buf, format=format)
        return buf.getvalue()


def pil_to_base64(pil_img, format="PNG") -> str:
    """Encodes a PIL Image into a base64 UTF-8 string."""
    return base64.b64encode(pil_to_bytes(pil_img, format=format)).decode("utf-8")


def format_omnigen_prompt(prompt: str, num_images: int) -> str:
    """
    Ensures prompt includes OmniGen image reference tokens <img><|image_1|></img> etc.
    If the prompt already contains explicit image tokens, preserves it verbatim.
    """
    clean_prompt = (prompt or "").strip()
    if num_images <= 0:
        return clean_prompt

    if "<img><|image_" in clean_prompt or "<|image_" in clean_prompt:
        return clean_prompt

    if num_images == 1:
        prefix = "<img><|image_1|></img>"
    elif num_images == 2:
        prefix = "<img><|image_1|></img> and <img><|image_2|></img>"
    else:
        prefix = "<img><|image_1|></img>, <img><|image_2|></img>, and <img><|image_3|></img>"

    return f"{prefix} {clean_prompt}" if clean_prompt else prefix


# --- ARCHITECT TIER MODAL CLASS ---
@app.cls(
    image=image,
    gpu="H100",
    volumes={CACHE_DIR: cache_volume, OUTPUTS_DIR: outputs_volume},
    secrets=[modal.Secret.from_name("alphacore-secrets")],
    scaledown_window=600,
    timeout=1200,
    memory=64 * 1024,
)
class OmniGen:
    """
    OmniGen Unified Multimodal Engine backend worker wrapping BAAI/OmniGen-v1.
    Supports text-to-image, single-image editing, and multi-image conditioning (up to 3 images).
    """

    @modal.enter()
    def enter(self):
        self.pipe = None
        self.model_loaded = False

    def _load_model(self):
        if self.model_loaded and self.pipe is not None:
            return

        import os
        import torch

        token = (
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or os.environ.get("HUGGINGFACE_TOKEN")
        )
        if token:
            os.environ["HF_TOKEN"] = token

        try:
            cache_volume.reload()
        except Exception as ve:
            print(f"[OmniGen] Volume reload note: {ve}")

        print(f"[OmniGen] Loading BAAI/OmniGen-v1 pipeline into VRAM from {CACHE_DIR_STR}...")

        try:
            from OmniGen import OmniGenPipeline
        except ImportError:
            try:
                from omnigen import OmniGenPipeline
            except ImportError:
                print("[OmniGen] Package missing, attempting dynamic install...")
                import subprocess
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "git+https://github.com/VectorSpaceLab/OmniGen.git"],
                    check=False,
                )
                from OmniGen import OmniGenPipeline

        self.pipe = OmniGenPipeline.from_pretrained(
            "BAAI/OmniGen-v1",
            cache_dir=CACHE_DIR_STR,
        )

        if hasattr(self.pipe, "to"):
            try:
                self.pipe.to("cuda")
            except Exception as e:
                print(f"[OmniGen] Note on pipe.to('cuda'): {e}")

        try:
            cache_volume.commit()
            print("[OmniGen] Persistent volume successfully synchronized.")
        except Exception as ce:
            print(f"[OmniGen] Volume commit note: {ce}")

        self.model_loaded = True
        print("✅ OmniGen-v1 pipeline loaded successfully!")

    @modal.method(is_generator=True)
    def run_stream(
        self,
        prompt: str,
        input_images: list[bytes] = [],
        height: int = 1024,
        width: int = 1024,
        num_inference_steps: int = 50,
        guidance_scale: float = 2.5,
        img_guidance_scale: float = 1.6,
        batch_size: int = 1,
        seed: int | None = None,
        separate_cfg_infer: bool = True,
        use_kv_cache: bool = True,
        offload_model: bool = False,
        max_input_image_size: int = 1024,
    ):
        """
        Executes streaming OmniGen generation with real-time SSE progress events.
        """
        import torch
        from PIL import Image

        self._load_model()

        # Dimension normalization (must be multiples of 16 for OmniGen patch sizing)
        target_h = max(128, int(round(height / 16) * 16))
        target_w = max(128, int(round(width / 16) * 16))

        # Decode up to 3 input conditioning images
        pil_images = []
        for raw_bytes in input_images[:3]:
            if raw_bytes:
                try:
                    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
                    pil_images.append(img)
                except Exception as e:
                    print(f"[OmniGen] Warning decoding input image: {e}")

        effective_prompt = format_omnigen_prompt(prompt, len(pil_images))
        print(f"[OmniGen] Prompt: '{effective_prompt}' | Conditioning images: {len(pil_images)} | Dims: ({target_w}x{target_h}) | Steps: {num_inference_steps}")

        q = queue.Queue()

        def generate_task():
            all_images_b64 = []
            try:
                images_completed = 0
                while images_completed < batch_size:
                    current_seed = (seed + images_completed) if seed is not None else random.randint(0, 2147483647)
                    generator = torch.Generator(device="cuda").manual_seed(current_seed) if torch.cuda.is_available() else None

                    q.put({
                        "step": 1,
                        "max_steps": num_inference_steps,
                        "images_completed": images_completed,
                        "total_images": batch_size,
                        "status": f"Generating image {images_completed + 1} of {batch_size}",
                    })

                    # Dynamically inspect call parameters for broad OmniGen version compatibility
                    pipe_params = inspect.signature(self.pipe.__call__).parameters
                    call_kwargs = {
                        "prompt": effective_prompt,
                        "input_images": pil_images if pil_images else None,
                        "height": target_h,
                        "width": target_w,
                        "num_inference_steps": num_inference_steps,
                        "guidance_scale": guidance_scale,
                        "img_guidance_scale": img_guidance_scale,
                    }

                    if "separate_cfg_infer" in pipe_params:
                        call_kwargs["separate_cfg_infer"] = separate_cfg_infer
                    if "use_kv_cache" in pipe_params:
                        call_kwargs["use_kv_cache"] = use_kv_cache
                    if "offload_model" in pipe_params:
                        call_kwargs["offload_model"] = offload_model
                    if "max_input_image_size" in pipe_params:
                        call_kwargs["max_input_image_size"] = max_input_image_size
                    if "generator" in pipe_params and generator is not None:
                        call_kwargs["generator"] = generator
                    if "seed" in pipe_params:
                        call_kwargs["seed"] = current_seed

                    # Run inference
                    output_imgs = self.pipe(**call_kwargs)
                    if not isinstance(output_imgs, list):
                        output_imgs = [output_imgs]

                    chunk_b64 = []
                    for img in output_imgs:
                        b64 = pil_to_base64(img, format="PNG")
                        chunk_b64.append(b64)
                        all_images_b64.append(b64)

                    images_completed += len(output_imgs)
                    q.put({
                        "step": num_inference_steps,
                        "max_steps": num_inference_steps,
                        "image_b64_partial": chunk_b64,
                        "images_completed": images_completed,
                        "total_images": batch_size,
                    })

                q.put({"image_b64": all_images_b64})
            except Exception as ex:
                import traceback
                traceback.print_exc()
                q.put({"error": str(ex)})

        threading.Thread(target=generate_task, daemon=True).start()

        while True:
            msg = q.get()
            yield msg
            if "image_b64" in msg or "error" in msg:
                break

    @modal.method()
    def inference(
        self,
        prompt: str,
        input_images: list[bytes] = [],
        height: int = 1024,
        width: int = 1024,
        num_inference_steps: int = 50,
        guidance_scale: float = 2.5,
        img_guidance_scale: float = 1.6,
        batch_size: int = 1,
        seed: int | None = None,
        separate_cfg_infer: bool = True,
        use_kv_cache: bool = True,
        offload_model: bool = False,
    ) -> list[bytes]:
        """
        Synchronous inference endpoint returning raw image bytes.
        """
        msgs = list(self.run_stream.local(
            prompt=prompt,
            input_images=input_images,
            height=height,
            width=width,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            img_guidance_scale=img_guidance_scale,
            batch_size=batch_size,
            seed=seed,
            separate_cfg_infer=separate_cfg_infer,
            use_kv_cache=use_kv_cache,
            offload_model=offload_model,
        ))

        final_msg = msgs[-1]
        if "error" in final_msg:
            raise RuntimeError(final_msg["error"])

        return [base64.b64decode(b64) for b64 in final_msg["image_b64"]]

    @modal.asgi_app()
    def web_omnigen(self):
        """
        FastAPI Web Application exposing REST and SSE streaming endpoints.
        """
        import fastapi
        from fastapi import File, Form, Request, Response, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, StreamingResponse

        web_app = fastapi.FastAPI(title="AlphaCore OmniGen Service", version="1.0.0")
        web_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        async def parse_request_payload(request: Request):
            """
            Extracts generation parameters and up to 3 input images from either
            JSON or multipart form submissions.
            """
            content_type = request.headers.get("content-type", "").lower()
            raw_images = []
            params = {}

            if "application/json" in content_type:
                try:
                    params = await request.json()
                except Exception:
                    params = {}

                # Extract images list
                for key in ["images", "input_images"]:
                    val = params.get(key)
                    if isinstance(val, list):
                        for item in val:
                            if item is not None and item != "":
                                raw_images.append(item)

                # Extract individual image slots
                for key in ["image", "image1", "image2", "image3", "ref1", "ref2"]:
                    val = params.get(key)
                    if val is not None and val != "" and val not in raw_images:
                        raw_images.append(val)
            else:
                try:
                    form = await request.form()
                    params = dict(form)

                    # Extract form file uploads or string values
                    for key in ["image", "image1", "image2", "image3", "ref1", "ref2"]:
                        val = form.get(key)
                        if val is not None and val != "":
                            raw_images.append(val)

                    if hasattr(form, "getlist"):
                        for item in form.getlist("images"):
                            if item is not None and item != "" and item not in raw_images:
                                raw_images.append(item)
                        for item in form.getlist("input_images"):
                            if item is not None and item != "" and item not in raw_images:
                                raw_images.append(item)
                except Exception:
                    params = {}

            # Convert extracted image items into raw bytes
            valid_image_bytes = []
            for item in raw_images[:3]:
                pil_img = load_and_convert_image(item)
                if pil_img is not None:
                    valid_image_bytes.append(pil_to_bytes(pil_img, format="PNG"))

            # Parse parameters with sensible defaults
            prompt = str(params.get("prompt") or params.get("instruction") or "A detailed realistic rendering").strip()
            negative_prompt = str(params.get("negative_prompt", "")).strip()

            try:
                height = int(params.get("height", 1024))
            except Exception:
                height = 1024

            try:
                width = int(params.get("width", 1024))
            except Exception:
                width = 1024

            try:
                steps = int(params.get("num_inference_steps") or params.get("steps", 50))
            except Exception:
                steps = 50

            try:
                guidance_scale = float(
                    params.get("guidance_scale")
                    or params.get("cfg")
                    or params.get("true_cfg_scale", 2.5)
                )
            except Exception:
                guidance_scale = 2.5

            try:
                img_guidance_scale = float(params.get("img_guidance_scale") or params.get("img_cfg", 1.6))
            except Exception:
                img_guidance_scale = 1.6

            try:
                batch_size = max(1, min(4, int(params.get("batch_size") or params.get("n", 1))))
            except Exception:
                batch_size = 1

            try:
                raw_seed = params.get("seed")
                seed = None if raw_seed in [None, "", -1, "-1"] else int(raw_seed)
            except Exception:
                seed = None

            return {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "input_images_bytes": valid_image_bytes,
                "height": height,
                "width": width,
                "num_inference_steps": steps,
                "guidance_scale": guidance_scale,
                "img_guidance_scale": img_guidance_scale,
                "batch_size": batch_size,
                "seed": seed,
            }

        @web_app.post("/stream")
        async def endpoint_stream(request: Request):
            """
            SSE streaming endpoint compatible with scripts/img2img.py protocol.
            Accepts multipart Form or JSON with up to 3 input images.
            """
            p = await parse_request_payload(request)

            def event_generator():
                for msg in self.run_stream.local(
                    prompt=p["prompt"],
                    input_images=p["input_images_bytes"],
                    height=p["height"],
                    width=p["width"],
                    num_inference_steps=p["num_inference_steps"],
                    guidance_scale=p["guidance_scale"],
                    img_guidance_scale=p["img_guidance_scale"],
                    batch_size=p["batch_size"],
                    seed=p["seed"],
                ):
                    yield f"data: {json.dumps(msg)}\n\n"

                    # Save finished outputs to persistent volume
                    if "image_b64" in msg:
                        out_dir = OUTPUTS_PATH / "omnigen"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        for idx, b64 in enumerate(msg["image_b64"]):
                            raw_out = base64.b64decode(b64)
                            filename = f"omnigen_{int(time.time() * 1000)}_{idx}.png"
                            (out_dir / filename).write_bytes(raw_out)
                        try:
                            outputs_volume.commit()
                        except Exception as ce:
                            print(f"[OmniGen] Volume commit note: {ce}")

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @web_app.post("/generate")
        async def endpoint_generate(request: Request):
            """
            JSON endpoint returning base64 data URLs, raw base64, and saved persistent file paths.
            """
            p = await parse_request_payload(request)

            output_bytes_list = self.inference.local(
                prompt=p["prompt"],
                input_images=p["input_images_bytes"],
                height=p["height"],
                width=p["width"],
                num_inference_steps=p["num_inference_steps"],
                guidance_scale=p["guidance_scale"],
                img_guidance_scale=p["img_guidance_scale"],
                batch_size=p["batch_size"],
                seed=p["seed"],
            )

            out_dir = OUTPUTS_PATH / "omnigen"
            out_dir.mkdir(parents=True, exist_ok=True)

            data_urls = []
            b64_list = []
            saved_paths = []

            for idx, raw_bytes in enumerate(output_bytes_list):
                b64_str = base64.b64encode(raw_bytes).decode("utf-8")
                data_url = f"data:image/png;base64,{b64_str}"
                filename = f"omnigen_{int(time.time() * 1000)}_{idx}.png"
                out_path = out_dir / filename
                out_path.write_bytes(raw_bytes)

                b64_list.append(b64_str)
                data_urls.append(data_url)
                saved_paths.append(str(out_path))

            try:
                if hasattr(outputs_volume, "commit"):
                    if hasattr(outputs_volume.commit, "aio"):
                        await outputs_volume.commit.aio()
                    else:
                        outputs_volume.commit()
            except Exception as ce:
                print(f"[OmniGen] Volume commit note: {ce}")

            return JSONResponse({
                "status": "success",
                "prompt": p["prompt"],
                "images": data_urls,
                "image_url": data_urls[0] if data_urls else "",
                "image_b64": b64_list[0] if b64_list else "",
                "file_path": saved_paths[0] if saved_paths else "",
                "file_paths": saved_paths,
                "data": [
                    {
                        "b64_json": b64,
                        "url": d_url,
                        "file_path": f_path,
                    }
                    for b64, d_url, f_path in zip(b64_list, data_urls, saved_paths)
                ],
            })

        @web_app.post("/")
        async def endpoint_root(request: Request):
            """
            Root POST endpoint. Returns raw PNG image bytes by default, or JSON if requested.
            """
            accept = request.headers.get("accept", "").lower()
            if "application/json" in accept:
                return await endpoint_generate(request)

            p = await parse_request_payload(request)
            output_bytes_list = self.inference.local(
                prompt=p["prompt"],
                input_images=p["input_images_bytes"],
                height=p["height"],
                width=p["width"],
                num_inference_steps=p["num_inference_steps"],
                guidance_scale=p["guidance_scale"],
                img_guidance_scale=p["img_guidance_scale"],
                batch_size=p["batch_size"],
                seed=p["seed"],
            )

            # Persist to disk
            out_dir = OUTPUTS_PATH / "omnigen"
            out_dir.mkdir(parents=True, exist_ok=True)
            for idx, raw_bytes in enumerate(output_bytes_list):
                filename = f"omnigen_{int(time.time() * 1000)}_{idx}.png"
                (out_dir / filename).write_bytes(raw_bytes)
            try:
                outputs_volume.commit()
            except Exception:
                pass

            return Response(content=output_bytes_list[0], media_type="image/png")

        @web_app.get("/health")
        def endpoint_health():
            return {
                "status": "ok",
                "service": "omnigen",
                "model": "BAAI/OmniGen-v1",
                "tier": "architect",
            }

        return web_app


# --- LOCAL ENTRYPOINT ---
@app.local_entrypoint()
def main(
    prompt: str = "A futuristic cyberpunk android portrait glowing with neon circuitry",
    output_path: str = "/tmp/omnigen-output/output.png",
    steps: int = 30,
):
    """
    CLI entrypoint for local execution and quick testing via Modal CLI.
    """
    print(f"🚀 Invoking OmniGen with prompt: '{prompt}'")
    out_bytes_list = OmniGen().inference.remote(
        prompt=prompt,
        input_images=[],
        num_inference_steps=steps,
    )
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(out_bytes_list[0])
    print(f"✅ Generated image saved to {p.resolve()}")
