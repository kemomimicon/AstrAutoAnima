"""Resolve standard LoRA loader names against the target ComfyUI, never local OS."""
from __future__ import annotations

import asyncio
import copy
from typing import Any

from .workflow_runtime import WorkflowError

LORA_LOADERS = frozenset({"LoraLoader", "LoraLoaderModelOnly"})


def match_lora_name(value: str, choices: list[str], *, node_id: str) -> str:
    # Exact spelling always wins (including legitimate POSIX backslashes).
    if value in choices:
        return value
    normalized = value.replace("\\", "/")
    matches = list(dict.fromkeys(name for name in choices
                                 if name.replace("\\", "/") == normalized))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise WorkflowError(
            f"LoRA 名称存在路径分隔符歧义（节点 {node_id}）：{value!r}；"
            "请从目标 ComfyUI 的 LoRA 列表复制完整原名，不会自动猜选模型。"
        )
    raise WorkflowError(
        f"目标 ComfyUI 未列出 LoRA（节点 {node_id}）：{value!r}。"
        f"已核对该节点的 {len(choices)} 个可选名称；"
        "请检查目标实例、完整相对路径与大小写，或刷新模型列表。"
        "不会删除目录前缀、按同名文件猜选或静默跳过 LoRA。"
    )


async def prepare_lora_workflow(session, workflow: dict[str, Any], base_url: str,
                                read_response) -> dict[str, Any]:
    references = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        kind = node.get("class_type")
        if not isinstance(kind, str) or kind not in LORA_LOADERS:
            continue
        inputs = node.get("inputs")
        value = inputs.get("lora_name") if isinstance(inputs, dict) else None
        # Linked STRING inputs and third-party loaders remain ComfyUI's responsibility.
        if isinstance(value, str):
            references.append((node_id, node["class_type"], value))
    if not references:
        return workflow

    catalogs = {}
    for class_type in dict.fromkeys(kind for _, kind, _ in references):
        async def fetch():
            async with session.get(
                f"{base_url.rstrip('/')}/object_info/{class_type}",
                allow_redirects=False,
            ) as response:
                return await read_response(response)
        try:
            info = await asyncio.wait_for(fetch(), timeout=15)
        except asyncio.TimeoutError as exc:
            raise WorkflowError("获取目标 ComfyUI LoRA 列表超时（15 秒），尚未提交生图任务。") from exc
        except Exception as exc:
            raise WorkflowError(f"获取目标 ComfyUI LoRA 列表失败，尚未提交生图任务：{exc}") from exc
        try:
            choices = info[class_type]["input"]["required"]["lora_name"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise WorkflowError(f"目标 ComfyUI 的 {class_type} 未返回有效 LoRA 枚举，尚未提交任务。") from exc
        if not isinstance(choices, list) or any(not isinstance(name, str) for name in choices):
            raise WorkflowError(f"目标 ComfyUI 的 {class_type} LoRA 枚举格式异常，尚未提交任务。")
        catalogs[class_type] = choices

    # Stage every resolution before editing anything: a partial match must not mutate
    # a reusable workflow, presets or a replay job. No process-wide cache: additions
    # and remote server switches are reflected on the next submission.
    names = [(node_id, match_lora_name(value, catalogs[kind], node_id=str(node_id)))
             for node_id, kind, value in references]
    prepared = copy.deepcopy(workflow)
    for node_id, name in names:
        prepared[node_id]["inputs"]["lora_name"] = name
    return prepared
