from __future__ import annotations

import hashlib
import json
import os
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
        return self.jobs_dir / f"{job_id}.json"

    def _asset_path(self, asset_id: str) -> Path:
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
        for path in self.assets_dir.glob("img_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("sha256") == digest:
                return data
        return None

    def parent_for_image(self, path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        digest = sha256_file(Path(path))
        asset = self.find_asset_by_sha256(digest)
        if not asset or not asset.get("job_id"):
            return asset, None
        try:
            return asset, self.get_job(str(asset["job_id"]))
        except WorkflowError:
            return asset, None
