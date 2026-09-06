from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct execution for local tests
    from workflow_runtime import WorkflowError


EMPTY_PRESETS: dict[str, Any] = {
    "version": 1,
    "styles": {},
    "characters": {},
}

DIRECTIVE_NAMES = {
    "角色": "character",
    "role": "character",
    "角色模式": "character_tag_mode",
    "角色标签": "character_tag_mode",
    "character_mode": "character_tag_mode",
    "画风": "style",
    "style": "style",
    "角色权重": "character_strength",
    "role_strength": "character_strength",
    "角色模型": "character_model",
    "role_model": "character_model",
    "角色clip": "character_clip",
    "role_clip": "character_clip",
    "画风倍率": "style_scale",
    "style_scale": "style_scale",
    "采样器": "sampler_preset",
    "sampler": "sampler_preset",
    "调度器": "scheduler",
    "scheduler": "scheduler",
    "步数": "sampler_steps",
    "step": "sampler_steps",
    "steps": "sampler_steps",
    "cfg": "sampler_cfg",
    "尺寸": "size",
    "size": "size",
    "比例": "ratio",
    "ratio": "ratio",
    "宽": "width",
    "width": "width",
    "高": "height",
    "height": "height",
    "放大": "scale",
    "scale": "scale",
    "重绘": "denoise",
    "denoise": "denoise",
    "任务": "parent_job_id",
    "job": "parent_job_id",
    "job_id": "parent_job_id",
}


def empty_presets() -> dict[str, Any]:
    return json.loads(json.dumps(EMPTY_PRESETS, ensure_ascii=False))


def load_presets(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_presets()
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取 LoRA 预设：{exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowError("LoRA 预设文件必须是 JSON 对象。")
    data.setdefault("version", 1)
    data.setdefault("styles", {})
    data.setdefault("characters", {})
    if not isinstance(data["styles"], dict) or not isinstance(
        data["characters"], dict
    ):
        raise WorkflowError("LoRA 预设中的 styles/characters 必须是对象。")
    return data


def save_presets(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise WorkflowError(f"无法保存 LoRA 预设：{exc}") from exc


def preset_category_key(category: str) -> str:
    mapping = {
        "画风": "styles",
        "style": "styles",
        "角色": "characters",
        "role": "characters",
        "character": "characters",
    }
    key = mapping.get(str(category or "").strip().casefold())
    if not key:
        raise WorkflowError("类型只能是：画风、角色、style、role。")
    return key


def get_preset(data: dict[str, Any], category: str, name: str) -> dict[str, Any]:
    key = preset_category_key(category)
    preset = data.get(key, {}).get(str(name).strip())
    if not isinstance(preset, dict):
        raise WorkflowError(f"找不到预设：{name}")
    return preset


def update_preset_trigger(
    path: Path,
    category: str,
    name: str,
    field: str,
    value: str,
) -> dict[str, Any]:
    data = load_presets(path)
    key = preset_category_key(category)
    preset = get_preset(data, category, name)
    field_name = str(field or "").strip().casefold()
    text = str(value or "").strip(" ,\n\t")
    if not text:
        raise WorkflowError("触发词内容不能为空；清空请使用 /aimg_trigger_del。")
    if field_name in {"prompt", "提示词", "固定串"}:
        preset["prompt"] = text
    elif field_name in {"match", "匹配", "触发词"}:
        if key != "styles":
            raise WorkflowError("角色预设只有 prompt 固定串，没有 match 自动画风匹配串。")
        preset["match"] = [item.strip() for item in text.split("|") if item.strip()]
    else:
        raise WorkflowError("字段只能是 prompt 或 match（match 仅画风可用）。")
    save_presets(path, data)
    return preset


def clear_preset_trigger(
    path: Path,
    category: str,
    name: str,
    field: str,
) -> tuple[str, dict[str, Any] | None]:
    data = load_presets(path)
    key = preset_category_key(category)
    preset = get_preset(data, category, name)
    field_name = str(field or "").strip().casefold()
    if field_name in {"all", "全部", "预设"}:
        del data[key][name]
        save_presets(path, data)
        return "all", None
    if field_name in {"prompt", "提示词", "固定串"}:
        preset["prompt"] = ""
        cleared = "prompt"
    elif field_name in {"match", "匹配", "触发词"}:
        if key != "styles":
            raise WorkflowError("角色预设没有 match 字段。")
        preset["match"] = []
        cleared = "match"
    else:
        raise WorkflowError("删除字段只能是 prompt、match 或 all。")
    save_presets(path, data)
    return cleared, preset


def _float_value(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"{label}必须是数字。") from exc
    if not -5.0 <= result <= 5.0:
        raise WorkflowError(f"{label}必须在 -5 到 5 之间。")
    return result


def parse_lora_spec(spec: str) -> dict[str, Any]:
    parts = [part.strip() for part in spec.split("|")]
    if not parts or not parts[0]:
        raise WorkflowError("LoRA 文件名不能为空。")
    if len(parts) > 3:
        raise WorkflowError("LoRA 条目格式应为 文件名|model权重|clip权重。")
    model = _float_value(parts[1], "model 权重") if len(parts) >= 2 and parts[1] else 1.0
    clip = _float_value(parts[2], "clip 权重") if len(parts) >= 3 and parts[2] else model
    return {
        "name": parts[0],
        "strength_model": model,
        "strength_clip": clip,
    }


def _split_definition_options(body: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r"\s+--(prompt|match)\s+", body.strip(), flags=re.IGNORECASE)
    base = parts[0].strip()
    options: dict[str, str] = {}
    for index in range(1, len(parts), 2):
        if index + 1 < len(parts):
            options[parts[index].lower()] = parts[index + 1].strip()
    return base, options


def parse_style_definition(body: str) -> tuple[str, dict[str, Any]]:
    base, options = _split_definition_options(body)
    try:
        name, lora_text = base.split(maxsplit=1)
    except ValueError as exc:
        raise WorkflowError(
            "用法：/aimg_style_set <名称> <文件|model|clip;...> "
            "[--prompt 固定提示词] [--match 匹配串1|匹配串2]"
        ) from exc
    loras = [parse_lora_spec(item) for item in lora_text.split(";") if item.strip()]
    if not loras:
        raise WorkflowError("画风预设至少需要一个 LoRA 条目。")
    matches = [item.strip() for item in options.get("match", "").split("|") if item.strip()]
    return name, {
        "loras": loras,
        "prompt": options.get("prompt", "").strip(),
        "match": matches,
    }


def parse_character_definition(body: str) -> tuple[str, dict[str, Any]]:
    base, options = _split_definition_options(body)
    try:
        name, lora_text = base.split(maxsplit=1)
    except ValueError as exc:
        raise WorkflowError(
            "用法：/aimg_role_set <名称> <文件|model|clip> [--prompt 固定提示词]"
        ) from exc
    if ";" in lora_text:
        raise WorkflowError("一个角色预设只能包含一个角色 LoRA。")
    return name, {
        "lora": parse_lora_spec(lora_text),
        "prompt": options.get("prompt", "").strip(),
    }


def parse_text_character_definition(body: str) -> tuple[str, dict[str, Any]]:
    base, options = _split_definition_options(body)
    name = base.strip()
    prompt = options.get("prompt", "").strip()
    if not name or not prompt:
        raise WorkflowError(
            "用法：/aimg_role_text_set <名称> --prompt <底模角色固定提示词>"
        )
    return name, {"lora": None, "prompt": prompt}


def parse_generation_directives(text: str) -> tuple[str, dict[str, Any]]:
    remaining = str(text or "").lstrip()
    options: dict[str, Any] = {}
    names = "|".join(sorted((re.escape(name) for name in DIRECTIVE_NAMES), key=len, reverse=True))
    pattern = re.compile(rf"^(?:({names})=([^\s]*))(?:\s+|$)", re.IGNORECASE)

    while remaining:
        match = pattern.match(remaining)
        if not match:
            break
        original_name, value = match.groups()
        key = DIRECTIVE_NAMES[original_name.lower()]
        if value and value != "默认":
            if key in {
                "character_strength",
                "character_model",
                "character_clip",
                "style_scale",
                "scale",
                "denoise",
            }:
                options[key] = _float_value(value, original_name)
            elif key in {"width", "height"}:
                try:
                    options[key] = int(value)
                except ValueError as exc:
                    raise WorkflowError(f"{original_name}必须是整数。") from exc
            else:
                options[key] = value
        remaining = remaining[match.end() :].lstrip()

    return remaining.strip(), options


def resolve_presets(
    prompt: str,
    options: dict[str, Any],
    presets: dict[str, Any],
    *,
    default_style: str = "",
    auto_match: bool = True,
    allow_character_text_fallback: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, str]:
    styles = presets.get("styles", {})
    characters = presets.get("characters", {})
    style_name = str(options.get("style", "") or default_style).strip()
    character_name = str(options.get("character", "")).strip()

    if not style_name and auto_match:
        folded_prompt = prompt.casefold()
        matches = []
        for candidate, preset in styles.items():
            if isinstance(preset, dict) and preset.get("hidden"):
                continue
            needles = preset.get("match", []) if isinstance(preset, dict) else []
            if any(str(needle).casefold() in folded_prompt for needle in needles if str(needle)):
                matches.append(candidate)
        if len(matches) > 1:
            raise WorkflowError(f"提示词同时匹配多个画风预设：{', '.join(matches)}")
        if matches:
            style_name = matches[0]

    style = styles.get(style_name) if style_name else None
    character = characters.get(character_name) if character_name else None
    if style_name and not isinstance(style, dict):
        raise WorkflowError(f"找不到画风预设：{style_name}")
    if (
        character_name
        and not isinstance(character, dict)
        and not allow_character_text_fallback
    ):
        raise WorkflowError(f"找不到角色预设：{character_name}")
    return style, character, style_name, character_name


def _node_inputs(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict) or node.get("class_type") != "LoraLoader":
        raise WorkflowError(f"LoRA 槽位节点 {node_id} 不存在或不是 LoraLoader。")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise WorkflowError(f"LoRA 槽位节点 {node_id} 缺少 inputs。")
    return inputs


def _bypass_lora_node(workflow: dict[str, Any], node_id: str) -> None:
    inputs = _node_inputs(workflow, node_id)
    model_source = inputs.get("model")
    clip_source = inputs.get("clip")
    if not isinstance(model_source, list) or not isinstance(clip_source, list):
        raise WorkflowError(f"LoRA 槽位节点 {node_id} 缺少 model/clip 输入连接。")

    for consumer_id, consumer in workflow.items():
        if consumer_id == str(node_id) or not isinstance(consumer, dict):
            continue
        consumer_inputs = consumer.get("inputs", {})
        if not isinstance(consumer_inputs, dict):
            continue
        for key, value in list(consumer_inputs.items()):
            if value == [str(node_id), 0]:
                consumer_inputs[key] = list(model_source)
            elif value == [str(node_id), 1]:
                consumer_inputs[key] = list(clip_source)
    del workflow[str(node_id)]


def apply_lora_plan(
    workflow: dict[str, Any],
    *,
    style: dict[str, Any] | None,
    character: dict[str, Any] | None,
    style_slot_ids: list[str],
    positive_node_id: str,
    negative_node_id: str,
    sampler_node_id: str,
    character_node_id: str,
    options: dict[str, Any],
    style_mode: str = "fixed",
    dynamic_style_node_id_start: int = 900100,
    max_dynamic_style_loras: int = 16,
) -> dict[str, Any]:
    applied: dict[str, Any] = {"style_loras": [], "character_lora": None}
    tail_model: list[Any] | None = None
    tail_clip: list[Any] | None = None

    if style is not None:
        loras = style.get("loras", [])
        if not isinstance(loras, list):
            raise WorkflowError("画风预设的 loras 必须是列表。")
        if not style_slot_ids:
            raise WorkflowError("未配置用于定位基础 MODEL/CLIP 的画风 LoRA 节点。")

        first_inputs = _node_inputs(workflow, style_slot_ids[0])
        base_model = list(first_inputs.get("model", []))
        base_clip = list(first_inputs.get("clip", []))
        scale = float(options.get("style_scale", 1.0))
        mode = str(style_mode or "fixed").strip().casefold()
        if mode == "dynamic":
            if len(loras) > max_dynamic_style_loras:
                raise WorkflowError(
                    f"画风包含 {len(loras)} 个 LoRA，超过动态上限 {max_dynamic_style_loras}。"
                )
            for node_id in reversed(style_slot_ids):
                _bypass_lora_node(workflow, node_id)
            tail_model, tail_clip = base_model, base_clip
            for index, lora in enumerate(loras):
                node_id = str(dynamic_style_node_id_start + index)
                if node_id in workflow:
                    raise WorkflowError(f"动态画风节点 ID {node_id} 与工作流现有节点冲突。")
                model_strength = _float_value(
                    lora.get("strength_model", 1.0), "model 权重"
                ) * scale
                clip_strength = _float_value(
                    lora.get("strength_clip", model_strength), "clip 权重"
                ) * scale
                workflow[node_id] = {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": str(lora.get("name", "")).strip(),
                        "strength_model": model_strength,
                        "strength_clip": clip_strength,
                        "model": tail_model,
                        "clip": tail_clip,
                    },
                    "_meta": {"title": f"AstrBot 动态画风 LoRA {index + 1}"},
                }
                tail_model, tail_clip = [node_id, 0], [node_id, 1]
                applied["style_loras"].append(
                    {
                        "node_id": node_id,
                        "name": workflow[node_id]["inputs"]["lora_name"],
                        "strength_model": model_strength,
                        "strength_clip": clip_strength,
                    }
                )
            sampler_inputs = workflow.get(str(sampler_node_id), {}).get("inputs", {})
            positive_inputs = workflow.get(str(positive_node_id), {}).get("inputs", {})
            negative_inputs = workflow.get(str(negative_node_id), {}).get("inputs", {})
            if isinstance(sampler_inputs, dict) and "model" in sampler_inputs:
                sampler_inputs["model"] = tail_model
            if isinstance(positive_inputs, dict) and "clip" in positive_inputs:
                positive_inputs["clip"] = tail_clip
            if isinstance(negative_inputs, dict) and "clip" in negative_inputs:
                negative_inputs["clip"] = tail_clip
        elif mode == "fixed":
            if len(loras) > len(style_slot_ids):
                raise WorkflowError(
                    f"画风包含 {len(loras)} 个 LoRA，但工作流只有 {len(style_slot_ids)} 个槽位。"
                )
            for index, lora in enumerate(loras):
                node_id = style_slot_ids[index]
                inputs = _node_inputs(workflow, node_id)
                model_strength = _float_value(
                    lora.get("strength_model", 1.0), "model 权重"
                ) * scale
                clip_strength = _float_value(
                    lora.get("strength_clip", model_strength), "clip 权重"
                ) * scale
                inputs["lora_name"] = str(lora.get("name", "")).strip()
                inputs["strength_model"] = model_strength
                inputs["strength_clip"] = clip_strength
                applied["style_loras"].append(
                    {
                        "node_id": node_id,
                        "name": inputs["lora_name"],
                        "strength_model": model_strength,
                        "strength_clip": clip_strength,
                    }
                )
            for node_id in reversed(style_slot_ids[len(loras) :]):
                _bypass_lora_node(workflow, node_id)
            if loras:
                tail_id = style_slot_ids[len(loras) - 1]
                tail_model, tail_clip = [tail_id, 0], [tail_id, 1]
            else:
                tail_model, tail_clip = base_model, base_clip
        else:
            raise WorkflowError("style_lora_mode 只能是 fixed 或 dynamic。")

    if character is not None and character.get("lora") is not None:
        if str(character_node_id) in workflow:
            raise WorkflowError(
                f"动态角色节点 ID {character_node_id} 与工作流现有节点冲突。"
            )
        lora = character.get("lora")
        if not isinstance(lora, dict):
            raise WorkflowError("角色预设缺少 lora 条目。")

        positive_inputs = workflow.get(str(positive_node_id), {}).get("inputs", {})
        sampler_inputs = workflow.get(str(sampler_node_id), {}).get("inputs", {})
        if tail_model is None:
            tail_model = list(sampler_inputs.get("model", []))
        if tail_clip is None:
            tail_clip = list(positive_inputs.get("clip", []))
        if not tail_model or not tail_clip:
            raise WorkflowError("无法确定角色 LoRA 的 model/clip 接入位置。")

        both = options.get("character_strength")
        model_strength = options.get(
            "character_model",
            both if both is not None else lora.get("strength_model", 1.0),
        )
        clip_strength = options.get(
            "character_clip",
            both if both is not None else lora.get("strength_clip", model_strength),
        )
        model_strength = _float_value(model_strength, "角色 model 权重")
        clip_strength = _float_value(clip_strength, "角色 clip 权重")
        workflow[str(character_node_id)] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": str(lora.get("name", "")).strip(),
                "strength_model": model_strength,
                "strength_clip": clip_strength,
                "model": tail_model,
                "clip": tail_clip,
            },
            "_meta": {"title": "AstrBot 动态角色 LoRA"},
        }
        sampler_inputs["model"] = [str(character_node_id), 0]
        positive_inputs["clip"] = [str(character_node_id), 1]
        negative = workflow.get(str(negative_node_id), {}).get("inputs", {})
        if isinstance(negative, dict) and "clip" in negative:
            negative["clip"] = [str(character_node_id), 1]
        applied["character_lora"] = {
            "node_id": str(character_node_id),
            "name": workflow[str(character_node_id)]["inputs"]["lora_name"],
            "strength_model": model_strength,
            "strength_clip": clip_strength,
        }

    return applied


def preset_prompt(style: dict[str, Any] | None, character: dict[str, Any] | None) -> str:
    parts = []
    for preset in (style, character):
        if isinstance(preset, dict) and str(preset.get("prompt", "")).strip():
            parts.append(str(preset["prompt"]).strip(" ,\n\t"))
    return ", ".join(parts)
