from __future__ import annotations

import copy
import json
import re
import secrets
from pathlib import Path
from typing import Any


class WorkflowError(ValueError):
    """Raised when a configured workflow cannot be used safely."""


RATIO_PRESETS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "2:3": (1024, 1536),
    "3:2": (1536, 1024),
    "3:4": (960, 1280),
    "4:3": (1280, 960),
    "9:16": (864, 1536),
    "16:9": (1536, 864),
}


def extract_command_body(
    message: str, parsed_value: str = "", command: str = "aimg"
) -> str:
    """Extract every character after a command, including spaces and newlines."""

    raw = str(message or "").strip()
    candidate = ""
    aliases = {'aremake': ('重跑一张',), 'aecho': ('看看串',), 'astyle': ('查看画风',),
               'acopy': ('抄一抄',), 'awatermark': ('打上水印',),
               'apalette': ('随机画风调色盘', '随机画风'),
               'ahelp': ('跑图帮助', '跑图指令', '跑图格式'), 'amulti': ('多人图',),
               'aimg_random': ('抽一抽',), 'aimg_random5': ('五连抽',),
               'aimg_chaos': ('混沌时刻',), 'aimg_chaos5': ('混沌五连',),
               'afavorite': ('收藏提示词', '收藏'), 'aunfavorite': ('取消收藏',),
               'areport': ('举报图片', '举报'), 'agallery': ('查看画廊', '画风画廊', '画廊')}
    names = (command, *aliases.get(command, ()))
    command_names = tuple(value for name in names for value in (f'/{name}', name))

    for command_name in command_names:
        if raw == command_name:
            candidate = ""
            break
        if raw.startswith(command_name) and len(raw) > len(command_name):
            next_character = raw[len(command_name)]
            if next_character.isspace():
                candidate = raw[len(command_name) :].lstrip()
                break
    else:
        candidate = raw

    if not candidate:
        candidate = str(parsed_value or "").strip()

    return candidate.strip()


def extract_command_prompt(
    message: str, parsed_prompt: str = "", command: str = "aimg"
) -> str:
    """Extract a full prompt and remove the old Anima compatibility token."""

    candidate = extract_command_body(message, parsed_prompt, command)

    compatibility_token = "无优化"
    if candidate == compatibility_token:
        candidate = ""
    elif candidate.startswith(compatibility_token):
        boundary = candidate[len(compatibility_token) : len(compatibility_token) + 1]
        if boundary and boundary.isspace():
            candidate = candidate[len(compatibility_token) :].lstrip()

    return candidate.strip()


def load_api_workflow(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise WorkflowError(f"工作流文件不存在：{path}")

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            workflow = json.load(file)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"工作流 JSON 无效：{exc}") from exc
    except OSError as exc:
        raise WorkflowError(f"无法读取工作流：{exc}") from exc

    if not isinstance(workflow, dict) or not workflow:
        raise WorkflowError("API 工作流必须是非空 JSON 对象。")
    if "nodes" in workflow or "links" in workflow:
        raise WorkflowError(
            "检测到普通界面工作流；请使用 ComfyUI 的 Save (API Format) 重新导出。"
        )

    invalid = [
        node_id
        for node_id, node in workflow.items()
        if not isinstance(node, dict)
        or not isinstance(node.get("class_type"), str)
        or not isinstance(node.get("inputs"), dict)
    ]
    if invalid:
        preview = ", ".join(map(str, invalid[:5]))
        raise WorkflowError(f"以下节点不是有效 API 节点：{preview}")

    return workflow


def _require_input(
    workflow: dict[str, Any], node_id: str, input_name: str
) -> dict[str, Any]:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        raise WorkflowError(f"找不到节点 ID：{node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict) or input_name not in inputs:
        raise WorkflowError(f"节点 {node_id} 缺少 inputs.{input_name}")
    return inputs


def build_prompt_text(prefix: str, prompt: str, suffix: str) -> str:
    return ", ".join(
        part.strip(" ,\n\t")
        for part in (prefix, prompt, suffix)
        if str(part or "").strip(" ,\n\t")
    )


def resolve_canvas_size(
    options: dict[str, Any],
    *,
    default_width: int = 1024,
    default_height: int = 1536,
    max_pixels: int = 2_359_296,
) -> tuple[int, int]:
    width = options.get("width")
    height = options.get("height")
    size = str(options.get("size", "")).strip().lower().replace("×", "x")
    ratio = str(options.get("ratio", "")).strip().replace("：", ":")

    if size:
        match = re.fullmatch(r"(\d+)\s*[x*]\s*(\d+)", size)
        if not match:
            raise WorkflowError("尺寸格式应为 尺寸=宽x高，例如 尺寸=1024x1536。")
        width, height = int(match.group(1)), int(match.group(2))
    elif ratio:
        if ratio not in RATIO_PRESETS:
            supported = "、".join(RATIO_PRESETS)
            raise WorkflowError(f"不支持比例={ratio}；可用比例：{supported}。")
        width, height = RATIO_PRESETS[ratio]

    width = int(width if width is not None else default_width)
    height = int(height if height is not None else default_height)
    if not (512 <= width <= 2048 and 512 <= height <= 2048):
        raise WorkflowError("画布宽高必须在 512 到 2048 之间。")
    if width % 32 or height % 32:
        raise WorkflowError("画布宽高必须是 32 的倍数。")
    if width * height > max_pixels:
        raise WorkflowError(f"画布像素超过上限 {max_pixels}，请降低宽高。")
    return width, height


def prepare_workflow(
    template: dict[str, Any],
    *,
    prompt: str,
    positive_node_id: str,
    negative_node_id: str = "",
    negative_prompt: str = "",
    positive_prefix: str = "",
    positive_suffix: str = "",
    sampler_node_id: str = "",
    randomize_seed: bool = True,
    fixed_seed: int = 0,
    sampler_overrides: dict[str, Any] | None = None,
    latent_node_id: str = "",
    width: int | None = None,
    height: int | None = None,
) -> tuple[dict[str, Any], int | None]:
    if not str(prompt or "").strip():
        raise WorkflowError("提示词不能为空。")

    workflow = copy.deepcopy(template)
    positive_inputs = _require_input(workflow, positive_node_id, "text")
    positive_inputs["text"] = build_prompt_text(
        positive_prefix, prompt, positive_suffix
    )

    if negative_node_id and negative_prompt.strip():
        negative_inputs = _require_input(workflow, negative_node_id, "text")
        negative_inputs["text"] = negative_prompt.strip()

    seed: int | None = None
    if sampler_node_id:
        sampler_inputs = _require_input(workflow, sampler_node_id, "seed")
        if randomize_seed:
            seed = secrets.randbelow(2**63 - 1)
        else:
            seed = int(fixed_seed)
        sampler_inputs["seed"] = seed
        overrides = dict(sampler_overrides or {})
        if overrides:
            supported = {"steps", "cfg", "sampler_name", "scheduler", "denoise"}
            invalid = sorted(set(overrides) - supported)
            if invalid:
                raise WorkflowError(
                    f"不支持的采样器覆盖字段：{', '.join(invalid)}"
                )
            for key in overrides:
                if key not in sampler_inputs:
                    raise WorkflowError(f"采样器节点 {sampler_node_id} 缺少 inputs.{key}")
            if "steps" in overrides:
                steps = int(overrides["steps"])
                if not 1 <= steps <= 200:
                    raise WorkflowError("采样步数必须在 1 到 200 之间。")
                sampler_inputs["steps"] = steps
            if "cfg" in overrides:
                cfg = float(overrides["cfg"])
                if not 0.0 <= cfg <= 30.0:
                    raise WorkflowError("CFG 必须在 0 到 30 之间。")
                sampler_inputs["cfg"] = cfg
            for key in ("sampler_name", "scheduler"):
                if key in overrides:
                    value = str(overrides[key]).strip()
                    if not value:
                        raise WorkflowError(f"采样器覆盖字段 {key} 不能为空。")
                    sampler_inputs[key] = value
            if "denoise" in overrides:
                denoise = float(overrides["denoise"])
                if not 0.0 <= denoise <= 1.0:
                    raise WorkflowError("denoise 必须在 0 到 1 之间。")
                sampler_inputs["denoise"] = denoise

    if latent_node_id and width is not None and height is not None:
        latent_inputs = _require_input(workflow, latent_node_id, "width")
        if "height" not in latent_inputs:
            raise WorkflowError(f"节点 {latent_node_id} 缺少 inputs.height")
        latent_inputs["width"] = int(width)
        latent_inputs["height"] = int(height)

    return workflow, seed


def prepare_prompt_batch_workflow(
    workflow: dict[str, Any],
    *,
    positive_node_id: str,
    latent_node_id: str,
    prompts: list[str],
    max_batch: int = 8,
) -> dict[str, Any]:
    clean_prompts = [str(prompt or "").strip() for prompt in prompts]
    if not clean_prompts or any(not prompt for prompt in clean_prompts):
        raise WorkflowError("批量提示词必须包含至少一条非空提示词。")
    if len(clean_prompts) > max(1, int(max_batch)):
        raise WorkflowError(
            f"批量提示词数量 {len(clean_prompts)} 超过上限 {max_batch}。"
        )

    positive = workflow.get(str(positive_node_id))
    if not isinstance(positive, dict):
        raise WorkflowError(f"找不到批量正面提示词节点：{positive_node_id}")
    positive_inputs = positive.get("inputs")
    if not isinstance(positive_inputs, dict) or not isinstance(
        positive_inputs.get("clip"), list
    ):
        raise WorkflowError(f"节点 {positive_node_id} 缺少 inputs.clip 连接。")

    latent_inputs = _require_input(workflow, latent_node_id, "batch_size")
    latent_inputs["batch_size"] = len(clean_prompts)
    workflow[str(positive_node_id)] = {
        "class_type": "AnimaPromptBatchEncode",
        "inputs": {
            "clip": list(positive_inputs["clip"]),
            "prompts_json": json.dumps(clean_prompts, ensure_ascii=False),
        },
        "_meta": {"title": "AstrAutoAnima 微批提示词编码"},
    }
    return workflow


def configure_sampler(
    workflow: dict[str, Any],
    node_id: str,
    overrides: dict[str, Any],
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """Apply validated sampling values to one KSampler-compatible node."""

    inputs = _require_input(workflow, node_id, "seed")
    supported = {"steps", "cfg", "sampler_name", "scheduler", "denoise"}
    invalid = sorted(set(overrides) - supported)
    if invalid:
        raise WorkflowError(f"不支持的采样器覆盖字段：{', '.join(invalid)}")
    for key in overrides:
        if key not in inputs:
            raise WorkflowError(f"采样器节点 {node_id} 缺少 inputs.{key}")
    if seed is not None:
        inputs["seed"] = int(seed)
    if "steps" in overrides:
        value = int(overrides["steps"])
        if not 1 <= value <= 200:
            raise WorkflowError("采样步数必须在 1 到 200 之间。")
        inputs["steps"] = value
    if "cfg" in overrides:
        value = float(overrides["cfg"])
        if not 0.0 <= value <= 30.0:
            raise WorkflowError("CFG 必须在 0 到 30 之间。")
        inputs["cfg"] = value
    for key in ("sampler_name", "scheduler"):
        if key in overrides:
            value = str(overrides[key]).strip()
            if not value:
                raise WorkflowError(f"采样器覆盖字段 {key} 不能为空。")
            inputs[key] = value
    if "denoise" in overrides:
        value = float(overrides["denoise"])
        if not 0.0 <= value <= 1.0:
            raise WorkflowError("denoise 必须在 0 到 1 之间。")
        inputs["denoise"] = value
    return inputs


def configure_hq_workflow(
    workflow: dict[str, Any],
    *,
    sampler_node_id: str,
    upscale_node_id: str,
    refiner_sampler_node_id: str,
    profile: dict[str, Any],
    seed: int,
    scale_override: float | None = None,
    denoise_override: float | None = None,
) -> dict[str, Any]:
    """Configure the second-stage latent upscale/refine path after LoRA injection."""

    sampling = profile.get("sampling", {})
    enhance = profile.get("enhance", {})
    if not isinstance(sampling, dict) or not isinstance(enhance, dict):
        raise WorkflowError("HQ profile 的 sampling/enhance 必须是对象。")
    primary_inputs = configure_sampler(workflow, sampler_node_id, sampling, seed=seed)
    refiner_overrides = {
        key: enhance[key]
        for key in ("steps", "cfg", "sampler_name", "scheduler", "denoise")
        if key in enhance
    }
    if denoise_override is not None:
        refiner_overrides["denoise"] = float(denoise_override)
    refiner_inputs = configure_sampler(
        workflow,
        refiner_sampler_node_id,
        refiner_overrides,
        seed=seed,
    )
    for key in ("model", "positive", "negative"):
        if key not in primary_inputs or key not in refiner_inputs:
            raise WorkflowError(
                f"HQ 采样器节点缺少用于同步的 inputs.{key}。"
            )
        refiner_inputs[key] = copy.deepcopy(primary_inputs[key])

    upscale_inputs = _require_input(workflow, upscale_node_id, "scale_by")
    scale = float(
        scale_override if scale_override is not None else enhance.get("scale", 1.25)
    )
    if not 1.0 <= scale <= 2.0:
        raise WorkflowError("HQ scale 必须在 1.0 到 2.0 之间。")
    upscale_inputs["scale_by"] = scale
    return {
        "scale": scale,
        "sampling": copy.deepcopy(primary_inputs),
        "refiner_sampling": copy.deepcopy(refiner_inputs),
    }


def configure_refine_workflow(
    workflow: dict[str, Any],
    *,
    image_name: str,
    image_node_id: str,
    upscale_node_id: str,
    sampler_node_id: str,
    profile: dict[str, Any],
    seed: int,
    scale_override: float | None = None,
    denoise_override: float | None = None,
) -> dict[str, Any]:
    """Inject an uploaded source image and a Light/Medium refine profile."""

    normalized_image = str(image_name or "").strip()
    if not normalized_image:
        raise WorkflowError("INVALID_INPUT：精修输入图片不能为空。")
    image_inputs = _require_input(workflow, image_node_id, "image")
    image_inputs["image"] = normalized_image

    sampling = profile.get("sampling", {})
    enhance = profile.get("enhance", {})
    if not isinstance(sampling, dict) or not isinstance(enhance, dict):
        raise WorkflowError("Refine profile 的 sampling/enhance 必须是对象。")
    overrides = dict(sampling)
    if denoise_override is not None:
        overrides["denoise"] = float(denoise_override)
    sampler_inputs = configure_sampler(workflow, sampler_node_id, overrides, seed=seed)

    upscale_inputs = _require_input(workflow, upscale_node_id, "scale_by")
    scale = float(
        scale_override if scale_override is not None else enhance.get("scale", 1.25)
    )
    if not 1.0 <= scale <= 2.0:
        raise WorkflowError("Refine scale 必须在 1.0 到 2.0 之间。")
    upscale_inputs["scale_by"] = scale
    return {
        "scale": scale,
        "sampling": copy.deepcopy(sampler_inputs),
        "metadata_restore": "pending",
    }


def configure_detail_repair_workflow(
    workflow: dict[str, Any],
    *,
    image_name: str,
    image_node_id: str,
    output_node_id: str,
    positive_node_id: str,
    negative_node_id: str,
    face_node_id: str,
    hand_node_id: str,
    foot_node_id: str,
    profile: dict[str, Any],
    seed: int,
    repair_face: bool,
    repair_hands: bool,
    repair_feet: bool,
    face_detector_name: str = "bbox/face_yolov8n.pt",
    hand_detector_name: str = "bbox/hand_yolov8s.pt",
    foot_detector_name: str = "bbox/foot_yolov8x.pt",
) -> dict[str, Any]:
    """Configure a sequential Impact-Pack repair pass over an uploaded image."""

    normalized_image = str(image_name or "").strip()
    if not normalized_image:
        raise WorkflowError("INVALID_INPUT：局部修复输入图片不能为空。")
    _require_input(workflow, image_node_id, "image")["image"] = normalized_image

    requested = {
        "face": bool(repair_face),
        "hands": bool(repair_hands),
        "feet": bool(repair_feet),
    }
    if not any(requested.values()):
        raise WorkflowError("局部修复至少需要启用脸、手或脚中的一项。")

    node_ids = {
        "face": str(face_node_id),
        "hands": str(hand_node_id),
        "feet": str(foot_node_id),
    }
    detector_ids = {"face": "50", "hands": "60", "feet": "70"}
    detector_names = {
        "face": str(face_detector_name).strip(),
        "hands": str(hand_detector_name).strip(),
        "feet": str(foot_detector_name).strip(),
    }
    detailer_profile = profile.get("detailer", {})
    if not isinstance(detailer_profile, dict):
        raise WorkflowError("局部修复 profile.detailer 必须是对象。")

    positive_ref = [str(positive_node_id), 0]
    negative_ref = [str(negative_node_id), 0]
    # apply_lora_plan rewires the first detailer's model and the prompt encoders'
    # CLIP.  Capture those references, then synchronize every enabled pass.
    anchor = _require_input(workflow, face_node_id, "model")
    model_ref = copy.deepcopy(anchor["model"])
    clip_ref = copy.deepcopy(
        _require_input(workflow, positive_node_id, "clip")["clip"]
    )
    vae_ref = copy.deepcopy(anchor.get("vae"))
    if not isinstance(model_ref, list) or not isinstance(clip_ref, list):
        raise WorkflowError("局部修复无法定位 MODEL/CLIP 接入点。")

    source: list[Any] = [str(image_node_id), 0]
    applied: list[dict[str, Any]] = []
    for offset, part in enumerate(("face", "hands", "feet")):
        node_id = node_ids[part]
        if not requested[part]:
            workflow.pop(node_id, None)
            continue
        detector = _require_input(workflow, detector_ids[part], "model_name")
        if not detector_names[part]:
            raise WorkflowError(f"{part} 检测模型文件名不能为空。")
        detector["model_name"] = detector_names[part]
        inputs = _require_input(workflow, node_id, "image")
        inputs["image"] = copy.deepcopy(source)
        inputs["model"] = copy.deepcopy(model_ref)
        inputs["clip"] = copy.deepcopy(clip_ref)
        if vae_ref is not None:
            inputs["vae"] = copy.deepcopy(vae_ref)
        inputs["positive"] = copy.deepcopy(positive_ref)
        inputs["negative"] = copy.deepcopy(negative_ref)
        inputs["bbox_detector"] = [detector_ids[part], 0]
        inputs["seed"] = (int(seed) + offset) % (2**32)
        overrides = detailer_profile.get(part, {})
        if not isinstance(overrides, dict):
            raise WorkflowError(f"局部修复 {part} 参数必须是对象。")
        for key in (
            "guide_size",
            "max_size",
            "steps",
            "cfg",
            "sampler_name",
            "scheduler",
            "denoise",
            "bbox_threshold",
            "bbox_dilation",
            "bbox_crop_factor",
            "wildcard",
        ):
            if key in overrides:
                inputs[key] = copy.deepcopy(overrides[key])
        source = [node_id, 0]
        applied.append(
            {
                "part": part,
                "node_id": node_id,
                "detector": detector_names[part],
                "denoise": inputs.get("denoise"),
                "steps": inputs.get("steps"),
            }
        )

    _require_input(workflow, output_node_id, "images")["images"] = source
    return {"detailer": applied, "output": source, "seed": int(seed) % (2**32)}


def configure_seedvr2_workflow(
    workflow: dict[str, Any],
    *,
    image_name: str,
    image_node_id: str,
    upscaler_node_id: str,
    profile: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Inject a bounded native or legacy tiled SeedVR2 profile."""

    normalized_image = str(image_name or "").strip()
    if not normalized_image:
        raise WorkflowError("INVALID_INPUT：SeedVR2 输入图片不能为空。")
    image_inputs = _require_input(workflow, image_node_id, "image")
    image_inputs["image"] = normalized_image
    if workflow.get(str(upscaler_node_id), {}).get("class_type") == "SeedVR2VideoUpscaler":
        inputs = _require_input(workflow, upscaler_node_id, "resolution")
        required = {"seed", "max_resolution", "batch_size", "uniform_batch_size", "color_correction"}
        missing = sorted(required - set(inputs))
        if missing:
            raise WorkflowError(f"SeedVR2 原生节点缺少 inputs：{', '.join(missing)}")
        enhance = profile.get("enhance", {})
        if not isinstance(enhance, dict):
            raise WorkflowError("SeedVR2 profile.enhance 必须是对象。")
        target = int(enhance.get("target_resolution", inputs.get("max_resolution") or inputs["resolution"]))
        if not 512 <= target <= 8192 or target % 16:
            raise WorkflowError("SeedVR2 目标边必须是 512-8192 之间且能被 16 整除。")
        if enhance.get("resolution_target", "longest") != "longest":
            raise WorkflowError("SeedVR2 原生模式当前仅支持最长边目标。")
        color = str(enhance.get("color_correction", inputs["color_correction"]))
        if color not in {"lab", "wavelet", "wavelet_adaptive", "hsv", "adain", "none"}:
            raise WorkflowError("SeedVR2 color_correction 无效。")
        # Native resolution is the shortest-edge request; the same maximum
        # then caps BOTH dimensions proportionally to the requested longest edge.
        inputs.update(resolution=target, max_resolution=target,
                      seed=int(seed) % (2**32), batch_size=1,
                      uniform_batch_size=False, color_correction=color)
        return {"target_resolution": target, "seed": inputs["seed"],
                "mode": "native", "tile": False,
                "resolution": target, "max_resolution": target,
                "color_correction": color}
    inputs = _require_input(workflow, upscaler_node_id, "new_resolution")
    required = {
        "seed",
        "tile_width",
        "tile_height",
        "mask_blur",
        "tile_padding",
        "tile_upscale_resolution",
        "tiling_strategy",
        "anti_aliasing_strength",
        "blending_method",
        "color_correction",
        "resolution_target",
        "tile_batch_size",
    }
    missing = sorted(required - set(inputs))
    if missing:
        raise WorkflowError(
            f"SeedVR2 节点 {upscaler_node_id} 缺少 inputs：{', '.join(missing)}"
        )
    enhance = profile.get("enhance", {})
    if not isinstance(enhance, dict):
        raise WorkflowError("SeedVR2 profile.enhance 必须是对象。")
    target = int(enhance.get("target_resolution", inputs["new_resolution"]))
    if not 512 <= target <= 8192 or target % 16:
        raise WorkflowError("SeedVR2 目标边必须是 512-8192 之间且能被 16 整除。")
    integer_ranges = {
        "tile_width": (256, 2048),
        "tile_height": (256, 2048),
        "mask_blur": (0, 64),
        "tile_padding": (0, 256),
        "tile_upscale_resolution": (512, 4096),
        "tile_batch_size": (1, 21),
    }
    inputs["seed"] = int(seed) % (2**32)
    inputs["new_resolution"] = target
    for name, (minimum, maximum) in integer_ranges.items():
        value = int(enhance.get(name, inputs[name]))
        if not minimum <= value <= maximum:
            raise WorkflowError(f"SeedVR2 {name} 必须在 {minimum}-{maximum} 之间。")
        inputs[name] = value
    anti_aliasing = float(
        enhance.get("anti_aliasing_strength", inputs["anti_aliasing_strength"])
    )
    if not 0.0 <= anti_aliasing <= 1.0:
        raise WorkflowError("SeedVR2 anti_aliasing_strength 必须在 0-1 之间。")
    inputs["anti_aliasing_strength"] = anti_aliasing
    for name in (
        "tiling_strategy",
        "blending_method",
        "color_correction",
        "resolution_target",
    ):
        if name in enhance:
            inputs[name] = str(enhance[name])
    return {
        "target_resolution": target,
        "seed": inputs["seed"],
        "tile_width": inputs["tile_width"],
        "tile_height": inputs["tile_height"],
        "tile_padding": inputs["tile_padding"],
        "tile_upscale_resolution": inputs["tile_upscale_resolution"],
        "blending_method": inputs["blending_method"],
    }


REVERSE_PRESETS = {"full", "scene", "action", "character", "safe", "raw", "custom"}
REVERSE_CATEGORIES = {
    "scene",
    "action",
    "character",
    "appearance",
    "special_features",
    "clothing",
    "composition",
    "other",
    "safety",
}


def prepare_reverse_workflow(
    template: dict[str, Any],
    *,
    image_name: str,
    preset: str = "full",
    categories: set[str] | list[str] | tuple[str, ...] | None = None,
    image_node_id: str = "1",
    compiler_node_id: str = "7",
    saver_node_id: str = "8",
    qq_user_id: str = "",
    session_type: str = "unknown",
    session_id: str = "",
    role_preset: str = "",
    style_preset: str = "",
    storage_root: str = "",
    save_thumbnail: bool = False,
) -> dict[str, Any]:
    """Prepare the dedicated WD/CT/JoyCaption reverse API workflow."""

    normalized_image = str(image_name or "").strip()
    if not normalized_image:
        raise WorkflowError("反推输入图片名不能为空。")

    selected_preset = str(preset or "full").strip().lower()
    if selected_preset not in REVERSE_PRESETS:
        allowed = ", ".join(sorted(REVERSE_PRESETS))
        raise WorkflowError(f"未知反推模式：{preset}；可用值：{allowed}")

    normalized_session_type = str(session_type or "unknown").strip().lower()
    if normalized_session_type not in {"unknown", "private", "group"}:
        normalized_session_type = "unknown"

    workflow = copy.deepcopy(template)
    image_inputs = _require_input(workflow, image_node_id, "image")
    compiler_inputs = _require_input(workflow, compiler_node_id, "preset")
    saver_inputs = _require_input(workflow, saver_node_id, "qq_user_id")

    image_inputs["image"] = normalized_image
    compiler_inputs["preset"] = selected_preset
    if categories is not None:
        selected_categories = {
            str(value).strip().lower() for value in categories if str(value).strip()
        }
        unknown = selected_categories - REVERSE_CATEGORIES
        if unknown:
            raise WorkflowError(
                "未知反推分类：" + ", ".join(sorted(unknown))
            )
        if not selected_categories:
            raise WorkflowError("反推分类不能为空。")
        compiler_inputs["preset"] = "custom"
        for name in REVERSE_CATEGORIES:
            compiler_inputs[f"include_{name}"] = name in selected_categories
    saver_inputs["qq_user_id"] = str(qq_user_id or "")
    saver_inputs["session_type"] = normalized_session_type
    saver_inputs["session_id"] = str(session_id or "")
    saver_inputs["role_preset"] = str(role_preset or "")
    saver_inputs["style_preset"] = str(style_preset or "")
    if str(storage_root or "").strip():
        saver_inputs["storage_root"] = str(storage_root).strip()
    saver_inputs["save_thumbnail"] = bool(save_thumbnail)
    return workflow


def _first_history_value(node_output: dict[str, Any], name: str) -> str:
    value = node_output.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def extract_reverse_result(
    history_record: dict[str, Any],
    saver_node_id: str = "8",
    *,
    allow_empty_prompt: bool = False,
) -> dict[str, Any]:
    """Read explicit reverse-result UI fields from ComfyUI history."""

    outputs = history_record.get("outputs", {})
    node_output = outputs.get(str(saver_node_id)) if isinstance(outputs, dict) else None
    if not isinstance(node_output, dict):
        raise WorkflowError(f"反推历史记录中没有保存节点 {saver_node_id} 的输出。")

    result = {
        "anima_prompt": _first_history_value(node_output, "anima_prompt"),
        "structured_json": _first_history_value(node_output, "structured_json"),
        "safety_level": _first_history_value(node_output, "safety_level") or "unknown",
        "record_path": _first_history_value(node_output, "text"),
        "reverse_id": _first_history_value(node_output, "reverse_id"),
    }
    if not result["anima_prompt"] and not allow_empty_prompt:
        raise WorkflowError(
            "反推任务已完成，但 history 中没有 anima_prompt；"
            "请确认已安装匹配版本的 AstrAutoAnima 工作流节点。"
        )
    return result


def describe_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    loras: list[dict[str, Any]] = []
    output_nodes: list[str] = []

    for node_id, node in workflow.items():
        class_type = node.get("class_type")
        inputs = node.get("inputs", {})
        if class_type == "LoraLoader":
            loras.append(
                {
                    "node_id": str(node_id),
                    "name": inputs.get("lora_name", ""),
                    "strength_model": inputs.get("strength_model"),
                    "strength_clip": inputs.get("strength_clip"),
                }
            )
        if class_type in {"SaveImage", "PreviewImage"}:
            output_nodes.append(str(node_id))

    return {
        "node_count": len(workflow),
        "lora_count": len(loras),
        "loras": loras,
        "output_nodes": output_nodes,
    }


def extract_output_images(history_record: dict[str, Any]) -> list[dict[str, str]]:
    outputs = history_record.get("outputs", {})
    if not isinstance(outputs, dict):
        return []

    images: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for image in node_output.get("images", []):
            if not isinstance(image, dict) or not image.get("filename"):
                continue
            normalized = {
                "filename": str(image["filename"]),
                "subfolder": str(image.get("subfolder", "")),
                "type": str(image.get("type", "output")),
            }
            key = (
                normalized["filename"],
                normalized["subfolder"],
                normalized["type"],
            )
            if key not in seen:
                seen.add(key)
                images.append(normalized)
    return images


def history_error(history_record: dict[str, Any]) -> str:
    status = history_record.get("status", {})
    messages = status.get("messages", []) if isinstance(status, dict) else []
    for message in reversed(messages):
        if not isinstance(message, (list, tuple)) or len(message) < 2:
            continue
        if message[0] != "execution_error":
            continue
        payload = message[1]
        if isinstance(payload, dict):
            node_id = payload.get("node_id", "?")
            node_type = payload.get("node_type", "?")
            exception = payload.get("exception_message", "未知错误")
            return f"节点 {node_id} ({node_type})：{exception}"
        return str(payload)
    return "ComfyUI 任务执行失败。"


def history_failed(history_record: dict[str, Any]) -> bool:
    """Return true as soon as ComfyUI records an execution failure.

    Failed history records commonly keep ``completed`` false, so callers must
    not wait for that flag before inspecting ``status_str`` and messages.
    """

    status = history_record.get("status", {})
    if not isinstance(status, dict):
        return False
    if str(status.get("status_str", "")).strip().lower() == "error":
        return True
    messages = status.get("messages", [])
    return any(
        isinstance(message, (list, tuple))
        and len(message) >= 1
        and message[0] == "execution_error"
        for message in messages
    )
