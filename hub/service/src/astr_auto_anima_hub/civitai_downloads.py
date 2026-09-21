"""Admin-only, opt-in LoRA downloader. Credentials never enter job records."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from .lora_catalog import scan_loras, update_lora
from .lora_sharing import civitai_source_url
from .schemas import LoraCatalogUpdateRequest


class DownloadRequest(BaseModel):
    version_id: int = Field(gt=0)
    file_id: int = Field(gt=0)
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    subdirectory: str = Field(default="anima_lora", max_length=200)
    create_directory: bool = False
    trained_words: list[str] | None = Field(default=None, max_length=100)


def safe_download_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = host == "civitai.com" or host.endswith(".civitai.com") or host.endswith(".r2.cloudflarestorage.com")
    if not allowed or parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("下载地址不在允许的 HTTPS 模型域名内")
    return url


def select_file(data: dict, request: DownloadRequest, max_bytes: int) -> dict:
    if data.get("model", {}).get("type", "").lower() not in {"lora", "locon"}:
        raise ValueError("仅允许下载 LoRA/LoCon")
    if "anima" not in str(data.get("baseModel", "")).lower():
        raise ValueError("该版本未声明为 Anima 底模，拒绝自动安装")
    files = [item for item in data.get("files", []) if item.get("id") == request.file_id]
    if len(files) != 1:
        raise ValueError("目标文件不存在或不可下载")
    item = files[0]
    sha = str(item.get("hashes", {}).get("SHA256", "")).lower()
    if sha != request.expected_sha256.lower():
        raise ValueError("文件哈希与预览确认值不一致，请刷新版本信息")
    if not str(item.get("name", "")).lower().endswith(".safetensors") or item.get("type") != "Model":
        raise ValueError("仅接受 safetensors 模型文件")
    size = int(float(item.get("sizeKB", 0)) * 1024)
    if not 0 < size <= max_bytes:
        raise ValueError("文件大小未知或超出下载额度")
    for key in ("virusScanResult", "pickleScanResult"):
        if str(item.get(key, "")).lower() not in {"success", "safe"}:
            raise ValueError("文件安全扫描未通过或状态未知")
    return {"file_id": request.file_id, "sha256": sha, "size_bytes": size,
            "source_url": civitai_source_url(data, request.version_id),
            "url": safe_download_url(item["downloadUrl"]),
            "trained_words": list(data.get("trainedWords", [])),
            "model_name": str(data.get("model", {}).get("name", ""))}


class CivitaiDownloads:
    def __init__(self, settings):
        self.settings = settings
        self.jobs: dict[str, dict] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Semaphore(1)
        self.root = settings.hub_state_dir / "civitai_downloads"
        self.token = os.getenv("AAH_CIVITAI_TOKEN", "").strip()
        self.enabled = os.getenv("AAH_CIVITAI_DOWNLOAD_ENABLED", "0") == "1"
        self.max_bytes = 4 * 1024**3

    def _check(self):
        if not self.enabled:
            raise ValueError("Civitai 下载未启用：设置 AAH_CIVITAI_DOWNLOAD_ENABLED=1")

    async def preview(self, version_id: int) -> dict:
        self._check()
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(f"https://civitai.com/api/v1/model-versions/{version_id}", headers=headers)
            if response.status_code != 200:
                raise ValueError(f"Civitai 元数据请求失败（HTTP {response.status_code}）；检查授权、资源状态或网络")
            if len(response.content) > 4 * 1024**2:
                raise ValueError("元数据响应过大")
            return response.json()

    async def versions(self, model_id: int):
        self._check()
        if model_id <= 0:
            raise ValueError("模型ID必须为正整数")
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(f"https://civitai.com/api/v1/models/{model_id}", headers=headers)
            if response.status_code != 200 or len(response.content) > 8 * 1024**2:
                raise ValueError("读取模型版本失败，请检查链接或授权")
            data = response.json()
        return {"name": str(data.get("name", "")), "versions": [
            {"id": row.get("id"), "name": str(row.get("name", "")), "base_model": str(row.get("baseModel", ""))}
            for row in data.get("modelVersions", [])]}

    def destination(self, relative, create=False):
        from .image_storage import checked
        parts = str(relative).replace("\\", "/").split("/")
        if len(str(relative)) > 200 or not parts or any(not re.fullmatch(r"[\w -]{1,80}", part) for part in parts):
            raise ValueError("保存目录必须是 LoRA 根目录下的相对目录名，禁止 .. 和绝对路径")
        if any(len(part.encode("utf-8")) > 240 for part in parts):
            raise ValueError("每层保存目录最多 80 个字符且不超过 240 个 UTF-8 字节")
        root = checked(self.settings.lora_root)
        target = checked(root.joinpath(*parts))
        if not target.exists() and create:
            target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise ValueError("目录不存在，请勾选新建目录")
        return target

    def save(self, job):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (job["id"] + ".json")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def list_jobs(self):
        saved = {}
        if self.root.is_dir():
            for path in self.root.glob("*.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job["status"] in {"queued", "downloading"} and job["id"] not in self.tasks:
                        job["status"] = "interrupted"
                    saved[job["id"]] = job
                except (OSError, ValueError, KeyError):
                    continue
        saved.update(self.jobs)
        return list(saved.values())[-100:]

    async def submit(self, request: DownloadRequest):
        self._check()
        if sum(not task.done() for task in self.tasks.values()) >= 10:
            raise ValueError("下载队列已满（最多10项）")
        data = await self.preview(request.version_id)
        item = select_file(data, request, self.max_bytes)
        self.destination(request.subdirectory, request.create_directory or request.subdirectory in {"anima_lora", "civitai"})
        if request.trained_words is not None:
            if any(len(word) > 500 for word in request.trained_words):
                raise ValueError("触发词过长")
            item["trained_words"] = request.trained_words
        if sum(not task.done() for task in self.tasks.values()) >= 10:
            raise ValueError("下载队列已满（最多10项）")
        for job in self.jobs.values():
            if job["sha256"] == item["sha256"] and job["status"] in {"queued", "downloading", "succeeded"}:
                return job
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "version_id": request.version_id, "file_id": request.file_id,
               "sha256": item["sha256"], "status": "queued", "downloaded": 0,
               "size_bytes": item["size_bytes"], "trained_words": item["trained_words"],
               "model_name": item["model_name"], "message": ""}
        job["source_url"] = item["source_url"]
        job["subdirectory"] = request.subdirectory
        self.jobs[job_id] = job
        self.save(job)
        self.tasks[job_id] = asyncio.create_task(self.run(job, item))
        return dict(job)

    async def cancel(self, job_id: str):
        task = self.tasks.get(job_id)
        if task is None or task.done():
            raise ValueError("任务不在运行队列中")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its coroutine starts still needs a terminal record.
        if self.jobs[job_id]["status"] in {"queued", "downloading"}:
            self.jobs[job_id]["status"] = "cancelled"
            self.save(self.jobs[job_id])
        return self.jobs[job_id]

    async def resume(self, job_id: str):
        self._check()
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("无效下载任务ID")
        job = next((item for item in self.list_jobs() if item.get("id") == job_id), None)
        if not job or job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError("只有失败、取消或中断任务可以续传")
        request = DownloadRequest(version_id=job["version_id"], file_id=job["file_id"], expected_sha256=job["sha256"])
        item = select_file(await self.preview(request.version_id), request, self.max_bytes)
        item["trained_words"] = job.get("trained_words", item["trained_words"])
        if sum(not task.done() for task in self.tasks.values()) >= 10:
            raise ValueError("下载队列已满")
        if job_id in self.tasks and not self.tasks[job_id].done():
            raise ValueError("任务已在运行")
        job.update(status="queued", message="")
        self.jobs[job_id] = job
        self.save(job)
        self.tasks[job_id] = asyncio.create_task(self.run(job, item))
        return dict(job)

    def _register_download(self, job, item, target):
        """Register even already-present or resumed files, preserving admin edits."""
        job["source_url"] = item.get("source_url", "")
        try:
            result = scan_loras(self.settings, actor="civitai-download")
            relative = target.relative_to(self.settings.lora_root).as_posix()
            entry = next(x for x in result.items if x.path == relative)
            changes = {}
            if not entry.source_url and job["source_url"]:
                changes["source_url"] = job["source_url"]
            if not entry.recommended_prompt:
                words = list(dict.fromkeys(str(x).strip() for x in item.get("trained_words", []) if str(x).strip()))
                if words:
                    changes["recommended_prompt"] = ", ".join(words)
            if changes:
                update_lora(self.settings, relative, LoraCatalogUpdateRequest(**changes),
                            result.revision, "civitai-download")
        except Exception:
            job["message"] = "下载校验成功；扫描或来源登记失败，请重新扫描并检查来源信息"

    async def run(self, job, item):
        try:
            async with self.lock:
                target_root = self.destination(job.get("subdirectory", "civitai"), True)
                if target_root.is_symlink():
                    raise ValueError("目标目录不能是符号链接")
                target_root.mkdir(parents=True, exist_ok=True)
                if not target_root.resolve().is_relative_to(self.settings.lora_root.resolve()):
                    raise ValueError("目标目录越界")
                target = target_root / f"{job['version_id']}_{item['sha256'][:16]}.safetensors"
                if target.exists():
                    if target.is_symlink() or await asyncio.to_thread(file_hash, target) != item["sha256"]:
                        raise ValueError("目标文件已存在但哈希不匹配，不会覆盖")
                    job.update(status="succeeded", downloaded=target.stat().st_size, path=str(target))
                    await asyncio.to_thread(self._register_download, job, item, target)
                    return
                part = target_root / f".{job['id']}.part"
                if part.is_symlink() or (part.exists() and not part.is_file()):
                    raise ValueError("临时文件类型异常，拒绝写入")
                offset = part.stat().st_size if part.is_file() else 0
                if offset > self.max_bytes:
                    raise ValueError("临时文件超过下载额度")
                # A previous run may have completed the bytes but failed publishing.
                if offset and await asyncio.to_thread(file_hash, part) == item["sha256"]:
                    os.link(part, target)
                    part.unlink()
                    job.update(status="succeeded", downloaded=offset, path=str(target))
                    await asyncio.to_thread(self._register_download, job, item, target)
                    return
                if shutil.disk_usage(target_root).free < max(0, item["size_bytes"] - offset) + 1024**3:
                    raise ValueError("空间不足：需要模型剩余容量外再预留1GiB")
                job["downloaded"] = offset
                job["status"] = "downloading"
                self.save(job)
                # Stream redirects manually: never forward credentials to a CDN.
                url = item["url"]
                async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20), follow_redirects=False) as client:
                    for hop in range(6):
                        safe_download_url(url)
                        headers = {"Authorization": f"Bearer {self.token}"} if self.token and urlparse(url).hostname == "civitai.com" else {}
                        if offset:
                            headers["Range"] = f"bytes={offset}-"
                        async with client.stream("GET", url, headers=headers) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                from urllib.parse import urljoin
                                url = urljoin(url, response.headers.get("location", ""))
                                continue
                            if offset and (response.status_code != 206 or not response.headers.get("content-range", "").startswith(f"bytes {offset}-")):
                                raise ValueError("服务器未接受断点范围；保留临时文件，不会错误拼接或覆盖")
                            if not offset and response.status_code != 200:
                                raise ValueError(f"模型下载失败（HTTP {response.status_code}）；授权限制不会被绕过")
                            digest = await asyncio.to_thread(partial_hash, part) if offset else hashlib.sha256()
                            with part.open("ab" if offset else "xb") as stream:
                                async for chunk in response.aiter_bytes(1024 * 1024):
                                    job["downloaded"] += len(chunk)
                                    if job["downloaded"] > self.max_bytes:
                                        raise ValueError("下载超过4GiB限制")
                                    if shutil.disk_usage(target_root).free < len(chunk) + 1024**3:
                                        raise ValueError("剩余空间低于1GiB，已停止")
                                    stream.write(chunk)
                                    digest.update(chunk)
                            if digest.hexdigest() != item["sha256"]:
                                raise ValueError("SHA256 校验失败；临时文件不会被扫描为LoRA")
                            # Exclusive publish: no overwrite even if another writer raced us.
                            os.link(part, target)
                            part.unlink()
                            job.update(status="succeeded", path=str(target))
                            await asyncio.to_thread(self._register_download, job, item, target)
                            break
                    else:
                        raise ValueError("下载重定向过多")
        except asyncio.CancelledError:
            job.update(status="cancelled", message="已取消；临时文件保留，不会作为LoRA加载")
        except ValueError as exc:
            job.update(status="failed", message=str(exc))
        except Exception:
            # HTTP exception strings can contain signed URLs; never store them.
            job.update(status="failed", message="网络或文件操作失败；临时文件保留，可检查磁盘与连接后重试")
        finally:
            self.save(job)

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def file_hash(path: Path) -> str:
    return partial_hash(path).hexdigest()


def partial_hash(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest
