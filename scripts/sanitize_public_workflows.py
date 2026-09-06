#!/usr/bin/env python3
"""Replace private model and LoRA names in copied workflow templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPLACEMENTS = {
    "anima_baseV10.safetensors": "YOUR_ANIMA_UNET.safetensors",
    "anima-base-v1.0.safetensors": "YOUR_ANIMA_UNET.safetensors",
    "qwen_3_06b_base.safetensors": "YOUR_ANIMA_CLIP.safetensors",
    "qwen_image_vae.safetensors": "YOUR_ANIMA_VAE.safetensors",
    "seedvr2_ema_3b-Q4_K_M.gguf": "YOUR_SEEDVR2_MODEL.gguf",
    "ema_vae_fp16.safetensors": "YOUR_SEEDVR2_VAE.safetensors",
}


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for source, target in REPLACEMENTS.items():
        result = result.replace(source, target)
    return result


def scrub_lora_nodes(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    lora_nodes = [
        (node_id, node)
        for node_id, node in payload.items()
        if isinstance(node, dict) and node.get("class_type") == "LoraLoader"
    ]
    for index, (_, node) in enumerate(sorted(lora_nodes), 1):
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and "lora_name" in inputs:
            inputs["lora_name"] = f"YOUR_STYLE_LORA_{index}.safetensors"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_dir", type=Path)
    args = parser.parse_args()
    for path in sorted(args.workflow_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        scrub_lora_nodes(payload)
        path.write_text(
            json.dumps(scrub(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"sanitized: {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
