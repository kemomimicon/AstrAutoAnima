#!/usr/bin/env python3
"""Validate the source release structure, JSON and Python syntax."""

from __future__ import annotations

import argparse
import json
import re
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
    'tools/install_progress.py',
    'tools/setup_center.py',
    'tools/relocate_install.py',
    'tools/napcat_setup.py',
    'tools/extension_guide.py',
    'tools/extension_installer.py',
    'tools/online_prompt_importer.py',
    'docs/NAPCAT_SETUP.md',
    'docs/INSTALL_PROGRESS.md',
    'docs/LINUX_RECORDING_CHECKLIST.txt',

    "tools/bootstrap_windows.ps1",
    "tools/deployment_support.py",
    "tools/project_components.py",
    "optional/prompt_importer/importer.py",
    "optional/prompt_importer/README.md",
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
        if not re.fullmatch(r'\d+\.\d+\.\d+-beta\.\d+', payload.get('release', '')) or payload.get('status') != 'prerelease':
            errors.append('release manifest must describe a versioned prerelease')
        versions = payload.get('components', {})
        checks = [
            ('plugin/astrbot_plugin_comfy_bridge/metadata.yaml', r'^version:\s*(\S+)', 'astrbot_plugin_comfy_bridge'),
            ('hub/service/pyproject.toml', r'^version\s*=\s*"([^"]+)"', 'astr_auto_anima_hub_service'),
            ('clients/flutter/pubspec.yaml', r'^version:\s*(\S+)', 'astr_auto_anima_hub_client'),
        ]
        for relative, pattern, component in checks:
            found = re.search(pattern, (root/relative).read_text('utf-8-sig'), re.M)
            if found is None or found[1] != versions.get(component):
                errors.append('component version differs from manifest: ' + relative)
        if versions.get('astrbot_plugin_comfy_bridge') != payload.get('release'):
            errors.append('plugin version differs from release identity')
        if payload.get('training_studio_connector_included'):
            for name in ('optional/studio/package.json', 'optional/studio/README.txt',
                         'optional/studio/AAA_Studio025_Connector-0.1.1.zip', 'tools/studio_optional.py'):
                if not (root/name).is_file():
                    errors.append('optional Studio artifact missing: ' + name)
        if payload.get('integrated_feature_review'):
            policy_paths = [root/'plugin/astrbot_plugin_comfy_bridge/group_policy_runtime.py',
                            root/'hub/service/src/astr_auto_anima_hub/group_policy_runtime.py']
            if not all(path.is_file() for path in policy_paths):
                errors.append('shared group policy runtime is missing')
            elif policy_paths[0].read_bytes() != policy_paths[1].read_bytes():
                errors.append('plugin and Hub group policies differ')
            for name in ('clients/flutter/lib/core/connection_profile.dart',
                         'clients/flutter/lib/features/users/chat_groups_page.dart',
                         'docs/LOCAL_MULTI_INSTANCE_ACCEPTANCE.txt'):
                if not (root/name).is_file():
                    errors.append('integrated feature artifact missing: ' + name)

    if errors:
        print("Release validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Release validation passed: structure, JSON and Python syntax are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
