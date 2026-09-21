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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .auth import AuthPrincipal, SYSTEM_ADMIN
from .config import Settings
from .personal_styles import _validate_loras
from .schemas import (
    DeliveryTarget,
    DeliveryTargetListResponse,
    RemoteJobCreateRequest,
    RemoteJobImage,
    RemoteJobPage,
    RemoteJobResponse,
)
from .personal_styles import resolve_personal_style_key, list_personal_styles
from .repositories import RepositoryError


class RemoteJobError(RuntimeError):
    pass


_UMO_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+:(?P<message_type>GroupMessage|FriendMessage):[A-Za-z0-9_.-]+$"
)
_POOL_PATTERN = re.compile(r"^[BGDCRKPNHS](?:[BGDCRKPNHS,/]*[BGDCRKPNHS])?$")
_PROMPT_ID_PATTERN = re.compile(r"\b(?:kp|liked|good|generate|discord|codex|reverse)-[A-Za-z0-9_.-]+\b")
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


def _filter_sources(value: str) -> set[str]:
    return {char for char in value if char in {"B", "G", "D", "C", "R", "K", "P"}}


def _prompt_ids_from_plain(messages: list[str]) -> list[str]:
    found: list[str] = []
    for message in messages:
        # Explicit ID fields support imported IDs without hard-coded source prefixes.
        for group in re.findall(r"条目=([^｜\s]+)", message):
            for ident in group.split(','):
                if re.fullmatch(r"[A-Za-z0-9_.-]{1,300}", ident) and ident not in found:
                    found.append(ident)
        for prompt_id in _PROMPT_ID_PATTERN.findall(message):
            if prompt_id not in found:
                found.append(prompt_id)
    return found[:20]


def build_remote_command(
    payload: RemoteJobCreateRequest, target: _TargetRecord
) -> tuple[str, str]:
    if payload.character_variant and (not payload.character.strip() or payload.kind in {"chaos", "multi", "remake"}):
        raise RemoteJobError("角色造型需要指定单个角色预设，不适用于混沌、多人或原图重跑")
    if payload.kind == "refine" and payload.profile in {"", "seedvr2"} and payload.denoise is not None:
        raise RemoteJobError("SeedVR2 没有传统 denoise；如需 Anima 重绘请选择 light 模式，不能静默忽略重绘参数")
    pool_filter = _normalize_pool_filter(payload.pool_filter)
    effective_safety = payload.safety_code
    selected_safety = _filter_safety(pool_filter)
    selected_sources = _filter_sources(pool_filter)
    if "K" in selected_sources and selected_sources != {"K"}:
        raise RemoteJobError("K prompt pool must be selected on its own")
    if selected_sources == {"K"} and selected_safety == {"H"}:
        raise RemoteJobError("K prompt pool supports K/N or K/S, not K/H")
    if selected_safety:
        if len(selected_safety) != 1:
            raise RemoteJobError("remote delivery requires one explicit safety level")
        effective_safety = next(iter(selected_safety))
    elif selected_sources == {"K"} and effective_safety == "H":
        # K uses a binary nudity switch: K/N is the covered variant, K/S is
        # the adult explicit variant.  H therefore falls back to the safe side.
        effective_safety = "N"

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
        ("random", False): "来张好图抽一抽",
        ("random", True): "来张好图五连抽",
        ("chaos", False): "来张好图混沌时刻",
        ("chaos", True): "来张好图混沌五连抽",
        ("hq", False): "/ahq",
        ("hq", True): "/ahq",
        ("refine", False): "/arefine",
        ("refine", True): "/arefine",
        ("remake", False): "/aremake",
        ("multi", False): "/amulti",
    }[(payload.kind, payload.five_draw)]
    parts = [prefix]
    visual = (("主光", payload.lighting_key), ("效果光", payload.lighting_effect),
              ("主材质", payload.material_primary), ("细节材质", ','.join(payload.material_details)),
              ("表面效果", payload.material_surface),
              ("镜头距离", payload.camera_distance), ("水平机位", payload.camera_yaw),
              ("俯仰机位", payload.camera_pitch), ("镜头效果", payload.camera_lens),
              ("画面倾斜", payload.camera_roll))
    for value in payload.material_details:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise RemoteJobError("材质预设 ID 不合法")
    if any(value for _, value in visual) and (payload.kind in {"remake", "multi"} or (payload.kind == "refine" and payload.profile in {"", "seedvr2"})):
        raise RemoteJobError("此任务不支持光影材质；请关闭预设或选择普通生图/Anima 精修")
    if payload.kind == "remake":
        if not re.fullmatch(r"引用令牌=[0-9a-f]{32}", payload.prompt):
            raise RemoteJobError("请使用图片旁的重跑按钮创建引用令牌")
        edits = [f'/aremake {payload.prompt}']
        for label, value in [('角色', payload.character), ('画风', payload.style), ('比例', payload.ratio)]:
            if value:
                edits.append(label + '=' + json.dumps(value, ensure_ascii=False))
        if payload.remake_fixed_seed:
            edits.append('固定种子')
        if payload.remake_adjustment.strip():
            edits.append(payload.remake_adjustment.strip())
        return ' '.join(edits), effective_safety
    if payload.kind == "multi":
        if payload.character or payload.style or payload.personal_style_slot or payload.trial_style:
            raise RemoteJobError("裸模多人图的人物请写在分段提示词中，不使用全局角色/画风预设")
        if not payload.prompt.strip():
            raise RemoteJobError("多人图需要人物分段描述")
        knobs = []
        for name, value in (("比例", payload.ratio), ("采样器", payload.sampler), ("调度器", payload.scheduler), ("步数", payload.steps), ("CFG", payload.cfg)):
            if value is not None and value != "":
                knobs.append(f"{name}={value}")
        return " ".join(["/amulti", *knobs, payload.prompt.strip()]), effective_safety
    if payload.kind == "hq":
        parts.append(payload.profile or "stable")
        parts.extend(
            (
                f"修手={'开启' if payload.detail_hands else '关闭'}",
                f"修脚={'开启' if payload.detail_feet else '关闭'}",
                f"修脸={'开启' if payload.detail_face else '关闭'}",
                f"修复后放大={'开启' if payload.detail_upscale else '关闭'}",
            )
        )
    elif payload.kind == "refine":
        parts.append(payload.profile or "seedvr2")
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
                "special_features": "特殊特征",
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
    # Positional selectors/profiles must precede every key=value directive.
    if payload.camera_extreme_lora or any((payload.camera_distance, payload.camera_yaw,
            payload.camera_pitch, payload.camera_lens, payload.camera_roll)):
        parts.append(f"极限辅助={'开启' if payload.camera_extreme_lora else '关闭'}")
    if payload.kind != "chaos":
        if payload.character_variant:
            if not payload.character.strip():
                raise RemoteJobError("选择造型时必须指定角色预设")
            parts.append(f"造型={payload.character_variant}")
        if payload.character.strip():
            name = payload.character.strip()
            parts.append("角色=" + (json.dumps(name, ensure_ascii=False) if any(c.isspace() for c in name) or '"' in name or "'" in name else name))
            parts.append(
                "角色模式="
                + {"weak": "弱", "strong": "强", "off": "关闭"}[
                    payload.character_tag_mode
                ]
            )
        if payload.style.strip():
            name = payload.style.strip()
            parts.append("画风=" + (json.dumps(name, ensure_ascii=False) if any(c.isspace() for c in name) or '"' in name or "'" in name else name))
        if payload.character_strength is not None:
            parts.append(f"角色权重={payload.character_strength:g}")
        if payload.ratio:
            parts.append(f"比例={payload.ratio}")
    if payload.sampler:
        parts.append(f"采样器={payload.sampler}")
    if payload.scheduler:
        parts.append(f"调度器={payload.scheduler}")
    if payload.steps is not None:
        parts.append(f"步数={payload.steps}")
    if payload.cfg is not None:
        parts.append(f"CFG={payload.cfg:g}")
    if payload.scale is not None and payload.profile != "seedvr2":
        parts.append(f"放大={payload.scale:g}")
    if payload.denoise is not None and payload.profile != "seedvr2":
        parts.append(f"重绘={payload.denoise:g}")
    if payload.parent_job_id.strip():
        if payload.kind != "refine":
            raise RemoteJobError("parent_job_id is only valid for refine jobs")
        parts.append(f"任务={payload.parent_job_id.strip()}")
    parts.extend(f"{name}={value}" for name, value in visual if value)
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
    if (
        payload.kind == "refine"
        and payload.profile != "seedvr2"
        and not payload.parent_job_id.strip()
        and not payload.prompt.strip()
    ):
        raise RemoteJobError(
            "上传外部图片精修时必须填写补充提示词，或填写历史任务 ID。"
        )
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
        self._suite_image_index: dict[str, int] = {}
        self._semaphore = asyncio.Semaphore(1)
        from .safety_runtime import PriorityGate
        self._safety_gate = PriorityGate(1)
        self._safety_users = {}
        self._admin_exempt_jobs = set()
        self._stream_targets = {}
        self._stream_sent = {}
        self._records_dir = self.settings.remote_job_store_dir / "records"
        self._media_dir = self.settings.remote_job_store_dir / "media"
        self._attachment_images: dict[tuple[str, str], RemoteJobImage] = {}
        self._load_persisted_jobs()

    def _safety_policy(self):
        from .safety_runtime import load_policy
        return load_policy(self.settings.plugin_data_dir / "safety")

    def _credit_store(self):
        from .safety_runtime import CreditStore
        return CreditStore(self.settings.plugin_data_dir / "safety")

    def _safety_priority(self, job_id):
        if job_id in self._admin_exempt_jobs or not self._safety_policy().enabled:
            return 0
        qq = self._safety_users.get(job_id, "")
        return int(not qq or self._credit_store().score(qq) < 5)

    def _require_approved(self, content, job_id=None):
        if job_id is not None and job_id in self._admin_exempt_jobs:
            return
        policy = self._safety_policy()
        if policy.enabled and not self._credit_store().approved(content, policy.fingerprint):
            raise RemoteJobError("图片未通过当前安全审核，不予提供")

    def _dispatch_slot(self, job_id):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def slot():
            if self._safety_policy().enabled:
                # Share the plugin queue with QQ; do not hold a Hub serial gate.
                yield
            else:
                async with self._safety_gate.slot(lambda: self._safety_priority(job_id)):
                    yield
        return slot()

    def _record_path(self, job_id: str) -> Path:
        return self._records_dir / f"{job_id}.json"

    def _persist(self, job_id: str) -> None:
        job = self._jobs[job_id]
        owner = self._owners[job_id]
        payload = {
            "schema_version": "1.0",
            "owner": owner,
            "admin_exempt": job_id in self._admin_exempt_jobs,
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
            if payload.get("admin_exempt") is True:
                self._admin_exempt_jobs.add(job.id)
        for job_id in interrupted:
            self._persist(job_id)
            if self._jobs[job_id].task_suite_id:
                try:
                    self.cancel_suite(job_id, SYSTEM_ADMIN)
                except OSError:
                    pass

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
        suite = None
        suite_id = ''
        if payload.task_suite_id:
            if payload.kind not in {'direct', 'chinese', 'reverse', 'remake'} or payload.five_draw or payload.reverse_only:
                raise RemoteJobError('套组仅支持直接/中文/反推生图/重跑，不支持五连抽或仅反推')
            from .task_suites import suite_snapshot
            try:
                suite = suite_snapshot(self.settings, principal, payload.task_suite_id)
            except RepositoryError as exc:
                raise RemoteJobError(str(exc)) from exc
            suite_id = uuid.uuid4().hex
            payload = payload.model_copy(update={'style': '__hub_suite_' + suite_id,
                'character': '__suite_replace_identity__', 'character_variant': '',
                'personal_style_slot': None, 'trial_style': None})
        qq = principal.qq
        if not qq and principal.is_admin:
            policy_path = self.settings.plugin_data_dir / "safety/policy.json"
            if policy_path.is_file():
                qq = str(json.loads(policy_path.read_text(encoding="utf-8")).get("safety_admin_qq", ""))
        if self._safety_policy().enabled and not principal.is_admin:
            if not re.fullmatch(r"[1-9][0-9]{4,14}", qq):
                raise RemoteJobError("安全模式需要绑定真实 QQ；管理员请配置 safety_admin_qq")
            if self._credit_store().score(qq) <= 0:
                raise RemoteJobError("信用为0，生成失败；请联系管理员")
        personal_style_slot = payload.personal_style_slot
        random_id = ''
        random_keys = []
        if payload.style == '随机模式':
            if payload.kind == 'chaos' or payload.personal_style_slot is not None or payload.trial_style is not None:
                raise RemoteJobError('随机预设不能与混沌、个人槽位或临时调色盘同时指定')
            if principal.role != 'legacy_lite':
                random_keys = [item.style_key for item in list_personal_styles(self.settings, principal).items]
            random_id = uuid.uuid4().hex
            payload = payload.model_copy(update={'style': '__hub_random_' + random_id})
        trial = payload.trial_style
        trial_id = ""
        if trial is not None:
            if payload.kind == "chaos" or payload.style or personal_style_slot is not None:
                raise RemoteJobError("临时调色盘不能与混沌、全局画风或个人槽位同时使用")
            try:
                _validate_loras(self.settings, trial)
            except RepositoryError as exc:
                raise RemoteJobError(str(exc)) from exc
            trial_id = uuid.uuid4().hex
            payload = payload.model_copy(update={"style": f"__hub_trial_{trial_id}"})
        if payload.personal_style_slot is not None:
            if payload.kind == "chaos":
                raise RemoteJobError("personal style cannot be used for chaos jobs")
            if payload.style.strip():
                raise RemoteJobError("global style and personal style cannot be used together")
            try:
                personal_style = resolve_personal_style_key(
                    self.settings, principal, payload.personal_style_slot
                )
            except RepositoryError as exc:
                raise RemoteJobError(str(exc)) from exc
            payload = payload.model_copy(update={"style": personal_style})
        targets = {
            record.public.id: record
            for record in visible_delivery_targets(self.settings, principal)
        }
        target = targets.get(payload.target_id)
        if target is None:
            raise RemoteJobError("unknown or disabled delivery target")
        command, effective_safety = build_remote_command(payload, target)
        command_preview = command
        if random_id:
            command_preview = command_preview.replace('__hub_random_' + random_id, '随机模式')
        if personal_style_slot is not None:
            command_preview = re.sub(
                r"画风=\S+",
                f"个人画风=槽位{personal_style_slot}",
                command_preview,
                count=1,
            )
        source_image = _decode_source_image(payload)
        if not self.settings.astrbot_api_key:
            raise RemoteJobError("AAH_ASTRBOT_API_KEY is not configured")
        now = _now()
        job = RemoteJobResponse(
            id=uuid.uuid4().hex,
            status="queued",
            kind=payload.kind,
            safety_code=effective_safety,
            profile=payload.profile,
            target_id=target.public.id,
            target_label=target.public.label,
            deliver_to_im=payload.deliver_to_im,
            command_preview=command_preview,
            message="任务已进入队列",
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.id] = job
        if principal.is_admin:
            self._admin_exempt_jobs.add(job.id)
        self._safety_users[job.id] = qq
        self._owners[job.id] = principal.subject
        self._persist(job.id)
        if suite is not None:
            suite_root = self.settings.plugin_data_dir / 'hub_state' / 'task_suite_runs'
            suite_root.mkdir(parents=True, exist_ok=True)
            with (suite_root / f'{suite_id}.json').open('x', encoding='utf-8') as stream:
                json.dump({**suite, 'owner': principal.subject, 'job_id': job.id,
                           'expires_at': time.time() + max(7200, self.settings.remote_job_timeout_seconds * len(suite['rows']) + 120),
                           'rows_status': ['queued'] * len(suite['rows'])}, stream, ensure_ascii=False)
            self._update(job.id, task_suite_id=suite_id, task_suite_name=suite['name'],
                         command_preview=command_preview.replace('__hub_suite_' + suite_id, suite['name']).replace('__suite_replace_identity__', '套组'),
                         message=f"套组已进入队列，共 {len(suite['rows'])} 项")
        trial_path = None
        random_path = None
        if random_id:
            random_root = self.settings.hub_state_dir / 'random_styles'
            random_root.mkdir(parents=True, exist_ok=True)
            random_path = random_root / f'{random_id}.json'
            with random_path.open('x', encoding='utf-8') as stream:
                json.dump({'expires_at': time.time() + 7200, 'owner': principal.subject,
                           'personal_keys': random_keys}, stream)
        if trial is not None:
            trial_root = self.settings.hub_state_dir / "style_trials"
            trial_root.mkdir(parents=True, exist_ok=True)
            trial_path = trial_root / f"{trial_id}.json"
            with trial_path.open("x", encoding="utf-8") as stream:
                json.dump({"expires_at": time.time() + 7200, "owner": principal.subject,
                           "style": {"hidden": True, "prompt": trial.prompt, "loras": [
                               {"name": item.path, "strength_model": item.strength, "strength_clip": item.strength if item.strength_clip is None else item.strength_clip} for item in trial.loras]}}, stream, ensure_ascii=False)
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
        if random_path is not None:
            def finish_random(_task):
                try:
                    if random_path.is_file() and not random_path.is_symlink():
                        random_path.unlink()
                except OSError:
                    pass
            task.add_done_callback(finish_random)
        if trial_path is not None:
            def finish_trial(_task):
                # Only this generated UUID file; never sweep user configuration.
                try:
                    if trial_path.is_file() and not trial_path.is_symlink():
                        trial_path.unlink()
                except OSError:
                    pass
            task.add_done_callback(finish_trial)
        task.add_done_callback(self._tasks.discard)
        return self._jobs[job.id]

    def get(
        self, job_id: str, principal: AuthPrincipal = SYSTEM_ADMIN
    ) -> RemoteJobResponse | None:
        if not principal.is_admin and self._owners.get(job_id) != principal.subject:
            return None
        job = self._jobs.get(job_id)
        return self._suite_progress(job) if job else None

    def _suite_progress(self, job):
        if not job.task_suite_id:
            return job
        path = self.settings.plugin_data_dir / 'hub_state' / 'task_suite_runs' / f'{job.task_suite_id}.json'
        try:
            run = json.loads(path.read_text(encoding='utf-8'))
            rows = [dict(index=i+1, character=r['character'], style=r['style'], status=run['rows_status'][i], job_id=run.get('row_job_ids', {}).get(str(i), ''))
                    for i, r in enumerate(run['rows'])]
            done = sum(r['status'] in {'succeeded', 'failed', 'cancelled'} for r in rows)
            message = f"套组 {run['name']}：{done}/{len(rows)} 项已结束"
            if job.status not in {'queued', 'running'}:
                message += '；' + job.message
            return job.model_copy(update={'task_suite_rows': rows, 'message': message})
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return job

    def cancel_suite(self, job_id, principal):
        job = self.get(job_id, principal)
        if job is None or not job.task_suite_id:
            raise RemoteJobError('任务套组不存在或无权取消')
        path = self.settings.plugin_data_dir / 'hub_state' / 'task_suite_runs' / f'{job.task_suite_id}.cancel'
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                stream.write('cancel pending rows')
        return {'message': '已请求取消未执行项；正在生成的单项会完成'}

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
            items=[self._suite_progress(job) for job in jobs[start : start + page_size]],
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
        try:
            self._require_approved(path.read_bytes(), job_id)
        except RemoteJobError:
            return None
        return image, path

    def mark_liked(
        self,
        job_id: str,
        prompt_id: str,
        principal: AuthPrincipal = SYSTEM_ADMIN,
    ) -> RemoteJobResponse | None:
        job = self.get(job_id, principal)
        if job is None or prompt_id not in job.prompt_ids:
            return None
        liked = list(job.liked_prompt_ids)
        if prompt_id not in liked:
            liked.append(prompt_id)
            self._update(job_id, liked_prompt_ids=liked)
        return self._jobs[job_id]

    def unmark_liked(self, prompt_id, principal):
        from .prompt_likes import _saved_id
        for job_id, job in list(self._jobs.items()):
            if self._owners.get(job_id) != principal.subject:
                continue
            liked = [p for p in job.liked_prompt_ids if p != prompt_id and _saved_id(principal, p) != prompt_id]
            if liked != job.liked_prompt_ids:
                self._update(job_id, liked_prompt_ids=liked)

    def remake_image(self, job_id: str, image_id: str, principal: AuthPrincipal, options=None):
        original = self.get(job_id, principal)
        located = self.get_image(job_id, image_id, principal)
        if original is None or located is None:
            raise RemoteJobError("图片不存在或无权访问")
        image, _ = located
        if not original.bridge_job_ids:
            raise RemoteJobError("旧记录未保存插件任务关联，不能保证原参数重跑")
        assets_root = self.settings.plugin_data_dir / "job_store" / "assets"
        suite_source_job = ''
        if image.task_suite_index:
            row = next((row for row in original.task_suite_rows if row['index'] == image.task_suite_index), None)
            suite_source_job = row.get('job_id', '') if row else ''
            if not suite_source_job:
                raise RemoteJobError('套组单项关联尚未落盘，请稍后刷新；不会猜测原图')
        found = []
        for path in assets_root.glob("img_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("sha256") == image.sha256 and data.get("job_id") in original.bridge_job_ids and data.get("type") == "result" and (not suite_source_job or data.get('job_id') == suite_source_job):
                    found.append(data)
            except (OSError, ValueError):
                continue
        if len(found) != 1:
            raise RemoteJobError("图片的原任务关联缺失或不唯一，拒绝猜测")
        token = uuid.uuid4().hex
        root = self.settings.hub_state_dir / "image_actions"
        root.mkdir(parents=True, exist_ok=True)
        ticket = root / f"{token}.json"
        with ticket.open("x", encoding="utf-8") as stream:
            json.dump({"action": "remake", "asset_id": found[0]["asset_id"], "expires_at": time.time()+7200}, stream)
        edits = {} if options is None else dict(character=options.character, style=options.style,
            ratio=options.ratio, remake_fixed_seed=options.fixed_seed, remake_adjustment=options.adjustment,
            task_suite_id=options.task_suite_id)
        return self.create(RemoteJobCreateRequest(target_id=original.target_id, kind="remake", prompt=f"引用令牌={token}", safety_code=original.safety_code, deliver_to_im=original.deliver_to_im, **edits), principal)

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
        async with self._dispatch_slot(job_id):
            self._update(job_id, status="running", message="AstrBot 正在生成")
            suite_rows = self._suite_progress(self._jobs[job_id]).task_suite_rows
            run_timeout = self.settings.remote_job_timeout_seconds * max(1, min(20, len(suite_rows)))
            try:
                policy = self._safety_policy()
                if policy.enabled or job_id in self._admin_exempt_jobs:
                    qq = self._safety_users.get(job_id, "")
                    admin_exempt = job_id in self._admin_exempt_jobs
                    if policy.enabled and not admin_exempt and (not re.fullmatch(r"[1-9][0-9]{4,14}", qq) or self._credit_store().score(qq) <= 0):
                        raise RemoteJobError("安全身份缺失或信用为0，生成失败")
                    token = uuid.uuid4().hex
                    tickets = self.settings.plugin_data_dir / "safety/tickets"
                    tickets.mkdir(parents=True, exist_ok=True)
                    with (tickets / f"{token}.json").open("x", encoding="utf-8") as stream:
                        json.dump({"qq": qq, "root": job_id, "admin_exempt": admin_exempt,
                                   "expires": time.time()+run_timeout+120}, stream)
                    username = f"aaa_safe_{token}"
                    if policy.enabled:
                        self._stream_targets[job_id] = target
                        self._stream_sent[job_id] = set()
                plain, attachments, images = await asyncio.wait_for(
                    self._chat_and_collect(
                        job_id,
                        command,
                        username,
                        source_image=source_image,
                        allow_text_only=text_only,
                    ),
                    timeout=run_timeout,
                )
                message = plain[-1] if plain else "生成完成"
                deliver = self._jobs[job_id].deliver_to_im
                if deliver and (job_id not in self._stream_targets or not attachments):
                    await self._send_im(target.umo, message, attachments, job_id=job_id,
                        bridge_ids=re.findall(r"任务=(job_[A-Za-z0-9_]+)", "\n".join(plain)))
                self._update(
                    job_id,
                    status="succeeded",
                    message=f"已发送到 {target.public.label}" if deliver else "生成完成，仅保存在跑图记录；未发送 QQ",
                    images=images,
                    prompt_ids=list(dict.fromkeys([*_prompt_ids_from_plain(plain), *(image.prompt_id for image in images if image.prompt_id)]))[:20],
                    bridge_job_ids=list(dict.fromkeys(re.findall(r"任务=(job_[A-Za-z0-9_]+)", "\n".join(plain))))[:20],
                )
                if self._jobs[job_id].task_suite_id:
                    suite_job = self._suite_progress(self._jobs[job_id])
                    if any(row['status'] != 'succeeded' for row in suite_job.task_suite_rows):
                        self._update(job_id, status='failed', message='套组部分失败或取消；已完成图片保留，请查看逐项状态')
            except Exception as exc:
                self._update(job_id, status="failed", message=str(exc)[:500])
            finally:
                if self._jobs[job_id].task_suite_id:
                    # A timeout/shutdown must not leave later rows submitting behind the UI.
                    try:
                        self.cancel_suite(job_id, SYSTEM_ADMIN)
                    except OSError:
                        pass
                self._suite_image_index.pop(job_id, None)
                self._stream_targets.pop(job_id, None)
                self._stream_sent.pop(job_id, None)
                for key in [key for key in self._attachment_images if key[0] == job_id]:
                    self._attachment_images.pop(key, None)

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
        image_sources: dict[str, str] = {}
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
                    stored = None
                    attachment_id = None
                    if event_type == "plain" and isinstance(data, str):
                        if data.startswith('AAA_IMAGE_SUITE=') and self._jobs[job_id].task_suite_id:
                            try:
                                index = int(json.loads(data.split('=', 1)[1])['index'])
                                if 1 <= index <= 20:
                                    self._suite_image_index[job_id] = index
                            except (ValueError, TypeError, KeyError):
                                pass
                        elif data.startswith('AAA_IMAGE_SOURCE='):
                            try:
                                mapping = json.loads(data.split('=', 1)[1])
                                digest, ident = mapping['sha256'], mapping['prompt_id']
                                if re.fullmatch(r'[0-9a-f]{64}', digest) and re.fullmatch(r'[A-Za-z0-9_.-]{1,300}', ident):
                                    image_sources[digest] = ident
                            except (ValueError, KeyError, TypeError):
                                pass
                        elif "已提交生成请求" not in data:
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
                            if self._safety_policy().enabled and stored is None:
                                raise RemoteJobError("安全图片读取失败，不予投递")
                            if stored is not None and all(
                                item.id != stored.id for item in images
                            ):
                                images.append(stored)
                    elif event_type in {"image", "file"}:
                        attachment_id = _find_attachment_id(data)
                        reference = _find_media_reference(data)
                        if attachment_id:
                            stored = await self._store_attachment(job_id, client, attachment_id)
                        else:
                            stored = await self._store_media_reference(job_id, reference)
                        if self._safety_policy().enabled and stored is None:
                            raise RemoteJobError("安全图片读取失败，不予投递")
                        if stored is not None and all(
                            item.id != stored.id for item in images
                        ):
                            images.append(stored)
                        if not attachment_id:
                            if self._safety_policy().enabled and stored is not None:
                                safe_path = self._media_dir / job_id / f"{stored.id}{Path(stored.filename).suffix.casefold()}"
                                content = safe_path.read_bytes()
                                self._require_approved(content, job_id)
                                attachment_id = await self._upload_bytes(client, content, stored.filename, stored.content_type)
                            elif reference.startswith(("[IMAGE]", "[FILE]")):
                                continue
                            else:
                                attachment_id = await self._upload_reference(client, reference)
                        if attachment_id and attachment_id not in attachments:
                            attachments.append(attachment_id)
                    elif event_type == "error":
                        raise RemoteJobError(str(data or "AstrBot chat failed"))
                    if attachment_id and stored is not None:
                        self._attachment_images[(job_id, attachment_id)] = stored
                    for image in images:
                        image.prompt_id = image_sources.get(image.sha256, image.prompt_id)
                    if images:
                        self._update(job_id, images=list(images), prompt_ids=list(dict.fromkeys([*_prompt_ids_from_plain(plain), *(image.prompt_id for image in images if image.prompt_id)]))[:20])
                    if job_id in self._stream_targets and images:
                        self._update(job_id, images=list(images),
                                     prompt_ids=list(dict.fromkeys([*_prompt_ids_from_plain(plain), *(image.prompt_id for image in images if image.prompt_id)]))[:20],
                                     message=f"已通过安全审核 {len(images)} 张，任务仍在执行")
                        if self._jobs[job_id].deliver_to_im:
                            sent = self._stream_sent[job_id]
                            for attachment in attachments:
                                if attachment not in sent:
                                    await self._send_im(self._stream_targets[job_id].umo, plain[-1] if plain else "安全审核通过", [attachment],
                                        job_id=job_id, bridge_ids=re.findall(r"任务=(job_[A-Za-z0-9_]+)", "\n".join(plain)))
                                    sent.add(attachment)
        if plain and plain[-1].startswith("生成失败"):
            raise RemoteJobError(plain[-1])
        if not attachments and not (allow_text_only and plain):
            if plain:
                raise RemoteJobError(plain[-1])
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
        self._require_approved(content, job_id)
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
        suite_index = self._suite_image_index.get(job_id, 0)
        if suite_index:
            image_id += f'_r{suite_index}'
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
            task_suite_index=suite_index,
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

    async def _send_im(self, umo: str, text: str, attachments: list[str], *, job_id: str = '', bridge_ids=None) -> None:
        if job_id and bridge_ids and attachments:
            from .qq_delivery import deliver_image
            async with self._client() as client:
                for attachment in attachments:
                    image = self._attachment_images.get((job_id, attachment))
                    if image is None:
                        raise RemoteJobError('QQ 投递图片关联缺失；图片保留在记录中')
                    await deliver_image(self.settings, client, umo, text, image.sha256, bridge_ids)
            return
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
