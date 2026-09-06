#!/usr/bin/env bash

set -euo pipefail

COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
COMFY_ROOT="${COMFY_ROOT:-/workspace/ComfyUI}"

echo "=== ComfyUI system_stats ==="
curl -fsS --max-time 10 "$COMFY_URL/system_stats" >/dev/null
echo "ComfyUI: OK"

echo "=== Required node class types ==="
python - "$COMFY_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/object_info", timeout=20) as response:
    data = json.load(response)

required = [
    "Load Booru Tagger",
    "Booru Tagger",
    "JJC_JoyCaption_Custom_GGUF",
    "AnimaPromptBatchEncode",
    "AnimaCaptionBatchGuard",
    "AnimaReverseCompiler",
    "AnimaReverseResultSaver",
    "SeedVR2LoadDiTModel",
    "SeedVR2LoadVAEModel",
    "SeedVR2TilingUpscaler",
    "LatentUpscaleBy",
    "ImageScaleBy",
    "VAEEncode",
]

missing = [name for name in required if name not in data]
for name in required:
    print(("OK      " if name in data else "MISSING ") + name)
if missing:
    raise SystemExit("Missing ComfyUI nodes: " + ", ".join(missing))
PY

echo "=== HQ / Refine API workflows ==="

for file in \
  "$COMFY_ROOT/user/default/workflows/Anima_HQ_Txt2Img_Beta_api.json" \
  "$COMFY_ROOT/user/default/workflows/Anima_Refine_Existing_Beta_api.json" \
  "$COMFY_ROOT/user/default/workflows/Anima_SeedVR2_Refine_Beta_api.json"
do
    if [ -f "$file" ]; then
        python -m json.tool "$file" >/dev/null
        echo "OK      $file"
    else
        echo "MISSING $file"
        exit 1
    fi
done

echo "=== Required model files ==="

for file in \
  "$COMFY_ROOT/models/llava_gguf/llama-joycaption-beta-one-hf-llava.Q6_K.gguf" \
  "$COMFY_ROOT/models/llava_gguf/llama-joycaption-beta-one-llava-mmproj-model-f16.gguf"
do
    if [ -f "$file" ]; then
        ls -lh "$file"
    else
        echo "MISSING $file"
        exit 1
    fi
done

echo "=== llama_cpp import ==="
python - <<'PY'
import llama_cpp
print("llama_cpp:", llama_cpp.__version__)
PY

echo "=== Installed external commits ==="

for repo in \
  "$COMFY_ROOT/custom_nodes/ComfyUI-Booru-Tagger" \
  "$COMFY_ROOT/custom_nodes/ComfyUI-joycaption-beta-one-GGUF"
do
    if [ -d "$repo/.git" ]; then
        printf '%s ' "$repo"
        git -C "$repo" rev-parse HEAD
    else
        echo "MISSING GIT REPOSITORY $repo"
        exit 1
    fi
done

echo "Anima workflow prerequisites: OK"
