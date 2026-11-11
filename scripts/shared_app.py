import modal
from pathlib import Path

app = modal.App("alphalive-backend")
CACHE_DIR = "/hf-hub-cache"
OUTPUTS_DIR = "/outputs"

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)
outputs_volume = modal.Volume.from_name("outputs", create_if_missing=True)
