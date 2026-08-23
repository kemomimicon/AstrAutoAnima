from __future__ import annotations

import base64
import os
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils.quoted_message.onebot_client import OneBotClient


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


class EventImageResolver:
    """Resolve the first image from current, quoted, or raw OneBot messages."""

    def __init__(self, output_dir: Path, logger: Any):
        self.output_dir = Path(output_dir)
        self.logger = logger

    def _target(self, original: str = "image.png") -> Path:
        suffix = Path(urlparse(str(original or "")).path).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            suffix = ".png"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"input_{uuid.uuid4().hex}{suffix}"

    def _save_bytes(self, payload: bytes, original: str = "image.png") -> str | None:
        if not payload:
            return None
        target = self._target(original)
        target.write_bytes(payload)
        return str(target)

    async def _save_ref(self, value: str, original: str = "image.png") -> str | None:
        ref = str(value or "").strip()
        if not ref:
            return None
        if ref.startswith("base64://"):
            try:
                return self._save_bytes(
                    base64.b64decode(ref.removeprefix("base64://")), original
                )
            except Exception:
                return None
        if ref.startswith("data:"):
            header, separator, body = ref.partition(",")
            if separator and "base64" in header.lower():
                try:
                    return self._save_bytes(base64.b64decode(body), original)
                except Exception:
                    return None
        if ref.startswith(("http://", "https://")):
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(ref) as response:
                        if response.status >= 400:
                            return None
                        return self._save_bytes(await response.read(), ref)
            except Exception as exc:
                self.logger.warning("Comfy bridge image download failed: %s", exc)
                return None
        if ref.startswith("file://"):
            ref = ref[7:]
        source = Path(ref).expanduser()
        if source.is_file():
            target = self._target(source.name)
            shutil.copy2(source, target)
            return str(target)
        return None

    async def _save_component(self, component: Comp.Image) -> str | None:
        try:
            source = Path(await component.convert_to_file_path())
            if source.is_file():
                target = self._target(
                    str(component.file or component.url or source.name)
                )
                shutil.copy2(source, target)
                return str(target)
        except Exception as exc:
            self.logger.info("Comfy bridge component image fallback: %s", exc)
        for value in (
            getattr(component, "path", ""),
            getattr(component, "url", ""),
            getattr(component, "file", ""),
        ):
            saved = await self._save_ref(str(value or ""), str(value or "image.png"))
            if saved:
                return saved
        return None

    def _raw_segments(self, event: AstrMessageEvent) -> list[dict[str, Any]]:
        raw = getattr(event.message_obj, "raw_message", None)
        message = raw.get("message") if hasattr(raw, "get") else None
        return message if isinstance(message, list) else []

    def _onebot_client(self, event: AstrMessageEvent) -> OneBotClient | None:
        try:
            client = OneBotClient(event)
        except Exception:
            return None
        direct = getattr(getattr(event, "bot", None), "call_action", None)
        if getattr(client, "_call_action", None) is None and callable(direct):
            client._call_action = direct
        return client if getattr(client, "_call_action", None) is not None else None

    def _segment_component(self, data: dict[str, Any]) -> Comp.Image:
        return Comp.Image(
            file=str(
                data.get("file")
                or data.get("url")
                or data.get("path")
                or data.get("file_id")
                or data.get("id")
                or ""
            ),
            url=str(data.get("url") or ""),
            path=str(data.get("path") or ""),
            _type=str(data.get("sub_type") or data.get("type") or ""),
        )

    async def _save_action_result(
        self, data: dict[str, Any], original: str
    ) -> str | None:
        encoded = str(data.get("base64") or "")
        if encoded:
            saved = await self._save_ref(f"base64://{encoded}", original)
            if saved:
                return saved
        for key in ("file", "path", "file_path", "url"):
            saved = await self._save_ref(str(data.get(key) or ""), original)
            if saved:
                return saved
        return None

    async def _save_onebot_segment(
        self,
        event: AstrMessageEvent,
        data: dict[str, Any],
    ) -> str | None:
        saved = await self._save_component(self._segment_component(data))
        if saved:
            return saved
        client = self._onebot_client(event)
        if client is None:
            return None
        candidates = []
        for key in ("file", "file_id", "id", "path", "url"):
            value = str(data.get(key) or "").strip()
            if value and value not in candidates:
                candidates.append(value)
        for candidate in candidates:
            base, extension = os.path.splitext(candidate)
            identifiers = [candidate]
            if extension.lower() in IMAGE_SUFFIXES and base:
                identifiers.append(base)
            for identifier in identifiers:
                for action, params in (
                    ("get_image", {"file": identifier}),
                    ("get_image", {"file_id": identifier}),
                    ("get_image", {"id": identifier}),
                    ("get_file", {"file_id": identifier}),
                ):
                    try:
                        result = await client.call(
                            action,
                            params,
                            warn_on_all_failed=False,
                            unwrap_data=True,
                        )
                    except Exception:
                        continue
                    if isinstance(result, dict):
                        saved = await self._save_action_result(result, candidate)
                        if saved:
                            return saved
        return None

    async def _save_raw_reply(self, event: AstrMessageEvent) -> str | None:
        client = self._onebot_client(event)
        if client is None:
            return None
        for segment in self._raw_segments(event):
            if not isinstance(segment, dict) or segment.get("type") != "reply":
                continue
            data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
            reply_id = data.get("id")
            if reply_id is None:
                continue
            try:
                reply = await client.get_msg(str(reply_id))
            except Exception as exc:
                self.logger.warning("Comfy bridge reply lookup failed: %s", exc)
                continue
            messages = reply.get("message") if isinstance(reply, dict) else None
            if not isinstance(messages, list):
                continue
            for item in messages:
                if not isinstance(item, dict) or item.get("type") != "image":
                    continue
                image_data = item.get("data") if isinstance(item.get("data"), dict) else {}
                saved = await self._save_onebot_segment(event, image_data)
                if saved:
                    return saved
        return None

    async def resolve(self, event: AstrMessageEvent) -> str | None:
        reply_images: list[Comp.Image] = []
        direct_images: list[Comp.Image] = []
        for component in event.get_messages():
            if isinstance(component, Comp.Image):
                direct_images.append(component)
            elif isinstance(component, Comp.Reply):
                for inner in component.chain or []:
                    if isinstance(inner, Comp.Image):
                        reply_images.append(inner)

        for component in reply_images:
            saved = await self._save_component(component)
            if saved:
                return saved
        saved = await self._save_raw_reply(event)
        if saved:
            return saved
        for component in direct_images:
            saved = await self._save_component(component)
            if saved:
                return saved
        for segment in self._raw_segments(event):
            if not isinstance(segment, dict) or segment.get("type") != "image":
                continue
            data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
            saved = await self._save_onebot_segment(event, data)
            if saved:
                return saved
        return None
