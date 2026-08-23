from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct execution for local tests
    from workflow_runtime import WorkflowError


SUPPORTED_CATEGORIES = {"generate", "refine", "analyze"}


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    category: str
    workflow_file: str
    config_path_key: str
    profiles: dict[str, dict[str, Any]]
    node_mapping: dict[str, str]
    required_nodes: tuple[str, ...]
    capability: dict[str, Any]

    def profile(self, name: str = "") -> tuple[str, dict[str, Any]]:
        selected = str(name or "").strip().casefold()
        if not selected:
            selected = str(self.capability.get("default_profile", "")).casefold()
        if not self.profiles:
            return "", {}
        value = self.profiles.get(selected)
        if not isinstance(value, dict):
            allowed = ", ".join(sorted(self.profiles))
            raise WorkflowError(
                f"PROFILE_NOT_FOUND：{self.workflow_id} 不支持 profile={name or selected}；"
                f"可用值：{allowed}"
            )
        return selected, copy.deepcopy(value)


class WorkflowRegistry:
    def __init__(self, definitions: dict[str, WorkflowDefinition], revision: int = 1):
        self._definitions = definitions
        self.revision = int(revision)

    def resolve(self, workflow_id: str) -> WorkflowDefinition:
        key = str(workflow_id or "").strip()
        definition = self._definitions.get(key)
        if definition is None:
            raise WorkflowError(f"WORKFLOW_NOT_FOUND：{key or '（空）'}")
        return definition

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取 Workflow Registry：{exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError("Workflow Registry 必须是 JSON 对象。")
    return data


def load_workflow_registry(path: Path) -> WorkflowRegistry:
    data = _read_json(Path(path))
    raw_definitions = data.get("workflows")
    if not isinstance(raw_definitions, list):
        raise WorkflowError("Workflow Registry 缺少 workflows 列表。")
    definitions: dict[str, WorkflowDefinition] = {}
    for raw in raw_definitions:
        if not isinstance(raw, dict):
            raise WorkflowError("Workflow Registry 中存在非对象条目。")
        workflow_id = str(raw.get("id", "")).strip()
        if not workflow_id or workflow_id in definitions:
            raise WorkflowError(f"Workflow Registry ID 无效或重复：{workflow_id!r}")
        category = str(raw.get("category", "")).strip().casefold()
        if category not in SUPPORTED_CATEGORIES:
            raise WorkflowError(f"工作流 {workflow_id} category 无效：{category}")
        profiles = raw.get("profiles", {})
        node_mapping = raw.get("node_mapping", {})
        if not isinstance(profiles, dict) or not isinstance(node_mapping, dict):
            raise WorkflowError(f"工作流 {workflow_id} profiles/node_mapping 必须是对象。")
        definitions[workflow_id] = WorkflowDefinition(
            workflow_id=workflow_id,
            version=str(raw.get("version", "1.0.0")).strip(),
            category=category,
            workflow_file=str(raw.get("workflow_file", "")).strip(),
            config_path_key=str(raw.get("config_path_key", "")).strip(),
            profiles=copy.deepcopy(profiles),
            node_mapping={str(k): str(v) for k, v in node_mapping.items()},
            required_nodes=tuple(str(value) for value in raw.get("required_nodes", [])),
            capability=copy.deepcopy(raw.get("capability", {})),
        )
    return WorkflowRegistry(definitions, data.get("registry_revision", 1))


def resolve_workflow_path(
    definition: WorkflowDefinition,
    *,
    config: Any,
    plugin_dir: Path,
) -> Path:
    configured = ""
    if definition.config_path_key:
        configured = str(config.get(definition.config_path_key, "")).strip()
    value = configured or definition.workflow_file
    if not value:
        raise WorkflowError(
            f"WORKFLOW_NOT_FOUND：{definition.workflow_id} 没有配置工作流文件。"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(plugin_dir) / path
    return path.resolve()


def validate_workflow_nodes(
    workflow: dict[str, Any], definition: WorkflowDefinition
) -> None:
    missing = [node_id for node_id in definition.required_nodes if node_id not in workflow]
    if missing:
        raise WorkflowError(
            f"工作流 {definition.workflow_id}@{definition.version} 缺少节点："
            + ", ".join(missing)
        )
