"""Character cards and confirmed features, separate from existing presets."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .auth import require_admin, require_reader
from .repositories import RepositoryError
from .remote_jobs import RemoteJobError
from .preset_lock import preset_file_lock

router = APIRouter(prefix="/api/v1/character-gallery", tags=["character-gallery"])
_IMPORT_LOCK = threading.RLock()


class CardWrite(BaseModel):
    revision: str
    character: str = Field(min_length=1, max_length=200)
    variant: str = Field(default="default", max_length=100)
    published: bool = False
    profile: dict | None = None
    cover_job: str = Field(default="", max_length=120)
    cover_image: str = Field(default="", max_length=120)


class CharacterGallery:
    def __init__(self, settings, jobs):
        self.settings, self.jobs = settings, jobs
        self.root = settings.preset_path.parent / "character_gallery"

    def core(self):
        with _IMPORT_LOCK:
            return self._core()

    def _core(self):
        source = self.settings.plugin_dir / "duo_profile_runtime.py"
        name = "aaa_duo_" + hashlib.sha256(str(source).encode()).hexdigest()[:12]
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, source)
            if spec is None or spec.loader is None:
                raise RepositoryError("请同步更新 AstrBot 插件中的特征档案模块")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(name, None)
                raise
        return sys.modules[name]

    def path(self, name):
        if Path(name).name != name or name in {"", ".", ".."} or "/" in name or "\\" in name:
            raise RepositoryError("画廊路径不合法")
        return self.core()._no_redirects(self.root / name)

    def read(self):
        path = self.path("catalog.json")
        data = self.core().read_json(path)[0] if path.exists() else {"schema": 1, "revision": "initial", "items": []}
        if (not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("revision"), str)
                or not isinstance(data.get("items"), list)):
            raise RepositoryError("角色画廊目录格式错误")
        for item in data["items"]:
            if not isinstance(item, dict) or not all(key in item for key in ("id", "character", "variant", "published", "profile")):
                raise RepositoryError("角色卡片格式错误")
            self.core().validate_profile(item["profile"])
        return data

    def view(self, admin=False):
        data = self.read()
        items = []
        for card in data["items"]:
            if not admin and not card.get("published"):
                continue
            item = {k: copy.deepcopy(card[k]) for k in ("id", "character", "variant", "published")}
            item["cover_url"] = f"/api/v1/character-gallery/images/{card['id']}" if card.get("cover") else ""
            item["features"] = {k: v["text"] for k, v in card["profile"]["features"].items() if v["confirmed"]}
            item["source_state"] = self.core().source_status(card["profile"]) if admin else ""
            if admin:
                item["profile"] = copy.deepcopy(card["profile"])
            items.append(item)
        return {"revision": data["revision"], "items": items}

    def write(self, payload, principal):
        self.path("catalog.json")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path("catalog.json.write.lock")
        with preset_file_lock(self.path("catalog.json")):
            return self._write(payload, principal)

    def _write(self, payload, principal):
        new_cover = None
        committed = False
        try:
            data = self.read()
            if payload.revision != data["revision"]:
                raise RepositoryError("画廊已更新，请刷新；当前草稿可保留后重试")
            if bool(payload.cover_job) != bool(payload.cover_image):
                raise RepositoryError("封面需同时提供任务 ID 和图片 ID")
            core = self.core()
            if payload.profile is not None and len(core.json_bytes(payload.profile)) > 1_000_000:
                raise RepositoryError("独立特征档案不能超过 1MB")
            catalog = core.load_catalog(self.settings.preset_path)
            current = core.new_profile(catalog, payload.character, payload.variant)
            profile = copy.deepcopy(payload.profile) if payload.profile is not None else current
            core.validate_profile(profile)
            if any(profile["source"][key] != current["source"][key] for key in ("name", "variant_id", "selected_prompt", "lora")):
                raise RepositoryError("特征档案与当前角色/造型不一致，请重新读取预设后核对")
            # Refresh hashes/path only after exact source content comparison.
            profile["source"] = current["source"]
            profile.pop("_etag", None)
            if payload.published:
                # Compiler checks explicit confirmation and identity text.
                core.compile_preview([{"profile": profile}, {"profile": profile}], {})
            old = next((i for i in data["items"] if i["character"] == payload.character and i["variant"] == payload.variant), None)
            item = {"id": old["id"] if old else uuid.uuid4().hex, "character": payload.character,
                    "variant": payload.variant, "published": payload.published, "profile": profile,
                    "cover": copy.deepcopy(old.get("cover")) if old else None}
            if payload.cover_job:
                image, path = self.jobs.get_image(payload.cover_job, payload.cover_image, principal)
                content = path.read_bytes()
                if len(content) > 25_000_000 or image.content_type not in {"image/png", "image/jpeg", "image/webp"}:
                    raise RepositoryError("封面需要不超过 25MB 的 PNG/JPEG/WebP")
                self.jobs._require_approved(content)
                name = uuid.uuid4().hex + ".image"
                new_cover = self.path(name)
                with new_cover.open("xb") as stream:
                    stream.write(content)
                item["cover"] = {"file": name, "content_type": image.content_type, "job_id": payload.cover_job}
            data["items"] = [i for i in data["items"] if i["id"] != item["id"]] + [item]
            data["revision"] = uuid.uuid4().hex
            serialized = core.json_bytes(data)
            if len(serialized) > core.MAX_JSON_BYTES:
                raise RepositoryError("角色画廊目录已达 16 MiB，请精简特征档案后再保存")
            previous = self.path("catalog.json")
            if previous.exists():
                with self.path(uuid.uuid4().hex + ".backup.json").open("xb") as stream:
                    stream.write(previous.read_bytes())
            temporary = self.path(uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(serialized)
                temporary.replace(previous)
                committed = True
            finally:
                temporary.unlink(missing_ok=True)
            return self.view(True)
        finally:
            if new_cover is not None and not committed:
                new_cover.unlink(missing_ok=True)

    def image(self, ident, admin):
        item = next((i for i in self.read()["items"] if i["id"] == ident and (admin or i.get("published"))), None)
        if not item or not item.get("cover"):
            raise RepositoryError("角色封面不可用")
        path = self.path(item["cover"]["file"])
        self.jobs._require_approved(path.read_bytes())
        return path, item["cover"]["content_type"]


def service(request):
    return CharacterGallery(request.app.state.settings, request.app.state.remote_jobs)


@router.get("")
def view(request: Request, principal=Depends(require_reader)):
    try:
        return service(request).view(principal.is_admin)
    except (ValueError, OSError, RepositoryError, RemoteJobError) as exc:
        raise HTTPException(422, "角色画廊不可读取，请检查插件版本与专用目录") from exc


@router.post("")
def write(payload: CardWrite, request: Request, principal=Depends(require_admin)):
    try:
        return service(request).write(payload, principal)
    except (ValueError, OSError, RepositoryError, RemoteJobError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/images/{ident}")
def image(ident: str, request: Request, principal=Depends(require_reader)):
    try:
        path, mime = service(request).image(ident, principal.is_admin)
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store"})
    except (ValueError, OSError, RepositoryError, RemoteJobError) as exc:
        raise HTTPException(404, "角色封面不可用") from exc
