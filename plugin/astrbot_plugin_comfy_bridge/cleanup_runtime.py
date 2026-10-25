from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path


IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
)


def _linked(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def checked_output_path(value: Path) -> Path:
    """Retain Windows reparse protection before creating/resolving output paths."""
    path = Path(os.path.abspath(Path(value).expanduser()))
    if any(_linked(part) for part in (path, *path.parents)):
        raise ValueError('图片输出目录包含链接或目录联接，拒绝处理')
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise ValueError('图片输出目录不能是磁盘根目录或用户主目录')
    return path


def require_idle_job_records(jobs_dir: Path) -> None:
    """Fail closed on active, unreadable or linked job state; never modify it."""
    root = Path(jobs_dir).absolute()
    if any(_linked(part) for part in (root, *root.parents)):
        raise ValueError('任务记录路径包含链接，停止清理')
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError('任务记录根路径不是目录，停止清理')
    for path in root.glob('*.json'):
        if _linked(path) or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('任务记录类型异常，停止清理')
        record = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(record, dict) or not isinstance(record.get('status'), str):
            raise ValueError('无法确认任务状态，停止清理')
        if record['status'] not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('仍有未结束或未知状态的任务，停止清理；中断记录请先核实')


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

    try:
        root = checked_output_path(output_dir)
    except (OSError, ValueError):
        return CleanupReport(scanned=0, deleted=0, deleted_bytes=0, failed=1)
    retention = max(48.0, float(retention_hours))
    cutoff = (time.time() if now is None else float(now)) - retention * 3600

    if not root.is_dir() or any(_linked(part) for part in (root, *root.parents)):
        return CleanupReport(scanned=0, deleted=0, deleted_bytes=0, failed=0)

    scanned = 0
    deleted = 0
    deleted_bytes = 0
    failed = 0

    def walk_error(error):
        raise error
    try:
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            base = Path(directory)
            dirs[:] = [name for name in dirs if not _linked(base / name)
                       and not os.path.ismount(base / name)]
            for name in names:
                path = base / name
                if path.suffix.lower() not in IMAGE_SUFFIXES or _linked(path):
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                scanned += 1
                if info.st_mtime >= cutoff:
                    continue
                # Only this ordinary file, still inside the inspected output tree.
                if any(_linked(part) for part in (path, *path.parents)):
                    raise OSError('cleanup path changed')
                current = path.lstat()
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                    raise OSError('cleanup file changed')
                path.unlink()
                deleted += 1
                deleted_bytes += info.st_size
    except OSError:
        # Never force-delete or continue after a filesystem failure.
        failed += 1

    return CleanupReport(
        scanned=scanned,
        deleted=deleted,
        deleted_bytes=deleted_bytes,
        failed=failed,
    )
