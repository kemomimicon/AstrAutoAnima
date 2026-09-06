from __future__ import annotations

from typing import Any, Mapping

try:
    from .workflow_runtime import RATIO_PRESETS, WorkflowError
except ImportError:  # pragma: no cover - direct local tests
    from workflow_runtime import RATIO_PRESETS, WorkflowError


AGENT_QUALITY_PROFILES = {
    "quick": ("quick_txt2img_v1", ""),
    "hq_stable": ("hq_txt2img_anima_v1", "stable"),
    "hq_beauty": ("hq_txt2img_anima_v1", "beauty"),
}

AGENT_SAMPLER_PRESETS = {
    "original": "original",
    "原有": "original",
    "2m": "2m",
    "dpm_2m": "2m",
    "2m_sde": "2m_sde",
    "dpm_2m_sde": "2m_sde",
    "2m_sde_gpu": "2m_sde_gpu",
    "dpm_2m_sde_gpu": "2m_sde_gpu",
}

AGENT_SCHEDULERS = {
    "workflow",
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

_NONE_PRESET_VALUES = {"none", "off", "null", "无", "关闭", "不使用"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _preset_value(explicit: Any, configured: Any) -> str:
    value = _text(explicit)
    if not value:
        value = _text(configured)
    if value.casefold() in _NONE_PRESET_VALUES:
        return ""
    return value


def build_agent_generation_request(
    config: Mapping[str, Any],
    *,
    prompt: str,
    ratio: str = "",
    character: str = "",
    style: str = "",
    quality: str = "",
    sampler: str = "",
    scheduler: str = "",
    steps: int | float = 0,
    cfg: int | float = 0,
) -> tuple[str, dict[str, Any], str, str]:
    """Build an Agent-only generation request without changing command defaults."""

    clean_prompt = _text(prompt)
    if not clean_prompt:
        raise WorkflowError("自主绘图提示词不能为空。")
    max_chars = max(100, int(config.get("agent_tool_max_prompt_chars", 1800)))
    if len(clean_prompt) > max_chars:
        raise WorkflowError(f"自主绘图提示词超过 {max_chars} 字符限制。")

    allow_override = bool(config.get("agent_tool_allow_parameter_override", True))
    if not allow_override:
        ratio = character = style = quality = sampler = scheduler = ""
        steps = cfg = 0

    chosen_ratio = _text(ratio) or _text(
        config.get("agent_tool_default_ratio", "2:3")
    )
    chosen_ratio = chosen_ratio.replace("：", ":")
    if chosen_ratio not in RATIO_PRESETS:
        raise WorkflowError(
            "自主绘图比例无效；支持：" + "、".join(RATIO_PRESETS)
        )

    chosen_quality = (_text(quality) or _text(
        config.get("agent_tool_default_quality", "quick")
    )).casefold()
    if chosen_quality not in AGENT_QUALITY_PROFILES:
        raise WorkflowError("自主绘图质量预设只能是 quick、hq_stable 或 hq_beauty。")
    workflow_type, profile = AGENT_QUALITY_PROFILES[chosen_quality]

    requested_sampler = _text(sampler) or _text(
        config.get("agent_tool_default_sampler", "original")
    )
    sampler_key = AGENT_SAMPLER_PRESETS.get(requested_sampler.casefold())
    if sampler_key is None:
        raise WorkflowError(
            "自主绘图采样器只能是 original、2m、2m_sde 或 2m_sde_gpu。"
        )

    chosen_scheduler = (_text(scheduler) or _text(
        config.get("agent_tool_default_scheduler", "workflow")
    )).casefold()
    if chosen_scheduler not in AGENT_SCHEDULERS:
        raise WorkflowError(
            "自主绘图调度器只能是 workflow、normal、karras、exponential、"
            "sgm_uniform、simple、ddim_uniform、beta、linear_quadratic "
            "或 kl_optimal。"
        )

    chosen_steps = int(steps or int(config.get("agent_tool_default_steps", 0)))
    if chosen_steps and not 1 <= chosen_steps <= 150:
        raise WorkflowError("自主绘图步数必须在 1 到 150 之间；0 表示使用采样器预设。")
    chosen_cfg = float(cfg or float(config.get("agent_tool_default_cfg", 0)))
    if chosen_cfg and not 0.1 <= chosen_cfg <= 30:
        raise WorkflowError("自主绘图 CFG 必须在 0.1 到 30 之间；0 表示使用采样器预设。")

    options: dict[str, Any] = {
        "ratio": chosen_ratio,
        "sampler_preset": sampler_key,
    }
    if chosen_scheduler != "workflow":
        options["scheduler"] = chosen_scheduler
    chosen_character = _preset_value(
        character, config.get("agent_tool_default_character", "")
    )
    chosen_style = _preset_value(
        style, config.get("agent_tool_default_style", "")
    )
    if chosen_character:
        options["character"] = chosen_character
    if chosen_style:
        options["style"] = chosen_style
    if chosen_steps:
        options["sampler_steps"] = chosen_steps
    if chosen_cfg:
        options["sampler_cfg"] = chosen_cfg
    return clean_prompt, options, workflow_type, profile


def list_agent_presets(
    presets: Mapping[str, Any],
    *,
    category: str = "all",
    query: str = "",
    limit: int = 20,
) -> dict[str, list[str]]:
    normalized = _text(category).casefold() or "all"
    aliases = {
        "all": "all", "全部": "all",
        "character": "characters", "characters": "characters",
        "role": "characters", "角色": "characters",
        "style": "styles", "styles": "styles", "画风": "styles",
    }
    selected = aliases.get(normalized)
    if selected is None:
        raise WorkflowError("预设类型只能是 all、character 或 style。")
    safe_limit = min(50, max(1, int(limit)))
    needle = _text(query).casefold()

    result: dict[str, list[str]] = {}
    for key in ("characters", "styles"):
        if selected not in {"all", key}:
            continue
        values = presets.get(key, {})
        names = sorted(
            str(name)
            for name, value in values.items()
            if not (key == "styles" and isinstance(value, dict) and value.get("hidden"))
            if not needle or needle in str(name).casefold()
        )
        result[key] = names[:safe_limit]
    return result
