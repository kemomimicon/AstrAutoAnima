from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .schemas import GpuMetrics, MemoryMetrics, WorkstationMetrics


@dataclass(frozen=True)
class _CpuTimes:
    idle: int
    total: int


_cpu_lock = threading.Lock()
_previous_cpu: _CpuTimes | None = None


def _read_linux_cpu_times() -> _CpuTimes | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
    except (OSError, IndexError, ValueError):
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return _CpuTimes(idle=idle, total=sum(values))


def _filetime_value(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _read_windows_cpu_times() -> _CpuTimes | None:
    if os.name != "nt":
        return None
    idle = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        success = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except (AttributeError, OSError):
        return None
    if not success:
        return None
    return _CpuTimes(
        idle=_filetime_value(idle),
        total=_filetime_value(kernel) + _filetime_value(user),
    )


def _read_cpu_times() -> _CpuTimes | None:
    return _read_linux_cpu_times() or _read_windows_cpu_times()


_previous_cpu = _read_cpu_times()


def _cpu_percent() -> float:
    global _previous_cpu
    current = _read_cpu_times()
    if current is None:
        return 0.0
    with _cpu_lock:
        previous = _previous_cpu
        _previous_cpu = current
    if previous is None:
        return 0.0
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return 0.0
    used = 100.0 * (1.0 - idle_delta / total_delta)
    return round(max(0.0, min(100.0, used)), 1)


def _linux_memory() -> MemoryMetrics | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values["MemAvailable"]
    except (OSError, KeyError, ValueError):
        return None
    used = max(0, total - available)
    percent = 100.0 * used / total if total else 0.0
    return MemoryMetrics(
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        utilization_percent=round(percent, 1),
    )


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_memory() -> MemoryMetrics | None:
    if os.name != "nt":
        return None
    state = _MemoryStatusEx()
    state.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state))
    except (AttributeError, OSError):
        return None
    if not success:
        return None
    total = int(state.ullTotalPhys)
    available = int(state.ullAvailPhys)
    return MemoryMetrics(
        total_bytes=total,
        used_bytes=max(0, total - available),
        available_bytes=available,
        utilization_percent=float(state.dwMemoryLoad),
    )


def _memory_metrics() -> MemoryMetrics:
    result = _linux_memory() or _windows_memory()
    if result is not None:
        return result
    return MemoryMetrics(
        total_bytes=0,
        used_bytes=0,
        available_bytes=0,
        utilization_percent=0.0,
    )


def _optional_number(value: str) -> float | None:
    normalized = value.strip()
    if not normalized or normalized.upper() in {"N/A", "[N/A]"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _gpu_metrics() -> list[GpuMetrics]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    devices: list[GpuMetrics] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 7:
            continue
        try:
            index = int(parts[0])
            total = int(float(parts[3]))
            used = int(float(parts[4]))
            free = int(float(parts[5]))
        except ValueError:
            continue
        devices.append(
            GpuMetrics(
                index=index,
                name=parts[1],
                utilization_percent=_optional_number(parts[2]),
                memory_total_mib=total,
                memory_used_mib=used,
                memory_free_mib=free,
                memory_utilization_percent=(
                    round(100.0 * used / total, 1) if total else 0.0
                ),
                temperature_c=_optional_number(parts[6]),
            )
        )
    return devices


def collect_system_metrics() -> WorkstationMetrics:
    try:
        load_averages = os.getloadavg()
    except (AttributeError, OSError):
        load_averages = (None, None, None)
    return WorkstationMetrics(
        collected_at=datetime.now().astimezone(),
        cpu_percent=_cpu_percent(),
        cpu_logical_count=os.cpu_count() or 1,
        load_average_1m=load_averages[0],
        load_average_5m=load_averages[1],
        load_average_15m=load_averages[2],
        memory=_memory_metrics(),
        gpus=_gpu_metrics(),
    )
