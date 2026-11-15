"""Fetch the public DSpark draft pinned for the serving comparison."""
from pathlib import Path
import json
from huggingface_hub import snapshot_download

MODEL = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark"
REVISION = "6d127b50ecd98562cea85d0087680b7d86091fb0"
destination = Path.home() / "swarm-lab" / "draft"
snapshot_download(MODEL, revision=REVISION, local_dir=str(destination),
                  max_workers=4, allow_patterns=["*.safetensors", "*.json", "LICENSE"])
size = (destination / "model.safetensors").stat().st_size
assert size == 1_349_057_504, size
for name in ("config.json", "hf_quant_config.json", "model.safetensors"):
    marker = destination / ".cache/huggingface/download" / (name + ".metadata")
    assert marker.read_text().splitlines()[0] == REVISION, name
receipt = {"model": MODEL, "revision": REVISION, "weight_bytes": size}
(destination.parent / "draft-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt), flush=True)
