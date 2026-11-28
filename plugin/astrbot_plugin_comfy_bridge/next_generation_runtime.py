"""Additive Anima generation modes. No configuration writes or model downloads."""
from __future__ import annotations
import copy
from pathlib import Path

from .workflow_runtime import WorkflowError
from .preset_runtime import select_character_variant, apply_lora_plan

TURBO = "turbo_txt2img_anima_v1"
SNAPREF = "snapref_anima_v1"


def ref_mode(body):
    fields = body.split(maxsplit=1)
    if fields and fields[0] in {"style", "画风"}:
        raise WorkflowError("本版暂不提供纯画风参考 style；可用 /aref 全部参考，或 /aref char 画风=名称")
    modes = {"角色": "char", "char": "char", "角色画风": "cs", "cs": "cs", "all": "cs", "全部": "cs"}
    if fields and fields[0] in modes:
        return (fields[1] if len(fields) == 2 else ""), modes[fields[0]]
    return body, "auto"


def resolve_reference_mode(mode, options):
    if mode == "auto":
        return "char" if options.get("style") else "cs"
    if mode not in {"char", "cs"}:
        raise WorkflowError("参考模式应为 char 或 cs（全部参考）")
    return mode


def set_reference(workflow, mapping, image_name, mode):
    if mode not in {"char", "cs"}:
        raise WorkflowError("参考模式只能是 char（角色）或 cs（角色画风）")
    image = workflow.get(mapping.get("image", "1"), {})
    node = workflow.get(mapping.get("reference", "60"), {})
    if image.get("class_type") != "LoadImage" or node.get("class_type") != "SnapRef":
        raise WorkflowError("/aref 工作流必须含 LoadImage 和 SnapRef Advanced 节点")
    if not str(node.get("inputs", {}).get("adapter", "")).strip():
        raise WorkflowError("请在 SnapRef 工作流选择参考适配器权重")
    image["inputs"]["image"] = image_name
    node["inputs"]["mode"] = mode


def replay_reference(store, parent, workflow):
    """Return the recorded source and exact graph binding for a fresh upload."""
    from .job_runtime import sha256_file
    asset = store.get_asset(str(parent.get("input", {}).get("image_asset_id") or ""))
    path = Path(str(asset.get("path", "")))
    if asset.get("type") != "source" or not path.is_file() or sha256_file(path) != asset.get("sha256"):
        raise WorkflowError("SnapRef 原始参考图片已失效或变化，请重新提供参考图")
    nodes = [(ident, node) for ident, node in workflow.items() if node.get("class_type") == "SnapRef"]
    if len(nodes) != 1:
        raise WorkflowError("SnapRef 快照缺少唯一参考节点")
    ident, node = nodes[0]
    link = node.get("inputs", {}).get("image")
    if not isinstance(link, list) or len(link) != 2 or link[1] != 0 or workflow.get(str(link[0]), {}).get("class_type") != "LoadImage":
        raise WorkflowError("SnapRef 快照参考图接线不完整")
    return str(path), {"reference": ident, "image": str(link[0])}, node["inputs"]["mode"]


def _fragment(*parts):
    value = ", ".join(str(p).strip(" ,，.。\r\n\t") for p in parts if str(p).strip(" ,，.。\r\n\t"))
    return value + "." if value else ""


def render_preset_scene(scene, presets, feature_root):
    """Resolve explicit preset names only; keep each role's snapshot and LoRA."""
    from .duo_profile_runtime import validate_profile, _feature_fragments, _no_redirects, read_json, LabError, _lora
    try:
        index_path = _no_redirects(Path(feature_root) / "catalog.json")
        catalog = read_json(index_path)[0] if index_path.is_file() else {"items": []}
        if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
            raise LabError("角色画廊目录格式错误")
    except (LabError, OSError) as exc:
        raise WorkflowError(str(exc)) from exc
    snapshots, paragraphs, loras = [], [], []
    for person in scene["people"]:
        name, sep, variant = person["name"].partition("::")
        raw = presets.get("characters", {}).get(name)
        if not isinstance(raw, dict):
            raise WorkflowError(f"角色预设不存在：{name}；用 名称::造型ID 选择造型")
        char = select_character_variant(raw, variant if sep else "default")
        base = char.get("prompt", "")
        profile_id, profile = "", None
        # Files are keyed by an opaque ID; index links exact preset and variant.
        for item in catalog["items"]:
            if not isinstance(item, dict):
                raise WorkflowError("角色画廊卡片格式错误")
            if item.get("published") and item.get("character") == name and item.get("variant", "default") == (variant if sep else "default"):
                profile = item.get("profile")
                profile_id = item.get("id", "")
                break
        if profile:
            try:
                validate_profile(profile)
                source_lora = _lora(char.get("lora"))
            except LabError as exc:
                raise WorkflowError(str(exc)) from exc
            if (profile["source"]["selected_prompt"].strip() != base.strip()
                    or profile["source"]["lora"] != source_lora
                    or profile["source"]["name"] != name
                    or profile["source"]["variant_id"] != (variant if sep else "default")):
                raise WorkflowError(f"{name} 的特征档案来自旧预设，请在角色画廊重新核对后保存")
            values = {}
            for key, feature in profile["features"].items():
                if feature["text"].strip() and not feature["confirmed"]:
                    raise WorkflowError(f"{name} 的特征 {key} 未确认")
                values[key] = feature["text"]
            if profile["composition_mode"] == "curated":
                if not profile.get("identity_confirmed") or not profile["identity_text"].strip():
                    raise WorkflowError(f"{name} 的身份词未确认")
                base = profile["identity_text"]
            base = ", ".join([base, *[v for v in _feature_fragments(values) if v]])
        if not base.strip():
            raise WorkflowError(f"{name} 的固定提示词为空")
        paragraphs.append(_fragment(base, person["appearance"], person["description"]))
        if char.get("lora"):
            loras.append(copy.deepcopy(char["lora"]))
        snapshots.append({"character": name, "variant": variant or "default", "preset": copy.deepcopy(char),
                          "feature_id": profile_id, "features": copy.deepcopy(profile)})
    paragraphs.append(_fragment(f"Exactly {len(paragraphs)} people", scene["interaction"], scene["scene"]))
    return "\n\n".join(paragraphs), snapshots, loras


def validate_mode_options(kind, options):
    if kind == SNAPREF:
        if options.get("character"):
            raise WorkflowError("/aref 由参考图提供角色，不叠加角色预设；char 模式可选择画风预设")
        if resolve_reference_mode(options.get("_ref_mode", "auto"), options) != "char" and options.get("style"):
            raise WorkflowError("cs 沿用参考图画风；调用画风预设请使用 /aref char 画风=名称")
    if kind == TURBO and options.get("sampler_cfg") is not None and float(options["sampler_cfg"]) != 1:
        raise WorkflowError("Anima Turbo 请使用 CFG=1；普通 Anima 可继续使用 /aimg")


def apply_reference_style(workflow, mapping, style, options):
    """Patch MODEL/CLIP before SnapRef; keep its output connected to sampling."""
    if not style or not style.get("loras"):
        return {"style_loras": [], "character_lora": None}
    reference_id = mapping.get("reference", "60")
    node = workflow.get(reference_id, {})
    positive = mapping.get("positive", "11")
    negative = mapping.get("negative", "12")
    sampler = workflow.get(mapping.get("sampler", "19"), {}).get("inputs", {})
    if (node.get("class_type") != "SnapRef" or sampler.get("model") != [reference_id, 0]
            or node.get("inputs", {}).get("clip") != workflow.get(positive, {}).get("inputs", {}).get("clip")):
        raise WorkflowError("SnapRef 画风接线需由参考节点输出 MODEL 至采样器，并与提示词共用 CLIP")
    plan = apply_lora_plan(workflow, style=style, character=None, style_slot_ids=[],
        positive_node_id=positive, negative_node_id=negative, sampler_node_id=reference_id,
        character_node_id="910100", options=options, style_mode="dynamic",
        dynamic_style_node_id_start=910000)
    node["inputs"]["clip"] = list(workflow[positive]["inputs"]["clip"])
    return plan


def apply_explicit_loras(workflow, mapping, entries):
    from .duo_profile_runtime import _lora, LabError
    try:
        normalized = [_lora(entry) for entry in entries]
        if any(entry is None for entry in normalized) or len(normalized) > 16:
            raise LabError("最多支持 16 个有效 LoRA")
    except LabError as exc:
        raise WorkflowError(str(exc)) from exc
    model = workflow[mapping["sampler"]]["inputs"]["model"]
    clip = workflow[mapping["positive"]]["inputs"]["clip"]
    for index, entry in enumerate(normalized):
        ident = str(910000 + index)
        if ident in workflow:
            raise WorkflowError("新增 LoRA 节点 ID 与工作流冲突")
        workflow[ident] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip,
            "lora_name": entry["name"], "strength_model": entry["strength_model"], "strength_clip": entry["strength_clip"]}}
        entry["node_id"] = ident
        model, clip = [ident, 0], [ident, 1]
    workflow[mapping["sampler"]]["inputs"]["model"] = model
    for key in ("positive", "negative"):
        workflow[mapping[key]]["inputs"]["clip"] = clip
    return {"style_loras": normalized, "character_lora": None}
