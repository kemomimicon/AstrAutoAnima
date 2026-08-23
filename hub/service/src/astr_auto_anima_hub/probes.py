from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .config import Settings
from .repositories import RepositoryError, read_json_object
from .schemas import ProbeStatus, WorkstationStatus


def _http_probe(
    name: str,
    base_url: str,
    route: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> ProbeStatus:
    url = urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(1_000_000)
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        latency = round((time.perf_counter() - started) * 1000)
        return ProbeStatus(
            name=name,
            status="offline",
            detail=f"HTTP {exc.code} from {url}",
            latency_ms=latency,
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        latency = round((time.perf_counter() - started) * 1000)
        return ProbeStatus(
            name=name,
            status="offline",
            detail=f"cannot connect to {url}: {exc}",
            latency_ms=latency,
        )
    latency = round((time.perf_counter() - started) * 1000)
    data: dict[str, Any] = {"url": url, "http_status": status_code}
    try:
        parsed = json.loads(body)
        if name == "comfyui" and isinstance(parsed, dict):
            devices = parsed.get("devices", [])
            data["device_count"] = len(devices) if isinstance(devices, list) else 0
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return ProbeStatus(
        name=name,
        status="online",
        detail=f"HTTP {status_code}",
        latency_ms=latency,
        data=data,
    )


def _plugin_probe(plugin_dir: Path) -> ProbeStatus:
    metadata = plugin_dir / "metadata.yaml"
    if not plugin_dir.is_dir() or not metadata.is_file():
        return ProbeStatus(
            name="comfy_bridge_plugin",
            status="missing",
            detail=f"plugin metadata not found: {metadata}",
        )
    try:
        text = metadata.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return ProbeStatus(
            name="comfy_bridge_plugin", status="invalid", detail=str(exc)
        )
    match = re.search(r"(?m)^version:\s*['\"]?([^'\"\s]+)", text)
    if not match:
        return ProbeStatus(
            name="comfy_bridge_plugin",
            status="invalid",
            detail="metadata.yaml has no version field",
        )
    return ProbeStatus(
        name="comfy_bridge_plugin",
        status="online",
        detail=f"version {match.group(1)}",
        data={"version": match.group(1), "path": str(plugin_dir)},
    )


def _prompt_pool_probe(path: Path) -> ProbeStatus:
    if not path.is_file():
        return ProbeStatus(
            name="prompt_pool", status="missing", detail=f"not found: {path}"
        )
    try:
        data = read_json_object(path)
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            raise RepositoryError("prompts is not a list")
        enabled = sum(
            1
            for item in prompts
            if isinstance(item, dict) and bool(item.get("enabled", True))
        )
        return ProbeStatus(
            name="prompt_pool",
            status="online",
            detail=f"{enabled}/{len(prompts)} enabled",
            data={
                "path": str(path),
                "total": len(prompts),
                "enabled": enabled,
                "catalog_revision": data.get("catalog_revision"),
            },
        )
    except RepositoryError as exc:
        return ProbeStatus(name="prompt_pool", status="invalid", detail=str(exc))


def _preset_probe(path: Path) -> ProbeStatus:
    if not path.is_file():
        return ProbeStatus(
            name="presets", status="missing", detail=f"not found: {path}"
        )
    try:
        data = read_json_object(path)
        styles = data.get("styles")
        characters = data.get("characters")
        if not isinstance(styles, dict) or not isinstance(characters, dict):
            raise RepositoryError("styles or characters is not an object")
        return ProbeStatus(
            name="presets",
            status="online",
            detail=f"{len(styles)} styles, {len(characters)} characters",
            data={
                "path": str(path),
                "styles": len(styles),
                "characters": len(characters),
            },
        )
    except RepositoryError as exc:
        return ProbeStatus(name="presets", status="invalid", detail=str(exc))


def _disk_probe(path: Path, name: str) -> ProbeStatus:
    if not path.exists():
        return ProbeStatus(name=name, status="missing", detail=f"not found: {path}")
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return ProbeStatus(name=name, status="unknown", detail=str(exc))
    gib = 1024**3
    return ProbeStatus(
        name=name,
        status="online",
        detail=f"{usage.free / gib:.1f} GiB free",
        data={
            "path": str(path),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        },
    )


def _gpu_probe() -> ProbeStatus:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return ProbeStatus(
            name="nvidia_gpu", status="missing", detail="nvidia-smi not found"
        )
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ProbeStatus(name="nvidia_gpu", status="offline", detail=str(exc))
    devices = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            devices.append(
                {
                    "name": parts[0],
                    "memory_total_mib": int(parts[1]),
                    "memory_used_mib": int(parts[2]),
                    "utilization_percent": int(parts[3]),
                }
            )
        except ValueError:
            continue
    if not devices:
        return ProbeStatus(
            name="nvidia_gpu", status="unknown", detail="no parseable GPU data"
        )
    return ProbeStatus(
        name="nvidia_gpu",
        status="online",
        detail=f"{len(devices)} GPU detected",
        data={"devices": devices},
    )


async def collect_workstation_status(settings: Settings) -> WorkstationStatus:
    astrbot_headers = {}
    if settings.astrbot_api_key:
        astrbot_headers["Authorization"] = f"Bearer {settings.astrbot_api_key}"
    probes = await asyncio.gather(
        asyncio.to_thread(
            _http_probe,
            "astrbot",
            settings.astrbot_url,
            "/api/v1/openapi.json",
            timeout=settings.request_timeout_seconds,
            headers=astrbot_headers,
        ),
        asyncio.to_thread(
            _http_probe,
            "comfyui",
            settings.comfyui_url,
            "/system_stats",
            timeout=settings.request_timeout_seconds,
        ),
        asyncio.to_thread(_plugin_probe, settings.plugin_dir),
        asyncio.to_thread(_prompt_pool_probe, settings.prompt_pool_path),
        asyncio.to_thread(_preset_probe, settings.preset_path),
        asyncio.to_thread(_disk_probe, settings.comfyui_root, "comfyui_disk"),
        asyncio.to_thread(_disk_probe, settings.output_dir, "output_disk"),
        asyncio.to_thread(_gpu_probe),
    )
    essential = {
        probe.name: probe.status
        for probe in probes
        if probe.name in {"astrbot", "comfyui", "comfy_bridge_plugin"}
    }
    if all(status == "online" for status in essential.values()) and len(essential) == 3:
        overall = "ready"
    elif essential.get("astrbot") == "offline" and essential.get("comfyui") == "offline":
        overall = "offline"
    else:
        overall = "degraded"
    return WorkstationStatus(
        status=overall,
        checked_at=datetime.now().astimezone(),
        probes=list(probes),
    )

