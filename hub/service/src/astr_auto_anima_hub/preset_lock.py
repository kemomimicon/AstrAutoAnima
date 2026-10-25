"""Cooperative cross-process lock shared by Hub and QQ preset writers."""
import os
import threading
import time
from contextlib import contextmanager

_registry_lock = threading.Lock()
_mutexes = {}
_local = threading.local()


@contextmanager
def preset_file_lock(path, timeout=15):
    key = str(path.absolute())
    with _registry_lock:
        mutex = _mutexes.setdefault(key, threading.RLock())
    with mutex:
        held = getattr(_local, 'held', set())
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_name(path.name + '.write.lock')
        with lock.open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('预设正在写入，请稍后查询提交状态')
                    time.sleep(.05)
            _local.held = {*held, key}
            try:
                yield
            finally:
                _local.held = held
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
