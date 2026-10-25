"""Shared bounded identifiers, never interpolated as free-form prompt text."""
import re


def normalize_group_ids(values: list[str]) -> list[str]:
    if len(values) > 16:
        raise ValueError('最多选择16个自定义分组')
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError('自定义分组ID必须是文本')
        value = value.strip().casefold()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value):
            raise ValueError('自定义分组ID须为字母、数字、_或-，不能含指令或空白')
        if value not in result:
            result.append(value)
    return result
