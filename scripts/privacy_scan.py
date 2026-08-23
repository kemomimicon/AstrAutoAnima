#!/usr/bin/env python3
"""Fail a public release scan when private/runtime artifacts are detected."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".dart",
    ".kt", ".kts", ".cpp", ".cc", ".h", ".cmake", ".ps1", ".sh", ".bat",
    ".properties", ".xml", ".example", ".gitignore",
}
FORBIDDEN_SUFFIXES = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".pem", ".key",
}
FORBIDDEN_NAMES = {
    ".env", "lite_users.json", "delivery_targets.json", "cmd_config.json",
}
FORBIDDEN_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".dart_tool", "build", ".gradle",
    "reverse_history", "job_store", "hub_state", "outputs", "inputs", "logs",
}
TEXT_PATTERNS = {
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\(?!YOUR_USER|username)", re.I),
    "private server account path": re.compile(r"/root/(?:\.config/QQ|\.local/share/QQ|Napcat)", re.I),
    "known private QQ": re.compile(r"(?<!\d)1487928670(?!\d)"),
    "known private Bot ID": re.compile(r"\bkemomimi\b", re.I),
    "private LoRA name": re.compile(r"\b(?:shiratama|guizhencao|staryfs|chyomimasu|6ctmika|edlf_itsuwari)\b", re.I),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "generic API secret": re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*[:=]\s*['\"]?(?!$|replace|your-|test-|example)[A-Za-z0-9_./+-]{24,}"),
}


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {
        "LICENSE", "README", "Dockerfile", ".env.example"
    }


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_DIRS for part in relative.parts):
            if path.is_dir() and path.name in FORBIDDEN_DIRS:
                findings.append(f"forbidden generated/private directory: {relative}")
            continue
        if not path.is_file():
            continue
        if path.name in FORBIDDEN_NAMES and path.name != ".env.example":
            findings.append(f"forbidden private filename: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden model/secret file: {relative}")
        if path.stat().st_size > 20 * 1024 * 1024:
            findings.append(f"unexpected file larger than 20 MiB: {relative}")
        if relative.as_posix() == "scripts/privacy_scan.py":
            continue
        if not is_text(path) or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in TEXT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")

    public_pool = root / "plugin/astrbot_plugin_comfy_bridge/data/anima_random_prompt_pool.json"
    if public_pool.is_file():
        try:
            data = json.loads(public_pool.read_text(encoding="utf-8-sig"))
            if data.get("prompts") != []:
                findings.append("public bundled prompt pool must contain exactly zero prompts")
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"public prompt pool is invalid JSON: {exc}")
    else:
        findings.append("public bundled prompt pool is missing")
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not (root / ".astr_auto_anima_public_root").is_file():
        print(f"Refusing to scan an unmarked release root: {root}", file=sys.stderr)
        return 2
    findings = scan(root)
    if findings:
        print("Privacy scan FAILED:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Privacy scan passed: no private/runtime artifacts detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
