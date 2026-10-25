"""Read-only, explicitly scoped image risk inventory. Not a release certificate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat

SECRET_NAMES = {
    ".env", ".netrc", ".git-credentials", ".npmrc", ".pypirc",
    "authorized_keys", "id_rsa", "id_ed25519", "idle.enc",
    "lite_users.json", "delivery_targets.json", "cmd_config.json",
    ".bash_history", ".zsh_history", ".python_history", ".wget-hsts",
}
RUNTIME_DIRS = {
    ".ssh", ".aws", ".huggingface", ".aaa-private", ".ipython",
    "hub_state", "plugin_data", "attachments", "outputs", "inputs",
    "style_gallery", "reverse_history", "job_store", "logs", "backups",
    "prompt_pool_backups",
}
LARGE_REVIEW_DIRS = {".venv", "venv", "node_modules", ".git"}
DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".bak", ".pem", ".key", ".p12", ".jks", ".keystore"}
MODEL_SUFFIXES = {".safetensors", ".gguf", ".ckpt", ".onnx", ".pt", ".pth"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".image"}
ARCHIVE_SUFFIXES = {".zip", ".gz", ".tar", ".7z", ".rar"}
TEXT_SUFFIXES = {".json", ".env", ".ini", ".toml", ".yaml", ".yml", ".conf", ".txt", ".sh", ".ps1", ".py"}
PATTERNS = (
    re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-proj-|sk-ant-|abk_|ghp_|github_pat_)[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\baah_(?:admin|lite|u)_[A-Za-z0-9_-]{24,}\b"),
)
MAX_TEXT = 2 * 1024 * 1024


def audit(roots):
    findings, gaps = [], []
    examined = 0
    normalized = []
    def add(path, kind):
        findings.append({"path": str(path), "category": kind})
    for value in roots:
        path = Path(os.path.abspath(value))
        try:
            if path.resolve(strict=True) != path or not stat.S_ISDIR(path.lstat().st_mode):
                raise ValueError()
            if any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
                   for parent in (path, *path.parents)):
                raise ValueError()
        except (OSError, ValueError):
            gaps.append({"path": str(path), "reason": "root_missing_linked_or_not_directory"})
            continue
        if any(path == parent or parent in path.parents for parent in normalized):
            continue
        normalized.append(path)
        def walk_error(exc):
            gaps.append({"path": str(exc.filename), "reason": "enumeration_failed"})
        for directory, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
            base = Path(directory)
            keep = []
            for name in dirs:
                item = base / name
                try:
                    info = item.lstat()
                    if not stat.S_ISDIR(info.st_mode) or item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                        gaps.append({"path": str(item), "reason": "link_or_special_directory_not_traversed"})
                        continue
                    if os.path.ismount(item):
                        gaps.append({"path": str(item), "reason": "nested_mount_not_traversed"})
                        continue
                    if name.casefold() in RUNTIME_DIRS:
                        add(item, "runtime_or_account_directory")
                    if name.casefold() in LARGE_REVIEW_DIRS:
                        gaps.append({"path": str(item), "reason": "environment_or_git_requires_separate_review"})
                        continue
                    keep.append(name)
                except OSError:
                    gaps.append({"path": str(item), "reason": "directory_stat_failed"})
            dirs[:] = keep
            for name in files:
                item = base / name
                try:
                    info = item.lstat()
                    if not stat.S_ISREG(info.st_mode) or item.is_symlink():
                        gaps.append({"path": str(item), "reason": "link_or_special_file_not_opened"})
                        continue
                    examined += 1
                    lower, suffix = name.casefold(), item.suffix.lower()
                    if (lower in SECRET_NAMES or lower.startswith("runtime-env")
                            or (lower.startswith(".env.") and lower != ".env.example")):
                        add(item, "credential_or_runtime_config")
                    if suffix in DATA_SUFFIXES:
                        add(item, "account_database_log_or_backup")
                    if suffix in MODEL_SUFFIXES:
                        add(item, "model_redistribution_review")
                    if suffix in IMAGE_SUFFIXES:
                        add(item, "image_ownership_or_private_media_review")
                    if suffix in ARCHIVE_SUFFIXES:
                        gaps.append({"path": str(item), "reason": "archive_contents_not_scanned"})
                    if suffix not in TEXT_SUFFIXES and lower not in SECRET_NAMES:
                        continue
                    if info.st_size > MAX_TEXT:
                        gaps.append({"path": str(item), "reason": "text_above_scan_limit"})
                        continue
                    # O_NOFOLLOW prevents opening a substituted symbolic link on Linux.
                    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                    fd = os.open(item, flags)
                    with os.fdopen(fd, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
                            gaps.append({"path": str(item), "reason": "file_changed_during_audit"})
                            continue
                        raw = stream.read(MAX_TEXT + 1)
                    try:
                        text = raw.decode("utf-8-sig")
                    except UnicodeError:
                        gaps.append({"path": str(item), "reason": "text_encoding_not_scanned"})
                        continue
                    if any(pattern.search(text) for pattern in PATTERNS):
                        add(item, "credential_pattern")
                except OSError:
                    gaps.append({"path": str(item), "reason": "file_read_failed"})
    return {
        "schema": "aaa-image-risk-inventory-v1",
        "read_only": True, "release_approved": False,
        "roots": [str(p) for p in normalized], "examined_files": examined,
        "findings": findings, "incomplete_or_manual_review": gaps,
        "notice": "No file contents emitted. Selected roots only; not proof of whole-image sanitization. No files removed.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, type=Path,
                        help="Explicit directory to inspect; repeat for additional image scopes.")
    args = parser.parse_args()
    result = audit(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["incomplete_or_manual_review"] else 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
