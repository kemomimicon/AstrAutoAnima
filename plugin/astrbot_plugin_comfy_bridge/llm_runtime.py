from __future__ import annotations

import re
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct local tests
    from workflow_runtime import WorkflowError


_CODE_FENCE = re.compile(r"^```(?:text|txt|tags|markdown)?\s*|\s*```$", re.I)
_CJK = re.compile(r"[\u3400-\u9fff]")


def clean_tag_output(value: str) -> str:
    text = str(value or "").strip()
    text = _CODE_FENCE.sub("", text).strip()
    text = re.sub(r"^(?:tags?|prompt)\s*[:：]\s*", "", text, flags=re.I)
    text = text.replace("，", ",")
    text = re.sub(r"[\r\n;；]+", ", ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    return text.strip(" ,")


def validate_english_tags(value: str, *, label: str) -> str:
    tags = clean_tag_output(value)
    if not tags:
        raise WorkflowError(f"{label}没有返回提示词。")
    if len(_CJK.findall(tags)) > 2:
        raise WorkflowError(f"{label}仍包含大量中文，请更换或检查模型。")
    return tags


async def current_text_provider_id(
    context: Any, event: Any, configured: str = ""
) -> str:
    provider_id = str(configured or "").strip()
    if provider_id:
        return provider_id
    try:
        provider_id = str(
            await context.get_current_chat_provider_id(event.unified_msg_origin) or ""
        ).strip()
    except Exception:
        provider_id = ""
    if provider_id:
        return provider_id
    try:
        config = context.get_config(umo=event.unified_msg_origin)
        settings = config.get("provider_settings", {})
        return str(settings.get("default_provider_id") or "").strip()
    except Exception:
        return ""


def image_caption_provider_id(
    context: Any, event: Any, configured: str = ""
) -> str:
    provider_id = str(configured or "").strip()
    if provider_id:
        return provider_id
    try:
        config = context.get_config(umo=event.unified_msg_origin)
        settings = config.get("provider_settings", {})
        return str(
            settings.get("default_image_caption_provider_id")
            or settings.get("default_provider_id")
            or ""
        ).strip()
    except Exception:
        return ""


async def translate_chinese_prompt(
    context: Any,
    event: Any,
    prompt: str,
    *,
    configured_provider_id: str = "",
    max_tokens: int = 700,
) -> tuple[str, str]:
    provider_id = await current_text_provider_id(
        context, event, configured_provider_id
    )
    if not provider_id:
        raise WorkflowError("未配置可用于 /aicn 的文本大模型 Provider。")
    response = await context.llm_generate(
        chat_provider_id=provider_id,
        prompt=str(prompt or "").strip(),
        system_prompt=(
            "你是 Anima 图像模型的提示词转换器。"
            "把用户中文描述转换为一行英文 Danbooru-style tags，使用英文逗号分隔。"
            "忠实保留角色、人数、服装、动作、表情、构图、环境和光影；"
            "只做必要的可视化补全，不擅自改变主题。"
            "不要输出解释、Markdown、质量词、画师词或 LoRA 语法，不要输出中文。"
        ),
        max_tokens=max(100, int(max_tokens)),
    )
    tags = validate_english_tags(
        getattr(response, "completion_text", ""), label="中文提示词转换"
    )
    return tags, provider_id


async def reverse_image_prompt(
    context: Any,
    event: Any,
    image_path: str,
    *,
    configured_provider_id: str = "",
    max_tokens: int = 700,
) -> tuple[str, str]:
    provider_id = image_caption_provider_id(
        context, event, configured_provider_id
    )
    if not provider_id:
        raise WorkflowError(
            "未配置支持识图的 Provider；请设置图片描述模型或 image_caption_provider_id。"
        )
    response = await context.llm_generate(
        chat_provider_id=provider_id,
        prompt=(
            "反推这张二次元图片的生图提示词。输出一行英文 Danbooru-style tags，"
            "用英文逗号分隔。优先描述人数、主体身份、外观、服装、动作、神态、"
            "构图、背景、光影和画风观感。不要解释，不要 Markdown，不要输出中文，"
            "不要臆造网页出处。"
        ),
        image_urls=[str(image_path)],
        max_tokens=max(100, int(max_tokens)),
    )
    tags = validate_english_tags(
        getattr(response, "completion_text", ""), label="图片反推"
    )
    return tags, provider_id
