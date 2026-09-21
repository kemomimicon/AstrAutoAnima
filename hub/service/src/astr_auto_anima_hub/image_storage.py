"""Administrator-only, snapshot based image maintenance. Never follows links."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

from .auth import require_admin


class StorageConfig(BaseModel):
    grouping: Literal["original", "style", "character", "user"] = "original"
    strip_metadata: bool = False
    scheduled: bool = False
    retention_days: int = Field(default=7, ge=1, le=3650)
    cleanup_hour: int = Field(default=4, ge=0, le=23)
    watermark: bool = False
    watermark_corner: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    watermark_folder: str = Field(default="Author Pictures", pattern=r"^[\w -]{1,80}$")


class StorageAction(BaseModel):
    area: Literal["cache", "random_style", "output", "author"]
    older_days: int = Field(default=0, ge=0, le=3650)
    snapshot: str = ""
    confirmed: bool = False
    acknowledge_unarchived: bool = False
    destination: str = ""
    include_recent: bool = False
    # None explicitly means all eligible folders; [] is never treated as all.
    folders: list[str] | None = Field(default=None, max_length=1000)


def checked(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in [path, *path.parents]:
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("路径包含链接，拒绝操作")
    return path


class ImageStorage:
    suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".image"}

    def __init__(self, settings, jobs):
        self.settings, self.jobs = settings, jobs
        self.config_path = settings.plugin_data_dir / "image_storage.json"
        self.snapshots = {}
        self.archived = set()
        self.task = None
        self.last_day = ""
        self.last_cleanup = "尚未执行"
        self.lock = asyncio.Lock()

    def config(self):
        path = checked(self.config_path)
        return StorageConfig.model_validate(json.loads(path.read_text("utf-8"))) if path.exists() else StorageConfig()

    def save(self, config):
        if config.watermark_folder.casefold() in {"aaa-randomstyle", "aaa-style", "aaa-character", "aaa-user", "models", "workflows"}:
            raise ValueError("签名目录名称保留，请换一个目录名")
        if config.watermark and not checked(self.settings.plugin_data_dir / "signature.png").is_file():
            raise ValueError("请先上传透明签名 PNG")
        path = checked(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = checked(path.with_name("image_storage." + uuid.uuid4().hex + ".tmp"))
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(config.model_dump(), stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
        return {"config": config.model_dump()}

    def root(self, area):
        output = self.settings.output_dir
        roots = {"cache": self.settings.plugin_data_dir / "outputs",
                 "random_style": output / "AAA-RandomStyle", "output": output,
                 "author": output / self.config().watermark_folder}
        return checked(roots[area])

    def inventory(self, area, older_days=0):
        root = self.root(area)
        rows = []
        skipped = 0
        cutoff = time.time() - max(300, older_days * 86400)
        if not root.exists():
            return rows, skipped
        if not root.is_dir():
            raise ValueError("图片根路径不是目录")
        for directory, dirs, names in os.walk(root, followlinks=False):
            base = checked(Path(directory))
            allowed = []
            for name in dirs:
                child = base / name
                if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                    skipped += 1
                elif area == "output" and base == root and name in {"AAA-RandomStyle", "Author Pictures", self.config().watermark_folder}:
                    continue
                else:
                    allowed.append(name)
            dirs[:] = allowed
            for name in names:
                path = base / name
                if path.suffix.lower() not in self.suffixes:
                    continue
                if path.is_symlink():
                    skipped += 1
                    continue
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                rows.append({"name": path.relative_to(root).as_posix(), "size": info.st_size,
                             "mtime": info.st_mtime_ns, "device": info.st_dev, "inode": info.st_ino,
                             "eligible": info.st_mtime < cutoff})
        return sorted(rows, key=lambda row: row["name"]), skipped

    def view(self):
        areas = []
        for area in ("cache", "random_style", "output", "author"):
            rows, skipped = self.inventory(area)
            folders = {}
            for row in rows:
                folder = str(Path(row["name"]).parent.as_posix())
                entry = folders.setdefault(folder, {"name": folder, "count": 0, "bytes": 0})
                entry["count"] += 1
                entry["bytes"] += row["size"]
            areas.append({"id": area, "path": str(self.root(area)), "count": len(rows),
                          "folders": [folders[name] for name in sorted(folders)],
                          "bytes": sum(r["size"] for r in rows), "skipped_links": skipped})
        return {"config": self.config().model_dump(), "areas": areas, "last_cleanup": self.last_cleanup}

    def preview(self, payload):
        rows, skipped = self.inventory(payload.area, payload.older_days)
        if payload.folders is not None:
            available = {Path(r["name"]).parent.as_posix() for r in rows}
            if not payload.folders or any(f not in available for f in payload.folders):
                raise ValueError("请选择当前盘点中的有效目录；空选择不会清理全部")
            selected = set(payload.folders)
            rows = [r for r in rows if Path(r["name"]).parent.as_posix() in selected]
        rows = [r for r in rows if r["eligible"] or payload.include_recent]
        token = uuid.uuid4().hex
        self.snapshots = {k: v for k, v in self.snapshots.items() if v["expires"] > time.time()}
        self.snapshots[token] = {"area": payload.area, "rows": rows, "expires": time.time() + 900}
        return {"snapshot": token, "count": len(rows), "bytes": sum(r["size"] for r in rows),
                "files": [r["name"] for r in rows], "skipped_links": skipped,
                "warning": ("打包本次图片清单，包含最近图片；源文件不修改。" if payload.include_recent else "仅清理本次清单内的图片，保留目录和任务记录；历史图片可能无法查看。最近五分钟的图片不会列入。")}

    def validate(self, payload):
        snap = self.snapshots.get(payload.snapshot)
        if not snap or snap["expires"] < time.time() or snap["area"] != payload.area:
            raise ValueError("清理清单过期，请重新盘点")
        root = self.root(payload.area)
        for row in snap["rows"]:
            path = checked(root / row["name"])
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("目标文件变化，停止操作")
            info = path.stat()
            if (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino) != (row["size"], row["mtime"], row["device"], row["inode"]):
                raise ValueError("目标文件变化，停止操作")
        return snap, root

    async def idle(self):
        if any(job.status in {"queued", "running"} for job in self.jobs._jobs.values()):
            raise ValueError("Hub 仍有排队或运行任务，请任务完成后清理")
        records = checked(self.settings.plugin_data_dir / "job_store" / "jobs")
        if records.is_dir():
            for path in records.glob("*.json"):
                job = json.loads(checked(path).read_text("utf-8-sig"))
                if job.get("status") in {"queued", "running"}:
                    raise ValueError("插件仍有未结束任务，请完成任务后清理（中断遗留任务请管理员先核实）")
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(str(self.settings.comfyui_url).rstrip("/") + "/queue")
            response.raise_for_status()
            queue = response.json()
        if not isinstance(queue, dict) or not all(key in queue for key in ("queue_running", "queue_pending")):
            raise ValueError("无法验证 ComfyUI 队列，禁止清理")
        if queue["queue_running"] or queue["queue_pending"]:
            raise ValueError("ComfyUI 队列不为空，请稍后清理")

    def archive(self, payload):
        snap, root = self.validate(payload)
        destination = Path(payload.destination).expanduser()
        if not destination.is_absolute():
            raise ValueError("打包位置必须是服务器绝对目录")
        destination = checked(destination)
        if not destination.is_dir():
            raise ValueError("打包目录不存在，请先在服务器创建")
        path = destination / ("AAA-" + payload.area + "-" + uuid.uuid4().hex + ".zip")
        hashes = {}
        temporary = path.with_suffix(".zip.partial")
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED) as archive:
            for row in snap["rows"]:
                source = checked(root / row["name"])
                digest = hashlib.sha256()
                with source.open("rb") as stream, archive.open(row["name"], "w", force_zip64=True) as target:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
                hashes[row["name"]] = digest.hexdigest()
            archive.writestr("AAA-SHA256.json", json.dumps(hashes))
        self.validate(payload)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("压缩包校验失败，不能作为清理依据")
        os.replace(temporary, path)
        self.archived.add(payload.snapshot)
        return {"path": str(path), "count": len(hashes), "verified": True}

    async def cleanup(self, payload, scheduled=False):
        async with self.lock:
            if not payload.confirmed:
                raise ValueError("需要二次确认")
            if not scheduled and payload.snapshot not in self.archived and not payload.acknowledge_unarchived:
                raise ValueError("建议先打包；仍要清理必须确认未打包警告")
            await self.idle()
            snap, root = self.validate(payload)
            if any(not row["eligible"] for row in snap["rows"]):
                raise ValueError("清单包含受保护的新图片，只能打包，不能清理")
            deleted = 0
            try:
                for row in snap["rows"]:
                    # Revalidate every remaining file immediately before unlink, no recursive deletion.
                    path = checked(root / row["name"])
                    info = path.stat()
                    if (info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev) != (row["size"], row["mtime"], row["inode"], row["device"]):
                        raise ValueError("文件变化，停止清理")
                    path.unlink()
                    deleted += 1
            except OSError as exc:
                raise ValueError(f"已清理 {deleted} 张后遇到文件错误，已停止，不会强制重试") from exc
            finally:
                self.snapshots.pop(payload.snapshot, None)
            self.last_cleanup = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {payload.area}: {deleted} 张"
            return {"deleted": deleted, "message": "图片已永久删除，任务记录保留；可从自行保存的压缩包恢复。"}

    async def scheduler(self):
        while True:
            await asyncio.sleep(30)
            try:
                config = self.config()
                today = time.strftime("%Y-%m-%d")
                if config.scheduled and time.localtime().tm_hour == config.cleanup_hour and self.last_day != today:
                    action = StorageAction(area="cache", older_days=config.retention_days, confirmed=True)
                    action.snapshot = self.preview(action)["snapshot"]
                    await self.cleanup(action, scheduled=True)
                    self.last_day = today
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_cleanup = "自动清理未执行：" + str(exc)[:200]


router = APIRouter(prefix="/api/v1/admin/storage", dependencies=[Depends(require_admin)])


class SignatureUpload(BaseModel):
    data: str = Field(max_length=6_000_000)


@router.post("/signature")
async def signature(payload: SignatureUpload, request: Request):
    import base64
    import io
    from PIL import Image
    try:
        content = base64.b64decode(payload.data, validate=True)
        with Image.open(io.BytesIO(content)) as picture:
            if picture.format != "PNG" or picture.width * picture.height > 4_000_000:
                raise ValueError("请上传不超过400万像素的透明 PNG")
            picture.load()
            if 'A' not in picture.getbands() and 'transparency' not in picture.info:
                raise ValueError("签名图片需要透明通道")
            clean = io.BytesIO()
            picture.convert("RGBA").save(clean, format="PNG")
        path = checked(request.app.state.settings.plugin_data_dir / "signature.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = checked(path.with_name(uuid.uuid4().hex + ".png.tmp"))
        with temporary.open("xb") as stream:
            stream.write(clean.getvalue())
        os.replace(temporary, path)
        return {"saved": True}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


class ManualWatermark(BaseModel):
    job_id: str
    image_id: str


@router.post("/watermark")
async def manual_watermark(payload: ManualWatermark, request: Request, principal=Depends(require_admin)):
    import importlib.util
    manager = request.app.state.image_storage
    try:
        located = manager.jobs.get_image(payload.job_id, payload.image_id, principal)
        if located is None:
            raise ValueError("任务图片不存在或不可访问")
        # The management endpoint is admin-only, matching explicit administrator exemption.
        source = checked(manager.settings.plugin_dir / "output_storage_runtime.py")
        spec = importlib.util.spec_from_file_location("aaa_output_storage", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = await asyncio.to_thread(module.watermark_image, located[1], manager.settings.plugin_data_dir,
                                       manager.settings.output_dir, manager.config().model_dump())
        return {"path": str(path), "message": "签名副本已保存，原图未改动；可从签名图片区打包下载。"}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
async def view(request: Request):
    try:
        return await asyncio.to_thread(request.app.state.image_storage.view)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/config")
async def configure(payload: StorageConfig, request: Request):
    try:
        return request.app.state.image_storage.save(payload)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{operation}")
async def action(operation: str, payload: StorageAction, request: Request):
    manager = request.app.state.image_storage
    try:
        if operation == "preview":
            return await asyncio.to_thread(manager.preview, payload)
        if operation == "archive":
            return await asyncio.to_thread(manager.archive, payload)
        if operation == "cleanup":
            return await manager.cleanup(payload)
        raise HTTPException(404)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
