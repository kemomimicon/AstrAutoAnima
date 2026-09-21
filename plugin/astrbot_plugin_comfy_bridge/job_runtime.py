from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct execution for local tests
    from workflow_runtime import WorkflowError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_digest(path: Path) -> str:
    """Exact decoded pixels only; never a perceptual similarity guess."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            if getattr(image, 'n_frames', 1) != 1 or image.width * image.height > 40000000:
                return ''
            pixels = image.convert('RGBA')
            digest = hashlib.sha256(str(pixels.size).encode())
            digest.update(pixels.tobytes())
            return digest.hexdigest()
    except (OSError, ValueError, ImportError):
        return ''


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class JobStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.jobs_dir = self.root / "jobs"
        self.assets_dir = self.root / "assets"

    def _job_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", job_id):
            raise WorkflowError("无效任务ID")
        return self.jobs_dir / f"{job_id}.json"

    def _asset_path(self, asset_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", asset_id):
            raise WorkflowError("无效图片ID")
        return self.assets_dir / f"{asset_id}.json"

    def create_job(
        self,
        *,
        workflow_type: str,
        workflow_version: str,
        profile: str,
        source: dict[str, Any],
        input_data: dict[str, Any],
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = f"job_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:10]}"
        record = {
            "schema_version": "1.0",
            "job_id": job_id,
            "parent_job_id": parent_job_id,
            "status": "queued",
            "workflow": {
                "type": workflow_type,
                "version": workflow_version,
                "profile": profile,
            },
            "source": dict(source),
            "input": dict(input_data),
            "model": {},
            "sampling": {},
            "enhance": {},
            "result": {
                "assets": [],
                "elapsed_ms": None,
                "safety": None,
                "error": None,
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        _write_json_atomic(self._job_path(job_id), record)
        return record

    def save_job(self, record: dict[str, Any]) -> None:
        job_id = str(record.get("job_id", "")).strip()
        if not job_id:
            raise WorkflowError("任务记录缺少 job_id。")
        record["updated_at"] = utc_now()
        _write_json_atomic(self._job_path(job_id), record)

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(str(job_id).strip())
        if not path.is_file():
            raise WorkflowError(f"METADATA_NOT_FOUND：找不到任务 {job_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"任务记录损坏：{job_id}：{exc}") from exc
        if not isinstance(data, dict):
            raise WorkflowError(f"任务记录格式无效：{job_id}")
        return data

    def register_asset(
        self,
        path: Path,
        *,
        asset_type: str,
        job_id: str | None,
        source: str,
        favorite: bool = False,
    ) -> dict[str, Any]:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise WorkflowError(f"ASSET_NOT_FOUND：{resolved}")
        digest = sha256_file(resolved)
        asset_id = f"img_{digest[:16]}_{uuid.uuid4().hex[:6]}"
        record = {
            "schema_version": "1.0",
            "asset_id": asset_id,
            "sha256": digest,
            "pixel_sha256": pixel_digest(resolved),
            "path": str(resolved),
            "type": str(asset_type),
            "job_id": job_id,
            "source": str(source),
            "size_bytes": resolved.stat().st_size,
            "created_at": utc_now(),
            "expire_at": None,
            "favorite": bool(favorite),
        }
        _write_json_atomic(self._asset_path(asset_id), record)
        return record

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        path = self._asset_path(str(asset_id).strip())
        if not path.is_file():
            raise WorkflowError(f"ASSET_NOT_FOUND：{asset_id}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise WorkflowError(f"Asset 记录格式无效：{asset_id}")
        return data

    def find_asset_by_sha256(self, digest: str) -> dict[str, Any] | None:
        if not self.assets_dir.is_dir():
            return None
        matches = []
        for path in self.assets_dir.glob("img_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("sha256") == digest:
                matches.append(data)
        results = [item for item in matches if item.get("type") == "result"]
        return max(results or matches, key=lambda item: str(item.get("created_at", "")), default=None)

    def record_delivery(self, message_id: str, scope: str, job_id: str, index: int):
        if not message_id or not scope: return
        job = self.get_job(job_id)
        assets = job.get('result', {}).get('assets', [])
        if not 0 <= index < len(assets): raise WorkflowError('发送图片序号无效')
        key = hashlib.sha256((scope + '\0' + message_id).encode()).hexdigest()
        _write_json_atomic(self.root / 'deliveries' / (key + '.json'),
            {'message_id': message_id, 'scope': scope, 'job_id': job_id, 'asset_id': assets[index], 'index': index})
        group = job.get('input', {}).get('draw_group', '')
        positions = job.get('input', {}).get('draw_positions', [])
        if re.fullmatch(r'[0-9a-f]{32}', group) and len(positions) == len(assets):
            position = positions[index]
            if isinstance(position, int) and 1 <= position <= 5:
                group_key = hashlib.sha256((scope + '\0' + group).encode()).hexdigest()
                _write_json_atomic(self.root / 'draw_deliveries' / group_key / f'{position}.json',
                    {'scope': scope, 'group': group, 'job_id': job_id, 'asset_id': assets[index], 'index': index})

    def selected_draws(self, parent, positions, scope):
        group = parent.get('input', {}).get('draw_group', '')
        if not re.fullmatch(r'[0-9a-f]{32}', group):
            raise WorkflowError('这张图没有完整五连抽批次关联（可能是旧图或单张图），请分别引用图片操作')
        key = hashlib.sha256((scope + '\0' + group).encode()).hexdigest()
        result = []
        for position in positions:
            if not isinstance(position, int) or not 1 <= position <= 5:
                raise WorkflowError('五连抽序号只能为 1–5')
            path = self.root / 'draw_deliveries' / key / f'{position}.json'
            if not path.is_file():
                raise WorkflowError(f'第 {position} 张尚未成功发送到当前会话，或关联缺失；本次未执行任何选择操作')
            data = json.loads(path.read_text(encoding='utf-8'))
            job = self.get_job(data['job_id'])
            index = data['index']
            assets = job.get('result', {}).get('assets', [])
            slots = job.get('input', {}).get('draw_positions', [])
            if (data.get('scope') != scope or data.get('group') != group or job.get('input', {}).get('draw_group') != group
                or not isinstance(index, int) or not 0 <= index < len(assets) or len(slots) != len(assets)
                or slots[index] != position or assets[index] != data['asset_id']):
                raise WorkflowError('五连抽关联不一致，未执行操作')
            result.append((position, job, index))
        return result

    def parent_for_message(self, message_id: str, scope: str):
        key = hashlib.sha256((scope + '\0' + message_id).encode()).hexdigest()
        path = self.root / 'deliveries' / (key + '.json')
        if not path.is_file(): return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('scope') != scope or data.get('message_id') != message_id: return None
        job = self.get_job(data['job_id'])
        assets = job.get('result', {}).get('assets', [])
        index = data['index']
        if not isinstance(index, int) or not 0 <= index < len(assets) or assets[index] != data['asset_id']:
            raise WorkflowError('发送图片关联失效')
        return job, index

    def parent_for_image(self, path: Path, source: dict | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        digest = sha256_file(Path(path))
        if source is not None:
            matches = []
            pixels = None
            for metadata in self.assets_dir.glob('img_*.json'):
                try:
                    item = json.loads(metadata.read_text(encoding='utf-8-sig'))
                    if item.get('type') != 'result' or not item.get('job_id'): continue
                    job = self.get_job(item['job_id'])
                    if any(job.get('source', {}).get(k) != source.get(k) for k in ('platform', 'session_id')): continue
                    if item.get('asset_id') not in job.get('result', {}).get('assets', []): continue
                    equal = item.get('sha256') == digest
                    if not equal:
                        if pixels is None: pixels = pixel_digest(path)
                        saved = item.get('pixel_sha256')
                        equal = bool(pixels and pixels == saved)
                    if equal: matches.append((item, job))
                except (OSError, ValueError, WorkflowError): continue
            if len(matches) > 1: raise WorkflowError('图片匹配到多个任务，请引用原始机器人消息；不会猜测任务')
            return matches[0] if matches else (None, None)
        asset = self.find_asset_by_sha256(digest)
        if not asset or not asset.get("job_id"):
            return asset, None
        try:
            return asset, self.get_job(str(asset["job_id"]))
        except WorkflowError:
            return asset, None
