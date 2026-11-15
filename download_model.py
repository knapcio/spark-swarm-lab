"""Fetch the public, pinned prototype checkpoint; run on the staging Spark."""
from pathlib import Path
import json
from huggingface_hub import snapshot_download

MODEL = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
REVISION = "bee7596271d1495f6992ae224aefde4410e816b8"
destination = Path.home() / "swarm-lab" / "model"
snapshot_download(
    MODEL, revision=REVISION, local_dir=str(destination), max_workers=8,
    allow_patterns=["*.safetensors", "*.json", "*.jinja", "*.model", "*.txt", "*.tiktoken"],
)
index = json.loads((destination / "model.safetensors.index.json").read_text())
shards = sorted(set(index["weight_map"].values()))
assert len(shards) == 52, f"Unexpected shard count: {len(shards)}"
size = sum((destination / name).stat().st_size for name in shards)
assert size == 21_561_882_284, f"Unexpected weight size: {size}"
for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
    assert (destination / name).is_file(), name
receipt = {"model": MODEL, "revision": REVISION, "shards": len(shards), "weight_bytes": size}
(destination.parent / "model-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt), flush=True)
