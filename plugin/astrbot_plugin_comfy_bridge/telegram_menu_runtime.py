"""Telegram reply-keyboard menu state; no second Telegram update consumer."""
from __future__ import annotations

import time
from dataclasses import dataclass


LAUNCH = "🎨 生图菜单"
CONFIRM = "✅ 确认提交"
EDIT = "✏️ 修改补充"
CANCEL = "❌ 取消"
SKIP = "⏭ 不补充"
BACK = "↩️ 返回模式"

# Reply-keyboard buttons arrive through AstrBot's ordinary message handler.
MODES = {
    "🖌 普通生图": ("aimg", "text", True),
    "✨ HQ 生图": ("ahq", "text", True),
    "🌏 中文生图": ("aicn", "text", True),
    "🎲 抽一抽": ("aimg_random", "text", False),
    "🎰 五连抽": ("aimg_random5", "text", False),
    "🌀 混沌时刻": ("aimg_chaos", "text", False),
    "🌀 混沌五连": ("aimg_chaos5", "text", False),
    "📷 反推生图": ("aip", "image", False),
    "🛠 修图放大": ("arefine", "image", False),
    "🔁 重跑一张": ("aremake", "job", False),
    "📝 抄一抄": ("acopy", "image", False),
    "👥 多人图": ("amulti", "text", True),
    "🎨 画风对比": ("apalette", "text", True),
}


@dataclass
class Draft:
    mode: str
    stage: str
    created: float
    body: str = ""
    image_path: str = ""
    selected_job: tuple | None = None
    prompt_message_id: str = ""

    def expired(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) - self.created > 600


def mode_rows() -> list[list[str]]:
    labels = list(MODES)
    return [labels[index:index + 2] for index in range(0, len(labels), 2)] + [[CANCEL]]


def draft_key(event) -> tuple[str, str]:
    return str(event.get_session_id()), str(event.get_sender_id())


def group_message(event) -> bool:
    origin = str(getattr(event, "unified_msg_origin", ""))
    return ":GroupMessage:" in origin or ":ChannelMessage:" in origin


def reply_to_id(event) -> str:
    for component in event.get_messages():
        if component.__class__.__name__ == "Reply":
            return str(getattr(component, "id", "") or "")
    return ""


def message_id(event) -> str:
    return str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")


def message_text(event) -> str:
    text = str(event.message_str or "").strip()
    # AstrBot prefixes group replies to the bot with "/@BotName ".
    bot_name = str(getattr(getattr(event, "message_obj", None), "self_id", "") or "")
    prefix = f"/@{bot_name} " if bot_name else ""
    if group_message(event) and prefix and text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


def chat_and_thread(event) -> tuple[int | str, int | None]:
    session = str(event.get_session_id())
    chat, _, topic = session.partition("#")
    if not chat or not chat.lstrip("-").isdigit():
        raise ValueError("无法识别 Telegram 会话地址")
    return int(chat), int(topic) if topic.isdigit() else None
