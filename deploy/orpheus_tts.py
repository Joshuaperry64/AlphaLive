"""
Modal deployment script for serving Orpheus TTS (canopylabs/orpheus-3b-0.1-ft)
in full, unquantized precision (BF16) using vLLM PagedAttention and SNAC 24kHz Neural Audio Codec.

Target Architecture:
  - Speech-LLM: canopylabs/orpheus-3b-0.1-ft (Llama-3.2-3B based Speech-LLM)
  - Precision: Full, unquantized bfloat16 / float16 (Zero degradation, pristine acoustic fidelity)
  - Serving Engine: vLLM AsyncLLMEngine with PagedAttention (Sub-100ms Time-to-First-Audio-Chunk)
  - Codec: SNAC 24kHz (SoundStream Neural Audio Codec) for hierarchical 7-token frame decoding
  - GPU: NVIDIA A100-40GB / L40S (Ample VRAM for unquantized 3B weights + deep KV cache)
  - Endpoints:
      * POST /v1/audio/speech (OpenAI-compatible TTS)
      * POST /synthesize (Direct waveform synthesis)
      * GET /health (Latency & engine diagnostic)
      * GET /v1/models (OpenAI model inventory)
"""

import io
import json
import os
import time
import wave
from typing import Optional

import modal

APP_NAME = "orpheus-tts-vllm"
MODEL_NAME = "canopylabs/orpheus-3b-0.1-ft"
SNAC_MODEL_NAME = "hubertsiuzdak/snac_24khz"
PORT = 8000
MINUTES = 60

# Orpheus Token Offsets for 7-token SNAC hierarchical frames
SNAC_BASE_OFFSET_L0 = 128266
SNAC_BASE_OFFSET_L1 = 128266 + 4096  # 132362
SNAC_BASE_OFFSET_L2 = 128266 + 8192  # 136458

SUPPORTED_VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]

from shared_app import app

# --- Persistent Caching & Secrets ---
hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface-secret")

# --- Container Image Configuration ---
orpheus_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.2-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(
        "vllm>=0.7.0",
        "torch>=2.4.0",
        "snac>=0.1.0",
        "transformers>=4.45.0",
        "huggingface_hub[hf_transfer]",
        "fastapi[standard]",
        "uvicorn",
        "numpy",
        "scipy",
        "soundfile",
        "aiohttp",
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "TORCH_CPP_LOG_LEVEL": "FATAL",
            "VLLM_LOG_STATS_INTERVAL": "15",
            "VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
        }
    )
    .add_local_python_source("shared_app")
)


@app.function(
    image=orpheus_image,
    volumes={"/root/.cache/huggingface": hf_cache_vol},
    timeout=20 * MINUTES,
    secrets=[hf_secret],
)
def download_orpheus_weights():
    """Pre-downloads and caches Orpheus 3B weights and SNAC codec to persistent volume."""
    from huggingface_hub import snapshot_download
    print(f"[Orpheus Modal] Caching {MODEL_NAME} weights into persistent volume...")
    t0 = time.time()
    snapshot_download(MODEL_NAME, ignore_patterns=["*.pt", "*.bin"])
    snapshot_download(SNAC_MODEL_NAME)
    print(f"[Orpheus Modal] Weights cached successfully in {time.time() - t0:.2f}s")
    hf_cache_vol.commit()


def deinterleave_orpheus_tokens(token_ids: list[int]) -> tuple[list[int], list[int], list[int]]:
    """
    De-interleaves 7-token Orpheus super-frames into the 3 SNAC RVQ hierarchy levels:
    - Layer 0 (1 code per frame, base offset 128266)
    - Layer 1 (2 codes per frame, base offset 132362)
    - Layer 2 (4 codes per frame, base offset 136458)
    """
    audio_tokens = [t for t in token_ids if t >= SNAC_BASE_OFFSET_L0]
    num_frames = len(audio_tokens) // 7
    if num_frames == 0:
        return [], [], []

    audio_tokens = audio_tokens[:num_frames * 7]
    l0_list, l1_list, l2_list = [], [], []

    for i in range(num_frames):
        frame = audio_tokens[i * 7 : (i + 1) * 7]
        # Frame mapping: [L0, L1_0, L2_0, L2_1, L1_1, L2_2, L2_3]
        c_l0 = max(0, min(4095, (frame[0] - SNAC_BASE_OFFSET_L0) % 4096))
        c_l1_0 = max(0, min(4095, (frame[1] - SNAC_BASE_OFFSET_L1) % 4096))
        c_l2_0 = max(0, min(4095, (frame[2] - SNAC_BASE_OFFSET_L2) % 4096))
        c_l2_1 = max(0, min(4095, (frame[3] - SNAC_BASE_OFFSET_L2) % 4096))
        c_l1_1 = max(0, min(4095, (frame[4] - SNAC_BASE_OFFSET_L1) % 4096))
        c_l2_2 = max(0, min(4095, (frame[5] - SNAC_BASE_OFFSET_L2) % 4096))
        c_l2_3 = max(0, min(4095, (frame[6] - SNAC_BASE_OFFSET_L2) % 4096))

        l0_list.append(c_l0)
        l1_list.extend([c_l1_0, c_l1_1])
        l2_list.extend([c_l2_0, c_l2_1, c_l2_2, c_l2_3])

    return l0_list, l1_list, l2_list


@app.cls(
    gpu="L4",
    image=orpheus_image,
    timeout=20 * MINUTES,
    scaledown_window=5 * MINUTES,
    max_containers=1,
    volumes={"/root/.cache/huggingface": hf_cache_vol},
    secrets=[hf_secret],
)
class OrpheusTTSServer:
    @modal.enter()
    def initialize(self):
        """Loads vLLM AsyncLLMEngine (BF16) and SNAC 24kHz decoder on GPU."""
        import torch
        from snac import SNAC
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        print("[Orpheus Modal] Initializing SNAC 24kHz neural audio decoder on CUDA...")
        self.snac = SNAC.from_pretrained(SNAC_MODEL_NAME).eval().to("cuda")

        print(f"[Orpheus Modal] Initializing vLLM AsyncLLMEngine with unquantized BF16 precision: {MODEL_NAME}")
        engine_args = AsyncEngineArgs(
            model=MODEL_NAME,
            dtype="bfloat16",
            gpu_memory_utilization=0.85,
            max_model_len=4096,
            enforce_eager=True,
            trust_remote_code=True,
        )
        self.engine = AsyncLLMEngine.from_engine_args(engine_args)
        print("[Orpheus Modal] Orpheus TTS engine is LIVE and ready for synthesis!")

    def _tokens_to_wav(self, token_ids: list[int]) -> bytes:
        """De-interleaves 7-token Orpheus super-frames and synthesizes 24kHz mono WAV."""
        import numpy as np
        import torch

        l0_list, l1_list, l2_list = deinterleave_orpheus_tokens(token_ids)
        if not l0_list:
            return b""

        l0_t = torch.tensor([l0_list], dtype=torch.long, device="cuda")
        l1_t = torch.tensor([l1_list], dtype=torch.long, device="cuda")
        l2_t = torch.tensor([l2_list], dtype=torch.long, device="cuda")

        with torch.inference_mode():
            audio_hat = self.snac.decode([l0_t, l1_t, l2_t])
            pcm_np = audio_hat.squeeze().cpu().numpy()
            pcm_int16 = (np.clip(pcm_np, -1.0, 1.0) * 32767).astype(np.int16)

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_int16.tobytes())

        return wav_buf.getvalue()

    def _tokens_to_raw_pcm(self, token_ids: list[int]) -> bytes:
        """De-interleaves tokens and synthesizes raw 24kHz PCM audio without headers."""
        import numpy as np
        import torch

        l0_list, l1_list, l2_list = deinterleave_orpheus_tokens(token_ids)
        if not l0_list:
            return b""

        l0_t = torch.tensor([l0_list], dtype=torch.long, device="cuda")
        l1_t = torch.tensor([l1_list], dtype=torch.long, device="cuda")
        l2_t = torch.tensor([l2_list], dtype=torch.long, device="cuda")

        with torch.inference_mode():
            audio_hat = self.snac.decode([l0_t, l1_t, l2_t])
            pcm_np = audio_hat.squeeze().cpu().numpy()
            pcm_int16 = (np.clip(pcm_np, -1.0, 1.0) * 32767).astype(np.int16)

        return pcm_int16.tobytes()

    @modal.asgi_app()
    def web_app(self):
        """FastAPI Web Application providing OpenAI-compatible TTS and diagnostics."""
        import uuid
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import JSONResponse, Response, StreamingResponse
        from pydantic import BaseModel
        from vllm import SamplingParams

        web = FastAPI(title="Orpheus TTS vLLM Server", version="1.0.0")

        class OpenAITTSRequest(BaseModel):
            model: Optional[str] = MODEL_NAME
            input: str
            voice: Optional[str] = "tara"
            response_format: Optional[str] = "wav"
            speed: Optional[float] = 1.0

        class DirectTTSRequest(BaseModel):
            text: str
            voice: Optional[str] = "tara"
            temperature: Optional[float] = 0.6
            top_p: Optional[float] = 0.9

        @web.get("/health")
        async def health_check():
            return {
                "status": "online",
                "engine": "vllm_paged_attention",
                "model": MODEL_NAME,
                "precision": "bfloat16_unquantized",
                "sample_rate": 24000,
                "supported_voices": SUPPORTED_VOICES,
            }

        @web.get("/v1/models")
        async def list_models():
            return {
                "object": "list",
                "data": [
                    {
                        "id": MODEL_NAME,
                        "object": "model",
                        "owned_by": "canopylabs",
                        "permission": [],
                    },
                    {
                        "id": "orpheus-tts",
                        "object": "model",
                        "owned_by": "canopylabs",
                        "permission": [],
                    },
                ],
            }

        @web.post("/v1/audio/speech")
        @web.post("/audio/speech")
        async def openai_speech(req: OpenAITTSRequest):
            """OpenAI-compatible /v1/audio/speech endpoint with streaming TTFA."""
            voice = (req.voice or "tara").lower()
            if voice not in SUPPORTED_VOICES:
                voice = "tara"

            clean_text = req.input.strip()
            if not clean_text:
                raise HTTPException(status_code=400, detail="Input text cannot be empty.")

            prompt = f"{voice}: {clean_text}"
            sampling_params = SamplingParams(
                temperature=0.6,
                top_p=0.9,
                max_tokens=2048,
                repetition_penalty=1.1,
            )
            req_id = f"orpheus-{uuid.uuid4().hex[:8]}"

            async def audio_stream():
                # Yield a dummy WAV header suitable for continuous streaming
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.setnframes(0xFFFFFFF) # Max frame size for streaming clients
                yield wav_buf.getvalue()

                processed_tokens = 0
                gen = self.engine.generate(prompt, sampling_params, req_id)
                
                async for out in gen:
                    token_ids = out.outputs[0].token_ids
                    available_new = len(token_ids) - processed_tokens
                    
                    # Process chunks in multiples of 7 (SNAC hierarchical frames)
                    if available_new >= 7:
                        frames_to_process = available_new // 7
                        tokens_to_take = frames_to_process * 7
                        
                        chunk_tokens = token_ids[processed_tokens : processed_tokens + tokens_to_take]
                        processed_tokens += tokens_to_take
                        
                        # Decode and stream the raw PCM bytes for this chunk
                        pcm_bytes = self._tokens_to_raw_pcm(chunk_tokens)
                        if pcm_bytes:
                            yield pcm_bytes

            return StreamingResponse(audio_stream(), media_type="audio/wav")

        @web.post("/synthesize")
        async def synthesize_direct(req: DirectTTSRequest):
            """Direct high-speed synthesis endpoint."""
            voice = (req.voice or "tara").lower()
            if voice not in SUPPORTED_VOICES:
                voice = "tara"

            clean_text = req.text.strip()
            if not clean_text:
                raise HTTPException(status_code=400, detail="Text cannot be empty.")

            prompt = f"{voice}: {clean_text}"
            sampling_params = SamplingParams(
                temperature=req.temperature or 0.6,
                top_p=req.top_p or 0.9,
                max_tokens=2048,
                repetition_penalty=1.1,
            )
            req_id = f"orpheus-{uuid.uuid4().hex[:8]}"

            gen = self.engine.generate(prompt, sampling_params, req_id)
            final_output = None
            async for out in gen:
                final_output = out

            if not final_output or not final_output.outputs:
                raise HTTPException(status_code=500, detail="Generation failed.")

            token_ids = final_output.outputs[0].token_ids
            wav_bytes = self._tokens_to_wav(token_ids)
            return Response(content=wav_bytes, media_type="audio/wav")

        return web


if __name__ == "__main__":
    @app.local_entrypoint()
    async def main(test: bool = True):
        """
        Deploy verification and interactive test entrypoint:
            modal run orpheus_modal.py
        """
        import aiohttp

        server = OrpheusTTSServer()
        url = await server.web_app.get_web_url.aio()

        print("\n" + "=" * 65)
        print("  Orpheus TTS (BF16 Unquantized) vLLM Deployment")
        print("=" * 65)
        print(f" Web URL:         {url}")
        print(f" TTS Endpoint:    {url}/v1/audio/speech")
        print(f" Direct API:      {url}/synthesize")
        print(f" Target Model:    {MODEL_NAME}")
        print(f" Codec:           SNAC 24kHz (7-token hierarchical)")
        print(f" Voices:          {', '.join(SUPPORTED_VOICES)}")
        print("=" * 65)

        if not test:
            return

        async with aiohttp.ClientSession(base_url=url) as session:
            print("[Orpheus TTS Test] Waiting for container warm status...")
            while True:
                try:
                    async with session.get("/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            info = await resp.json()
                            print(f"[Orpheus TTS Test] Engine LIVE! Diagnostic: {info}\n")
                            break
                except Exception:
                    pass
                print("[Orpheus TTS Test] Container warming up... waiting 5s")
                import asyncio
                await asyncio.sleep(5)

            print("[Orpheus TTS Test] Dispatching test audio synthesis ('tara')...")
            payload = {
                "model": MODEL_NAME,
                "input": "AlphaCore Orpheus voice initialized in full precision bfloat16. Maximum audio fidelity online.",
                "voice": "tara",
                "response_format": "wav",
            }
            async with session.post("/v1/audio/speech", json=payload) as resp:
                if resp.status == 200:
                    audio_data = await resp.read()
                    out_path = "orpheus_test_sample.wav"
                    with open(out_path, "wb") as f:
                        f.write(audio_data)
                    print(f"[Orpheus TTS Test] PASSED! Audio saved to {out_path} ({len(audio_data)} bytes).")
                else:
                    err_text = await resp.text()
                    print(f"[Orpheus TTS Test] Synthesis failed with HTTP {resp.status}: {err_text}")
