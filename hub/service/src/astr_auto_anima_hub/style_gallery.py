"""Managed, authenticated style previews. No direct ComfyUI or audit bypass."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .repositories import RepositoryError, list_presets
from .schemas import RemoteJobCreateRequest
from .gallery_defaults import PROMPTS


class GalleryConfig(BaseModel):
    prompts: list[str] = Field(default_factory=lambda: list(PROMPTS), min_length=4, max_length=4)
    model_kind: Literal["character", "text"] = "text"
    character: str = Field(default="", max_length=200)
    character_text: str = Field(default="", max_length=10000)
    target_id: str = Field(default="", max_length=80)


class GalleryUpdate(BaseModel):
    revision: str
    config: GalleryConfig
    confirm_clear: bool = False


class GalleryGenerate(BaseModel):
    revision: str
    styles: list[str] = Field(default_factory=list, max_length=500)
    slot_index: int | None = Field(default=None, ge=0, le=3)


class StyleGallery:
    def __init__(self, settings, jobs):
        self.settings, self.jobs = settings, jobs
        self.root = settings.plugin_data_dir / "style_gallery"
        self.task = None
        self.lock = asyncio.Lock()

    def _path(self, name):
        if not re.fullmatch(r"(?:gallery\.json|请勿手动清理\.txt|[a-f0-9]{32}\.image)", name):
            raise RepositoryError("非法画廊文件名")
        base = self.settings.plugin_data_dir.resolve()
        current = self.root
        while current != self.settings.plugin_data_dir:
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                raise RepositoryError("画廊目录不能是符号链接")
            current = current.parent
        path = self.root / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.resolve().is_relative_to(base / "style_gallery"):
            raise RepositoryError("画廊文件路径越界")
        return path

    def _read(self):
        path = self._path("gallery.json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = {"revision": "initial", "config": GalleryConfig().model_dump(), "items": [], "updated_at": None}
        self._save(data)
        return data

    def _save(self, data):
        path = self._path("gallery.json")
        self.root.mkdir(parents=True, exist_ok=True)
        warning = self._path("请勿手动清理.txt")
        if not warning.exists():
            warning.write_text("此目录为 AstrAutoAnima 画风画廊，不是普通图片缓存。\n请勿手动删除或让清理工具扫描此目录。\n请在管理端更换模特或更新画廊；删除会导致预览缺失。\n", encoding="utf-8")
        # Exclusive temp creation prevents following a pre-existing symlink.
        temporary = self.root / (uuid.uuid4().hex + ".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)

    def view(self, admin=False):
        data = self._read()
        active = self.task is not None and not self.task.done()
        result = copy.deepcopy(data)
        result["active"] = active
        result["ready"] = self._ready(data["config"])
        for item in result["items"]:
            for slot in item["slots"]:
                if slot["status"] in {"queued", "running"} and not active:
                    slot["status"] = "interrupted"
                if slot.get("file"):
                    slot["url"] = f"/api/v1/gallery/images/{slot['file'].split('.')[0]}"
                slot.pop("file", None)
                if not admin:
                    slot.pop("job_id", None)
        if not admin:
            result["config"] = {k: data["config"][k] for k in ("model_kind", "character", "character_text")}
        else:
            result["config"]["default_prompts"] = list(PROMPTS)
        return result

    @staticmethod
    def _ready(config):
        return all(p.strip() for p in config["prompts"]) and bool(config["target_id"]) and bool(
            config["character"] if config["model_kind"] == "character" else config["character_text"].strip())

    def _delete_owned(self, data):
        paths = []
        for item in data["items"]:
            for slot in item["slots"]:
                if slot.get("file"):
                    path = self._path(slot["file"])
                    if path.exists():
                        if not path.is_file():
                            raise RepositoryError("画廊清理目标不是普通文件")
                        paths.append(path)
        # Validate the complete manifest before deleting any file; never recurse.
        for path in set(paths):
            path.unlink()

    async def update(self, payload):
        async with self.lock:
            data = self._read()
            if payload.revision != data["revision"]:
                raise RepositoryError("画廊已变化，请刷新后重试")
            config = payload.config.model_dump()
            if any(len(p) > 10000 for p in config["prompts"]):
                raise RepositoryError("单条固定提示词不能超过 10000 字符")
            if config == data["config"]:
                return self.view(True)
            if data["items"] and not payload.confirm_clear:
                raise RepositoryError("修改画廊配置将清理旧预览，请确认")
            self._delete_owned(data)
            data = {"revision": uuid.uuid4().hex, "config": config, "items": [], "updated_at": time.time()}
            self._save(data)
            # The worker checks revision after every wait and never republishes old results.
            return self.view(True)

    async def generate(self, payload, principal):
        async with self.lock:
            if self.task and not self.task.done():
                raise RepositoryError("画廊更新仍在进行，请等待；不会重复提交")
            data = self._read()
            if payload.revision != data["revision"]:
                raise RepositoryError("画廊已变化，请刷新后重试")
            if not self._ready(data["config"]):
                raise RepositoryError("请先配置模特、任务身份目标以及四条固定提示词")
            presets = list_presets(self.settings.preset_path)
            config = data["config"]
            if config["model_kind"] == "character":
                role = next((p for p in presets.characters if p.name == config["character"]), None)
                if role is None or role.text_only or re.search(r"\s", role.name):
                    raise RepositoryError("请选择有效且名称不含空格的角色 LoRA 预设")
            selected = payload.styles or [s.name for s in presets.styles]
            if payload.slot_index is not None and len(payload.styles) != 1:
                raise RepositoryError("单张重绘必须明确选择一个画风")
            styles = {s.name: s for s in presets.styles}
            if not selected or len(set(selected)) != len(selected) or any(s not in styles or re.search(r"\s", s) for s in selected):
                raise RepositoryError("画风为空、重复、不存在或名称含空格")
            if config["target_id"] not in {t.id for t in self.jobs.targets(principal).targets}:
                raise RepositoryError("任务身份目标不可用，请重新选择；画廊任务不会发送 QQ 图片")
            # Preserve other styles; regenerate only the explicitly selected styles.
            previous = {i["style"]: i for i in data["items"]}
            data["items"] = [i for i in data["items"] if i["style"] not in selected]
            for name in selected:
                slots = copy.deepcopy(previous.get(name, {}).get("slots", [
                    {"index": n, "status": "queued"} for n in range(4)]))
                for n, slot in enumerate(slots):
                    if payload.slot_index is None or n == payload.slot_index:
                        slot.update(status="queued")
                        slot.pop("message", None)
                data["items"].append({"style": name, "preset_snapshot": styles[name].model_dump(),
                                      "character_snapshot": role.model_dump() if config["model_kind"] == "character" else None,
                                      "slots": slots})
            data["revision"] = uuid.uuid4().hex
            self._save(data)
            self.task = asyncio.create_task(self._run(data["revision"], selected, principal, payload.slot_index))
            return self.view(True)

    async def _run(self, revision, selected, principal, slot_index=None):
        for name in selected:
            for index in (range(4) if slot_index is None else [slot_index]):
                data = self._read()
                if data["revision"] != revision:
                    return
                item = next(i for i in data["items"] if i["style"] == name)
                slot = item["slots"][index]
                config = data["config"]
                replaced_file = None
                try:
                    # Detect edits during generation instead of silently mixing different presets.
                    current = next((s for s in list_presets(self.settings.preset_path).styles if s.name == name), None)
                    if current is None or current.model_dump() != item["preset_snapshot"]:
                        raise RepositoryError("画风预设已变化，请重新更新该画风")
                    if item.get("character_snapshot"):
                        role = next((r for r in list_presets(self.settings.preset_path).characters if r.name == config["character"]), None)
                        if role is None or role.model_dump() != item["character_snapshot"]:
                            raise RepositoryError("模特预设已变化，请重新更新画廊")
                    prompt = config["prompts"][index]
                    if config["model_kind"] == "text":
                        prompt = config["character_text"].strip() + ", " + prompt
                    request = RemoteJobCreateRequest(kind="direct", target_id=config["target_id"],
                        character=config["character"] if config["model_kind"] == "character" else "",
                        character_tag_mode="off", style=name, prompt=prompt, deliver_to_im=False)
                    job = self.jobs.create(request, principal)
                    slot.update(status="running", job_id=job.id)
                    self._save(data)
                    while job.status in {"queued", "running"}:
                        await asyncio.sleep(1)
                        if self._read()["revision"] != revision:
                            return
                        job = self.jobs.get(job.id, principal)
                        if job is None:
                            raise RepositoryError("画廊任务记录不可用")
                    if job.status != "succeeded" or not job.images:
                        raise RepositoryError(job.message or "任务未返回审核通过的图片")
                    latest = list_presets(self.settings.preset_path)
                    current = next((s for s in latest.styles if s.name == name), None)
                    if current is None or current.model_dump() != item["preset_snapshot"]:
                        raise RepositoryError("生成期间画风被修改，结果不发布，请重新更新")
                    if item.get("character_snapshot"):
                        role = next((r for r in latest.characters if r.name == config["character"]), None)
                        if role is None or role.model_dump() != item["character_snapshot"]:
                            raise RepositoryError("生成期间模特被修改，结果不发布，请重新更新")
                    located = self.jobs.get_image(job.id, job.images[0].id, principal)
                    if located is None:
                        raise RepositoryError("结果未通过访问或安全审核")
                    content = located[1].read_bytes()
                    self.jobs._require_approved(content)
                    old_file = slot.get("file")
                    if old_file:
                        # Validate the exact owned target before committing its replacement.
                        old_path = self._path(old_file)
                        if old_path.exists() and not old_path.is_file():
                            raise RepositoryError("旧画廊图片不是普通文件，停止替换")
                    filename = uuid.uuid4().hex + ".image"
                    with self._path(filename).open("xb") as stream:
                        stream.write(content)
                    slot.update(status="succeeded", file=filename, content_type=located[0].content_type)
                    replaced_file = old_file
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    slot.update(status="failed", message=str(exc)[:500])
                data["updated_at"] = time.time()
                self._save(data)
                if replaced_file:
                    path = self._path(replaced_file)
                    if path.exists():
                        try:
                            path.unlink()
                        except OSError as exc:
                            slot["message"] = f"新图已保存，但旧图清理失败：{exc}"
                            self._save(data)
                            return  # No stronger deletion or automatic retry.

    def image(self, image_id):
        if not re.fullmatch(r"[a-f0-9]{32}", image_id):
            raise RepositoryError("图片不存在")
        filename = image_id + ".image"
        slots = [s for i in self._read()["items"] for s in i["slots"] if s.get("file") == filename]
        if len(slots) != 1:
            raise RepositoryError("图片不存在或已过期")
        path = self._path(filename)
        if not path.is_file():
            raise RepositoryError("画廊图片已被手动清理，请管理员重新生成")
        self.jobs._require_approved(path.read_bytes())
        return path, slots[0]["content_type"]

    async def shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
