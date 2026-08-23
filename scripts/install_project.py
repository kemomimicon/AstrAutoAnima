#!/usr/bin/env python3
"""Cross-platform installer for AstrAutoAnima project files (dry-run by default)."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


def copy_directory(source: Path, target: Path, apply: bool) -> None:
    print(f"directory: {source} -> {target}")
    if not apply:
        return
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target.with_name(f"{target.name}.backup_{stamp}")
        if backup.exists():
            raise RuntimeError(f"backup already exists: {backup}")
        shutil.copytree(target, backup)
        print(f"  backup: {backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)


def copy_workflows(source: Path, target: Path, apply: bool) -> None:
    print(f"workflows: {source} -> {target}")
    if not apply:
        return
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for workflow in sorted(source.glob("*.json")):
        destination = target / workflow.name
        if destination.exists():
            backup = destination.with_name(f"{destination.stem}.backup_{stamp}.json")
            shutil.copy2(destination, backup)
            print(f"  backup: {backup}")
        shutil.copy2(workflow, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot-data", required=True, type=Path)
    parser.add_argument("--comfyui-root", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true", help="perform copies; otherwise dry-run")
    args = parser.parse_args()

    repo = args.repo_root.expanduser().resolve()
    astrbot_data = args.astrbot_data.expanduser().resolve()
    comfyui_root = args.comfyui_root.expanduser().resolve()
    if not (repo / ".astr_auto_anima_public_root").is_file():
        print(f"invalid repository root: {repo}", file=sys.stderr)
        return 2
    if not astrbot_data.is_dir() or not comfyui_root.is_dir():
        print("AstrBot data or ComfyUI root directory does not exist", file=sys.stderr)
        return 2

    copy_directory(
        repo / "plugin/astrbot_plugin_comfy_bridge",
        astrbot_data / "plugins/astrbot_plugin_comfy_bridge",
        args.apply,
    )
    copy_directory(
        repo / "comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools",
        comfyui_root / "custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools",
        args.apply,
    )
    copy_workflows(
        repo / "comfyui/workflows",
        comfyui_root / "user/default/workflows",
        args.apply,
    )
    print("Applied." if args.apply else "Dry-run only. Re-run with --apply after reviewing targets.")
    print("Plugin data was not touched. Restart/reload AstrBot and restart ComfyUI manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
