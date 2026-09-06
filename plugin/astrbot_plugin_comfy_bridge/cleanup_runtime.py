from __future__ import annotations

import time
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

    root = Path(output_dir).expanduser()
    retention = max(1.0, float(retention_hours))
    cutoff = (time.time() if now is None else float(now)) - retention * 3600

    if not root.is_dir() or root.is_symlink():
        return CleanupReport(scanned=0, deleted=0, deleted_bytes=0, failed=0)

    scanned = 0
    deleted = 0
    deleted_bytes = 0
    failed = 0

    for path in root.rglob("*"):
        try:
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
        except (FileNotFoundError, OSError):
            failed += 1

    return CleanupReport(
        scanned=scanned,
        deleted=deleted,
        deleted_bytes=deleted_bytes,
        failed=failed,
    )
