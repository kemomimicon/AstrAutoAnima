"""Base-model multi-person planning. No LoRA or model mutations here."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .workflow_runtime import WorkflowError


def parse_scene(text: str) -> dict[str, Any]:
    """A deterministic, LLM-free format: one 人物 line per identity."""
    people: list[dict[str, str]] = []
    scene: list[str] = []
    interaction: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(?:人物|角色|person)\s*([1-4A-D]?)\s*[:：]\s*(.+)$", line, re.I)
        if match:
            fields = [part.strip() for part in match.group(2).split("|")]
            if len(fields) != 3 or not fields[0]:
                raise WorkflowError("人物格式：人物1：姓名或tag | 基本外貌 | 衣着、表情、动作")
            people.append(dict(name=fields[0], appearance=fields[1], description=fields[2]))
        elif re.match(r"^(?:互动|关系|interaction)[:：]", line, re.I):
            interaction.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
        elif re.match(r"^(?:场景|环境|scene)[:：]", line, re.I):
            scene.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
        else:
            raise WorkflowError("多人图请分行填写 人物1：、人物2：、场景：、互动：；或使用 /amulti 自动 <中文描述>。")
    return validate_scene({"people": people, "scene": " ".join(scene), "interaction": " ".join(interaction)})


def validate_scene(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("people"), list):
        raise WorkflowError("多人规划缺少 people 数组。")
    if not 2 <= len(data["people"]) <= 4:
        raise WorkflowError("裸模多人图支持2–4个人物；建议先从双人开始。")
    people = []
    for raw in data["people"]:
        if not isinstance(raw, dict):
            raise WorkflowError("人物规划必须是对象。")
        person = {key: str(raw.get(key, "")).strip() for key in ("name", "appearance", "description")}
        if not person["name"] or any(len(value) > 2500 for value in person.values()):
            raise WorkflowError("人物姓名不能为空，每个人物字段最多2500字符。")
        if any("<lora:" in value.lower() for value in person.values()):
            raise WorkflowError("裸模多人图不接受角色LoRA语法。")
        people.append(person)
    result = {"people": people}
    for key in ("scene", "interaction"):
        value = str(data.get(key, "")).strip()
        if len(value) > 4000:
            raise WorkflowError("场景或互动描述过长。")
        result[key] = value
    return result


def render_scene(data: dict[str, Any], lookup: Callable[[str], Any] | None = None) -> str:
    data = validate_scene(data)
    lines = [f"Exactly {len(data['people'])} people. One coherent scene, one camera view."]
    for i, person in enumerate(data["people"]):
        name, appearance = person["name"], person["appearance"]
        match = lookup(name) if lookup else None
        if match:
            name = match.tag.replace("_", " ")
            if not appearance:
                appearance = ", ".join(match.appearance).replace("_", " ")
            if match.copyright:
                name += " from " + ", ".join(match.copyright).replace("_", " ")
        if re.search(r"[\u3400-\u9fff]", name + appearance + person["description"]):
            raise WorkflowError("手动模式只自动解析词典中文姓名；外貌、动作请写英文，或用 /amulti 自动。")
        if not appearance:
            raise WorkflowError(f"{person['name']} 缺少基本外貌，请补充外貌或在词典中维护强模式特征。")
        lines.append(f"Character {chr(65+i)}: {name}. Appearance: {appearance}. {person['description']}")
    for key, label in (("scene", "Scene"), ("interaction", "Interaction")):
        if re.search(r"[\u3400-\u9fff]", data[key]):
            raise WorkflowError("手动模式场景和互动请用英文；中文自由描述请用 /amulti 自动。")
        if data[key]:
            lines.append(f"{label}: {data[key]}")
    return "\n".join(lines)


def strip_standard_loras(workflow: dict[str, Any]) -> None:
    """Bypass every standard LoRA in a copied API graph; reject unknown loaders."""
    routes = {}
    for node_id, node in workflow.items():
        kind = str(node.get("class_type", ""))
        if "lora" not in kind.lower():
            continue
        if kind not in {"LoraLoader", "LoraLoaderModelOnly"}:
            raise WorkflowError(f"裸模多人图不支持自动旁路 {kind}；请使用无LoRA的API工作流。")
        inputs = node.get("inputs", {})
        routes[(str(node_id), 0)] = inputs.get("model")
        if kind == "LoraLoader":
            routes[(str(node_id), 1)] = inputs.get("clip")
    def resolve(value):
        visited = set()
        while isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
            key = (str(value[0]), value[1])
            if key not in routes:
                break
            if key in visited or routes[key] is None:
                raise WorkflowError("LoRA连接缺失或存在循环，无法安全旁路。")
            visited.add(key)
            value = routes[key]
        return value
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            node["inputs"][key] = resolve(value)
    for node_id in list(workflow):
        if (str(node_id), 0) in routes:
            del workflow[node_id]


async def plan_scene(context, event, text: str, provider_id: str) -> dict[str, Any]:
    if not provider_id:
        raise WorkflowError("多人自动规划需要配置 AstrBot 文本 Provider；也可使用分行手动模式。")
    response = await context.llm_generate(
        chat_provider_id=provider_id,
        prompt=text,
        system_prompt=(
            'Plan one coherent image with exactly 2 to 4 people. Return JSON only: '
            '{"people":[{"name":"English canonical name or tag","appearance":"visible identity traits",'
            '"description":"clothing, expression, pose and props"}],"scene":"shared setting",'
            '"interaction":"one directed interaction using Character A, Character B etc"}. '
            'All fields must be English. Preserve requested identities, count, traits and actions. '
            'Give each person their own appearance. No solo, no split-screen, no LoRA syntax. '
            'Use explicit left/right positioning only if requested. Do not add extra people.'
        ),
        max_tokens=2000,
    )
    raw = str(getattr(response, "completion_text", "")).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        return validate_scene(json.loads(raw))
    except (ValueError, TypeError) as exc:
        raise WorkflowError("多人规划未返回有效JSON，请重试或改用手动分行模式。") from exc
