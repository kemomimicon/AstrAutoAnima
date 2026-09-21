"""Cross-process admission lock for opt-in idle shutdown (Linux only)."""
import json
import os
from pathlib import Path

DEFAULT_ROOT = '/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge'


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def root_path(root=None):
    path = Path(root or os.getenv('AAH_PLUGIN_DATA_DIR', DEFAULT_ROOT))
    if path.resolve() != path:
        raise RuntimeError('休眠状态路径包含链接')
    return path


def blocked(root=None):
    path = root_path(root) / 'idle_shutdown_gate.json'
    if not path.exists():
        return False
    if path.is_symlink():
        raise RuntimeError('休眠状态文件包含链接')
    data = json.loads(path.read_text('utf-8'))
    return data.get('boot_id') == boot_id() and data.get('blocked') is True


def admission(root=None):
    """Return a held shared lock; fail immediately, never block an event loop."""
    root = root_path(root)
    # Before opt-in creates the lock, there is no shutdown controller.
    path = root / 'idle_shutdown.lock'
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError('休眠锁文件包含链接')
    import fcntl
    stream = path.open('a')
    try:
        fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if blocked(root):
            raise RuntimeError('实例正在准备休眠，暂不接受新任务')
        return stream
    except Exception:
        stream.close()
        raise RuntimeError('实例正在准备休眠，暂不接受新任务') from None
