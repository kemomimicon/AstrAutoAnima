"""Small, AstrBot-free prompt and workflow adapter for the local workstation.

The API workflow is supplied by the user's ComfyUI installation.  This module
never imports AstrBot or changes that saved template on disk.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
from pathlib import Path
from typing import Any

from .character_catalog import search_character_dictionary
from .config import Settings
from .local_prompt_compiler import order_tags
from .schemas import RemoteJobCreateRequest


class LocalGenerationError(ValueError):
    pass


SIZES = {
    "1:1": (1024, 1024), "2:3": (1024, 1536), "3:2": (1536, 1024),
    "3:4": (960, 1280), "4:3": (1280, 960), "9:16": (864, 1536),
    "16:9": (1536, 864),
}


def clean_llm_tags(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|tags|txt)?\s*|\s*```$", "", text, flags=re.I)
    text = re.sub(r"^(?:tags?|prompt)\s*[:：]\s*", "", text, flags=re.I)
    text = re.sub(r"[，\r\n;；]+", ", ", text)
    text = re.sub(r"\s*,\s*", ", ", text).strip(" ,")
    if not text or len(re.findall(r"[\u3400-\u9fff]", text)) > 2:
        raise LocalGenerationError("中文转换没有返回有效英文 tags")
    return text


def _join(*parts: str) -> str:
    return ", ".join(part.strip(" ,\n\t") for part in parts if part.strip(" ,\n\t"))


def _preset(settings: Settings, payload: RemoteJobCreateRequest) -> tuple[str, list[dict[str, Any]]]:
    if not settings.preset_path.is_file():
        if payload.character or payload.style:
            raise LocalGenerationError("尚未导入角色／画风预设")
        return "", []
    try:
        data = json.loads(settings.preset_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LocalGenerationError(f"预设文件无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise LocalGenerationError("预设文件格式错误")
    styles = data.get("styles", {})
    characters = data.get("characters", {})
    if not isinstance(styles, dict) or not isinstance(characters, dict):
        raise LocalGenerationError("预设文件缺少 styles/characters")
    style = styles.get(payload.style) if payload.style else None
    character = characters.get(payload.character) if payload.character else None
    if payload.style and (not isinstance(style, dict) or style.get("hidden")):
        raise LocalGenerationError(f"找不到画风预设：{payload.style}")
    dictionary_prompt = ""
    if payload.character and not isinstance(character, dict):
        if payload.character_tag_mode == "off":
            dictionary_prompt = payload.character
        else:
            matches = search_character_dictionary(settings.character_dictionary_path,
                                                  edits_path=settings.character_dictionary_edits_path,
                                                  query=payload.character, limit=5)
            exact = [item for item in matches.items
                     if not item.disabled and payload.character.casefold() in
                     {item.tag.casefold(),
                      *(name.casefold() for name in item.aliases),
                      *(name.casefold() for name in item.chinese_names)}]
            if len(exact) != 1:
                raise LocalGenerationError(f"找不到唯一角色预设／词典角色：{payload.character}")
            dictionary_prompt = (exact[0].strong_prompt if payload.character_tag_mode == "strong"
                                 else exact[0].weak_prompt)
    variant_id = payload.character_variant.strip()
    if variant_id not in {"", "default"} and isinstance(character, dict):
        variants = character.get("variants", [])
        matches = [item for item in variants if isinstance(item, dict)
                   and item.get("id") == variant_id] if isinstance(variants, list) else []
        if (len(matches) != 1 or not isinstance(matches[0].get("prompt"), str)
                or not matches[0]["prompt"].strip(" ,\n\t")):
            raise LocalGenerationError(f"角色造型不存在、重复或触发词为空：{variant_id}")
        character = {**character, "prompt": matches[0]["prompt"]}
    elif variant_id not in {"", "default"}:
        raise LocalGenerationError("造型需要已有角色预设；可使用无 LoRA 的底模角色预设")
    loras: list[dict[str, Any]] = []
    if isinstance(style, dict):
        raw = style.get("loras", [])
        if not isinstance(raw, list):
            raise LocalGenerationError("画风 LoRA 列表无效")
        loras.extend(raw)
    if isinstance(character, dict) and character.get("lora") is not None:
        loras.append(character["lora"])
    prompt = _join(str(style.get("prompt", "")) if isinstance(style, dict) else "",
                   str(character.get("prompt", "")) if isinstance(character, dict) else "",
                   dictionary_prompt)
    return prompt, loras


def local_preset_snapshot(settings: Settings, payload: RemoteJobCreateRequest) -> dict[str, Any]:
    """Freeze each preset independently so a later partial remake keeps the other."""
    result = {}
    for kind in ("style", "character"):
        selection = payload.model_copy(update=(
            {"character": "", "character_variant": ""} if kind == "style" else {"style": ""}))
        prompt, loras = _preset(settings, selection)
        result[kind] = {"prompt": prompt, "loras": copy.deepcopy(loras)}
    return result


def _base_link(workflow: dict[str, Any], link: Any, port: int) -> list[Any]:
    if not isinstance(link, list) or len(link) != 2:
        raise LocalGenerationError("工作流 MODEL/CLIP 接线无效")
    seen: set[str] = set()
    while str(link[0]) in workflow and workflow[str(link[0])].get("class_type") == "LoraLoader":
        node_id = str(link[0])
        if node_id in seen:
            raise LocalGenerationError("工作流 LoRA 接线有循环")
        seen.add(node_id)
        link = workflow[node_id]["inputs"].get("model" if port == 0 else "clip")
        if not isinstance(link, list) or len(link) != 2:
            raise LocalGenerationError("工作流 LoRA 缺少基础 MODEL/CLIP")
    return list(link)


def _lora_name(settings: Settings, raw: dict[str, Any]) -> str:
    name = str(raw.get("name", "")).replace("\\", "/").strip()
    relative = Path(name)
    if not name or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts) or ":" in name:
        raise LocalGenerationError("LoRA 路径必须是 models/loras 下的相对路径")
    root = settings.lora_root.resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise LocalGenerationError(f"LoRA 文件不存在：{name}")
    return name


def build_local_workflow(settings: Settings, payload: RemoteJobCreateRequest,
                         tags: str, *, workflow_snapshot: dict[str, Any] | None = None,
                         preset_snapshot: dict[str, Any] | None = None) -> tuple[dict[str, Any], int, str]:
    if workflow_snapshot is None:
        path = settings.local_workflow_path
        if path is None or not path.is_file():
            raise LocalGenerationError("请配置 AAH_LOCAL_WORKFLOW_PATH 为已安装的 ComfyUI API 工作流")
        try:
            workflow = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise LocalGenerationError(f"无法读取 API 工作流：{exc}") from exc
    else:
        workflow = workflow_snapshot
    if not isinstance(workflow, dict) or not workflow or "nodes" in workflow:
        raise LocalGenerationError("需要 ComfyUI API 格式工作流")
    workflow = copy.deepcopy(workflow)
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            node.get("inputs", {})["filename_prefix"] = "AAA-Local/generated"
    try:
        positive = workflow["11"]["inputs"]
        sampler = workflow["19"]["inputs"]
        latent = workflow["28"]["inputs"]
        negative = workflow["12"]["inputs"]
        if not isinstance(positive["text"], str) or not isinstance(sampler["model"], list):
            raise KeyError("positive.text/model")
    except (KeyError, TypeError) as exc:
        raise LocalGenerationError("本机工作流需要 11/12/19/28 标准节点映射") from exc
    presets = preset_snapshot if preset_snapshot is not None else local_preset_snapshot(settings, payload)
    if not isinstance(presets, dict) or any(
            not isinstance(presets.get(kind), dict)
            or not isinstance(presets[kind].get("prompt"), str)
            or not isinstance(presets[kind].get("loras"), list)
            for kind in ("style", "character")):
        raise LocalGenerationError("本机预设快照缺失或损坏")
    preset_prompt = _join(presets["style"]["prompt"], presets["character"]["prompt"])
    loras = presets["style"]["loras"] + presets["character"]["loras"]
    final_prompt = order_tags(_join(preset_prompt, tags), settings.character_dictionary_path)
    if not final_prompt:
        raise LocalGenerationError("提示词不能为空")
    positive["text"] = final_prompt
    if payload.ratio:
        latent["width"], latent["height"] = SIZES[payload.ratio]
    # The bundled HQ template has a second sampler behind LatentUpscaleBy.
    # Direct generation must stop at the first sampler, not silently run HQ.
    if workflow_snapshot is None and payload.kind in {"direct", "chinese", "random"}:
        saves = [node for node in workflow.values() if isinstance(node, dict)
                 and node.get("class_type") == "SaveImage"]
        decoders = [node for node in workflow.values() if isinstance(node, dict)
                    and node.get("class_type") == "VAEDecode"]
        if (saves or decoders) and (len(saves) != 1 or len(decoders) != 1):
            raise LocalGenerationError("直接生图需要唯一的 SaveImage 和 VAEDecode")
        if not saves and any(key != "19" and node.get("class_type") == "KSampler"
                             for key, node in workflow.items() if isinstance(node, dict)):
            raise LocalGenerationError("多段工作流缺少输出节点，不能安全裁剪为直接生图")
        if saves:
            decoder = decoders[0]
            decoder["inputs"]["samples"] = ["19", 0]
            # Prune nodes no longer reachable from the output. A custom
            # single-pass template without output nodes remains valid.
            reachable: set[str] = set()
            def visit(node_id: str) -> None:
                if node_id in reachable or node_id not in workflow:
                    return
                reachable.add(node_id)
                for value in workflow[node_id].get("inputs", {}).values():
                    if isinstance(value, list) and len(value) == 2 and str(value[0]) in workflow:
                        visit(str(value[0]))
            for key, node in workflow.items():
                if node is saves[0]:
                    visit(key)
            workflow = {key: node for key, node in workflow.items() if key in reachable}
    seed = secrets.randbelow(2**63 - 1)
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = seed
    for key, value in (("steps", payload.steps), ("cfg", payload.cfg),
                       ("scheduler", payload.scheduler), ("sampler_name", payload.sampler)):
        if workflow_snapshot is None and value not in (None, "", "original"):
            if key == "sampler_name":
                value = {"2m": "dpmpp_2m", "2m_sde": "dpmpp_2m_sde",
                         "2m_sde_gpu": "dpmpp_2m_sde_gpu"}.get(value, value)
            sampler[key] = value
            if key in {"cfg", "scheduler", "sampler_name"}:
                for node in workflow.values():
                    if isinstance(node, dict) and node.get("class_type") == "KSampler":
                        node["inputs"][key] = value
    # Remove template-baked LoRAs so an unselected preset never leaks into a run.
    lora_nodes = {key for key, node in workflow.items()
                  if isinstance(node, dict) and node.get("class_type") == "LoraLoader"}
    consumers: list[tuple[dict[str, Any], str, int]] = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        for key, link in list(inputs.items()):
            if isinstance(link, list) and len(link) == 2 and str(link[0]) in lora_nodes:
                if link[1] not in (0, 1):
                    raise LocalGenerationError("工作流 LoRA 输出端口无效")
                consumers.append((inputs, key, int(link[1])))
                inputs[key] = _base_link(workflow, link, int(link[1]))
    for node_id in lora_nodes:
        del workflow[node_id]
    model_base = _base_link(workflow, sampler["model"], 0)
    clip_base = _base_link(workflow, positive["clip"], 1)
    model_tail, clip_tail = model_base, clip_base
    if len(loras) > 16:
        raise LocalGenerationError("单次最多使用 16 个 LoRA")
    original_nodes = tuple(workflow.values())
    for index, raw in enumerate(loras):
        if not isinstance(raw, dict):
            raise LocalGenerationError("LoRA 预设条目无效")
        name = _lora_name(settings, raw)
        node_id = str(990000 + index)
        if node_id in workflow:
            raise LocalGenerationError(f"本机 LoRA 节点冲突：{node_id}")
        model_strength = float(raw.get("strength_model", 1.0))
        clip_strength = float(raw.get("strength_clip", model_strength))
        if not all(-5 <= value <= 5 for value in (model_strength, clip_strength)):
            raise LocalGenerationError("LoRA 强度必须在 -5 到 5 之间")
        workflow[node_id] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": name,
            "strength_model": model_strength,
            "strength_clip": clip_strength,
            "model": model_tail, "clip": clip_tail}}
        model_tail, clip_tail = [node_id, 0], [node_id, 1]
    if loras:
        for inputs, key, port in consumers:
            inputs[key] = list(model_tail if port == 0 else clip_tail)
        # Also support templates with no baked LoRA nodes.
        for node in original_nodes:
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, link in list(inputs.items()):
                if key == "model" and link == model_base:
                    inputs[key] = list(model_tail)
                elif key == "clip" and link == clip_base:
                    inputs[key] = list(clip_tail)
    return workflow, seed, final_prompt
