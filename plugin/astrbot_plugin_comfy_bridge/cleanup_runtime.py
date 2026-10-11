from __future__ import annotations

import time
import os
from dataclasses import dataclass
from pathlib import Path


IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
)


@dataclass(frozen=True)
class CleanupReport:
    scanned: int
    deleted: int
    deleted_bytes: int
    failed: int


def checked_output_path(value: Path) -> Path:
    """Check original spelling before resolve(), including Windows reparse points."""
    path = Path(os.path.abspath(Path(value).expanduser()))
    for part in (path, *path.parents):
        try:
            linked = part.is_symlink() or bool(getattr(part.lstat(), "st_file_attributes", 0) & 0x400)
        except FileNotFoundError:
            continue
        if linked:
            raise ValueError("图片清理目录包含符号链接或目录联接，拒绝操作")
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise ValueError("图片清理目录不能是磁盘根目录或用户主目录")
    return path


def cleanup_old_output_images(
    output_dir: Path,
    retention_hours: float = 48.0,
    *,
    now: float | None = None,
) -> CleanupReport:
    """Delete old image files from the plugin output directory only.

    Symlinks and non-image files are deliberately ignored. The caller must pass
    the plugin output directory; this function never discovers or touches the
    ComfyUI output directory.
    """

    try:
        root = checked_output_path(output_dir)
    except (OSError, ValueError):
        return CleanupReport(scanned=0, deleted=0, deleted_bytes=0, failed=1)
    retention = max(1.0, float(retention_hours))
    cutoff = (time.time() if now is None else float(now)) - retention * 3600

    if not root.is_dir() or root.is_symlink():
        return CleanupReport(scanned=0, deleted=0, deleted_bytes=0, failed=0)

    scanned = 0
    deleted = 0
    deleted_bytes = 0
    failed = 0

    def images():
        for current, directories, files in os.walk(root, followlinks=False):
            safe_directories = []
            for name in directories:
                try:
                    checked_output_path(Path(current) / name)
                    safe_directories.append(name)
                except (OSError, ValueError):
                    pass
            directories[:] = safe_directories
            for name in files:
                yield Path(current) / name

    for path in images():
        try:
            checked_output_path(path)
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            scanned += 1
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                continue
            path.unlink()
            deleted += 1
            deleted_bytes += stat.st_size
        except (OSError, ValueError):
            failed += 1

    return CleanupReport(
        scanned=scanned,
        deleted=deleted,
        deleted_bytes=deleted_bytes,
        failed=failed,
    )
