from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import math
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .auth import AuthPrincipal, SYSTEM_ADMIN
from .config import Settings
from .schemas import (
    DeliveryTarget,
    DeliveryTargetListResponse,
    RemoteJobCreateRequest,
    RemoteJobImage,
    RemoteJobPage,
    RemoteJobResponse,
)


class RemoteJobError(RuntimeError):
    pass


_UMO_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+:(?P<message_type>GroupMessage|FriendMessage):[A-Za-z0-9_.-]+$"
)
_POOL_PATTERN = re.compile(r"^[BGDCRNHS](?:[BGDCRNHS,/]*[BGDCRNHS])?$")
_MAX_MEDIA_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_IMAGE_BYTES = 20 * 1024 * 1024
_SOURCE_IMAGE_MIME_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


@dataclass(frozen=True, slots=True)
class _TargetRecord:
    public: DeliveryTarget
    umo: str
    allow_safety: frozenset[str]


def _now() -> datetime:
    return datetime.now().astimezone()


def load_delivery_targets(path: Path) -> list[_TargetRecord]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemoteJobError(f"invalid delivery targets file: {exc}") from exc
    raw_targets = payload.get("targets", []) if isinstance(payload, dict) else []
    if not isinstance(raw_targets, list):
        raise RemoteJobError("delivery targets file must contain a targets list")
    records: list[_TargetRecord] = []
    seen: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, dict) or not bool(raw.get("enabled", True)):
            continue
        target_id = str(raw.get("id", "")).strip()
        label = str(raw.get("label", "")).strip()
        umo = str(raw.get("umo", "")).strip()
        match = _UMO_PATTERN.fullmatch(umo)
        if not match:
            raise RemoteJobError(f"invalid UMO for delivery target {target_id!r}")
        inferred_kind = (
            "group" if match.group("message_type") == "GroupMessage" else "private"
        )
        kind = str(raw.get("kind", inferred_kind)).strip().casefold()
        if kind != inferred_kind:
            raise RemoteJobError(f"delivery target kind does not match UMO: {target_id}")
        public = DeliveryTarget(id=target_id, label=label, kind=kind)
        if public.id in seen:
            raise RemoteJobError(f"duplicate delivery target id: {public.id}")
        seen.add(public.id)
        default_safety = ["N", "H"] if kind == "group" else ["N", "H", "S"]
        raw_safety = raw.get("allow_safety", default_safety)
        allow_safety = frozenset(
            str(value).upper() for value in raw_safety if str(value).upper() in {"N", "H", "S"}
        )
        if not allow_safety:
            raise RemoteJobError(f"delivery target has no allowed safety levels: {public.id}")
        records.append(_TargetRecord(public=public, umo=umo, allow_safety=allow_safety))
    return records


def list_delivery_targets(settings: Settings) -> DeliveryTargetListResponse:
    return DeliveryTargetListResponse(
        targets=[record.public for record in load_delivery_targets(settings.delivery_targets_path)]
    )


def _self_private_target(settings: Settings, principal: AuthPrincipal) -> _TargetRecord:
    if principal.role != "user" or not principal.qq:
        raise RemoteJobError("this token is not bound to a private QQ target")
    return _TargetRecord(
        public=DeliveryTarget(id="self-private", label="我的 QQ 私聊", kind="private"),
        umo=f"{settings.astrbot_bot_id}:FriendMessage:{principal.qq}",
        allow_safety=frozenset({"N", "H", "S"}),
    )


def visible_delivery_targets(
    settings: Settings, principal: AuthPrincipal
) -> list[_TargetRecord]:
    configured = load_delivery_targets(settings.delivery_targets_path)
    if principal.is_admin:
        return configured
    groups = [record for record in configured if record.public.kind == "group"]
    if principal.role == "legacy_lite":
        return groups
    result = groups if principal.allow_group else []
    if any(record.public.id == "self-private" for record in configured):
        raise RemoteJobError("configured target id 'self-private' is reserved")
    return [*result, _self_private_target(settings, principal)]


def _normalize_pool_filter(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").upper())
    if normalized and not _POOL_PATTERN.fullmatch(normalized):
        raise RemoteJobError("invalid prompt pool filter")
    return normalized


def _filter_safety(value: str) -> set[str]:
    return {char for char in value if char in {"N", "H", "S"}}


def build_remote_command(
    payload: RemoteJobCreateRequest, target: _TargetRecord
) -> tuple[str, str]:
    pool_filter = _normalize_pool_filter(payload.pool_filter)
    effective_safety = payload.safety_code
    selected_safety = _filter_safety(pool_filter)
    if selected_safety:
        if len(selected_safety) != 1:
            raise RemoteJobError("remote delivery requires one explicit safety level")
        effective_safety = next(iter(selected_safety))

    random_kind = payload.kind in {"random", "chaos"}
    if random_kind:
        if not pool_filter:
            pool_filter = effective_safety
        elif not selected_safety:
            pool_filter = f"{pool_filter}/{effective_safety}"
    elif pool_filter:
        raise RemoteJobError("prompt pool filters are only valid for random jobs")

    if effective_safety not in target.allow_safety:
        raise RemoteJobError(
            f"target {target.public.label} does not allow safety level {effective_safety}"
        )
    if target.public.kind == "group" and effective_safety == "S":
        raise RemoteJobError("group delivery does not allow S content")
    if payload.kind == "reverse" and target.public.kind != "private":
        raise RemoteJobError("reverse generation can only be delivered to a private target")
    if payload.five_draw and not random_kind:
        raise RemoteJobError("five draw is only valid for random or chaos jobs")

    prefix = {
        ("direct", False): "/aimg",
        ("direct", True): "/aimg",
        ("chinese", False): "/aicn",
        ("chinese", True): "/aicn",
        ("reverse", False): "/aip",
        ("reverse", True): "/aip",
        ("random", False): "来张好图抄一抄",
        ("random", True): "来张好图五连抽",
        ("chaos", False): "来张好图混沌时刻",
        ("chaos", True): "来张好图混沌五连抽",
        ("hq", False): "/ahq",
        ("hq", True): "/ahq",
        ("refine", False): "/arefine",
        ("refine", True): "/arefine",
    }[(payload.kind, payload.five_draw)]
    parts = [prefix]
    if payload.kind == "hq":
        parts.append(payload.profile or "stable")
    elif payload.kind == "refine":
        parts.append(payload.profile or "light")
    if payload.kind == "reverse":
        if payload.reverse_only:
            parts.append("仅反推")
        categories = list(dict.fromkeys(payload.reverse_categories))
        if categories:
            labels = {
                "scene": "场景",
                "action": "动作",
                "character": "角色",
                "appearance": "外观",
                "clothing": "服装",
                "composition": "构图",
                "other": "其他",
                "safety": "安全",
            }
            parts.append("分类=" + ",".join(labels[value] for value in categories))
        else:
            parts.append(f"模式={payload.reverse_preset}")
    if random_kind and pool_filter:
        parts.append(pool_filter)
    if payload.kind != "chaos":
        if payload.character.strip():
            parts.append(f"角色={payload.character.strip()}")
        if payload.style.strip():
            parts.append(f"画风={payload.style.strip()}")
        if payload.ratio:
            parts.append(f"比例={payload.ratio}")
    if payload.sampler:
        parts.append(f"采样器={payload.sampler}")
    if payload.steps is not None:
        parts.append(f"步数={payload.steps}")
    if payload.cfg is not None:
        parts.append(f"CFG={payload.cfg:g}")
    if payload.scale is not None:
        parts.append(f"放大={payload.scale:g}")
    if payload.denoise is not None:
        parts.append(f"重绘={payload.denoise:g}")
    if payload.parent_job_id.strip():
        if payload.kind != "refine":
            raise RemoteJobError("parent_job_id is only valid for refine jobs")
        parts.append(f"任务={payload.parent_job_id.strip()}")
    if payload.prompt.strip():
        parts.append(payload.prompt.strip())
    if payload.kind in {"direct", "chinese", "hq"} and not payload.prompt.strip():
        raise RemoteJobError(f"{payload.kind} generation requires a prompt")
    return " ".join(parts), effective_safety


def _decode_source_image(payload: RemoteJobCreateRequest) -> tuple[bytes, str, str] | None:
    encoded = payload.source_image_data.strip()
    image_kinds = {"reverse", "refine"}
    if payload.kind not in image_kinds:
        if encoded or payload.source_image_name.strip():
            raise RemoteJobError("source images are only valid for reverse/refine jobs")
        return None
    if not encoded:
        if payload.kind == "refine" and payload.parent_job_id.strip():
            return None
        raise RemoteJobError(f"{payload.kind} generation requires a source image")
    try:
        header, body = encoded.split(",", 1)
    except ValueError as exc:
        raise RemoteJobError("source image must be a base64 data URI") from exc
    match = re.fullmatch(r"data:([^;,]+);base64", header, flags=re.IGNORECASE)
    if not match:
        raise RemoteJobError("source image must be a base64 data URI")
    mime = match.group(1).casefold()
    signatures = _SOURCE_IMAGE_MIME_TYPES.get(mime)
    if signatures is None:
        raise RemoteJobError("source image must be JPEG, PNG, or WebP")
    try:
        content = base64.b64decode(body, validate=True)
    except binascii.Error as exc:
        raise RemoteJobError("source image contains invalid base64 data") from exc
    if not content:
        raise RemoteJobError("source image is empty")
    if len(content) > _MAX_SOURCE_IMAGE_BYTES:
        raise RemoteJobError("source image exceeds the 20 MiB upload limit")
    if mime == "image/webp":
        valid_signature = content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    else:
        valid_signature = any(content.startswith(signature) for signature in signatures)
    if not valid_signature:
        raise RemoteJobError("source image content does not match its media type")
    default_extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
    supplied_name = Path(payload.source_image_name.strip()).name
    filename = supplied_name or f"{payload.kind}-source{default_extension}"
    return content, filename, mime


def _find_attachment_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("attachment_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for nested in value.values():
            found = _find_attachment_id(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_attachment_id(nested)
            if found:
                return found
    return ""


def _find_media_reference(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("file", "path", "file_path", "url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            found = _find_media_reference(nested)
            if found:
                return found
    return ""


def _filename_from_content_disposition(value: str) -> str:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        return Path(unquote(encoded.group(1).strip())).name
    quoted = re.search(r'filename="([^"]+)"', value, re.IGNORECASE)
    if quoted:
        return Path(quoted.group(1).strip()).name
    plain = re.search(r"filename=([^;]+)", value, re.IGNORECASE)
    if plain:
        return Path(plain.group(1).strip().strip('"')).name
    return ""


def _detected_image_type(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


class RemoteJobManager:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._jobs: dict[str, RemoteJobResponse] = {}
        self._owners: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(1)
        self._records_dir = self.settings.remote_job_store_dir / "records"
        self._media_dir = self.settings.remote_job_store_dir / "media"
        self._load_persisted_jobs()

    def _record_path(self, job_id: str) -> Path:
        return self._records_dir / f"{job_id}.json"

    def _persist(self, job_id: str) -> None:
        job = self._jobs[job_id]
        owner = self._owners[job_id]
        payload = {
            "schema_version": "1.0",
            "owner": owner,
            "job": job.model_dump(mode="json"),
        }
        path = self._record_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _load_persisted_jobs(self) -> None:
        if not self._records_dir.is_dir():
            return
        interrupted: list[str] = []
        for path in sorted(self._records_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                owner = str(payload.get("owner", "")).strip()
                job = RemoteJobResponse.model_validate(payload.get("job", {}))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if not owner or path.stem != job.id:
                continue
            if job.status in {"queued", "running"}:
                job = job.model_copy(
                    update={
                        "status": "failed",
                        "message": "Hub 重启，未完成任务已终止",
                        "updated_at": _now(),
                    }
                )
                interrupted.append(job.id)
            self._jobs[job.id] = job
            self._owners[job.id] = owner
        for job_id in interrupted:
            self._persist(job_id)

    def targets(
        self, principal: AuthPrincipal = SYSTEM_ADMIN
    ) -> DeliveryTargetListResponse:
        return DeliveryTargetListResponse(
            targets=[
                record.public
                for record in visible_delivery_targets(self.settings, principal)
            ]
        )

    def create(
        self,
        payload: RemoteJobCreateRequest,
        principal: AuthPrincipal = SYSTEM_ADMIN,
    ) -> RemoteJobResponse:
        targets = {
            record.public.id: record
            for record in visible_delivery_targets(self.settings, principal)
        }
        target = targets.get(payload.target_id)
        if target is None:
            raise RemoteJobError("unknown or disabled delivery target")
        command, _ = build_remote_command(payload, target)
        source_image = _decode_source_image(payload)
        if not self.settings.astrbot_api_key:
            raise RemoteJobError("AAH_ASTRBOT_API_KEY is not configured")
        now = _now()
        job = RemoteJobResponse(
            id=uuid.uuid4().hex,
            status="queued",
            kind=payload.kind,
            safety_code=payload.safety_code,
            profile=payload.profile,
            target_id=target.public.id,
            target_label=target.public.label,
            command_preview=command,
            message="任务已进入队列",
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.id] = job
        self._owners[job.id] = principal.subject
        self._persist(job.id)
        task = asyncio.create_task(
            self._run(
                job.id,
                command,
                target,
                principal.chat_username,
                source_image,
                payload.kind == "reverse" and payload.reverse_only,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(
        self, job_id: str, principal: AuthPrincipal = SYSTEM_ADMIN
    ) -> RemoteJobResponse | None:
        if not principal.is_admin and self._owners.get(job_id) != principal.subject:
            return None
        return self._jobs.get(job_id)

    def list(
        self,
        principal: AuthPrincipal = SYSTEM_ADMIN,
        *,
        kind: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> RemoteJobPage:
        normalized_kind = str(kind or "").strip().casefold()
        normalized_status = str(status or "").strip().casefold()
        allowed_kinds = {
            "direct", "chinese", "reverse", "random", "chaos", "hq", "refine"
        }
        allowed_statuses = {"queued", "running", "succeeded", "failed"}
        if normalized_kind and normalized_kind not in allowed_kinds:
            raise RemoteJobError("invalid remote job kind filter")
        if normalized_status and normalized_status not in allowed_statuses:
            raise RemoteJobError("invalid remote job status filter")
        jobs = [
            job
            for job_id, job in self._jobs.items()
            if (principal.is_admin or self._owners.get(job_id) == principal.subject)
            and (not normalized_kind or job.kind == normalized_kind)
            and (not normalized_status or job.status == normalized_status)
        ]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        total = len(jobs)
        pages = max(1, math.ceil(total / page_size))
        if page > pages:
            raise RemoteJobError("remote job page out of range")
        start = (page - 1) * page_size
        return RemoteJobPage(
            items=jobs[start : start + page_size],
            page=page,
            pages=pages,
            total=total,
        )

    def get_image(
        self,
        job_id: str,
        image_id: str,
        principal: AuthPrincipal = SYSTEM_ADMIN,
    ) -> tuple[RemoteJobImage, Path] | None:
        job = self.get(job_id, principal)
        if job is None:
            return None
        image = next((item for item in job.images if item.id == image_id), None)
        if image is None:
            return None
        suffix = Path(image.filename).suffix.casefold()
        path = self._media_dir / job_id / f"{image.id}{suffix}"
        if not path.is_file():
            return None
        return image, path

    def _update(self, job_id: str, **changes: Any) -> None:
        current = self._jobs[job_id]
        self._jobs[job_id] = current.model_copy(
            update={**changes, "updated_at": _now()}
        )
        self._persist(job_id)

    async def shutdown(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(
        self,
        job_id: str,
        command: str,
        target: _TargetRecord,
        username: str,
        source_image: tuple[bytes, str, str] | None = None,
        text_only: bool = False,
    ) -> None:
        async with self._semaphore:
            self._update(job_id, status="running", message="AstrBot 正在生成")
            try:
                plain, attachments, images = await asyncio.wait_for(
                    self._chat_and_collect(
                        job_id,
                        command,
                        username,
                        source_image=source_image,
                        allow_text_only=text_only,
                    ),
                    timeout=self.settings.remote_job_timeout_seconds,
                )
                message = plain[-1] if plain else "生成完成"
                await self._send_im(target.umo, message, attachments)
                self._update(
                    job_id,
                    status="succeeded",
                    message=f"已发送到 {target.public.label}",
                    images=images,
                )
            except Exception as exc:
                self._update(job_id, status="failed", message=str(exc)[:500])

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.astrbot_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.settings.astrbot_api_key}"},
            timeout=httpx.Timeout(self.settings.remote_job_timeout_seconds),
            transport=self._transport,
        )

    async def _chat_and_collect(
        self,
        job_id: str,
        command: str,
        username: str,
        *,
        source_image: tuple[bytes, str, str] | None = None,
        allow_text_only: bool = False,
    ) -> tuple[list[str], list[str], list[RemoteJobImage]]:
        plain: list[str] = []
        attachments: list[str] = []
        images: list[RemoteJobImage] = []
        async with self._client() as client:
            message: str | list[dict[str, str]] = command
            if source_image is not None:
                content, filename, mime = source_image
                source_attachment = await self._upload_bytes(
                    client, content, filename, mime
                )
                message = [
                    {"type": "plain", "text": command},
                    {"type": "image", "attachment_id": source_attachment},
                ]
            async with client.stream(
                "POST",
                "/api/v1/chat",
                json={
                    "username": username,
                    "session_id": f"hub_job_{job_id}",
                    "message": message,
                    "enable_streaming": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    event_type = str(event.get("type", ""))
                    data = event.get("data")
                    if event_type == "plain" and isinstance(data, str):
                        if "已提交生成请求" not in data:
                            plain.append(data)
                    elif event_type == "attachment_saved":
                        attachment_id = _find_attachment_id(data)
                        attachment_type = (
                            str(data.get("type", ""))
                            if isinstance(data, dict)
                            else ""
                        )
                        if (
                            attachment_id
                            and attachment_type == "image"
                            and attachment_id not in attachments
                        ):
                            attachments.append(attachment_id)
                            stored = await self._store_attachment(
                                job_id, client, attachment_id
                            )
                            if stored is not None and all(
                                item.sha256 != stored.sha256 for item in images
                            ):
                                images.append(stored)
                    elif event_type in {"image", "file"}:
                        attachment_id = _find_attachment_id(data)
                        reference = _find_media_reference(data)
                        stored = await self._store_media_reference(job_id, reference)
                        if stored is not None and all(
                            item.sha256 != stored.sha256 for item in images
                        ):
                            images.append(stored)
                        if not attachment_id:
                            if reference.startswith(("[IMAGE]", "[FILE]")):
                                continue
                            attachment_id = await self._upload_reference(
                                client, reference
                            )
                        if attachment_id and attachment_id not in attachments:
                            attachments.append(attachment_id)
                    elif event_type == "error":
                        raise RemoteJobError(str(data or "AstrBot chat failed"))
        if plain and plain[-1].startswith("生成失败"):
            raise RemoteJobError(plain[-1])
        if not attachments and not (allow_text_only and plain):
            raise RemoteJobError(
                "AstrBot 已处理任务但未返回可投递结果；请检查 SSE 事件格式"
            )
        return plain, attachments, images

    async def _store_media_reference(
        self, job_id: str, reference: str
    ) -> RemoteJobImage | None:
        normalized = str(reference or "").strip()
        for prefix in ("[IMAGE]", "[FILE]"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        if not normalized:
            return None
        filename = "generated-image.png"
        content_type = "image/png"
        content: bytes | None = None
        source_path: Path | None = None
        if normalized.startswith("data:"):
            try:
                header, encoded = normalized.split(",", 1)
                if ";base64" not in header:
                    return None
                content_type = header[5:].split(";", 1)[0] or content_type
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                return None
        elif normalized.startswith("base64://"):
            try:
                content = base64.b64decode(normalized[9:], validate=True)
            except binascii.Error:
                return None
        elif normalized.startswith(("http://", "https://")):
            parsed = urlparse(normalized)
            filename = Path(unquote(parsed.path)).name or filename
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.remote_job_timeout_seconds),
                follow_redirects=True,
                transport=self._transport,
            ) as media_client:
                response = await media_client.get(normalized)
            response.raise_for_status()
            content = response.content
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
        else:
            if normalized.startswith("file://"):
                normalized = normalized[7:]
            path = Path(normalized)
            if not path.is_file() or path.stat().st_size > _MAX_MEDIA_BYTES:
                return None
            source_path = path
            filename = path.name
            content_type = mimetypes.guess_type(filename)[0] or content_type
            content = path.read_bytes()
        return self._store_media_bytes(
            job_id,
            content,
            filename,
            content_type,
            source_path=source_path,
        )

    async def _store_attachment(
        self,
        job_id: str,
        client: httpx.AsyncClient,
        attachment_id: str,
    ) -> RemoteJobImage | None:
        try:
            response = await client.get(
                "/api/v1/file",
                params={"attachment_id": attachment_id},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type == "application/json":
            return None
        filename = _filename_from_content_disposition(
            response.headers.get("content-disposition", "")
        )
        return self._store_media_bytes(
            job_id,
            response.content,
            filename or f"astrbot-{attachment_id}.png",
            content_type,
        )

    def _store_media_bytes(
        self,
        job_id: str,
        content: bytes | None,
        filename: str,
        content_type: str,
        *,
        source_path: Path | None = None,
    ) -> RemoteJobImage | None:
        if not content or len(content) > _MAX_MEDIA_BYTES:
            return None
        detected = _detected_image_type(content)
        guessed = mimetypes.guess_type(filename)[0] or ""
        if not content_type.startswith("image/"):
            if guessed.startswith("image/"):
                content_type = guessed
            elif detected is not None:
                content_type = detected[0]
            else:
                return None
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = detected[1] if detected is not None else {
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }.get(content_type, ".png")
            filename = f"generated-image{suffix}"
        digest = hashlib.sha256(content).hexdigest()
        image_id = f"img_{digest[:16]}"
        target_dir = self._media_dir / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{image_id}{suffix}"
        if not target.is_file():
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            if source_path is not None:
                try:
                    os.link(source_path, temporary)
                except OSError:
                    temporary.write_bytes(content)
            else:
                temporary.write_bytes(content)
            os.replace(temporary, target)
        return RemoteJobImage(
            id=image_id,
            filename=Path(filename).name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=digest,
            download_url=f"/api/v1/lite/jobs/{job_id}/images/{image_id}",
        )

    async def _upload_bytes(
        self,
        client: httpx.AsyncClient,
        content: bytes,
        filename: str,
        mime: str,
    ) -> str:
        response = await client.post(
            "/api/v1/file",
            files={"file": (filename, content, mime)},
        )
        response.raise_for_status()
        attachment_id = _find_attachment_id(response.json())
        if not attachment_id:
            raise RemoteJobError("AstrBot file upload did not return an attachment id")
        return attachment_id

    async def _upload_reference(self, client: httpx.AsyncClient, reference: str) -> str:
        if not reference:
            return ""
        filename = "generated-image.png"
        mime = "image/png"
        content: bytes | None = None

        if reference.startswith("data:"):
            try:
                header, encoded = reference.split(",", 1)
                if ";base64" not in header:
                    raise RemoteJobError("generated image data URI is not base64 encoded")
                mime = header[5:].split(";", 1)[0] or mime
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RemoteJobError("generated image has an invalid data URI") from exc
        elif reference.startswith("base64://"):
            try:
                content = base64.b64decode(reference[9:], validate=True)
            except binascii.Error as exc:
                raise RemoteJobError("generated image has invalid base64 data") from exc
        elif reference.startswith(("http://", "https://")):
            parsed = urlparse(reference)
            candidate = Path(unquote(parsed.path)).name
            if candidate:
                filename = candidate
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.remote_job_timeout_seconds),
                follow_redirects=True,
                transport=self._transport,
            ) as media_client:
                media_response = await media_client.get(reference)
            media_response.raise_for_status()
            content = media_response.content
            mime = media_response.headers.get("content-type", "").split(";", 1)[0] or (
                mimetypes.guess_type(filename)[0] or mime
            )

        if reference.startswith("file://"):
            reference = reference[7:]
        if content is None:
            path = Path(reference)
            if not path.is_file():
                raise RemoteJobError(
                    f"generated image is not a readable media reference: {reference[:200]}"
                )
            filename = path.name
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.stat().st_size > _MAX_MEDIA_BYTES:
                raise RemoteJobError("generated image exceeds the 64 MiB upload limit")
            with path.open("rb") as handle:
                response = await client.post(
                    "/api/v1/file",
                    files={"file": (filename, handle, mime)},
                )
        else:
            if len(content) > _MAX_MEDIA_BYTES:
                raise RemoteJobError("generated image exceeds the 64 MiB upload limit")
            return await self._upload_bytes(client, content, filename, mime)
        response.raise_for_status()
        attachment_id = _find_attachment_id(response.json())
        if not attachment_id:
            raise RemoteJobError("AstrBot file upload did not return an attachment id")
        return attachment_id

    async def _send_im(self, umo: str, text: str, attachments: list[str]) -> None:
        chain: list[dict[str, str]] = []
        if text:
            chain.append({"type": "plain", "text": text})
        chain.extend(
            {"type": "image", "attachment_id": attachment_id}
            for attachment_id in attachments
        )
        async with self._client() as client:
            response = await client.post(
                "/api/v1/im/message", json={"umo": umo, "message": chain}
            )
            response.raise_for_status()
