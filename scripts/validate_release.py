#!/usr/bin/env python3
"""Validate the source release structure, JSON and Python syntax."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED = (
    "README.md",
    "LICENSE",
    "docs/INSTALL.md",
    "docs/EASY_INSTALL.md",
    "docs/USAGE.md",
    "docs/TROUBLESHOOTING.md",
    "plugin/astrbot_plugin_comfy_bridge/main.py",
    "plugin/astrbot_plugin_comfy_bridge/data/anima_random_prompt_pool.json",
    "plugin/astrbot_plugin_comfy_bridge/data/kp_prompt_pool.json",
    "plugin/astrbot_plugin_comfy_bridge/data/kp_dynamic_modules.json",
    "plugin/astrbot_plugin_comfy_bridge/data/workflow_registry.json",
    "comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/nodes.py",
    "comfyui/workflows/Anima_HQ_Txt2Img_Beta_api.json",
    "comfyui/workflows/Anima_Refine_Existing_Beta_api.json",
    "comfyui/workflows/Anima_SeedVR2_Refine_Beta_api.json",
    "comfyui/workflows/Anima_WD_CT_JoyCaption_Reverse_Beta_api.json",
    "hub/service/pyproject.toml",
    "clients/flutter/pubspec.yaml",
    "tools/prompt_pool_manager.py",
    "tools/hub_lite_user_manager.py",
    "tools/easy_installer.py",
    "tools/deploy_project.py",
    "tools/bootstrap_windows.ps1",
    "tools/deployment_support.py",
    "tools/model_catalog.json",
    "Deploy-Windows.cmd",
    "Deploy-Linux.sh",
    "docs/DEPLOY_WINDOWS.md",
    "docs/DEPLOY_LINUX.md",
    "docs/ANIMA_MASTER.md",
    "artwork-manifest.json",
    "docs/WORKFLOWS.md",
    "tools/optional_components.json",
    "examples/prompt_pool.custom-groups.example.json",
    "一键部署_AstrAutoAnima.bat",
    "一键部署_AstrAutoAnima.sh",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    if not (root / ".astr_auto_anima_public_root").is_file():
        errors.append("release root marker is missing")
    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"required file missing: {relative}")

    for path in root.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")

    for path in root.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8-sig")
            compile(source, str(path), "exec")
        except (OSError, SyntaxError) as exc:
            errors.append(f"Python compile failed {path.relative_to(root)}: {exc}")

    for relative in (
        "comfyui/workflows/Anima_HQ_Txt2Img_Beta_api.json",
        "comfyui/workflows/Anima_Refine_Existing_Beta_api.json",
    ):
        path = root / relative
        if path.is_file():
            text = path.read_text(encoding="utf-8-sig")
            for placeholder in ("YOUR_ANIMA_UNET", "YOUR_ANIMA_CLIP", "YOUR_ANIMA_VAE"):
                if placeholder not in text:
                    errors.append(f"sanitized placeholder {placeholder} missing from {relative}")

    seedvr = root / "comfyui/workflows/Anima_SeedVR2_Refine_Beta_api.json"
    if seedvr.is_file():
        text = seedvr.read_text(encoding="utf-8-sig")
        for placeholder in ("YOUR_SEEDVR2_MODEL", "YOUR_SEEDVR2_VAE.safetensors"):
            if placeholder not in text:
                errors.append(f"sanitized placeholder {placeholder} missing from SeedVR2 workflow")

    manifest = root / "release-manifest.json"
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if payload.get("release") != "0.5.0-beta.2" or payload.get("status") != "prerelease":
            errors.append("release manifest does not describe 0.5.0-beta.2 prerelease")

    if errors:
        print("Release validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Release validation passed: structure, JSON and Python syntax are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
