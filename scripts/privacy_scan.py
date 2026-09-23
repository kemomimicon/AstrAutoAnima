#!/usr/bin/env python3
"""Fail a public release scan when private/runtime artifacts are detected."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".dart",
    ".kt", ".kts", ".cpp", ".cc", ".h", ".cmake", ".ps1", ".sh", ".bat",
    ".properties", ".xml", ".example", ".gitignore", ".cmd",
}
FORBIDDEN_SUFFIXES = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".pem", ".key",
    ".jks", ".keystore", ".p12", ".sqlite", ".sqlite3", ".db",
}
FORBIDDEN_NAMES = {
    ".env", "lite_users.json", "delivery_targets.json", "cmd_config.json",
    "runtime-env.json", "last-plan.json", "services.json", "extension_host.py",
}
FORBIDDEN_DIRS = {
    ".venv", "venv", "__pycache__", ".dart_tool", "build", ".gradle",
    "reverse_history", "job_store", "hub_state", "outputs", "inputs", "logs",
    ".pytest_cache", ".idea", ".ipynb_checkpoints", "kp_upstream",
    "plugin_data", "style_gallery",
}
TEXT_PATTERNS = {
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider API key": re.compile(r"\b(?:sk-proj-|sk-ant-|abk_)[A-Za-z0-9_-]{24,}\b"),
    "excluded training connector route": re.compile(r"/extensions/anima-lora-studio(?:/|['\"])", re.I),
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\(?!YOUR_USER|username)", re.I),
    "private server account path": re.compile(r"/root/(?:\.config/QQ|\.local/share/QQ|Napcat)", re.I),
    "container instance id": re.compile(r"\bcpod-[a-z0-9-]+\b", re.I),
    "literal Hub bearer token": re.compile(r"\baah_(?:admin|lite|u)_[A-Za-z0-9_-]{24,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "generic API secret": re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*[:=]\s*['\"]?(?!$|replace|your-|test-|example)[A-Za-z0-9_./+-]{24,}"),
}


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {
        "LICENSE", "README", "Dockerfile", ".env.example"
    }


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    manifest = root / 'artwork-manifest.json'
    approved = {item['path']: item['sha256'] for item in json.loads(manifest.read_text('utf-8-sig'))} if manifest.is_file() else {}
    for name, expected in approved.items():
        item = root / name
        if not name.startswith('clients/flutter/assets/') or '..' in Path(name).parts:
            findings.append('invalid artwork whitelist path: ' + name)
        elif not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest() != expected:
            findings.append('missing or altered authorized artwork: ' + name)
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if any(part in FORBIDDEN_DIRS for part in relative.parts):
            if path.is_dir() and path.name in FORBIDDEN_DIRS:
                findings.append(f"forbidden generated/private directory: {relative}")
            continue
        if any(part.endswith(".egg-info") for part in relative.parts):
            if path.is_dir() and path.name.endswith(".egg-info"):
                findings.append(f"forbidden generated package directory: {relative}")
            continue
        if not path.is_file():
            continue
        if path.name in FORBIDDEN_NAMES and path.name != ".env.example":
            findings.append(f"forbidden private filename: {relative}")
        if path.name.startswith('.env.') and path.name != '.env.example':
            findings.append(f"private environment file: {relative}")
        if 'courtyard' in relative.parts or 'splash' in relative.parts or path.name.startswith('oc_'):
            if path.suffix.lower() in {'.png', '.jpg', '.webp'}:
                if approved.get(relative.as_posix()) != hashlib.sha256(path.read_bytes()).hexdigest():
                    findings.append(f"unapproved or changed artwork: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden model/secret file: {relative}")
        if path.stat().st_size > 20 * 1024 * 1024:
            findings.append(f"unexpected file larger than 20 MiB: {relative}")
        if relative.as_posix() in {"scripts/privacy_scan.py", "scripts/verify_release_archives.py"}:
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

    for pool_name in ("anima_random_prompt_pool.json", "kp_prompt_pool.json"):
        public_pool = root / "plugin/astrbot_plugin_comfy_bridge/data" / pool_name
        if not public_pool.is_file():
            findings.append(f"public bundled prompt pool is missing: {pool_name}")
            continue
        try:
            data = json.loads(public_pool.read_text(encoding="utf-8-sig"))
            if data.get("prompts") != []:
                findings.append(f"public bundled prompt pool must contain exactly zero prompts: {pool_name}")
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"public prompt pool is invalid JSON ({pool_name}): {exc}")
    module_path = root / "plugin/astrbot_plugin_comfy_bridge/data/kp_dynamic_modules.json"
    if module_path.is_file():
        try:
            modules = json.loads(module_path.read_text(encoding="utf-8-sig")).get("modules", {})
            if any(value for value in modules.values()):
                findings.append("public K dynamic module catalog must be empty")
        except (OSError, AttributeError, json.JSONDecodeError) as exc:
            findings.append(f"public K dynamic module catalog is invalid: {exc}")
    else:
        findings.append("public K dynamic module catalog is missing")
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
