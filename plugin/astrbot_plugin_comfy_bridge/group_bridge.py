"""QQ group policy integration. No network calls and no global config mutation."""
from __future__ import annotations

import hashlib
import ast
import json
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path

from .group_policy_runtime import GroupPolicyError, GroupStore, group_key
from .workflow_runtime import WorkflowError


class GroupDenied(WorkflowError):
    def __init__(self, message, *, silent=False):
        super().__init__(message)
        self.silent = silent


@lru_cache(maxsize=4)
def registered_group_commands(source_path: str, source_mtime: int, source_size: int):
    """Discover the actual trusted source's handlers, rather than a second list.

    No code is executed. The signature refreshes this small cache after an
    installed plugin reload, including newly added commands and aliases.
    """
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ComfyWorkflowBridge")
    commands, handler_names = set(), set()
    for method in cls.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in method.decorator_list:
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "filter"
                    and decorator.func.attr == "command"):
                continue
            name = ast.literal_eval(decorator.args[0])
            if not isinstance(name, str):
                raise ValueError("command name must be literal text")
            commands.add(name)
            handler_names.add(method.name)
            for keyword in decorator.keywords:
                if keyword.arg == "alias":
                    aliases = ast.literal_eval(keyword.value)
                    if not isinstance(aliases, (set, tuple, list)) or not all(isinstance(v, str) for v in aliases):
                        raise ValueError("command aliases must be literal text")
                    commands.update(aliases)
    route = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "natural_random_picture_route")
    prefixes = set()
    for node in ast.walk(route):
        if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 2:
            first, second = node.elts[:2]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if isinstance(second, ast.Constant) and second.value in handler_names:
                    commands.update(first.value.split("|"))
                elif first.value.startswith("来张好图"):
                    commands.add(first.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "message"
                and node.func.attr == "startswith" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            prefixes.add(node.args[0].value)
    if not commands:
        raise ValueError("plugin command registry is empty")
    return frozenset(commands), frozenset(prefixes)


class GroupBridge:
    @staticmethod
    def _group_request_matches(message):
        source = Path(__file__).with_name("main.py")
        try:
            info = source.stat()
            commands, prefixes = registered_group_commands(str(source), info.st_mtime_ns, info.st_size)
        except (OSError, ValueError, TypeError, StopIteration, SyntaxError) as exc:
            raise WorkflowError("无法核实插件命令注册表；群权限检查已停止") from exc
        raw = str(message).strip()
        text = raw.removeprefix("/")
        for name in commands:
            if text == name or (text.startswith(name) and (text[len(name):len(name)+1].isspace() or text[len(name):len(name)+1].isdigit())):
                return True
        # Includes the existing compact '来张好图抄一抄...' route, whose
        # handler intentionally accepts text immediately after the prefix.
        return any(raw.startswith(prefix) for prefix in prefixes)

    def _group_store(self):
        return GroupStore(self._character_dictionary_path().parent / "hub_state" / "group_management.sqlite3")

    @staticmethod
    def _group_platform(event):
        platform = str(getattr(event, "get_platform_name", lambda: "")()).casefold()
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if "webchat" in platform or "webchat" in origin.casefold():
            return "webchat"
        if platform in {"aiocqhttp", "qq"} or (not platform and origin.startswith("qq:")):
            return "qq"
        return platform

    def _native_group_key(self, event):
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        parts = origin.split(":")
        if len(parts) != 3 or parts[1] != "GroupMessage":
            return ""
        return group_key("qq", parts[0], parts[2])

    def _group_ticket(self, event):
        sender = str(event.get_sender_id())
        match = re.search(r"(?:^|_)aaa_safe_([a-f0-9]{32})$", sender)
        if not match:
            raise GroupDenied("群管理已启用，请使用带身份凭据的新版 Hub")
        root = self._character_dictionary_path().parent / "safety" / "tickets"
        path = root / f"{match[1]}.json"
        try:
            if path.resolve() != path or not path.is_file():
                raise ValueError("ticket path")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or float(data.get("expires", 0)) <= time.time():
                raise ValueError("expired")
            return data
        except (OSError, ValueError, TypeError) as exc:
            raise GroupDenied("群管理身份凭据无效或已过期") from exc

    def _group_policy(self, event, *, consume=False):
        default = dict(enabled=False, allowed=True, silent=False, grade=3, safety_mode=None)
        if event is None or self._group_platform(event) not in {"qq", "webchat"}:
            return default
        try:
            store = self._group_store()
            if not store.is_enabled():
                return default
            if self._group_platform(event) == "webchat":
                ticket = self._group_ticket(event)
                key, uid = str(ticket.get("group_key", "")), str(ticket.get("qq", ""))
                request_id = str(ticket.get("group_request_id", ""))
                scope = str(ticket.get("group_scope", ""))
                admin = ticket.get("admin_exempt") is True
                # Old tickets are not allowed to silently opt out of group rules.
                if not request_id:
                    request_id = "hub:" + str(ticket.get("root", ""))
                if not uid and admin:
                    return default
            else:
                key, uid = self._native_group_key(event), str(event.get_sender_id())
                origin = str(getattr(event, "unified_msg_origin", "") or "")
                scope = "qq:" + origin.split(":", 1)[0] if ":" in origin else ""
                admin = self._event_is_admin(event)
                request_id = getattr(event, "_aaa_group_request", "")
                if not request_id:
                    message_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
                    if message_id in {"", "0", "None"}:
                        message_id = uuid.uuid4().hex
                    payload = f"{getattr(event, 'unified_msg_origin', '')}|{uid}|{message_id}"
                    request_id = "qq:" + hashlib.sha256(payload.encode()).hexdigest()
                    setattr(event, "_aaa_group_request", request_id)
            return store.check(key, uid, admin=admin, request_id=request_id, consume=consume, scope=scope)
        except GroupPolicyError as exc:
            raise GroupDenied(str(exc)) from exc

    def _group_admit(self, event, *, consume=False):
        decision = self._group_policy(event, consume=consume)
        if not decision["allowed"]:
            # Grade 0 is silent only in a real group. In a private chat the
            # sender receives an actionable permission message instead.
            silent = bool(decision.get("silent")) and bool(self._native_group_key(event))
            raise GroupDenied(decision.get("reason") or "本群不接受此任务", silent=silent)
        return decision

    def _group_can_manage_presets(self, event):
        if self._group_platform(event) == "webchat":
            exempt = getattr(self, "_safety_admin_exempt", None)
            return bool(callable(exempt) and exempt(event))
        if self._event_is_admin(event):
            return True
        if self._group_platform(event) != "qq":
            return False
        decision = self._group_policy(event)
        return bool(decision.get("enabled") and decision.get("allowed") and decision.get("grade") == 4)

    def _group_admin_command(self, event, command, content=""):
        if not self._event_is_admin(event):
            raise WorkflowError("仅管理员可以管理群聊权限")
        if self._group_platform(event) != "qq":
            raise WorkflowError("此管理指令仅支持 QQ 群聊")
        key = self._native_group_key(event)
        if not key:
            raise WorkflowError("请在要管理的 QQ 群内发送此指令")
        store = self._group_store()
        state = store.read()
        group = next((g for g in state["groups"] if g["key"] == key), None)
        if not state["enabled"] or not group or not group["enabled"]:
            raise WorkflowError("请先在管理端启用群聊管理并接入此 QQ 群")
        if command in {"aimg_safemode", "aimg_unsafemode"}:
            store.patch_group(key, {"safety_mode": command == "aimg_safemode"})
            return "本群安全模式已" + ("开启" if command == "aimg_safemode" else "关闭") + "；其他群与全局配置未修改。"
        message = str(content or getattr(event, "message_str", "") or "")
        message = re.sub(r"^/?" + re.escape(command) + r"(?:\s+|$)", "", message).strip()
        mentions = []
        for item in getattr(getattr(event, "message_obj", None), "message", []) or []:
            if type(item).__name__ == "At":
                target = str(getattr(item, "qq", ""))
                if re.fullmatch(r"[1-9][0-9]{4,14}", target):
                    mentions.append(target)
        explicit = re.findall(r"(?<![0-9])([1-9][0-9]{4,14})(?![0-9])", message)
        users = set(mentions or explicit)
        if len(users) != 1:
            raise WorkflowError("请明确 @ 一位用户，或填写一个 QQ 号")
        uid = next(iter(users))
        if command == "aimg_duser":
            store.delete_user(key, uid)
            return f"已移除用户 {uid} 在本群的登记；其他群不变。"
        previous = next((u for u in state["users"] if u["group_key"] == key and u["user_id"] == uid), None)
        if command == "aimg_grade":
            grade_match = re.search(r"(?:^|\s)([0-4])\s*$", message)
            if not grade_match:
                raise WorkflowError("用法：/aimg_grade @用户 0–4")
            grade = int(grade_match[1])
        else:
            if previous:
                return f"用户 {uid} 已在本群登记，等级 {previous['grade']}；未重置。"
            grade = 1 if group["level_system_enabled"] else 3
        store.set_user_grade(key, uid, grade)
        return f"用户 {uid} 本群等级已设为 {grade}。" + ("（等级系统关闭时，仅显式 4 级生效，其余按 3 级）" if not group["level_system_enabled"] else "")
