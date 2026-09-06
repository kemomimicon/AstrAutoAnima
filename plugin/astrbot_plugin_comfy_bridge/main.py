from __future__ import annotations

import asyncio
import copy
import json
import re
import secrets
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import EventMessageType
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star

from .preset_runtime import (
    apply_lora_plan,
    clear_preset_trigger,
    get_preset,
    load_presets,
    parse_character_definition,
    parse_generation_directives,
    parse_style_definition,
    parse_text_character_definition,
    preset_prompt,
    resolve_presets,
    save_presets,
    preset_category_key,
    update_preset_trigger,
)
from .prompt_pool_runtime import (
    SOURCE_CODES,
    SAFETY_CODES,
    add_prompt_entry,
    apply_protected_character_policy,
    compose_random_body,
    decode_custom_group_token,
    decode_group_code_token,
    delete_prompt_entry,
    describe_selection,
    ensure_prompt_pool,
    export_prompt_entries,
    filter_prompt_entries,
    get_prompt_entry,
    import_prompt_entries,
    load_prompt_pool,
    parse_group_selector,
    parse_protected_characters,
    prompt_entry_custom_groups,
    prompt_pool_stats,
    quality_prompt,
    require_source_safety_selector,
    select_random_prompt,
    select_random_prompts,
    update_prompt_entry,
)
from .kp_dynamic_runtime import (
    assemble_dynamic_k_prompts,
    dynamic_k_history_count,
    load_kp_module_catalog,
    persist_dynamic_k_entries,
)
from .workflow_runtime import (
    RATIO_PRESETS,
    REVERSE_CATEGORIES,
    REVERSE_PRESETS,
    WorkflowError,
    build_prompt_text,
    configure_hq_workflow,
    configure_refine_workflow,
    configure_seedvr2_workflow,
    describe_workflow,
    extract_command_body,
    extract_command_prompt,
    extract_output_images,
    extract_reverse_result,
    history_error,
    history_failed,
    load_api_workflow,
    prepare_prompt_batch_workflow,
    prepare_workflow,
    prepare_reverse_workflow,
    resolve_canvas_size,
)
from .image_runtime import EventImageResolver
from .job_runtime import JobStore
from .llm_runtime import reverse_image_prompt, translate_chinese_prompt
from .cleanup_runtime import CleanupReport, cleanup_old_output_images
from .character_dictionary_runtime import resolve_character
from .agent_tools_runtime import (
    build_agent_generation_request,
    list_agent_presets,
)
from .workflow_registry import (
    WorkflowDefinition,
    load_workflow_registry,
    resolve_workflow_path,
    validate_workflow_nodes,
)


@dataclass
class PendingImageRequest:
    token: str
    event: AstrMessageEvent
    options: dict[str, Any]
    extra_prompt: str
    reverse_preset: str = "full"
    reverse_categories: tuple[str, ...] = ()
    reverse_only: bool = False
    timeout_task: asyncio.Task[Any] | None = None


REVERSE_CATEGORY_ALIASES = {
    "场景": "scene", "环境": "scene", "scene": "scene",
    "动作": "action", "姿势": "action", "action": "action",
    "角色": "character", "人物": "character", "character": "character",
    "外观": "appearance", "外貌": "appearance", "appearance": "appearance",
    "特殊特征": "special_features", "兽征": "special_features", "special": "special_features", "special_features": "special_features",
    "服装": "clothing", "衣着": "clothing", "clothing": "clothing",
    "构图": "composition", "镜头": "composition", "composition": "composition",
    "其他": "other", "细节": "other", "other": "other",
    "安全": "safety", "安全过滤": "safety", "safe": "safety", "safety": "safety",
}
REVERSE_CATEGORY_LABELS = {
    "scene": "场景",
    "action": "动作",
    "character": "角色",
    "appearance": "外观",
    "special_features": "特殊特征",
    "clothing": "服装",
    "composition": "构图",
    "other": "其他",
}
REVERSE_PRESET_CATEGORIES = {
    "full": tuple(REVERSE_CATEGORY_LABELS),
    "scene": ("scene", "composition"),
    "action": ("action", "composition"),
    "character": ("character", "appearance", "special_features", "clothing"),
    "safe": tuple(REVERSE_CATEGORY_LABELS),
}


class ComfyWorkflowBridge(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        concurrency = max(1, int(config.get("max_concurrency", 1)))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._five_draw_cooldowns: dict[str, float] = {}
        self._five_draw_active_users: set[str] = set()
        self._five_draw_lock = asyncio.Lock()
        self._agent_tool_cooldowns: dict[str, float] = {}
        self._agent_tool_active_users: set[str] = set()
        self._agent_tool_lock = asyncio.Lock()
        self._pending_images: dict[tuple[str, str], PendingImageRequest] = {}
        self._pending_lock = asyncio.Lock()
        self._image_resolver = EventImageResolver(self._input_dir(), logger)
        self._cleanup_task: asyncio.Task[Any] | None = None

    async def initialize(self):
        """Start the bounded plugin-output cleanup worker."""
        if bool(self.config.get("output_cleanup_enabled", True)):
            self._cleanup_task = asyncio.create_task(
                self._output_cleanup_loop(),
                name="aaa-output-cleanup",
            )

    def _base_url(self) -> str:
        value = str(
            self.config.get("comfyui_base_url", "http://127.0.0.1:8188")
        ).strip()
        return value.rstrip("/")

    def _workflow_path(self) -> Path:
        configured = str(self.config.get("workflow_path", "")).strip()
        if not configured:
            raise WorkflowError("请先在插件配置中填写 workflow_path。")
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path.resolve()

    def _reverse_workflow_path(self) -> Path:
        configured = str(self.config.get("reverse_workflow_path", "")).strip()
        if not configured:
            raise WorkflowError("请先在插件配置中填写 reverse_workflow_path。")
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path.resolve()

    def _registry_path(self) -> Path:
        configured = str(
            self.config.get("workflow_registry_path", "data/workflow_registry.json")
        ).strip()
        path = Path(configured or "data/workflow_registry.json").expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path.resolve()

    def _job_store(self) -> JobStore:
        configured = str(self.config.get("job_store_path", "")).strip()
        path = Path(
            configured
            or "data/plugin_data/astrbot_plugin_comfy_bridge/job_store"
        ).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return JobStore(path)

    def _workflow_definition(
        self, workflow_type: str
    ) -> tuple[WorkflowDefinition, Path]:
        registry = load_workflow_registry(self._registry_path())
        definition = registry.resolve(workflow_type)
        path = resolve_workflow_path(
            definition,
            config=self.config,
            plugin_dir=Path(__file__).resolve().parent,
        )
        return definition, path

    @staticmethod
    def _event_source(event: AstrMessageEvent | None) -> dict[str, Any]:
        if event is None:
            return {"platform": "unknown", "session_id": "", "user_id": ""}
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        platform = origin.split(":", 1)[0] if ":" in origin else "astrbot"
        return {
            "platform": platform,
            "session_id": str(event.get_session_id() or origin),
            "user_id": str(event.get_sender_id() or ""),
        }

    def _output_dir(self) -> Path:
        configured = str(self.config.get("output_dir", "")).strip()
        if configured:
            output_dir = Path(configured).expanduser()
        else:
            output_dir = Path(
                "data/plugin_data/astrbot_plugin_comfy_bridge/outputs"
            )
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir.resolve()

    def _output_retention_hours(self) -> float:
        try:
            return max(
                1.0,
                float(self.config.get("output_retention_hours", 48)),
            )
        except (TypeError, ValueError):
            return 48.0

    def _output_cleanup_interval_seconds(self) -> int:
        try:
            minutes = float(
                self.config.get("output_cleanup_interval_minutes", 60)
            )
        except (TypeError, ValueError):
            minutes = 60.0
        return max(300, int(minutes * 60))

    async def _cleanup_plugin_outputs(self) -> CleanupReport:
        return await asyncio.to_thread(
            cleanup_old_output_images,
            self._output_dir(),
            self._output_retention_hours(),
        )

    async def _output_cleanup_loop(self) -> None:
        while True:
            try:
                report = await self._cleanup_plugin_outputs()
                if report.deleted or report.failed:
                    logger.info(
                        "[comfy_bridge] output cleanup scanned=%s deleted=%s "
                        "deleted_bytes=%s failed=%s retention_hours=%s dir=%s",
                        report.scanned,
                        report.deleted,
                        report.deleted_bytes,
                        report.failed,
                        self._output_retention_hours(),
                        self._output_dir(),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[comfy_bridge] output cleanup failed: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            await asyncio.sleep(self._output_cleanup_interval_seconds())

    def _input_dir(self) -> Path:
        configured = str(self.config.get("input_dir", "")).strip()
        if configured:
            input_dir = Path(configured).expanduser()
        else:
            input_dir = Path(
                "data/plugin_data/astrbot_plugin_comfy_bridge/inputs"
            )
        if not input_dir.is_absolute():
            input_dir = Path.cwd() / input_dir
        input_dir.mkdir(parents=True, exist_ok=True)
        return input_dir.resolve()

    def _preset_path(self) -> Path:
        configured = str(self.config.get("preset_store_path", "")).strip()
        if configured:
            path = Path(configured).expanduser()
        else:
            path = Path(
                "data/plugin_data/astrbot_plugin_comfy_bridge/presets.json"
            )
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def _character_dictionary_path(self) -> Path:
        configured = str(self.config.get("character_dictionary_path", "")).strip()
        if configured:
            path = Path(configured).expanduser()
        else:
            path = Path(
                "data/plugin_data/astrbot_plugin_comfy_bridge/character_dictionary.json"
            )
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def _character_dictionary_edits_path(self) -> Path:
        configured = str(
            self.config.get("character_dictionary_edits_path", "")
        ).strip()
        if configured:
            path = Path(configured).expanduser()
        else:
            path = Path(
                "/workspace/astrbot-runtime/data/plugin_data/"
                "astrbot_plugin_comfy_bridge/hub_state/"
                "character_dictionary_edits.json"
            )
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path.resolve()

    def _prompt_pool_path(self) -> Path:
        configured = str(self.config.get("prompt_pool_path", "")).strip()
        if configured:
            path = Path(configured).expanduser()
        else:
            path = Path(
                "data/plugin_data/astrbot_plugin_comfy_bridge/"
                "anima_random_prompt_pool.json"
            )
        if not path.is_absolute():
            path = Path.cwd() / path
        bundled = Path(__file__).resolve().parent / "data" / "anima_random_prompt_pool.json"
        return ensure_prompt_pool(path.resolve(), bundled)

    def _kp_prompt_pool_path(self) -> Path:
        """Return the isolated K prompt pool, installing the bundled catalog once."""

        path = self._prompt_pool_path().with_name("kp_prompt_pool.json")
        bundled = Path(__file__).resolve().parent / "data" / "kp_prompt_pool.json"
        return ensure_prompt_pool(path.resolve(), bundled)

    def _kp_dynamic_catalog_path(self) -> Path:
        raw = str(self.config.get("kp_dynamic_modules_path", "")).strip()
        if not raw:
            return Path(__file__).resolve().parent / "data" / "kp_dynamic_modules.json"
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return path.resolve()

    def _kp_dynamic_items(
        self,
        pool: dict[str, Any],
        selection: dict[str, Any],
        *,
        count: int,
        options: dict[str, Any],
        user_prompt: str = "",
        excluded_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            catalog = load_kp_module_catalog(self._kp_dynamic_catalog_path())
            return assemble_dynamic_k_prompts(
                pool,
                catalog,
                count,
                safety_codes=selection.get("safety_codes", ["N", "H"]),
                preserve_character=bool(str(options.get("character", "")).strip()),
                min_optional_modules=int(
                    self.config.get("kp_dynamic_optional_modules_min", 4)
                ),
                max_optional_modules=int(
                    self.config.get("kp_dynamic_optional_modules_max", 7)
                ),
                max_tags=int(self.config.get("kp_dynamic_max_tags", 72)),
                excluded_ids=excluded_ids,
            )
        except WorkflowError:
            if not bool(self.config.get("kp_dynamic_fallback_examples", True)):
                raise
            logger.exception("KP dynamic composition failed; falling back to examples")
            working_pool = dict(pool)
            if excluded_ids:
                working_pool["prompts"] = [
                    item
                    for item in pool.get("prompts", [])
                    if str(item.get("id", "")) not in excluded_ids
                    and not bool(item.get("runtime_generated"))
                ]
            selected, _, _ = select_random_prompts(
                working_pool,
                count,
                user_prompt,
                source_codes=["K"],
                safety_codes=selection.get("safety_codes", ["N", "H"]),
            )
            return selected

    def _random_prompt_pool(self, selection: dict[str, Any]) -> dict[str, Any]:
        sources = list(selection.get("source_codes", []))
        if "K" not in sources:
            return load_prompt_pool(self._prompt_pool_path())
        if selection.get("custom_groups"):
            raise WorkflowError("K 动态库不支持自定义分组筛选；请移除 @分组。")
        if sources != ["K"]:
            raise WorkflowError("K 组使用独立 KP 库，必须单独选择 K；可写 K/N、K/H 或 K/S。")
        pool = load_prompt_pool(self._kp_prompt_pool_path())
        if not bool(self.config.get("kp_dynamic_enabled", True)):
            pool = dict(pool)
            pool["prompts"] = [
                item
                for item in pool.get("prompts", [])
                if not (isinstance(item, dict) and item.get("runtime_generated"))
            ]
        return pool

    def _prompt_pool_trash_path(self) -> Path:
        return self._prompt_pool_path().with_name("prompt_pool_trash.json")

    def _export_dir(self) -> Path:
        path = self._prompt_pool_path().parent / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _private_umo(event: AstrMessageEvent) -> str:
        parts = str(event.unified_msg_origin or "").split(":", 2)
        if len(parts) != 3 or not parts[0]:
            raise WorkflowError("无法从当前消息构造私聊目标，请直接私聊机器人后重试。")
        return f"{parts[0]}:FriendMessage:{event.get_sender_id()}"

    @staticmethod
    def _is_private_event(event: AstrMessageEvent) -> bool:
        parts = str(event.unified_msg_origin or "").split(":", 2)
        return len(parts) == 3 and parts[1].casefold() == "friendmessage"

    async def _send_private_text(
        self, event: AstrMessageEvent, text: str, *, acknowledge: bool = True
    ) -> bool:
        chunks = [text[index : index + 3500] for index in range(0, len(text), 3500)] or [""]
        try:
            if self._is_private_event(event):
                for chunk in chunks:
                    await event.send(event.plain_result(chunk))
            else:
                target = self._private_umo(event)
                for chunk in chunks:
                    sent = await self.context.send_message(
                        target, MessageChain().message(chunk)
                    )
                    if sent is False:
                        raise WorkflowError("AstrBot 没有找到可用的私聊平台实例。")
                if acknowledge:
                    await event.send(event.plain_result("查询结果已私聊发送。"))
            return True
        except Exception as exc:
            logger.warning("Comfy bridge private message failed: %s", exc)
            if not self._is_private_event(event):
                await event.send(
                    event.plain_result(
                        f"私聊发送失败：{exc}\n请先私聊机器人发送一次消息，再在私聊中重试该指令。"
                    )
                )
            return False

    async def _send_private_file(
        self,
        event: AstrMessageEvent,
        path: Path,
        *,
        caption: str,
    ) -> bool:
        try:
            chain = MessageChain().message(caption)
            chain.chain.append(Comp.File(file=str(path), name=path.name))
            if self._is_private_event(event):
                await event.send(chain)
            else:
                sent = await self.context.send_message(self._private_umo(event), chain)
                if sent is False:
                    raise WorkflowError("AstrBot 没有找到可用的私聊平台实例。")
                await event.send(event.plain_result("导出文件已私聊发送。"))
            return True
        except Exception as exc:
            logger.warning("Comfy bridge private file failed: %s", exc)
            await event.send(
                event.plain_result(
                    f"私聊文件发送失败：{exc}\n文件已保留在服务器：{path}"
                )
            )
            return False

    @staticmethod
    def _parse_pool_filter(
        body: str,
    ) -> tuple[list[str], list[str], list[str], int, str, str]:
        remaining = str(body or "").strip()
        sources = list(SOURCE_CODES)
        safety = list(SAFETY_CODES)
        custom_groups: list[str] = []
        selectors: list[str] = []
        while remaining:
            first, _, tail = remaining.partition(" ")
            decoded = decode_group_code_token(first)
            custom = decode_custom_group_token(first)
            if decoded is not None and not any(not item.startswith("@") for item in selectors):
                selected_sources, selected_safety = decoded
                sources = selected_sources or sources
                safety = selected_safety or safety
                selectors.append(first.upper())
                remaining = tail.strip()
            elif custom is not None and not custom_groups:
                custom_groups = custom
                selectors.append("@" + "+".join(custom))
                remaining = tail.strip()
            else:
                break
        selector = " ".join(selectors) or "ALL"
        page = 1
        if remaining:
            first, _, tail = remaining.partition(" ")
            if first.isdigit():
                page = max(1, int(first))
                remaining = tail.strip()
        return sources, safety, custom_groups, page, remaining, selector

    @staticmethod
    def _format_prompt_entry(item: dict[str, Any], *, full: bool = True) -> str:
        prompt = str(item.get("prompt", ""))
        if not full and len(prompt) > 140:
            prompt = prompt[:137] + "..."
        categories = ", ".join(str(value) for value in item.get("categories", []))
        custom_groups = ", ".join(prompt_entry_custom_groups(item))
        return (
            f"ID：{item.get('id', '?')}\n"
            f"名称：{item.get('name', '未命名')}\n"
            f"分组：{item.get('source_code', '?')}/{item.get('safety_code', '?')}｜"
            f"启用：{bool(item.get('enabled', True))}｜权重：{item.get('weight', 1)}\n"
            f"分类：{categories or '无'}\n"
            f"自定义分组：{custom_groups or '无'}\n"
            f"提示词：{prompt}"
        )

    @staticmethod
    def _format_preset_detail(category: str, name: str, preset: dict[str, Any]) -> str:
        key = preset_category_key(category)
        lines = [f"{'画风' if key == 'styles' else '角色'}：{name}"]
        if key == "styles":
            loras = preset.get("loras", [])
            lines.append(f"LoRA：{len(loras)} 个")
            for index, lora in enumerate(loras, start=1):
                lines.append(
                    f"  {index}. {lora.get('name', '?')}｜"
                    f"model={lora.get('strength_model', 1)}｜"
                    f"clip={lora.get('strength_clip', 1)}"
                )
            lines.append(
                "match：" + (" | ".join(str(x) for x in preset.get("match", [])) or "无")
            )
        else:
            lora = preset.get("lora")
            if isinstance(lora, dict):
                lines.append(
                    f"LoRA：{lora.get('name', '?')}｜"
                    f"model={lora.get('strength_model', 1)}｜"
                    f"clip={lora.get('strength_clip', 1)}"
                )
            else:
                lines.append("LoRA：无（底模直出角色）")
        lines.append(f"prompt：{str(preset.get('prompt', '')).strip() or '无'}")
        return "\n".join(lines)

    def _style_slot_ids(self) -> list[str]:
        value = str(self.config.get("style_lora_node_ids", "46,47,48,49"))
        return [item.strip() for item in value.split(",") if item.strip()]

    def _timeout_seconds(self) -> int:
        return max(10, int(self.config.get("timeout_seconds", 300)))

    def _poll_interval(self) -> float:
        return max(0.25, float(self.config.get("poll_interval_seconds", 1.0)))

    def _sampler_overrides(self, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        requested = str(options.get("sampler_preset", "")).strip().casefold()
        if requested in {
            "", "default", "current", "original", "原始", "原有", "现有"
        }:
            preset = "original"
            overrides: dict[str, Any] = {}
        elif requested in {
            "dpm", "2m", "dpm2m", "dpmpp", "dpmpp_2m", "dpm++2m"
        }:
            preset = "2m"
            overrides = {
                "sampler_name": str(
                    self.config.get("dpm_sampler_name", "dpmpp_2m")
                ).strip(),
                "steps": int(self.config.get("dpm_sampler_steps", 30)),
                "cfg": float(self.config.get("dpm_sampler_cfg", 6.0)),
                "scheduler": str(
                    self.config.get("dpm_sampler_scheduler", "normal")
                ).strip(),
            }
        elif requested in {
            "sde", "2m_sde", "dpm2msde", "dpm_2m_sde",
            "dpmpp_2m_sde", "dpm++2msde"
        }:
            preset = "2m_sde"
            overrides = {
                "sampler_name": str(
                    self.config.get(
                        "dpm_2m_sde_sampler_name", "dpmpp_2m_sde"
                    )
                ).strip(),
                "steps": int(self.config.get("dpm_2m_sde_sampler_steps", 30)),
                "cfg": float(self.config.get("dpm_2m_sde_sampler_cfg", 6.0)),
                "scheduler": str(
                    self.config.get("dpm_2m_sde_sampler_scheduler", "normal")
                ).strip(),
            }
        elif requested in {
            "gpu", "2m_sde_gpu", "dpm2msdegpu", "dpm_2m_sde_gpu",
            "dpmpp_2m_sde_gpu", "dpm++2msdegpu"
        }:
            preset = "2m_sde_gpu"
            overrides = {
                "sampler_name": str(
                    self.config.get(
                        "dpm_2m_sde_gpu_sampler_name", "dpmpp_2m_sde_gpu"
                    )
                ).strip(),
                "steps": int(
                    self.config.get("dpm_2m_sde_gpu_sampler_steps", 30)
                ),
                "cfg": float(
                    self.config.get("dpm_2m_sde_gpu_sampler_cfg", 6.0)
                ),
                "scheduler": str(
                    self.config.get(
                        "dpm_2m_sde_gpu_sampler_scheduler", "normal"
                    )
                ).strip(),
            }
        else:
            raise WorkflowError(
                "采样器选项只能是 原有、2m、2m_sde 或 2m_sde_gpu。"
            )

        requested_scheduler = str(options.get("scheduler", "")).strip().casefold()
        supported_schedulers = {
            "normal",
            "karras",
            "exponential",
            "sgm_uniform",
            "simple",
            "ddim_uniform",
            "beta",
            "linear_quadratic",
            "kl_optimal",
        }
        if requested_scheduler:
            if requested_scheduler not in supported_schedulers:
                raise WorkflowError(
                    "调度器选项只能是 normal、karras、exponential、"
                    "sgm_uniform、simple、ddim_uniform、beta、"
                    "linear_quadratic 或 kl_optimal。"
                )
            overrides["scheduler"] = requested_scheduler

        if "sampler_steps" in options:
            try:
                overrides["steps"] = int(str(options["sampler_steps"]).strip())
            except (TypeError, ValueError) as exc:
                raise WorkflowError("步数必须是整数。") from exc
        if "sampler_cfg" in options:
            try:
                overrides["cfg"] = float(str(options["sampler_cfg"]).strip())
            except (TypeError, ValueError) as exc:
                raise WorkflowError("CFG 必须是数字。") from exc
        return preset, overrides

    def _five_draw_cooldown_seconds(self) -> int:
        return max(0, int(self.config.get("five_draw_cooldown_seconds", 150)))

    def _five_draw_cooldown_remaining(self, event: AstrMessageEvent) -> int:
        if event.is_admin():
            return 0
        sender_id = str(event.get_sender_id())
        elapsed = time.monotonic() - self._five_draw_cooldowns.get(sender_id, 0.0)
        return max(0, int(self._five_draw_cooldown_seconds() - elapsed + 0.999))

    def _start_five_draw_cooldown(self, event: AstrMessageEvent) -> None:
        if not event.is_admin():
            self._five_draw_cooldowns[str(event.get_sender_id())] = time.monotonic()

    async def _claim_five_draw(self, event: AstrMessageEvent) -> tuple[bool, str]:
        sender_id = str(event.get_sender_id() or "unknown-sender")
        if self._event_is_admin(event) or not bool(
            self.config.get("five_draw_single_active", True)
        ):
            return True, sender_id
        async with self._five_draw_lock:
            if sender_id in self._five_draw_active_users:
                return False, sender_id
            self._five_draw_active_users.add(sender_id)
        return True, sender_id

    async def _release_five_draw(
        self, event: AstrMessageEvent, sender_id: str
    ) -> None:
        if self._event_is_admin(event):
            return
        async with self._five_draw_lock:
            self._five_draw_active_users.discard(sender_id)

    @staticmethod
    def _event_is_admin(event: AstrMessageEvent) -> bool:
        checker = getattr(event, "is_admin", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    async def _claim_agent_tool_generation(
        self, event: AstrMessageEvent
    ) -> tuple[bool, str]:
        sender_id = str(event.get_sender_id() or "unknown-sender")
        if self._event_is_admin(event):
            return True, sender_id
        cooldown = max(
            0, int(self.config.get("agent_tool_user_cooldown_seconds", 30))
        )
        elapsed = time.monotonic() - self._agent_tool_cooldowns.get(sender_id, 0.0)
        remaining = max(0, int(cooldown - elapsed + 0.999))
        async with self._agent_tool_lock:
            if sender_id in self._agent_tool_active_users:
                return False, "该用户已有自主绘图任务正在执行。"
            if remaining > 0:
                return False, f"自主绘图冷却中，请等待 {remaining} 秒。"
            self._agent_tool_active_users.add(sender_id)
        return True, sender_id

    async def _release_agent_tool_generation(
        self, event: AstrMessageEvent, sender_id: str, *, success: bool
    ) -> None:
        if self._event_is_admin(event):
            return
        async with self._agent_tool_lock:
            self._agent_tool_active_users.discard(sender_id)
            if success:
                self._agent_tool_cooldowns[sender_id] = time.monotonic()

    async def _response_json(self, response: aiohttp.ClientResponse) -> Any:
        text = await response.text()
        if response.status >= 400:
            raise WorkflowError(
                f"ComfyUI HTTP {response.status}：{text[:1000]}"
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"ComfyUI 返回了无效 JSON：{text[:500]}") from exc

    async def _submit_workflow(
        self, session: aiohttp.ClientSession, workflow: dict[str, Any]
    ) -> str:
        payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}
        async with session.post(f"{self._base_url()}/prompt", json=payload) as response:
            data = await self._response_json(response)

        prompt_id = str(data.get("prompt_id", "")) if isinstance(data, dict) else ""
        if not prompt_id:
            raise WorkflowError(f"ComfyUI 未返回 prompt_id：{data}")
        return prompt_id

    async def _wait_for_history(
        self, session: aiohttp.ClientSession, prompt_id: str
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_seconds()
        history_url = f"{self._base_url()}/history/{prompt_id}"

        while loop.time() < deadline:
            async with session.get(history_url) as response:
                data = await self._response_json(response)

            record = data.get(prompt_id) if isinstance(data, dict) else None
            if isinstance(record, dict):
                status = record.get("status", {})
                if history_failed(record):
                    raise WorkflowError(history_error(record))
                completed = (
                    status.get("completed", False)
                    if isinstance(status, dict)
                    else False
                )
                if completed:
                    return record

            await asyncio.sleep(self._poll_interval())

        raise WorkflowError(f"生成超过 {self._timeout_seconds()} 秒，任务已超时。")

    async def _download_images(
        self,
        session: aiohttp.ClientSession,
        prompt_id: str,
        image_refs: list[dict[str, str]],
        *,
        max_images_override: int | None = None,
    ) -> list[Path]:
        output_dir = self._output_dir()
        max_images = (
            max(1, int(max_images_override))
            if max_images_override is not None
            else max(1, int(self.config.get("max_images", 4)))
        )
        paths: list[Path] = []

        for index, image_ref in enumerate(image_refs[:max_images], start=1):
            async with session.get(
                f"{self._base_url()}/view", params=image_ref
            ) as response:
                if response.status >= 400:
                    detail = (await response.text())[:500]
                    raise WorkflowError(
                        f"下载结果失败 HTTP {response.status}：{detail}"
                    )
                content = await response.read()

            suffix = Path(image_ref["filename"]).suffix or ".png"
            path = output_dir / f"{prompt_id}_{index}{suffix}"
            path.write_bytes(content)
            paths.append(path)

        return paths

    async def _upload_reverse_image(
        self, session: aiohttp.ClientSession, image_path: str
    ) -> str:
        path = Path(str(image_path)).expanduser().resolve()
        if not path.is_file():
            raise WorkflowError(f"反推输入图片不存在：{path}")

        upload_name = f"aaa_reverse_{uuid.uuid4().hex}{path.suffix or '.png'}"
        form = aiohttp.FormData()
        with path.open("rb") as handle:
            form.add_field(
                "image",
                handle,
                filename=upload_name,
                content_type="application/octet-stream",
            )
            form.add_field("type", "input")
            form.add_field("overwrite", "false")
            async with session.post(
                f"{self._base_url()}/upload/image", data=form
            ) as response:
                data = await self._response_json(response)

        if not isinstance(data, dict) or not data.get("name"):
            raise WorkflowError(f"ComfyUI 上传图片后未返回文件名：{data}")
        subfolder = str(data.get("subfolder", "")).strip("/\\")
        name = str(data["name"]).strip()
        return f"{subfolder}/{name}" if subfolder else name

    def _reverse_session_metadata(
        self, event: AstrMessageEvent
    ) -> tuple[str, str, str]:
        origin = str(
            getattr(event, "unified_msg_origin", "")
            or event.get_session_id()
            or ""
        )
        lowered = origin.lower()
        if "groupmessage" in lowered:
            session_type = "group"
        elif "friendmessage" in lowered or "privatemessage" in lowered:
            session_type = "private"
        else:
            session_type = "unknown"
        return (
            str(event.get_sender_id() or ""),
            session_type,
            str(event.get_session_id() or origin),
        )

    async def _run_reverse_workflow(
        self,
        event: AstrMessageEvent,
        image_path: str,
        options: dict[str, Any],
        reverse_preset: str,
        reverse_categories: tuple[str, ...] = (),
        reverse_only: bool = False,
    ) -> dict[str, Any]:
        template = load_api_workflow(self._reverse_workflow_path())
        qq_user_id, session_type, session_id = self._reverse_session_metadata(event)
        effective_categories = tuple(reverse_categories)
        if str(options.get("character", "")).strip():
            if not effective_categories:
                effective_categories = tuple(
                    category
                    for category in (
                        REVERSE_PRESET_CATEGORIES.get(reverse_preset)
                        or tuple(REVERSE_CATEGORY_LABELS)
                    )
                    if category != "appearance"
                )
                if reverse_preset == "safe":
                    effective_categories = (*effective_categories, "safety")
            else:
                effective_categories = tuple(
                    category for category in effective_categories
                    if category != "appearance"
                )
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds() + 30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            uploaded_name = await self._upload_reverse_image(session, image_path)
            workflow = prepare_reverse_workflow(
                template,
                image_name=uploaded_name,
                preset=reverse_preset,
                categories=effective_categories or None,
                image_node_id=str(
                    self.config.get("reverse_image_node_id", "1")
                ).strip(),
                compiler_node_id=str(
                    self.config.get("reverse_compiler_node_id", "7")
                ).strip(),
                saver_node_id=str(
                    self.config.get("reverse_saver_node_id", "8")
                ).strip(),
                qq_user_id=qq_user_id,
                session_type=session_type,
                session_id=session_id,
                role_preset=str(options.get("character", "")),
                style_preset=str(options.get("style", "")),
                storage_root=str(
                    self.config.get(
                        "reverse_history_dir",
                        "/workspace/astrbot-runtime/data/plugin_data/"
                        "astrbot_plugin_comfy_bridge/reverse_history",
                    )
                ),
                save_thumbnail=bool(
                    self.config.get("reverse_save_thumbnail", False)
                ),
            )
            prompt_id = await self._submit_workflow(session, workflow)
            logger.info(
                "Comfy bridge submitted reverse prompt_id=%s workflow=%s preset=%s categories=%s",
                prompt_id,
                self._reverse_workflow_path(),
                reverse_preset,
                ",".join(effective_categories),
            )
            record = await self._wait_for_history(session, prompt_id)
        result = extract_reverse_result(
            record,
            str(self.config.get("reverse_saver_node_id", "8")).strip(),
            allow_empty_prompt=reverse_only,
        )
        result["prompt_id"] = prompt_id
        result["effective_categories"] = effective_categories
        return result

    async def _generate(
        self,
        prompt: str,
        options: dict[str, Any],
        *,
        extra_prefix: str = "",
        strict_no_style: bool = False,
        allow_character_text_fallback: bool = False,
        workflow_type: str = "quick_txt2img_v1",
        profile: str = "",
        event: AstrMessageEvent | None = None,
        source_image_path: str = "",
        parent_job_id: str | None = None,
        metadata_restore: str = "none",
        batch_prompts: list[str] | None = None,
    ) -> tuple[list[Path], int | None, str, dict[str, Any]]:
        clean_batch_prompts = [
            str(item or "").strip() for item in (batch_prompts or [])
        ]
        if clean_batch_prompts:
            if workflow_type != "quick_txt2img_v1":
                raise WorkflowError("批量提示词当前仅支持 Quick 生图工作流。")
            if any(not item for item in clean_batch_prompts):
                raise WorkflowError("批量提示词中不能包含空内容。")
            prompt = clean_batch_prompts[0]
        definition, workflow_path = self._workflow_definition(workflow_type)
        selected_profile, profile_data = definition.profile(profile)
        template = load_api_workflow(workflow_path)
        validate_workflow_nodes(template, definition)
        mapping = dict(definition.node_mapping)
        if workflow_type == "quick_txt2img_v1":
            mapping.update(
                {
                    "positive": str(
                        self.config.get("positive_prompt_node_id", "11")
                    ).strip(),
                    "negative": str(
                        self.config.get("negative_prompt_node_id", "12")
                    ).strip(),
                    "sampler": str(
                        self.config.get("sampler_node_id", "19")
                    ).strip(),
                    "latent": str(
                        self.config.get("latent_node_id", "28")
                    ).strip(),
                }
            )
        presets = load_presets(self._preset_path())
        restored_loras = options.get("_restore_lora_stack")
        if isinstance(restored_loras, list):
            style_entries = [
                {
                    "name": str(item.get("name", "")),
                    "strength_model": float(item.get("strength_model", 1.0)),
                    "strength_clip": float(item.get("strength_clip", 1.0)),
                }
                for item in restored_loras
                if isinstance(item, dict) and item.get("kind") == "style"
            ]
            character_entry = next(
                (
                    item
                    for item in restored_loras
                    if isinstance(item, dict) and item.get("kind") == "character"
                ),
                None,
            )
            style = {"loras": style_entries, "prompt": "", "match": []}
            character = (
                {
                    "lora": {
                        "name": str(character_entry.get("name", "")),
                        "strength_model": float(
                            character_entry.get("strength_model", 1.0)
                        ),
                        "strength_clip": float(
                            character_entry.get("strength_clip", 1.0)
                        ),
                    },
                    "prompt": "",
                }
                if isinstance(character_entry, dict)
                else None
            )
            style_name = str(options.get("_restored_style_name", ""))
            character_name = str(options.get("_restored_character_name", ""))
        else:
            style, character, style_name, character_name = resolve_presets(
                prompt,
                options,
                presets,
                default_style=(
                    ""
                    if strict_no_style
                    else str(self.config.get("default_style_preset", ""))
                ),
                auto_match=(
                    False
                    if strict_no_style and not options.get("style")
                    else bool(self.config.get("style_auto_match", True))
                ),
                allow_character_text_fallback=allow_character_text_fallback,
            )
        character_text = ""
        if character_name and character is None:
            character_text = character_name
            dictionary_path = self._character_dictionary_path()
            if (
                bool(self.config.get("character_dictionary_enabled", True))
                and dictionary_path.is_file()
            ):
                match = resolve_character(
                    dictionary_path,
                    character_name,
                    mode=str(
                        options.get("character_tag_mode")
                        or self.config.get("character_dictionary_default_mode", "weak")
                    ),
                    edits_path=self._character_dictionary_edits_path(),
                )
                if match is not None:
                    character_text = match.prompt
                    options["_character_dictionary_tag"] = match.tag
                    options["_character_dictionary_mode"] = match.mode
        if strict_no_style and not style_name:
            style = {"loras": [], "prompt": "", "match": []}
        positive_node_id = mapping.get("positive", "11")
        negative_node_id = mapping.get("negative", "12")
        sampler_node_id = mapping.get("sampler", "19")
        sampler_preset, user_sampler_overrides = self._sampler_overrides(options)
        profile_sampling = profile_data.get("sampling", {})
        if profile_sampling and not isinstance(profile_sampling, dict):
            raise WorkflowError("Profile sampling 必须是对象。")
        sampler_overrides = dict(profile_sampling or {})
        sampler_overrides.update(user_sampler_overrides)
        width: int | None = None
        height: int | None = None
        if definition.category == "generate":
            width, height = resolve_canvas_size(
                options,
                default_width=int(self.config.get("default_width", 1024)),
                default_height=int(self.config.get("default_height", 1536)),
                max_pixels=int(self.config.get("max_canvas_pixels", 2359296)),
            )
        if bool(options.get("_compiled_prompt")):
            dynamic_prefix = ""
        else:
            dynamic_prefix = build_prompt_text(
                str(self.config.get("positive_prefix", "")),
                extra_prefix,
                build_prompt_text(
                    preset_prompt(style, character),
                    character_text,
                    "",
                ),
            )
        workflow, seed = prepare_workflow(
            template,
            prompt=prompt,
            positive_node_id=positive_node_id,
            negative_node_id=negative_node_id,
            negative_prompt=str(self.config.get("negative_prompt", "")),
            positive_prefix=dynamic_prefix,
            positive_suffix=str(self.config.get("positive_suffix", "")),
            sampler_node_id=sampler_node_id,
            randomize_seed=bool(self.config.get("randomize_seed", True)),
            fixed_seed=int(self.config.get("fixed_seed", 0)),
            sampler_overrides=sampler_overrides,
            latent_node_id=mapping.get("latent", ""),
            width=width,
            height=height,
        ) if workflow_type != "seedvr2_refine_v1" else (
            copy.deepcopy(template),
            secrets.randbelow(2**32) if bool(self.config.get("randomize_seed", True))
            else int(self.config.get("fixed_seed", 0)) % (2**32),
        )
        if workflow_type == "seedvr2_refine_v1":
            plan = {"style_loras": [], "character_lora": None}
        else:
            plan = apply_lora_plan(
                workflow,
                style=style,
                character=character,
                style_slot_ids=self._style_slot_ids(),
                positive_node_id=positive_node_id,
                negative_node_id=negative_node_id,
                sampler_node_id=sampler_node_id,
                character_node_id=str(
                    self.config.get("character_lora_node_id", "900001")
                ).strip(),
                options=options,
                style_mode=str(self.config.get("style_lora_mode", "dynamic")),
                dynamic_style_node_id_start=int(
                    self.config.get("dynamic_style_node_id_start", 900100)
                ),
                max_dynamic_style_loras=int(
                    self.config.get("max_dynamic_style_loras", 16)
                ),
            )
        plan["style_name"] = style_name
        plan["character_name"] = character_name
        plan["character_source"] = (
            "lora"
            if character is not None and character.get("lora") is not None
            else "text"
            if character is not None or character_text
            else "none"
        )
        if options.get("_character_dictionary_tag"):
            plan["character_source"] = "dictionary"
            plan["character_dictionary"] = {
                "tag": str(options["_character_dictionary_tag"]),
                "mode": str(options.get("_character_dictionary_mode", "weak")),
            }
        compiled_batch_prompts: list[str] = []
        if clean_batch_prompts:
            compiled_batch_prompts = [
                build_prompt_text(
                    dynamic_prefix,
                    item,
                    str(self.config.get("positive_suffix", "")),
                )
                for item in clean_batch_prompts
            ]
            workflow = prepare_prompt_batch_workflow(
                workflow,
                positive_node_id=positive_node_id,
                latent_node_id=mapping.get("latent", ""),
                prompts=compiled_batch_prompts,
                max_batch=5,
            )
            plan["batch_size"] = len(compiled_batch_prompts)
            plan["batch_prompts"] = list(compiled_batch_prompts)
        if width is not None and height is not None:
            plan["canvas"] = f"{width}x{height}"
        sampler_inputs = workflow.get(sampler_node_id, {}).get("inputs", {})
        if isinstance(sampler_inputs, dict):
            plan["sampler"] = {
                "preset": sampler_preset,
                "custom": bool(user_sampler_overrides),
                "sampler_name": sampler_inputs.get("sampler_name"),
                "steps": sampler_inputs.get("steps"),
                "cfg": sampler_inputs.get("cfg"),
                "scheduler": sampler_inputs.get("scheduler"),
                "denoise": sampler_inputs.get("denoise"),
            }

        scale_override = options.get("scale")
        denoise_override = options.get("denoise")
        if workflow_type == "hq_txt2img_anima_v1":
            effective_profile = copy.deepcopy(profile_data)
            effective_profile["sampling"] = dict(sampler_overrides)
            hq_plan = configure_hq_workflow(
                workflow,
                sampler_node_id=sampler_node_id,
                upscale_node_id=mapping.get("upscale", "29"),
                refiner_sampler_node_id=mapping.get("refiner_sampler", "30"),
                profile=effective_profile,
                seed=int(seed or 0),
                scale_override=(float(scale_override) if scale_override is not None else None),
                denoise_override=(
                    float(denoise_override) if denoise_override is not None else None
                ),
            )
            plan["enhance"] = {
                "profile": selected_profile,
                "scale": hq_plan["scale"],
                "denoise": hq_plan["refiner_sampling"].get("denoise"),
                "refiner_sampling": {
                    key: hq_plan["refiner_sampling"].get(key)
                    for key in ("sampler_name", "scheduler", "steps", "cfg", "denoise")
                },
                "detailer": [],
                "tile": False,
            }

        job_store = self._job_store()
        compiled_prompt = (
            compiled_batch_prompts[0]
            if compiled_batch_prompts
            else str(
                workflow.get(positive_node_id, {})
                .get("inputs", {})
                .get("text", prompt)
            )
        )
        job = job_store.create_job(
            workflow_type=definition.workflow_id,
            workflow_version=definition.version,
            profile=selected_profile,
            source=self._event_source(event),
            input_data={
                "prompt": prompt,
                "compiled_prompt": compiled_prompt,
                "batch_prompts": list(compiled_batch_prompts),
                "batch_size": len(compiled_batch_prompts) or 1,
                "negative": str(
                    workflow.get(negative_node_id, {}).get("inputs", {}).get("text", "")
                ),
                "image_asset_id": None,
                "metadata_restore": metadata_restore,
            },
            parent_job_id=parent_job_id,
        )
        plan["job_id"] = job["job_id"]
        plan["workflow_type"] = definition.workflow_id
        plan["workflow_version"] = definition.version
        plan["profile"] = selected_profile
        plan["workflow_path"] = str(workflow_path)
        started = time.monotonic()

        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds() + 30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if workflow_type in {"refine_existing_v1", "seedvr2_refine_v1"}:
                    if not source_image_path:
                        raise WorkflowError("INVALID_INPUT：精修任务缺少输入图片。")
                    source_asset = job_store.register_asset(
                        Path(source_image_path),
                        asset_type="source",
                        job_id=job["job_id"],
                        source="qq_or_client",
                    )
                    job["input"]["image_asset_id"] = source_asset["asset_id"]
                    uploaded_name = await self._upload_reverse_image(
                        session, source_image_path
                    )
                    if workflow_type == "seedvr2_refine_v1":
                        refine_plan = configure_seedvr2_workflow(
                            workflow,
                            image_name=uploaded_name,
                            image_node_id=mapping.get("image", "1"),
                            upscaler_node_id=mapping.get("upscaler", "4"),
                            profile=copy.deepcopy(profile_data),
                            seed=int(seed or 0),
                        )
                        plan["enhance"] = {
                            "profile": selected_profile,
                            "target_resolution": refine_plan["target_resolution"],
                            "tile": True,
                            "seedvr2": refine_plan,
                        }
                    else:
                        refine_plan = configure_refine_workflow(
                            workflow,
                            image_name=uploaded_name,
                            image_node_id=mapping.get("image", "1"),
                            upscale_node_id=mapping.get("upscale", "2"),
                            sampler_node_id=sampler_node_id,
                            profile={
                                **copy.deepcopy(profile_data),
                                "sampling": dict(sampler_overrides),
                            },
                            seed=int(seed or 0),
                            scale_override=(
                                float(scale_override) if scale_override is not None else None
                            ),
                            denoise_override=(
                                float(denoise_override)
                                if denoise_override is not None
                                else None
                            ),
                        )
                        refine_plan["metadata_restore"] = metadata_restore
                        plan["enhance"] = {
                            "profile": selected_profile,
                            "scale": refine_plan["scale"],
                            "denoise": refine_plan["sampling"].get("denoise"),
                            "detailer": [],
                            "tile": False,
                        }
                prompt_id = await self._submit_workflow(session, workflow)
                logger.info(
                    "Comfy bridge submitted job_id=%s prompt_id=%s workflow=%s profile=%s",
                    job["job_id"],
                    prompt_id,
                    workflow_path,
                    selected_profile,
                )
                record = await self._wait_for_history(session, prompt_id)
                image_refs = extract_output_images(record)
                if not image_refs:
                    raise WorkflowError("任务成功但没有找到 SaveImage/PreviewImage 输出。")
                paths = await self._download_images(
                    session,
                    prompt_id,
                    image_refs,
                    max_images_override=(
                        len(compiled_batch_prompts)
                        if compiled_batch_prompts
                        else None
                    ),
                )
                if compiled_batch_prompts and len(paths) != len(compiled_batch_prompts):
                    raise WorkflowError(
                        "批次任务输出数量异常："
                        f"期望 {len(compiled_batch_prompts)} 张，实际 {len(paths)} 张。"
                    )
            assets = [
                job_store.register_asset(
                    path,
                    asset_type="result",
                    job_id=job["job_id"],
                    source="comfyui_download",
                )
                for path in paths
            ]
            lora_stack = [
                {**entry, "kind": "style"}
                for entry in plan.get("style_loras", [])
            ]
            if isinstance(plan.get("character_lora"), dict):
                lora_stack.append({**plan["character_lora"], "kind": "character"})
            job["status"] = "completed"
            job["comfyui_prompt_id"] = prompt_id
            job["model"] = {
                "family": "anima",
                "checkpoint": str(
                    workflow.get("44", {}).get("inputs", {}).get("unet_name", "")
                ),
                "vae": str(
                    workflow.get("15", {}).get("inputs", {}).get("vae_name", "")
                ),
                "text_encoder": str(
                    workflow.get("45", {}).get("inputs", {}).get("clip_name", "")
                ),
                "style_name": style_name,
                "character_name": character_name,
                "lora_stack": lora_stack,
            }
            job["sampling"] = {
                key: workflow.get(sampler_node_id, {}).get("inputs", {}).get(key)
                for key in ("seed", "sampler_name", "scheduler", "steps", "cfg", "denoise")
            }
            job["enhance"] = copy.deepcopy(plan.get("enhance", {}))
            job["result"] = {
                "assets": [asset["asset_id"] for asset in assets],
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "safety": None,
                "error": None,
            }
            job_store.save_job(job)
            plan["assets"] = assets
        except Exception as exc:
            job["status"] = "failed"
            job["result"]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            job["result"]["error"] = {
                "code": (
                    str(exc).split("：", 1)[0]
                    if "：" in str(exc)
                    else "COMFYUI_EXECUTION_ERROR"
                ),
                "message": str(exc),
            }
            job_store.save_job(job)
            raise
        return paths, seed, prompt_id, plan

    async def _deliver_generation(
        self,
        event: AstrMessageEvent,
        *,
        prompt: str,
        options: dict[str, Any],
        extra_prefix: str = "",
        strict_no_style: bool = False,
        allow_character_text_fallback: bool = False,
        completion_prefix: str = "生成完成",
        workflow_type: str = "quick_txt2img_v1",
        profile: str = "",
        source_image_path: str = "",
        parent_job_id: str | None = None,
        metadata_restore: str = "none",
        send_progress: bool | None = None,
        batch_prompts: list[str] | None = None,
        send_errors: bool = True,
    ) -> bool:
        progress_enabled = (
            bool(self.config.get("send_progress", True))
            if send_progress is None
            else bool(send_progress)
        )
        if progress_enabled:
            await event.send(event.plain_result("已提交生成请求，正在等待 ComfyUI…"))
        try:
            async with self._semaphore:
                paths, seed, prompt_id, plan = await self._generate(
                    prompt,
                    options,
                    extra_prefix=extra_prefix,
                    strict_no_style=strict_no_style,
                    allow_character_text_fallback=allow_character_text_fallback,
                    workflow_type=workflow_type,
                    profile=profile,
                    event=event,
                    source_image_path=source_image_path,
                    parent_job_id=parent_job_id,
                    metadata_restore=metadata_restore,
                    batch_prompts=batch_prompts,
                )
        except (WorkflowError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Comfy bridge generation failed: %s", exc)
            if send_errors:
                await event.send(event.plain_result(f"生成失败：{exc}"))
            return False
        except Exception as exc:
            logger.exception("Unexpected Comfy bridge error")
            if send_errors:
                await event.send(
                    event.plain_result(
                        f"生成失败：未预期错误 {type(exc).__name__}: {exc}"
                    )
                )
            return False

        labels = []
        if plan.get("style_name"):
            labels.append(f"画风={plan['style_name']}")
        if plan.get("character_name"):
            source = {
                "lora": "LoRA",
                "dictionary": "角色词典",
            }.get(str(plan.get("character_source")), "文本")
            labels.append(f"角色={plan['character_name']}({source})")
        if plan.get("canvas"):
            labels.append(f"画布={plan['canvas']}")
        if plan.get("profile"):
            labels.append(f"Profile={plan['profile']}")
        enhance = plan.get("enhance", {})
        if isinstance(enhance, dict) and enhance:
            if enhance.get("target_resolution"):
                labels.append(
                    f"增强=SeedVR2/最长边{enhance.get('target_resolution')}px"
                )
            else:
                labels.append(
                    f"增强={enhance.get('scale', '?')}x/denoise={enhance.get('denoise', '?')}"
                )
        sampler = plan.get("sampler", {})
        if isinstance(sampler, dict) and sampler.get("custom"):
            sampler_label = {
                "original": "原有",
                "2m": "2m",
                "2m_sde": "2m_sde",
                "2m_sde_gpu": "2m_sde_gpu",
            }.get(str(sampler.get("preset")), str(sampler.get("preset")))
            labels.append(
                f"采样器={sampler_label}({sampler.get('sampler_name')},"
                f"{sampler.get('steps')}步,CFG={sampler.get('cfg')},"
                f"{sampler.get('scheduler')})"
            )
        preset_text = f"｜{'｜'.join(labels)}" if labels else ""
        await event.send(
            event.plain_result(
                f"{completion_prefix}｜seed={seed if seed is not None else '保留工作流值'}"
                f"｜任务={plan.get('job_id', prompt_id[:8])}"
                f"｜Comfy={prompt_id[:8]}{preset_text}"
            )
        )
        for path in paths:
            await event.send(event.image_result(str(path)))
        return True

    def _random_quality_prompt(self, pool: dict[str, Any]) -> str:
        if not bool(self.config.get("random_quality_enabled", True)):
            return ""
        override = str(self.config.get("random_quality_prompt", "")).strip()
        if override:
            return override
        preset_name = str(
            self.config.get("random_quality_preset_name", "general")
        ).strip()
        return quality_prompt(pool, preset_name or "general")

    async def _handle_random_picture(
        self,
        event: AstrMessageEvent,
        body: str,
        *,
        draw_count: int = 1,
        chaos: bool = False,
    ) -> None:
        event.should_call_llm(False)
        if draw_count == 5 and chaos:
            remaining = self._five_draw_cooldown_remaining(event)
            if remaining > 0:
                await event.send(
                    event.plain_result(
                        f"混沌五连抽冷却中，请等待 {remaining} 秒后再试。"
                    )
                )
                return
        claimed = False
        sender_id = ""
        if draw_count == 5 and not chaos:
            claimed, sender_id = await self._claim_five_draw(event)
            if not claimed:
                await event.send(
                    event.plain_result("你已有普通五连抽正在执行，请等待完成后再试。")
                )
                return
        try:
            await self._execute_random_picture(
                event, body, draw_count=draw_count, chaos=chaos
            )
        finally:
            if claimed:
                await self._release_five_draw(event, sender_id)

    async def _execute_random_picture(
        self,
        event: AstrMessageEvent,
        body: str,
        *,
        draw_count: int = 1,
        chaos: bool = False,
    ) -> None:
        try:
            body, selection = parse_group_selector(body)
            if "S" in selection.get("safety_codes", []) and not self._is_private_event(event):
                raise WorkflowError("S 组只能在 QQ 私聊或 App 的私聊目标中调用。")
            user_prompt, options = parse_generation_directives(body)
            pool = self._random_prompt_pool(selection)
            quality = self._random_quality_prompt(pool)
            draw_plans: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            matched_categories: list[str] = []
            used_match = False

            if chaos:
                presets = load_presets(self._preset_path())
                style_names = sorted(
                    name
                    for name, value in presets.get("styles", {}).items()
                    if not (isinstance(value, dict) and value.get("hidden"))
                )
                character_names = sorted(presets.get("characters", {}))
                ratio_names = sorted(RATIO_PRESETS)
                if not style_names or not character_names:
                    raise WorkflowError("混沌时刻至少需要 1 个画风预设和 1 个角色预设。")
                excluded_ids: set[str] = set()
                for _ in range(draw_count):
                    draw_options = dict(options)
                    draw_options["style"] = secrets.choice(style_names)
                    draw_options["character"] = secrets.choice(character_names)
                    draw_options["ratio"] = secrets.choice(ratio_names)
                    for key in ("size", "width", "height"):
                        draw_options.pop(key, None)
                    draw_selection = apply_protected_character_policy(
                        selection,
                        str(draw_options["character"]),
                        self.config.get("sexual_protected_characters", ""),
                    )
                    if (
                        draw_selection.get("source_codes") == ["K"]
                        and bool(self.config.get("kp_dynamic_enabled", True))
                    ):
                        selected = self._kp_dynamic_items(
                            pool,
                            draw_selection,
                            count=1,
                            options=draw_options,
                            user_prompt=user_prompt,
                            excluded_ids=excluded_ids,
                        )[0]
                        matched, used = [], False
                    else:
                        working_pool = dict(pool)
                        working_pool["prompts"] = [
                            item
                            for item in pool.get("prompts", [])
                            if str(item.get("id", "")) not in excluded_ids
                        ]
                        selected, matched, used = select_random_prompt(
                            working_pool,
                            user_prompt,
                            source_codes=draw_selection["source_codes"],
                            safety_codes=draw_selection["safety_codes"],
                            custom_groups=draw_selection.get("custom_groups", []),
                        )
                    excluded_ids.add(str(selected.get("id", "")))
                    matched_categories = matched
                    used_match = used_match or used
                    draw_plans.append((selected, draw_options, draw_selection))
            else:
                selection = apply_protected_character_policy(
                    selection,
                    str(options.get("character", "")),
                    self.config.get("sexual_protected_characters", ""),
                )
                if (
                    selection.get("source_codes") == ["K"]
                    and bool(self.config.get("kp_dynamic_enabled", True))
                ):
                    selected_items = self._kp_dynamic_items(
                        pool,
                        selection,
                        count=draw_count,
                        options=options,
                        user_prompt=user_prompt,
                    )
                    matched_categories, used_match = [], False
                else:
                    selected_items, matched_categories, used_match = select_random_prompts(
                        pool,
                        draw_count,
                        user_prompt,
                        source_codes=selection["source_codes"],
                        safety_codes=selection["safety_codes"],
                        custom_groups=selection.get("custom_groups", []),
                    )
                draw_plans = [(item, dict(options), selection) for item in selected_items]
        except WorkflowError as exc:
            await event.send(event.plain_result(f"抽取失败：{exc}"))
            return

        dynamic_items = [
            item for item, _, _ in draw_plans if bool(item.get("runtime_generated"))
        ]
        if dynamic_items:
            try:
                persist_dynamic_k_entries(
                    self._kp_prompt_pool_path(),
                    dynamic_items,
                    history_limit=int(self.config.get("kp_dynamic_history_limit", 2000)),
                )
            except WorkflowError as exc:
                logger.warning("KP dynamic history persistence failed: %s", exc)

        if draw_count == 5 and chaos:
            self._start_five_draw_cooldown(event)
        selected_ids = [str(item.get("id", "?")) for item, _, _ in draw_plans]
        logger.info(
            "Comfy bridge random prompts ids=%s range=%s chaos=%s matched=%s used_match=%s",
            selected_ids,
            describe_selection(selection),
            chaos,
            matched_categories,
            used_match,
        )
        match_text = (
            f"，匹配分类={','.join(matched_categories)}"
            if used_match and matched_categories
            else ""
        )
        fallback_count = sum(
            int(draw_selection.get("protected_fallback", False))
            for _, _, draw_selection in draw_plans
        )
        protected_text = (
            f"受保护角色触发 {fallback_count} 次 S 组禁则，相应抽取已强制改为 N/H。\n"
            if fallback_count
            else ""
        )
        await event.send(
            event.plain_result(
                f"{protected_text}抽取范围={describe_selection(selection)}｜"
                f"抽中 {', '.join(selected_ids)}{match_text}，"
                f"准备生成 {draw_count} 张{'混沌好图' if chaos else '好图'}。"
            )
        )
        successes = await self._deliver_random_draw_plans(
            event,
            draw_plans=draw_plans,
            user_prompt=user_prompt,
            quality=quality,
            chaos=chaos,
        )
        if draw_count > 1:
            await event.send(
                event.plain_result(
                    f"{'混沌' if chaos else ''}五连抽结束：成功 {successes}/5。"
                )
            )

    async def _deliver_random_draw_plans(
        self,
        event: AstrMessageEvent,
        *,
        draw_plans: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
        user_prompt: str,
        quality: str,
        chaos: bool,
    ) -> int:
        draw_count = len(draw_plans)
        batch_enabled = (
            draw_count == 5
            and not chaos
            and bool(self.config.get("five_draw_batch_enabled", True))
        )
        micro_batch_size = max(
            1, min(5, int(self.config.get("five_draw_micro_batch_size", 2)))
        )
        fallback_enabled = bool(
            self.config.get("five_draw_batch_fallback_sequential", True)
        )
        if not batch_enabled or micro_batch_size == 1:
            successes = 0
            for index, (selected, draw_options, _) in enumerate(
                draw_plans, start=1
            ):
                success = await self._deliver_generation(
                    event,
                    prompt=compose_random_body(user_prompt, selected),
                    options=draw_options,
                    extra_prefix=quality,
                    strict_no_style=True,
                    allow_character_text_fallback=True,
                    completion_prefix=(
                        f"{'混沌好图' if chaos else '好图'} "
                        f"{index}/{draw_count} 完成｜条目={selected.get('id', '?')}"
                    ),
                )
                successes += int(success)
            return successes

        successes = 0
        for start in range(0, draw_count, micro_batch_size):
            chunk = draw_plans[start : start + micro_batch_size]
            chunk_prompts = [
                compose_random_body(user_prompt, selected)
                for selected, _, _ in chunk
            ]
            chunk_ids = [str(selected.get("id", "?")) for selected, _, _ in chunk]
            end = start + len(chunk)
            if len(chunk) == 1:
                selected, draw_options, _ = chunk[0]
                success = await self._deliver_generation(
                    event,
                    prompt=chunk_prompts[0],
                    options=draw_options,
                    extra_prefix=quality,
                    strict_no_style=True,
                    allow_character_text_fallback=True,
                    completion_prefix=(
                        f"好图 {start + 1}/{draw_count} 完成｜"
                        f"条目={selected.get('id', '?')}"
                    ),
                )
                successes += int(success)
                continue
            success = await self._deliver_generation(
                event,
                prompt=chunk_prompts[0],
                batch_prompts=chunk_prompts,
                options=chunk[0][1],
                extra_prefix=quality,
                strict_no_style=True,
                allow_character_text_fallback=True,
                completion_prefix=(
                    f"好图微批 {start + 1}-{end}/{draw_count} 完成｜"
                    f"条目={','.join(chunk_ids)}"
                ),
                send_errors=False,
            )
            if success:
                successes += len(chunk)
                continue
            if not fallback_enabled:
                await event.send(
                    event.plain_result(
                        f"好图微批 {start + 1}-{end}/5 失败，未启用逐张回退。"
                    )
                )
                continue

            await event.send(
                event.plain_result(
                    f"好图微批 {start + 1}-{end}/5 未完成，自动改为逐张生成。"
                )
            )
            for offset, (selected, draw_options, _) in enumerate(chunk):
                index = start + offset + 1
                sequential_success = await self._deliver_generation(
                    event,
                    prompt=chunk_prompts[offset],
                    options=draw_options,
                    extra_prefix=quality,
                    strict_no_style=True,
                    allow_character_text_fallback=True,
                    completion_prefix=(
                        f"好图 {index}/{draw_count} 回退完成｜"
                        f"条目={selected.get('id', '?')}"
                    ),
                )
                successes += int(sequential_success)
        return successes

    def _pending_key(self, event: AstrMessageEvent) -> tuple[str, str]:
        origin = str(
            getattr(event, "unified_msg_origin", "")
            or event.get_session_id()
            or "unknown-session"
        )
        sender = str(event.get_sender_id() or "unknown-sender")
        return origin, sender

    def _llm_max_tokens(self) -> int:
        return max(100, int(self.config.get("llm_prompt_max_tokens", 700)))

    async def _handle_chinese_generation(
        self, event: AstrMessageEvent, body: str
    ) -> None:
        event.should_call_llm(False)
        try:
            chinese_prompt, options = parse_generation_directives(body)
            if not chinese_prompt:
                raise WorkflowError(
                    "用法：/aicn [角色=名称] [画风=名称] <中文提示词>"
                )
            tags, provider_id = await translate_chinese_prompt(
                self.context,
                event,
                chinese_prompt,
                configured_provider_id=str(
                    self.config.get("text_provider_id", "")
                ),
                max_tokens=self._llm_max_tokens(),
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"中文转换失败：{exc}"))
            return
        except Exception as exc:
            logger.exception("Comfy bridge Chinese conversion failed")
            await event.send(
                event.plain_result(
                    f"中文转换失败：{type(exc).__name__}: {exc}"
                )
            )
            return

        logger.info(
            "Comfy bridge translated Chinese prompt provider=%s chars=%s",
            provider_id,
            len(tags),
        )
        if bool(self.config.get("show_converted_tags", True)):
            await event.send(event.plain_result(f"转换后的 tags：\n{tags[:1800]}"))
        await self._deliver_generation(
            event,
            prompt=tags,
            options=options,
            allow_character_text_fallback=True,
            completion_prefix="中文生图完成",
        )

    def _format_reverse_report(
        self,
        reverse_result: dict[str, Any],
        reverse_preset: str,
        reverse_categories: tuple[str, ...],
    ) -> str:
        tags = str(reverse_result.get("anima_prompt", "")).strip()
        safety_level = str(reverse_result.get("safety_level", "unknown"))
        reverse_id = str(reverse_result.get("reverse_id", "")).strip()
        try:
            structured = json.loads(str(reverse_result.get("structured_json", "")))
            compiled = structured.get("compiled", {})
        except (json.JSONDecodeError, TypeError, AttributeError):
            compiled = {}

        effective = reverse_result.get("effective_categories")
        selected = (
            tuple(str(value) for value in effective)
            if isinstance(effective, (list, tuple)) and effective
            else reverse_categories or REVERSE_PRESET_CATEGORIES.get(reverse_preset, ())
        )
        lines: list[str] = []
        if isinstance(compiled, dict) and reverse_preset != "raw":
            for category in selected:
                if category == "safety":
                    continue
                values = compiled.get(category, [])
                if isinstance(values, list):
                    text = ", ".join(str(value) for value in values if str(value).strip())
                else:
                    text = str(values or "").strip()
                if text:
                    lines.append(
                        f"{REVERSE_CATEGORY_LABELS.get(category, category)}：{text}"
                    )
        lines.append(f"安全级别：{safety_level}")
        lines.append(f"合并提示词：{tags or '（空）'}")
        if reverse_id:
            lines.append(f"反推记录：{reverse_id}")
        report = "\n".join(lines)
        return report[:5000]

    async def _handle_reverse_generation(
        self,
        event: AstrMessageEvent,
        image_path: str,
        options: dict[str, Any],
        extra_prompt: str = "",
        reverse_preset: str = "full",
        reverse_categories: tuple[str, ...] = (),
        reverse_only: bool = False,
    ) -> None:
        try:
            if bool(self.config.get("reverse_workflow_enabled", True)):
                async with self._semaphore:
                    reverse_result = await self._run_reverse_workflow(
                        event,
                        image_path,
                        options,
                        reverse_preset,
                        reverse_categories,
                        reverse_only,
                    )
                tags = str(reverse_result["anima_prompt"])
                source = f"ComfyUI:{str(reverse_result.get('prompt_id', ''))[:8]}"
                safety_level = str(reverse_result.get("safety_level", "unknown"))
                reverse_id = str(reverse_result.get("reverse_id", ""))
            else:
                tags, provider_id = await reverse_image_prompt(
                    self.context,
                    event,
                    image_path,
                    configured_provider_id=str(
                        self.config.get("image_caption_provider_id", "")
                    ),
                    max_tokens=self._llm_max_tokens(),
                )
                source = f"Provider:{provider_id}"
                safety_level = "unknown"
                reverse_id = ""
                reverse_result = {
                    "anima_prompt": tags,
                    "structured_json": "",
                    "safety_level": safety_level,
                    "reverse_id": reverse_id,
                }
            final_prompt = build_prompt_text("", tags, extra_prompt)
        except WorkflowError as exc:
            await event.send(event.plain_result(f"图片反推失败：{exc}"))
            return
        except Exception as exc:
            logger.exception("Comfy bridge image reverse failed")
            await event.send(
                event.plain_result(
                    f"图片反推失败：{type(exc).__name__}: {exc}"
                )
            )
            return

        logger.info(
            "Comfy bridge reversed image source=%s chars=%s path=%s preset=%s safety=%s reverse_id=%s",
            source,
            len(tags),
            image_path,
            reverse_preset,
            safety_level,
            reverse_id,
        )
        if reverse_only:
            if extra_prompt:
                final_prompt = build_prompt_text("", tags, extra_prompt)
                reverse_result["anima_prompt"] = final_prompt
            await event.send(
                event.plain_result(
                    self._format_reverse_report(
                        reverse_result, reverse_preset, reverse_categories
                    )
                )
            )
            return
        if bool(self.config.get("show_reversed_tags", True)):
            header = f"图片反推 tags（{reverse_preset} / {safety_level}）"
            if reverse_id:
                header += f"｜记录={reverse_id}"
            await event.send(event.plain_result(f"{header}：\n{tags[:1800]}"))
        await self._deliver_generation(
            event,
            prompt=final_prompt,
            options=options,
            allow_character_text_fallback=True,
            completion_prefix="反推生图完成",
        )

    async def _expire_pending_image(
        self, key: tuple[str, str], token: str
    ) -> None:
        try:
            wait_seconds = max(10, int(self.config.get("image_wait_seconds", 60)))
            await asyncio.sleep(wait_seconds)
            async with self._pending_lock:
                pending = self._pending_images.get(key)
                if pending is None or pending.token != token:
                    return
                self._pending_images.pop(key, None)
            await pending.event.send(
                pending.event.plain_result(
                    f"等待图片已超过{wait_seconds}秒，本次 /aip 已失效，"
                    "请重新发送指令。"
                )
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Comfy bridge pending timeout notice failed: %s", exc)

    async def _begin_pending_image(
        self,
        event: AstrMessageEvent,
        options: dict[str, Any],
        extra_prompt: str,
        reverse_preset: str = "full",
        reverse_categories: tuple[str, ...] = (),
        reverse_only: bool = False,
    ) -> None:
        key = self._pending_key(event)
        token = uuid.uuid4().hex
        pending = PendingImageRequest(
            token=token,
            event=event,
            options=options,
            extra_prompt=extra_prompt,
            reverse_preset=reverse_preset,
            reverse_categories=reverse_categories,
            reverse_only=reverse_only,
        )
        async with self._pending_lock:
            previous = self._pending_images.get(key)
            if previous and previous.timeout_task:
                previous.timeout_task.cancel()
            self._pending_images[key] = pending
            pending.timeout_task = asyncio.create_task(
                self._expire_pending_image(key, token)
            )
        wait_seconds = max(10, int(self.config.get("image_wait_seconds", 60)))
        await event.send(
            event.plain_result(
                f"请在 {wait_seconds} 秒内发送一张图片。"
                "只会捕获同一QQ在当前私聊/群聊中的第一张图片。"
            )
        )

    async def _capture_pending_image(self, event: AstrMessageEvent) -> bool:
        key = self._pending_key(event)
        async with self._pending_lock:
            pending = self._pending_images.get(key)
        if pending is None:
            return False
        image_path = await self._image_resolver.resolve(event)
        if not image_path:
            return False
        async with self._pending_lock:
            current = self._pending_images.get(key)
            if current is None or current.token != pending.token:
                return False
            self._pending_images.pop(key, None)
            if current.timeout_task:
                current.timeout_task.cancel()
        event.should_call_llm(False)
        event.stop_event()
        await event.send(event.plain_result("已收到图片，正在反推提示词…"))
        await self._handle_reverse_generation(
            event,
            image_path,
            current.options,
            current.extra_prompt,
            current.reverse_preset,
            current.reverse_categories,
            current.reverse_only,
        )
        return True

    def _parse_reverse_body(
        self, body: str
    ) -> tuple[str, dict[str, Any], str, tuple[str, ...], bool]:
        aliases = {
            "完整": "full", "full": "full",
            "场景": "scene", "scene": "scene",
            "动作": "action", "action": "action",
            "角色": "character", "character": "character",
            "安全": "safe", "safe": "safe",
            "原始": "raw", "raw": "raw",
        }
        cleaned = str(body or "").strip()
        reverse_only = bool(
            re.search(r"(?:^|\s)(?:仅反推|只反推|不跑图)(?=\s|$)", cleaned)
        )
        cleaned = re.sub(
            r"(?:^|\s)(?:仅反推|只反推|不跑图)(?=\s|$)", " ", cleaned
        ).strip()
        selected = str(self.config.get("reverse_default_preset", "full")).strip().lower()
        selected_categories: tuple[str, ...] = ()
        category_match = re.search(
            r"(?:^|\s)(?:反推分类|分类)\s*=\s*([^\s]+)", cleaned
        )
        if category_match:
            raw_categories = re.split(r"[,，、/+]+", category_match.group(1))
            normalized: list[str] = []
            unknown: list[str] = []
            for value in raw_categories:
                name = value.strip().lower()
                if not name:
                    continue
                category = REVERSE_CATEGORY_ALIASES.get(name)
                if category is None:
                    unknown.append(value.strip())
                elif category not in normalized:
                    normalized.append(category)
            if unknown:
                raise WorkflowError(
                    "未知反推分类：" + "、".join(unknown)
                    + "；支持：场景/动作/角色/外观/特殊特征/服装/构图/其他/安全"
                )
            if not normalized:
                raise WorkflowError("分类= 后至少选择一项。")
            if normalized == ["safety"]:
                selected = "safe"
            else:
                selected = "custom"
                selected_categories = tuple(normalized)
            cleaned = (
                cleaned[: category_match.start()]
                + " "
                + cleaned[category_match.end() :]
            ).strip()
        match = re.search(r"(?:^|\s)(?:反推模式|模式)\s*=\s*([^\s]+)", cleaned)
        if match:
            requested = aliases.get(match.group(1).strip().lower())
            if requested is None:
                raise WorkflowError("反推模式仅支持：完整/场景/动作/角色/安全/原始")
            selected = requested
            selected_categories = ()
            cleaned = (cleaned[: match.start()] + " " + cleaned[match.end() :]).strip()
        elif cleaned:
            first, *remaining = cleaned.split(maxsplit=1)
            requested = aliases.get(first.lower())
            if requested is not None:
                selected = requested
                selected_categories = ()
                cleaned = remaining[0] if remaining else ""
        if selected not in REVERSE_PRESETS:
            raise WorkflowError(
                f"默认反推模式无效：{selected}；请检查 reverse_default_preset。"
            )
        extra_prompt, options = parse_generation_directives(cleaned)
        if not str(options.get("style", "")).strip():
            options["style"] = "当前画风"
        return extra_prompt, options, selected, selected_categories, reverse_only

    @filter.event_message_type(EventMessageType.ALL, priority=sys.maxsize - 3)
    async def natural_random_picture_route(self, event: AstrMessageEvent):
        """Handle pending /aip images and slash-free random commands."""
        message = str(event.message_str or "").strip()
        if message == "/aip" or message.startswith("/aip "):
            return
        if await self._capture_pending_image(event):
            return
        commands = (
            ("来张好图混沌五连抽", 5, True),
            ("来张好图混沌五连", 5, True),
            ("来张好图混沌时刻", 1, True),
            ("来张好图五连抽", 5),
            ("来张好图抄五张", 5),
            ("来张好图抄一抄", 1),
            ("来张好图抽一抽", 1),
        )
        for command_spec in commands:
            command, draw_count = command_spec[:2]
            chaos = bool(command_spec[2]) if len(command_spec) > 2 else False
            if not message.startswith(command):
                continue
            if len(message) > len(command) and not message[len(command)].isspace():
                continue
            event.stop_event()
            await self._handle_random_picture(
                event,
                message[len(command) :].strip(),
                draw_count=draw_count,
                chaos=chaos,
            )
            return

    @filter.command("aimg_random", alias={"抽一抽", "抄一抄"})
    async def aimg_random(self, event: AstrMessageEvent, content: str = ""):
        """随机抽取后续提示词并生图。"""
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aimg_random")
        await self._handle_random_picture(event, body)

    @filter.command("aimg_random5", alias={"五连抽"})
    async def aimg_random5(self, event: AstrMessageEvent, content: str = ""):
        """随机抽取五条不同的后续提示词，逐条生图。"""
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aimg_random5")
        await self._handle_random_picture(event, body, draw_count=5)

    @filter.command("aimg_chaos", alias={"混沌时刻"})
    async def aimg_chaos(self, event: AstrMessageEvent, content: str = ""):
        """随机角色、画风、比例与后续提示词生成一张图。"""
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aimg_chaos")
        await self._handle_random_picture(event, body, chaos=True)

    @filter.command("aimg_chaos5", alias={"混沌五连"})
    async def aimg_chaos5(self, event: AstrMessageEvent, content: str = ""):
        """逐张随机角色、画风、比例与提示词生成五张图。"""
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aimg_chaos5")
        await self._handle_random_picture(event, body, draw_count=5, chaos=True)

    @filter.command("aicn")
    async def aicn(self, event: AstrMessageEvent, content: str = ""):
        """将中文描述转换为英文 tags 后生图。"""
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aicn")
        await self._handle_chinese_generation(event, body)

    @filter.command("aip")
    async def aip(self, event: AstrMessageEvent, content: str = ""):
        """通过专用反推工作流处理当前/引用/下一张图片并立即生图。"""
        event.should_call_llm(False)
        event.stop_event()
        body = extract_command_body(event.message_str, content, "aip")
        try:
            (
                extra_prompt,
                options,
                reverse_preset,
                reverse_categories,
                reverse_only,
            ) = self._parse_reverse_body(body)
        except WorkflowError as exc:
            await event.send(event.plain_result(f"参数错误：{exc}"))
            return
        image_path = await self._image_resolver.resolve(event)
        if image_path:
            await event.send(event.plain_result("已取得图片，正在反推提示词…"))
            await self._handle_reverse_generation(
                event,
                image_path,
                options,
                extra_prompt,
                reverse_preset,
                reverse_categories,
                reverse_only,
            )
            return
        await self._begin_pending_image(
            event,
            options,
            extra_prompt,
            reverse_preset,
            reverse_categories,
            reverse_only,
        )

    @filter.command("ahq")
    async def ahq(self, event: AstrMessageEvent, content: str = ""):
        """使用独立 Anima HQ 工作流生成 Stable/Beauty 高清图。"""
        event.should_call_llm(False)
        event.stop_event()
        body = extract_command_body(event.message_str, content, "ahq")
        profile = "stable"
        if body:
            first, *tail = body.split(maxsplit=1)
            aliases = {
                "stable": "stable",
                "稳定": "stable",
                "beauty": "beauty",
                "美化": "beauty",
                "成品": "beauty",
            }
            selected = aliases.get(first.casefold())
            if selected:
                profile = selected
                body = tail[0] if tail else ""
        try:
            prompt, options = parse_generation_directives(body)
            if not prompt:
                raise WorkflowError(
                    "用法：/ahq [stable|beauty] [角色=名称] [画风=名称] "
                    "[比例=2:3] [放大=1.25] [重绘=0.28] <提示词>"
                )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"参数错误：{exc}"))
            return
        await self._deliver_generation(
            event,
            prompt=prompt,
            options=options,
            workflow_type="hq_txt2img_anima_v1",
            profile=profile,
            completion_prefix="HQ 生成完成",
        )

    @filter.command("arefine", alias={"aimg_refine"})
    async def arefine(self, event: AstrMessageEvent, content: str = ""):
        """放大并低重绘当前、引用或历史 Job 图片。"""
        event.should_call_llm(False)
        event.stop_event()
        body = extract_command_body(event.message_str, content, "arefine")
        profile = "seedvr2"
        if body:
            first, *tail = body.split(maxsplit=1)
            aliases = {
                "light": "light",
                "轻度": "light",
                "轻微": "light",
                "medium": "medium",
                "中度": "medium",
                "seedvr2": "seedvr2",
                "seed": "seedvr2",
                "智能放大": "seedvr2",
            }
            selected = aliases.get(first.casefold())
            if selected:
                profile = selected
                body = tail[0] if tail else ""
        try:
            prompt, options = parse_generation_directives(body)
            store = self._job_store()
            parent_job_id = str(options.get("parent_job_id", "")).strip()
            parent: dict[str, Any] | None = None
            image_path = await self._image_resolver.resolve(event)
            if parent_job_id:
                parent = store.get_job(parent_job_id)
            elif image_path:
                _, parent = store.parent_for_image(Path(image_path))
                if parent:
                    parent_job_id = str(parent.get("job_id", ""))

            if parent and not image_path:
                result_assets = parent.get("result", {}).get("assets", [])
                if isinstance(result_assets, list) and result_assets:
                    source_asset = store.get_asset(str(result_assets[0]))
                    candidate = Path(str(source_asset.get("path", "")))
                    if candidate.is_file():
                        image_path = str(candidate)

            restored_exact = False
            if parent:
                parent_input = parent.get("input", {})
                parent_model = parent.get("model", {})
                if not prompt:
                    prompt = str(parent_input.get("compiled_prompt", "")).strip()
                    if prompt:
                        options["_compiled_prompt"] = True
                if not options.get("style") and not options.get("character"):
                    lora_stack = parent_model.get("lora_stack", [])
                    if isinstance(lora_stack, list):
                        options["_restore_lora_stack"] = lora_stack
                        options["_restored_style_name"] = str(
                            parent_model.get("style_name", "")
                        )
                        options["_restored_character_name"] = str(
                            parent_model.get("character_name", "")
                        )
                        restored_exact = bool(prompt)

            if not image_path:
                raise WorkflowError(
                    "INVALID_INPUT：请在指令中附图、回复一张图，或填写 任务=job_xxx。"
                )
            if not prompt and profile != "seedvr2":
                raise WorkflowError(
                    "METADATA_NOT_FOUND：找不到原任务提示词。请补充提示词，"
                    "或使用新版生成结果的完整 任务=job_xxx。"
                )
            metadata_restore = "full" if restored_exact else "partial"
        except (WorkflowError, OSError, json.JSONDecodeError) as exc:
            await event.send(event.plain_result(f"精修准备失败：{exc}"))
            return

        await self._deliver_generation(
            event,
            prompt=prompt,
            options=options,
            workflow_type=(
                "seedvr2_refine_v1" if profile == "seedvr2" else "refine_existing_v1"
            ),
            profile=profile,
            source_image_path=image_path,
            parent_job_id=parent_job_id or None,
            metadata_restore=metadata_restore,
            completion_prefix="放大精修完成",
        )

    @filter.command("ajob")
    async def ajob(self, event: AstrMessageEvent, content: str = ""):
        """私聊查询统一生成任务的可追溯参数。"""
        event.should_call_llm(False)
        event.stop_event()
        job_id = extract_command_body(event.message_str, content, "ajob").strip()
        if not job_id:
            await event.send(event.plain_result("用法：/ajob job_xxx"))
            return
        try:
            record = self._job_store().get_job(job_id)
            workflow = record.get("workflow", {})
            sampling = record.get("sampling", {})
            enhance = record.get("enhance", {})
            result = record.get("result", {})
            text = (
                f"任务：{record.get('job_id')}\n"
                f"状态：{record.get('status')}\n"
                f"父任务：{record.get('parent_job_id') or '无'}\n"
                f"工作流：{workflow.get('type')}@{workflow.get('version')}\n"
                f"Profile：{workflow.get('profile') or '无'}\n"
                f"采样：{sampling.get('sampler_name')} / {sampling.get('scheduler')} / "
                f"{sampling.get('steps')} 步 / CFG={sampling.get('cfg')} / "
                f"seed={sampling.get('seed')}\n"
                f"增强：scale={enhance.get('scale', 1)} / "
                f"denoise={enhance.get('denoise', sampling.get('denoise'))}\n"
                f"输出 Asset：{', '.join(result.get('assets', [])) or '无'}\n"
                f"耗时：{result.get('elapsed_ms')} ms\n"
                f"错误：{result.get('error') or '无'}"
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(str(exc)))
            return
        await self._send_private_text(event, text)

    @filter.llm_tool(name="anima_generate_image")
    async def anima_generate_image(
        self,
        event: AstrMessageEvent,
        prompt: str,
        ratio: str = "",
        character: str = "",
        style: str = "",
        quality: str = "",
        sampler: str = "",
        scheduler: str = "",
        steps: float = 0,
        cfg: float = 0,
    ):
        """使用 AstrAutoAnima 与 ComfyUI 生成一张图片并发送到当前聊天。

        只在用户明确要求画图、生成图片或绘制场景时调用。普通聊天、知识问答、
        解释问题时不要调用。同一请求只调用一次。prompt 应优先写成一行英文
        Danbooru-style tags。角色和画风名称不确定时先调用 anima_list_presets。

        Args:
            prompt(string): 图片内容的一行英文 tags，包含主体、服装、动作、构图、环境和光影。
            ratio(string): 可选比例；空值使用插件自主绘图默认值，支持 1:1、2:3、3:2、3:4、4:3、9:16、16:9。
            character(string): 可选角色预设名；空值使用插件默认值，none 表示明确不使用角色预设。
            style(string): 可选画风预设名；空值使用插件默认值，none 表示明确不使用画风预设。
            quality(string): 可选质量预设；quick、hq_stable 或 hq_beauty，空值使用插件默认值。
            sampler(string): 可选采样器预设；original、2m、2m_sde 或 2m_sde_gpu。
            scheduler(string): 可选调度器；workflow 保留工作流/Profile 原值，空值使用插件自主绘图默认值。
            steps(number): 可选步数；0 使用插件自主绘图默认值或采样器预设。
            cfg(number): 可选 CFG；0 使用插件自主绘图默认值或采样器预设。
        """

        if not bool(self.config.get("agent_tools_enabled", False)) or not bool(
            self.config.get("agent_generate_tool_enabled", True)
        ):
            yield event.plain_result("AstrAutoAnima 自主绘图工具当前已关闭。")
            return
        if not self._is_private_event(event) and not bool(
            self.config.get("agent_tool_group_enabled", False)
        ):
            yield event.plain_result(
                "自主绘图当前只允许在私聊使用；请私聊机器人，或由管理员开启群聊自主绘图。"
            )
            return

        claimed, claim_result = await self._claim_agent_tool_generation(event)
        if not claimed:
            yield event.plain_result(claim_result)
            return
        sender_id = claim_result
        success = False
        try:
            try:
                prompt, options, workflow_type, profile = (
                    build_agent_generation_request(
                        self.config,
                        prompt=prompt,
                        ratio=ratio,
                        character=character,
                        style=style,
                        quality=quality,
                        sampler=sampler,
                        scheduler=scheduler,
                        steps=steps,
                        cfg=cfg,
                    )
                )
                presets = load_presets(self._preset_path())
                character_name = str(options.get("character", ""))
                style_name = str(options.get("style", ""))
                if character_name and character_name not in presets.get("characters", {}):
                    raise WorkflowError(f"找不到角色预设：{character_name}")
                if style_name and style_name not in presets.get("styles", {}):
                    raise WorkflowError(f"找不到画风预设：{style_name}")
                if re.search(r"[\u3400-\u9fff]", prompt):
                    if not bool(
                        self.config.get("agent_tool_translate_chinese", False)
                    ):
                        raise WorkflowError(
                            "自主绘图提示词仍包含中文；请先整理成英文 tags 后再次调用。"
                        )
                    prompt, provider_id = await translate_chinese_prompt(
                        self.context,
                        event,
                        prompt,
                        configured_provider_id=str(
                            self.config.get("text_provider_id", "")
                        ),
                        max_tokens=self._llm_max_tokens(),
                    )
                    logger.info(
                        "Agent image tool translated prompt provider=%s", provider_id
                    )
            except (WorkflowError, TypeError, ValueError) as exc:
                yield event.plain_result(f"自主绘图参数错误：{exc}")
                return

            success = await self._deliver_generation(
                event,
                prompt=prompt,
                options=options,
                strict_no_style=True,
                allow_character_text_fallback=False,
                completion_prefix="自主绘图完成",
                workflow_type=workflow_type,
                profile=profile,
                send_progress=bool(
                    self.config.get("agent_tool_send_progress", True)
                ),
            )
            if success:
                yield event.plain_result(
                    "图片已生成并发送到当前聊天。不要为同一请求重复调用绘图工具。"
                )
            else:
                yield event.plain_result("图片生成失败；不要自动重复调用，请向用户说明失败。")
        finally:
            await self._release_agent_tool_generation(
                event, sender_id, success=success
            )

    @filter.llm_tool(name="anima_list_presets")
    async def anima_list_presets(
        self,
        event: AstrMessageEvent,
        category: str = "all",
        query: str = "",
        limit: float = 20,
    ):
        """查询 AstrAutoAnima 可供自主绘图使用的角色和画风预设名称。

        仅在需要确认角色或画风的准确预设名称时调用。不要猜测不存在的名称。

        Args:
            category(string): 查询类型；all、character 或 style。
            query(string): 可选名称关键词；空值返回该分类的前若干项。
            limit(number): 每类最多返回数量，范围 1 到 50。
        """

        if not bool(self.config.get("agent_tools_enabled", False)) or not bool(
            self.config.get("agent_preset_tool_enabled", True)
        ):
            yield event.plain_result("AstrAutoAnima 预设查询工具当前已关闭。")
            return
        try:
            result = list_agent_presets(
                load_presets(self._preset_path()),
                category=category,
                query=query,
                limit=int(limit),
            )
        except (WorkflowError, TypeError, ValueError) as exc:
            yield event.plain_result(f"预设查询失败：{exc}")
            return
        lines = ["AstrAutoAnima 可用预设："]
        if "characters" in result:
            lines.append("角色：" + ("、".join(result["characters"]) or "无匹配项"))
        if "styles" in result:
            lines.append("画风：" + ("、".join(result["styles"]) or "无匹配项"))
        lines.append("请只使用以上返回的准确名称；none 表示不使用对应预设。")
        yield event.plain_result("\n".join(lines))

    @filter.command("aimg")
    async def aimg(self, event: AstrMessageEvent, prompt: str = ""):
        """原样提交配置的 ComfyUI API 工作流：/aimg <提示词>"""
        event.should_call_llm(False)
        prompt = extract_command_prompt(event.message_str, prompt, "aimg")
        try:
            prompt, options = parse_generation_directives(prompt)
        except WorkflowError as exc:
            yield event.plain_result(f"参数错误：{exc}")
            return
        if not prompt:
            yield event.plain_result(
                "用法：/aimg [角色=名称] [画风=名称] "
                "[采样器=原有|2m|2m_sde|2m_sde_gpu] "
                "[调度器=normal|karras|exponential|sgm_uniform|simple|"
                "ddim_uniform|beta|linear_quadratic|kl_optimal] "
                "[步数=30] [CFG=6] [角色权重=0.8] <提示词或 tags>"
            )
            return

        if bool(self.config.get("send_progress", True)):
            yield event.plain_result("已提交生成请求，正在等待 ComfyUI…")

        try:
            async with self._semaphore:
                paths, seed, prompt_id, plan = await self._generate(
                    prompt,
                    options,
                    event=event,
                    allow_character_text_fallback=True,
                )
        except (WorkflowError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Comfy bridge generation failed: %s", exc)
            yield event.plain_result(f"生成失败：{exc}")
            return
        except Exception as exc:
            logger.exception("Unexpected Comfy bridge error")
            yield event.plain_result(f"生成失败：未预期错误 {type(exc).__name__}: {exc}")
            return

        labels = []
        if plan.get("style_name"):
            labels.append(f"画风={plan['style_name']}")
        if plan.get("character_name"):
            labels.append(f"角色={plan['character_name']}")
        sampler = plan.get("sampler", {})
        if isinstance(sampler, dict) and sampler.get("custom"):
            sampler_label = {
                "original": "原有",
                "2m": "2m",
                "2m_sde": "2m_sde",
                "2m_sde_gpu": "2m_sde_gpu",
            }.get(str(sampler.get("preset")), str(sampler.get("preset")))
            labels.append(
                f"采样器={sampler_label}({sampler.get('sampler_name')},"
                f"{sampler.get('steps')}步,CFG={sampler.get('cfg')},"
                f"{sampler.get('scheduler')})"
            )
        preset_text = f"｜{'｜'.join(labels)}" if labels else ""
        yield event.plain_result(
            f"生成完成｜seed={seed if seed is not None else '保留工作流值'}"
            f"｜任务={plan.get('job_id', prompt_id[:8])}"
            f"｜Comfy={prompt_id[:8]}{preset_text}"
        )
        for path in paths:
            yield event.image_result(str(path))

    @filter.command("aimg_presets")
    async def aimg_presets(self, event: AstrMessageEvent):
        """查看可用的角色和画风 LoRA 预设。"""
        event.should_call_llm(False)
        try:
            presets = load_presets(self._preset_path())
            styles = presets.get("styles", {})
            characters = presets.get("characters", {})
            style_lines = []
            for name, preset in styles.items():
                if isinstance(preset, dict) and preset.get("hidden"):
                    continue
                count = len(preset.get("loras", [])) if isinstance(preset, dict) else 0
                style_lines.append(f"  - {name}（{count} 个 LoRA）")
            character_lines = [f"  - {name}" for name in characters]
            yield event.plain_result(
                "LoRA 预设：\n"
                "画风：\n"
                f"{chr(10).join(style_lines) if style_lines else '  - 无'}\n"
                "角色：\n"
                f"{chr(10).join(character_lines) if character_lines else '  - 无'}"
            )
        except WorkflowError as exc:
            yield event.plain_result(f"读取预设失败：{exc}")

    @filter.command("aimg_pool_list")
    async def aimg_pool_list(self, event: AstrMessageEvent, content: str = ""):
        """私聊分页查看随机提示词库：/aimg_pool_list [B/N] [页码] [关键词]"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_pool_list")
        try:
            sources, safety, custom_groups, page, keyword, selector = self._parse_pool_filter(body)
            entries = filter_prompt_entries(
                load_prompt_pool(self._prompt_pool_path()),
                source_codes=sources,
                safety_codes=safety,
                custom_groups=custom_groups,
                keyword=keyword,
            )
            page_size = 10
            page_count = max(1, (len(entries) + page_size - 1) // page_size)
            if page > page_count:
                raise WorkflowError(f"页码超过范围，当前共 {page_count} 页。")
            start = (page - 1) * page_size
            lines = [
                f"随机提示词库｜筛选={selector}｜关键词={keyword or '无'}｜"
                f"第 {page}/{page_count} 页｜共 {len(entries)} 条"
            ]
            for item in entries[start : start + page_size]:
                prompt = str(item.get("prompt", "")).replace("\n", " ")
                if len(prompt) > 100:
                    prompt = prompt[:97] + "..."
                lines.append(
                    f"\n[{item.get('id', '?')}] "
                    f"{item.get('source_code', '?')}/{item.get('safety_code', '?')} "
                    f"{'启用' if item.get('enabled', True) else '停用'}\n{prompt}"
                )
            await self._send_private_text(event, "\n".join(lines))
        except WorkflowError as exc:
            await event.send(event.plain_result(f"查询失败：{exc}"))

    @filter.command("aimg_pool_show")
    async def aimg_pool_show(self, event: AstrMessageEvent, content: str = ""):
        """私聊查看一条完整提示词记录。"""
        event.should_call_llm(False)
        prompt_id = extract_command_body(event.message_str, content, "aimg_pool_show")
        if not prompt_id:
            await event.send(event.plain_result("用法：/aimg_pool_show <条目 ID>"))
            return
        try:
            item = get_prompt_entry(load_prompt_pool(self._prompt_pool_path()), prompt_id)
            await self._send_private_text(event, self._format_prompt_entry(item))
        except WorkflowError as exc:
            await event.send(event.plain_result(f"查询失败：{exc}"))

    @filter.command("aimg_pool_export")
    async def aimg_pool_export(self, event: AstrMessageEvent, content: str = ""):
        """筛选并私聊导出提示词 JSON。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_pool_export")
        try:
            sources, safety, custom_groups, _, keyword, selector = self._parse_pool_filter(body)
            entries = filter_prompt_entries(
                load_prompt_pool(self._prompt_pool_path()),
                source_codes=sources,
                safety_codes=safety,
                custom_groups=custom_groups,
                keyword=keyword,
            )
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_selector = "".join(ch for ch in selector if ch.isalnum()) or "ALL"
            path = self._export_dir() / f"prompt_pool_{safe_selector}_{stamp}.json"
            export_prompt_entries(path, entries, selector=selector)
            await self._send_private_file(
                event,
                path,
                caption=f"提示词库导出：{selector}，共 {len(entries)} 条。",
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"导出失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_pool_add")
    async def aimg_pool_add(self, event: AstrMessageEvent, content: str = ""):
        """管理员添加提示词：/aimg_pool_add B/N <提示词>"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_pool_add")
        selector, _, prompt = body.partition(" ")
        try:
            source, safety = require_source_safety_selector(selector)
            entry, _ = add_prompt_entry(
                self._prompt_pool_path(),
                prompt=prompt,
                source_code=source,
                safety_code=safety,
            )
            await event.send(
                event.plain_result(
                    f"提示词已添加：{entry['id']}｜{source}/{safety}。"
                )
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"添加失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_pool_set")
    async def aimg_pool_set(self, event: AstrMessageEvent, content: str = ""):
        """管理员修改提示词及可选分组：/aimg_pool_set <ID> [B/N] <提示词>"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_pool_set")
        prompt_id, _, remaining = body.partition(" ")
        if not prompt_id or not remaining.strip():
            await event.send(
                event.plain_result("用法：/aimg_pool_set <ID> [B/N] <新提示词>")
            )
            return
        first, _, tail = remaining.strip().partition(" ")
        decoded = decode_group_code_token(first)
        source = safety = None
        prompt = remaining.strip()
        try:
            if decoded is not None:
                source, safety = require_source_safety_selector(first)
                prompt = tail
            entry, _ = update_prompt_entry(
                self._prompt_pool_path(),
                prompt_id,
                prompt=prompt,
                source_code=source,
                safety_code=safety,
            )
            await event.send(
                event.plain_result(
                    f"提示词已更新：{entry['id']}｜"
                    f"{entry['source_code']}/{entry['safety_code']}。"
                )
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"修改失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_pool_enable")
    async def aimg_pool_enable(self, event: AstrMessageEvent, content: str = ""):
        """管理员启用或停用条目：/aimg_pool_enable <ID> <on|off>"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_pool_enable")
        prompt_id, _, state = body.partition(" ")
        states = {"on": True, "true": True, "1": True, "启用": True,
                  "off": False, "false": False, "0": False, "停用": False}
        enabled = states.get(state.strip().casefold())
        if not prompt_id or enabled is None:
            await event.send(
                event.plain_result("用法：/aimg_pool_enable <ID> <on|off>")
            )
            return
        try:
            entry, _ = update_prompt_entry(
                self._prompt_pool_path(), prompt_id, enabled=enabled
            )
            await event.send(
                event.plain_result(
                    f"条目 {entry['id']} 已{'启用' if enabled else '停用'}。"
                )
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"操作失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_pool_del")
    async def aimg_pool_del(self, event: AstrMessageEvent, content: str = ""):
        """管理员可恢复删除提示词条目。"""
        event.should_call_llm(False)
        prompt_id = extract_command_body(event.message_str, content, "aimg_pool_del")
        if not prompt_id:
            await event.send(event.plain_result("用法：/aimg_pool_del <条目 ID>"))
            return
        try:
            entry, _ = delete_prompt_entry(
                self._prompt_pool_path(),
                self._prompt_pool_trash_path(),
                prompt_id,
                actor=str(event.get_sender_id()),
            )
            await event.send(
                event.plain_result(
                    f"已删除条目 {entry['id']}；原记录已写入 prompt_pool_trash.json。"
                )
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"删除失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_pool_import")
    async def aimg_pool_import(self, event: AstrMessageEvent, content: str = ""):
        """管理员从服务器 JSON 路径批量导入提示词。"""
        event.should_call_llm(False)
        raw_path = extract_command_body(event.message_str, content, "aimg_pool_import").strip().strip('"')
        path = Path(raw_path).expanduser() if raw_path else Path()
        if not raw_path or not path.is_absolute() or path.suffix.casefold() != ".json":
            await event.send(
                event.plain_result("用法：/aimg_pool_import <服务器上的 JSON 绝对路径>")
            )
            return
        try:
            added, skipped, _ = import_prompt_entries(self._prompt_pool_path(), path)
            await event.send(
                event.plain_result(f"导入完成：新增 {added} 条，跳过 {skipped} 条。")
            )
        except (WorkflowError, ValueError, TypeError) as exc:
            await event.send(event.plain_result(f"导入失败：{exc}"))

    @filter.command("aimg_trigger_list")
    async def aimg_trigger_list(self, event: AstrMessageEvent, content: str = ""):
        """私聊查看角色/画风触发词摘要。"""
        event.should_call_llm(False)
        category = extract_command_body(event.message_str, content, "aimg_trigger_list")
        try:
            presets = load_presets(self._preset_path())
            categories = [preset_category_key(category)] if category else ["styles", "characters"]
            lines = ["角色 / 画风触发词目录："]
            for key in categories:
                lines.append(f"\n{'画风' if key == 'styles' else '角色'}：")
                for name, preset in presets[key].items():
                    if key == "styles" and isinstance(preset, dict) and preset.get("hidden"):
                        continue
                    prompt = str(preset.get("prompt", "")).replace("\n", " ")
                    if len(prompt) > 90:
                        prompt = prompt[:87] + "..."
                    match = " | ".join(str(x) for x in preset.get("match", []))
                    lines.append(
                        f"- {name}\n  prompt={prompt or '无'}"
                        + (f"\n  match={match or '无'}" if key == "styles" else "")
                    )
                if not presets[key]:
                    lines.append("- 无")
            await self._send_private_text(event, "\n".join(lines))
        except WorkflowError as exc:
            await event.send(event.plain_result(f"查询失败：{exc}"))

    @filter.command("aimg_manage_help")
    async def aimg_manage_help(self, event: AstrMessageEvent):
        """私聊发送当前提示词库与触发词管理速查。"""
        event.should_call_llm(False)
        text = (
            "ComfyUI 桥接 0.3.4 Beta 管理速查\n\n"
            "查询（普通用户可用，结果私聊）：\n"
            "/aimg_pool_list [B|G|D|C|R|P/级别] [@自定义分组] [页码] [关键词]\n"
            "/aimg_pool_show <ID>\n"
            "/aimg_pool_export [B|G|D|C|R|P/级别] [关键词]\n"
            "/aimg_trigger_list [画风|角色]\n"
            "/aimg_trigger_show <画风|角色> <名称>\n\n"
            "提示词写操作（管理员）：\n"
            "/aimg_pool_add P/N <提示词>\n"
            "/aimg_pool_set <ID> [P/N] <提示词>\n"
            "/aimg_pool_enable <ID> <on|off>\n"
            "/aimg_pool_del <ID>\n"
            "/aimg_pool_import <服务器 JSON 绝对路径>\n"
            "/aimg_cleanup（立即清理超过保留时间的插件图片）\n\n"
            "KP 独立库：\n"
            "K/N、K/H、K/S 分别动态拼装对应级别；可在配置中关闭动态模式。\n"
            "动态失败默认回退原有 77 个 N/S 配对范例。\n"
            "KP 不参与上述主库删改；App 点赞后会复制为主库 P 组。\n\n"
            "触发词写操作（管理员）：\n"
            "/aimg_trigger_set <画风|角色> <名称> <prompt|match> <内容>\n"
            "/aimg_trigger_del <画风|角色> <名称> <prompt|match|all>\n\n"
            "混沌时刻：\n"
            "来张好图混沌时刻 [分组] [补充提示词]\n"
            "来张好图混沌五连抽 [分组] [补充提示词]\n\n"
            "自定义分组：固定分组前后可加 @分组ID；多个写成 @组1+组2。"
        )
        await self._send_private_text(event, text)

    @filter.command("aimg_trigger_show")
    async def aimg_trigger_show(self, event: AstrMessageEvent, content: str = ""):
        """私聊查看一个角色或画风的完整触发词和 LoRA 信息。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_trigger_show")
        category, _, name = body.partition(" ")
        if not category or not name.strip():
            await event.send(
                event.plain_result("用法：/aimg_trigger_show <画风|角色> <名称>")
            )
            return
        try:
            preset = get_preset(load_presets(self._preset_path()), category, name.strip())
            if isinstance(preset, dict) and preset.get("hidden"):
                raise WorkflowError("找不到该公共预设")
            await self._send_private_text(
                event, self._format_preset_detail(category, name.strip(), preset)
            )
        except WorkflowError as exc:
            await event.send(event.plain_result(f"查询失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_trigger_set")
    async def aimg_trigger_set(self, event: AstrMessageEvent, content: str = ""):
        """管理员修改已有触发词字段。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_trigger_set")
        parts = body.split(maxsplit=3)
        if len(parts) != 4:
            await event.send(
                event.plain_result(
                    "用法：/aimg_trigger_set <画风|角色> <名称> <prompt|match> <内容>"
                )
            )
            return
        category, name, field, value = parts
        try:
            update_preset_trigger(self._preset_path(), category, name, field, value)
            await event.send(event.plain_result(f"已更新{category}“{name}”的 {field}。"))
        except WorkflowError as exc:
            await event.send(event.plain_result(f"修改失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_trigger_del")
    async def aimg_trigger_del(self, event: AstrMessageEvent, content: str = ""):
        """管理员清空触发词字段或删除整个预设。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_trigger_del")
        parts = body.split(maxsplit=2)
        if len(parts) != 3:
            await event.send(
                event.plain_result(
                    "用法：/aimg_trigger_del <画风|角色> <名称> <prompt|match|all>"
                )
            )
            return
        category, name, field = parts
        try:
            cleared, _ = clear_preset_trigger(
                self._preset_path(), category, name, field
            )
            detail = "整个预设" if cleared == "all" else f"{cleared} 触发词"
            await event.send(event.plain_result(f"已删除{category}“{name}”的{detail}。"))
        except WorkflowError as exc:
            await event.send(event.plain_result(f"删除失败：{exc}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_style_set")
    async def aimg_style_set(self, event: AstrMessageEvent, content: str = ""):
        """管理员新建或覆盖画风预设。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_style_set")
        try:
            name, preset = parse_style_definition(body)
            if (
                str(self.config.get("style_lora_mode", "dynamic")).casefold()
                == "fixed"
                and len(preset["loras"]) > len(self._style_slot_ids())
            ):
                raise WorkflowError(
                    f"当前只配置了 {len(self._style_slot_ids())} 个画风槽位。"
                )
            max_loras = int(self.config.get("max_dynamic_style_loras", 16))
            if len(preset["loras"]) > max_loras:
                raise WorkflowError(f"画风 LoRA 数量不能超过 {max_loras}。")
            presets = load_presets(self._preset_path())
            presets["styles"][name] = preset
            save_presets(self._preset_path(), presets)
            yield event.plain_result(
                f"画风预设“{name}”已保存：{len(preset['loras'])} 个 LoRA，"
                f"固定提示词={'有' if preset['prompt'] else '无'}，"
                f"自动匹配串={preset['match'] or '无'}"
            )
        except WorkflowError as exc:
            yield event.plain_result(f"保存失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_role_set")
    async def aimg_role_set(self, event: AstrMessageEvent, content: str = ""):
        """管理员新建或覆盖角色 LoRA 预设。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_role_set")
        try:
            name, preset = parse_character_definition(body)
            presets = load_presets(self._preset_path())
            presets["characters"][name] = preset
            save_presets(self._preset_path(), presets)
            yield event.plain_result(
                f"角色预设“{name}”已保存：{preset['lora']['name']}，"
                f"model={preset['lora']['strength_model']}，"
                f"clip={preset['lora']['strength_clip']}，"
                f"固定提示词={'有' if preset['prompt'] else '无'}"
            )
        except WorkflowError as exc:
            yield event.plain_result(f"保存失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_role_text_set")
    async def aimg_role_text_set(self, event: AstrMessageEvent, content: str = ""):
        """管理员创建无需 LoRA 的底模直出角色固定串。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_role_text_set")
        try:
            name, preset = parse_text_character_definition(body)
            presets = load_presets(self._preset_path())
            presets["characters"][name] = preset
            save_presets(self._preset_path(), presets)
            yield event.plain_result(
                f"底模角色“{name}”已保存：不加载 LoRA，固定提示词已配置。"
            )
        except WorkflowError as exc:
            yield event.plain_result(f"保存失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_preset_del")
    async def aimg_preset_del(self, event: AstrMessageEvent, content: str = ""):
        """管理员删除角色或画风预设。"""
        event.should_call_llm(False)
        body = extract_command_body(event.message_str, content, "aimg_preset_del")
        parts = body.split(maxsplit=1)
        if len(parts) != 2:
            yield event.plain_result("用法：/aimg_preset_del <画风|角色> <名称>")
            return
        category, name = parts
        mapping = {"画风": "styles", "style": "styles", "角色": "characters", "role": "characters"}
        key = mapping.get(category.lower())
        if not key:
            yield event.plain_result("类型只能是：画风、角色、style、role")
            return
        try:
            presets = load_presets(self._preset_path())
            if name not in presets[key]:
                raise WorkflowError(f"找不到预设：{name}")
            del presets[key][name]
            save_presets(self._preset_path(), presets)
            yield event.plain_result(f"已删除{category}预设“{name}”。")
        except WorkflowError as exc:
            yield event.plain_result(f"删除失败：{exc}")

    @filter.command("aimg_status")
    async def aimg_status(self, event: AstrMessageEvent):
        """检查 ComfyUI、工作流节点与 LoRA 数量。"""
        event.should_call_llm(False)
        try:
            path = self._workflow_path()
            workflow = load_api_workflow(path)
            summary = describe_workflow(workflow)
            presets = load_presets(self._preset_path())
            pool_stats = prompt_pool_stats(
                load_prompt_pool(self._prompt_pool_path())
            )
            kp_pool = load_prompt_pool(self._kp_prompt_pool_path())
            kp_stats = prompt_pool_stats(kp_pool)
            kp_dynamic_count = dynamic_k_history_count(kp_pool)
            protected_count = len(
                parse_protected_characters(
                    self.config.get("sexual_protected_characters", "")
                )
            )
            sampler_node_id = str(self.config.get("sampler_node_id", "19")).strip()
            sampler_inputs = workflow.get(sampler_node_id, {}).get("inputs", {})
            if not isinstance(sampler_inputs, dict):
                sampler_inputs = {}
            reverse_enabled = bool(
                self.config.get("reverse_workflow_enabled", True)
            )
            reverse_path = self._reverse_workflow_path() if reverse_enabled else None
            reverse_nodes = 0
            if reverse_path is not None:
                reverse_nodes = len(load_api_workflow(reverse_path))
            registry = load_workflow_registry(self._registry_path())
            hq_definition = registry.resolve("hq_txt2img_anima_v1")
            refine_definition = registry.resolve("refine_existing_v1")
            hq_path = resolve_workflow_path(
                hq_definition,
                config=self.config,
                plugin_dir=Path(__file__).resolve().parent,
            )
            refine_path = resolve_workflow_path(
                refine_definition,
                config=self.config,
                plugin_dir=Path(__file__).resolve().parent,
            )
            validate_workflow_nodes(load_api_workflow(hq_path), hq_definition)
            validate_workflow_nodes(load_api_workflow(refine_path), refine_definition)
            job_store = self._job_store()
            job_count = (
                sum(1 for _ in job_store.jobs_dir.glob("job_*.json"))
                if job_store.jobs_dir.is_dir()
                else 0
            )

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._base_url()}/system_stats") as response:
                    await self._response_json(response)

            lora_lines = [
                f"  - 节点 {item['node_id']}: {item['name']} "
                f"(model={item['strength_model']}, clip={item['strength_clip']})"
                for item in summary["loras"]
            ]
            lora_text = "\n".join(lora_lines) if lora_lines else "  - 无"
            yield event.plain_result(
                "ComfyUI 桥接状态：\n"
                f"- 连接：正常 {self._base_url()}\n"
                f"- 工作流：{path}\n"
                f"- 节点数：{summary['node_count']}\n"
                f"- 输出节点：{', '.join(summary['output_nodes']) or '无'}\n"
                f"- LoRA 数量：{summary['lora_count']}\n"
                f"- 画风槽位：{', '.join(self._style_slot_ids()) or '无'}\n"
                f"- 画风加载模式：{str(self.config.get('style_lora_mode', 'dynamic'))}\n"
                f"- 画风预设：{len(presets['styles'])} 个\n"
                f"- 角色预设：{len(presets['characters'])} 个\n"
                f"- 随机提示词：{pool_stats['enabled']} 个启用 / "
                f"{pool_stats['total']} 个记录\n"
                f"- 来源组记录：B={pool_stats['sources'].get('B', 0)}，"
                f"G={pool_stats['sources'].get('G', 0)}，"
                f"D={pool_stats['sources'].get('D', 0)}，"
                f"C={pool_stats['sources'].get('C', 0)}，"
                f"R={pool_stats['sources'].get('R', 0)}，"
                f"P={pool_stats['sources'].get('P', 0)}\n"
                f"- 级别组记录：N={pool_stats['safety_codes'].get('N', 0)}，"
                f"H={pool_stats['safety_codes'].get('H', 0)}，"
                f"S={pool_stats['safety_codes'].get('S', 0)}\n"
                f"- 自定义分组：{', '.join(f'{key}={value}' for key, value in pool_stats.get('custom_groups', {}).items()) or '无'}\n"
                f"- KP 独立库：{kp_stats['enabled']} 个启用 / "
                f"{kp_stats['total']} 个记录（"
                f"N={kp_stats['safety_codes'].get('N', 0)}，"
                f"H={kp_stats['safety_codes'].get('H', 0)}，"
                f"S={kp_stats['safety_codes'].get('S', 0)}）\n"
                f"- KP 动态拼装：{'开启' if bool(self.config.get('kp_dynamic_enabled', True)) else '关闭'}｜"
                f"已保存动态记录={kp_dynamic_count}｜"
                f"模块库={self._kp_dynamic_catalog_path()}\n"
                f"- S 组保护角色：{protected_count} 个\n"
                f"- 默认采样：{sampler_inputs.get('sampler_name', '未知')}｜"
                f"steps={sampler_inputs.get('steps', '未知')}｜"
                f"CFG={sampler_inputs.get('cfg', '未知')}｜"
                f"scheduler={sampler_inputs.get('scheduler', '未知')}\n"
                f"- DPM++ 2M：{str(self.config.get('dpm_sampler_name', 'dpmpp_2m'))}｜"
                f"steps={int(self.config.get('dpm_sampler_steps', 30))}｜"
                f"CFG={float(self.config.get('dpm_sampler_cfg', 6.0))}｜"
                f"scheduler={str(self.config.get('dpm_sampler_scheduler', 'normal'))}\n"
                f"- DPM++ 2M SDE：{str(self.config.get('dpm_2m_sde_sampler_name', 'dpmpp_2m_sde'))}｜"
                f"steps={int(self.config.get('dpm_2m_sde_sampler_steps', 30))}｜"
                f"CFG={float(self.config.get('dpm_2m_sde_sampler_cfg', 6.0))}｜"
                f"scheduler={str(self.config.get('dpm_2m_sde_sampler_scheduler', 'normal'))}\n"
                f"- DPM++ 2M SDE GPU：{str(self.config.get('dpm_2m_sde_gpu_sampler_name', 'dpmpp_2m_sde_gpu'))}｜"
                f"steps={int(self.config.get('dpm_2m_sde_gpu_sampler_steps', 30))}｜"
                f"CFG={float(self.config.get('dpm_2m_sde_gpu_sampler_cfg', 6.0))}｜"
                f"scheduler={str(self.config.get('dpm_2m_sde_gpu_sampler_scheduler', 'normal'))}\n"
                f"- 默认画布：{int(self.config.get('default_width', 1024))}x"
                f"{int(self.config.get('default_height', 1536))}（节点 "
                f"{str(self.config.get('latent_node_id', '28'))}）\n"
                f"- 普通五连抽：{'微批' if bool(self.config.get('five_draw_batch_enabled', True)) else '逐张'}｜"
                f"batch={max(1, min(5, int(self.config.get('five_draw_micro_batch_size', 2))))}｜"
                f"同用户单任务={'是' if bool(self.config.get('five_draw_single_active', True)) else '否'}\n"
                f"- 混沌五连抽冷却：{self._five_draw_cooldown_seconds()} 秒（管理员豁免）\n"
                f"- 专用反推：{'启用' if reverse_enabled else '关闭'}\n"
                f"- 反推工作流：{reverse_path if reverse_path else '使用旧 Provider'}\n"
                f"- 反推节点数：{reverse_nodes}\n"
                f"- 默认反推模式：{str(self.config.get('reverse_default_preset', 'full'))}\n"
                f"- Workflow Registry：rev {registry.revision}｜"
                f"{', '.join(registry.ids())}\n"
                f"- HQ 工作流：{hq_path}｜profiles=stable, beauty\n"
                f"- 放大重修工作流：{refine_path}｜profiles=light, medium\n"
                f"- Job 记录：{job_count} 个｜{job_store.root}\n"
                f"- 插件图片清理：{'启用' if bool(self.config.get('output_cleanup_enabled', True)) else '关闭'}｜"
                f"保留 {self._output_retention_hours():g} 小时｜"
                f"每 {self._output_cleanup_interval_seconds() // 60} 分钟扫描｜"
                f"{self._output_dir()}\n"
                f"{lora_text}"
            )
        except Exception as exc:
            yield event.plain_result(f"状态检查失败：{type(exc).__name__}: {exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("aimg_cleanup")
    async def aimg_cleanup(self, event: AstrMessageEvent):
        """Immediately remove expired images from the plugin output directory."""
        event.should_call_llm(False)
        try:
            report = await self._cleanup_plugin_outputs()
            mib = report.deleted_bytes / (1024 * 1024)
            yield event.plain_result(
                "插件图片清理完成：\n"
                f"- 目录：{self._output_dir()}\n"
                f"- 保留时间：{self._output_retention_hours():g} 小时\n"
                f"- 扫描图片：{report.scanned} 张\n"
                f"- 删除图片：{report.deleted} 张\n"
                f"- 释放空间：{mib:.2f} MiB\n"
                f"- 失败：{report.failed} 个\n"
                "ComfyUI/output 未处理。"
            )
        except Exception as exc:
            yield event.plain_result(
                f"插件图片清理失败：{type(exc).__name__}: {exc}"
            )

    async def terminate(self):
        """Cancel background tasks during reload or shutdown."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        async with self._pending_lock:
            pending = list(self._pending_images.values())
            self._pending_images.clear()
        for item in pending:
            if item.timeout_task:
                item.timeout_task.cancel()
