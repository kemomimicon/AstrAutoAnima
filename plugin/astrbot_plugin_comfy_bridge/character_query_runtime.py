"""Read-only Chinese/English dictionary query; no generation or LLM required."""
from pathlib import Path
import re

try:
    from .character_dictionary_runtime import resolve_character
except ImportError:
    from character_dictionary_runtime import resolve_character


def character_query_text(path: Path, body: str, edits_path: Path | None = None) -> str:
    body = str(body or '').strip()
    mode = 'strong'
    suffix = re.search(r'\s+(?:模式=)?(强|弱|strong|weak)$', body, re.I)
    if suffix:
        mode = suffix.group(1).lower()
        body = body[:suffix.start()].strip()
    if not body:
        return '用法：查询角色 初音未来\n默认强模式；可用：查询角色 初音未来 弱\n也支持英文角色 tag；仅查询，不生图。'
    if len(body) > 200:
        return '角色名过长，请输入不超过 200 个字符的中文名或英文 tag。'
    match = resolve_character(path, body, mode=mode, edits_path=edits_path)
    if match is None:
        return f'角色词表未找到：{body}\n请尝试完整中文名、作品限定名或英文角色 tag；也可能已被管理员停用。'
    label = '强' if match.mode == 'strong' else '弱'
    appearance = ', '.join(match.appearance) or '未收录（强模式不会虚构外貌词）'
    return (f'角色词表查询｜{label}模式\n查询：{body}\n角色 tag：{match.tag}\n'
            f'作品 tag：{", ".join(match.copyright) or "未收录"}\n外貌词：{appearance}\n\n'
            f'可复制提示词：\n{match.prompt}\n\n仅返回词典记录，不代表模型一定能准确还原。')
