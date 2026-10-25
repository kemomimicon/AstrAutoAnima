import ast
import asyncio
import concurrent.futures
import json
import sqlite3
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_comfy_bridge.group_bridge import GroupBridge, GroupDenied, registered_group_commands
from astrbot_plugin_comfy_bridge.group_policy_runtime import GroupStore, GroupPolicyError, group_key
from astrbot_plugin_comfy_bridge.safety_runtime import Policy
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError

ROOT = Path(__file__).resolve().parents[1]
KEY = "qq:qqbot:12345"


def setup_store(tmp_path, *, grade=1, safety=True, daily=2, cooldown=0):
    store = GroupStore(tmp_path / "hub_state" / "group_management.sqlite3")
    store.upsert_group(dict(key=KEY, level_system_enabled=True, safety_mode=safety,
                           daily_limit=daily, cooldown_seconds=cooldown))
    store.upsert_user(dict(group_key=KEY, qq="123456", grade=grade))
    store.set_enabled(True)
    return store


def event(*, uid="123456", group="12345", admin=False, platform="aiocqhttp", message_id="1"):
    origin = f"qqbot:GroupMessage:{group}" if group else "qqbot:FriendMessage:123456"
    return SimpleNamespace(get_sender_id=lambda: uid, unified_msg_origin=origin,
                           get_platform_name=lambda: platform, is_admin=lambda: admin,
                           message_obj=SimpleNamespace(message_id=message_id, message=[]),
                           message_str="/aimg test", should_call_llm=Mock(), stop_event=Mock(),
                           plain_result=lambda t: t, send=AsyncMock())


class Harness(GroupBridge):
    def __init__(self, root):
        self.root = root
        self.config = {"safety_mode_enabled": False, "safety_review_scope": "both"}

    def _character_dictionary_path(self):
        return self.root / "dictionary.json"

    @staticmethod
    def _event_is_admin(ev):
        return ev.is_admin()


def bind_main(name, owner):
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ComfyWorkflowBridge")
    method = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    method.decorator_list = []
    import re
    ns = dict(WorkflowError=WorkflowError, AstrMessageEvent=object, re=re, time=time)
    exec(compile(ast.Module(body=[method], type_ignores=[]), "group_main_test", "exec"), ns)
    return MethodType(ns[name], owner)


def test_disabled_never_creates_files_or_requires_identity(tmp_path):
    store = GroupStore(tmp_path / "absent" / "group_management.sqlite3")
    assert store.policy("", "")["allowed"]
    assert store.reserve("", "", "")["allowed"]
    assert not store.path.parent.exists()
    store.set_enabled(False)
    assert store.policy("invalid", "")["allowed"]


def test_corrupt_database_never_reinitialized(tmp_path):
    path = tmp_path / "group_management.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE stray (value TEXT)")
    before = path.read_bytes()
    store = GroupStore(path)
    for fn in (store.read, lambda: store.set_enabled(False), lambda: store.policy(KEY, "123456")):
        with pytest.raises(GroupPolicyError):
            fn()
    assert path.read_bytes() == before


@pytest.mark.parametrize("grade,allowed", [(0, False), (1, True), (2, True), (3, True), (4, True)])
def test_explicit_levels_and_missing_user(tmp_path, grade, allowed):
    store = setup_store(tmp_path, grade=grade)
    decision = store.policy(KEY, "123456")
    assert decision["allowed"] is allowed
    assert decision["grade"] == grade
    assert decision["safety_mode"] is True
    assert not store.policy(KEY, "999999")["allowed"]
    assert store.policy(KEY, "999999")["silent"]
    assert store.policy(KEY, "999999", is_admin=True)["allowed"]
    assert not store.policy("qq:other:12345", "123456")["allowed"]


def test_levels_disabled_only_grade4_special(tmp_path):
    store = setup_store(tmp_path, grade=0)
    group = store.read()["groups"][0]
    store.upsert_group({**group, "level_system_enabled": False, "safety_mode": None})
    assert store.policy(KEY, "123456")["grade"] == 3
    assert store.policy(KEY, "999999")["grade"] == 3
    assert store.policy(KEY, "123456")["safety_mode"] is None
    store.upsert_user(dict(group_key=KEY, qq="123456", grade=4))
    assert store.policy(KEY, "123456")["grade"] == 4


def test_daily_count_atomic_and_idempotent_across_connections(tmp_path):
    store = setup_store(tmp_path, daily=1)
    def reserve(index):
        return GroupStore(store.path).reserve(KEY, "123456", f"request-{index}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(reserve, range(12)))
    assert sum(r["allowed"] for r in results) == 1
    accepted = next(r for r in results if r["allowed"])
    assert store.reserve(KEY, "123456", accepted["request_id"])["already_reserved"]
    with pytest.raises(GroupPolicyError, match="幂等"):
        store.reserve(KEY, "999999", accepted["request_id"], is_admin=True)


def test_cooldown_grade2_and_grade3_daily_behavior(tmp_path):
    store = setup_store(tmp_path, daily=2, cooldown=60)
    assert store.reserve(KEY, "123456", "one")["allowed"]
    assert not store.reserve(KEY, "123456", "two")["allowed"]
    store.upsert_user(dict(group_key=KEY, qq="123456", grade=2))
    assert store.reserve(KEY, "123456", "two")["allowed"]
    assert not store.reserve(KEY, "123456", "three")["allowed"]
    store.upsert_user(dict(group_key=KEY, qq="123456", grade=3))
    assert store.reserve(KEY, "123456", "three")["allowed"]


def test_primary_scope_cannot_leak_between_bots_or_platforms(tmp_path):
    store = setup_store(tmp_path, grade=0)
    other = "telegram:qqbot:12345"
    store.upsert_group(dict(key=other, level_system_enabled=True))
    store.upsert_user(dict(group_key=other, qq="123456", grade=4))
    assert store.policy("", "123456", scope="qq:qqbot")["grade"] == 0
    assert store.policy("", "123456", scope="telegram:qqbot")["grade"] == 4
    assert not store.policy("", "123456", scope="qq:other")["allowed"]
    assert not store.policy("", "123456")["allowed"]
    assert store.policy("", "", is_admin=True)["allowed"]


def test_user_deletion_retains_quota_no_reset_loophole(tmp_path):
    store = setup_store(tmp_path, daily=1)
    store.reserve(KEY, "123456", "one")
    store.delete_user(KEY, "123456")
    assert not store.policy(KEY, "123456")["allowed"]
    store.upsert_user(dict(group_key=KEY, qq="123456", grade=1))
    assert not store.reserve(KEY, "123456", "two")["allowed"]


def test_bridge_five_draw_same_event_count_once_and_admin_only_commands(tmp_path):
    store = setup_store(tmp_path, daily=1)
    bridge = Harness(tmp_path)
    ev = event()
    for _ in range(5):
        assert bridge._group_admit(ev, consume=True)["allowed"]
    with pytest.raises(GroupDenied, match="次数"):
        bridge._group_admit(event(message_id="next"), consume=True)
    with pytest.raises(WorkflowError, match="仅管理员"):
        bridge._group_admin_command(ev, "aimg_nuser", "654321")
    admin = event(admin=True)
    bridge._group_admin_command(admin, "aimg_nuser", "654321")
    assert store.policy(KEY, "654321")["grade"] == 1
    bridge._group_admin_command(admin, "aimg_grade", "654321 4")
    assert store.policy(KEY, "654321")["grade"] == 4
    bridge._group_admin_command(admin, "aimg_unsafemode")
    assert store.policy(KEY, "654321")["safety_mode"] is False
    assert bridge.config["safety_mode_enabled"] is False
    with pytest.raises(WorkflowError, match="群内"):
        bridge._group_admin_command(event(admin=True, group=""), "aimg_safemode")


def test_grade0_guard_is_silent_before_generation(tmp_path):
    setup_store(tmp_path, grade=0)
    bridge = Harness(tmp_path)
    ev = event()
    asyncio.run(bind_main("group_command_guard", bridge)(ev))
    ev.stop_event.assert_called_once()
    ev.send.assert_not_awaited()


def test_hub_ticket_cannot_claim_admin_or_change_group_from_text(tmp_path):
    store = setup_store(tmp_path, daily=1)
    bridge = Harness(tmp_path)
    ev = event(platform="webchat", admin=True)
    ev.unified_msg_origin = "webchat:FriendMessage:test"
    with pytest.raises(GroupDenied, match="凭据"):
        bridge._group_policy(ev)
    token = "a" * 32
    ev.get_sender_id = lambda: f"aaa_safe_{token}"
    tickets = tmp_path / "safety" / "tickets"
    tickets.mkdir(parents=True)
    (tickets / f"{token}.json").write_text(json.dumps(dict(qq="123456", root="job", expires=time.time()+30,
                                                        group_key=KEY, group_request_id="hub:job", admin_exempt=False)))
    store.reserve(KEY, "123456", "hub:job")
    assert bridge._group_admit(ev, consume=True)["already_reserved"]
    assert bridge._group_admit(ev)["grade"] == 1


def test_grade4_only_preset_add_not_global_admin(tmp_path):
    store = setup_store(tmp_path, grade=4)
    bridge = Harness(tmp_path)
    assert bridge._group_can_manage_presets(event())
    with pytest.raises(WorkflowError, match="仅管理员"):
        bridge._group_admin_command(event(), "aimg_unsafemode")
    store.set_enabled(False)
    assert not bridge._group_can_manage_presets(event())


def test_safety_override_is_event_scoped_not_shared_config(tmp_path):
    store = setup_store(tmp_path)
    store.upsert_group(dict(key="qq:qqbot:67890", level_system_enabled=False, safety_mode=False))
    bridge = Harness(tmp_path)
    bridge._safety_root_dir = tmp_path / "safety"
    bridge._safety_root_dir.mkdir()
    bridge._safety_policy_signature = None
    tree = ast.parse((ROOT / "safety_bridge.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SafetyBridge")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_safety_policy")
    import uuid
    ns = dict(Policy=Policy, json=json, uuid=uuid)
    exec(compile(ast.Module(body=[method], type_ignores=[]), "scoped_safety", "exec"), ns)
    get_policy = MethodType(ns["_safety_policy"], bridge)
    assert get_policy(event()).enabled
    assert not get_policy(event(group="67890")).enabled
    assert get_policy(event()).enabled
    assert not get_policy().enabled
    assert bridge.config["safety_mode_enabled"] is False


def test_group_admin_mention_parse(tmp_path):
    store = setup_store(tmp_path)
    bridge = Harness(tmp_path)
    ev = event(admin=True)
    At = type("At", (), {})
    target = At()
    target.qq = "654321"
    ev.message_obj.message = [target]
    assert "654321" in bridge._group_admin_command(ev, "aimg_grade", "4")
    assert store.policy(KEY, "654321")["grade"] == 4


def test_entity_patches_preserve_current_other_fields_and_primary(tmp_path):
    store = setup_store(tmp_path)
    store.patch_group(KEY, {"daily_limit": 12})
    store.patch_group(KEY, {"safety_mode": False})
    assert store.read()["groups"][0]["daily_limit"] == 12
    other = "qq:qqbot:56789"
    store.upsert_group(dict(key=other, level_system_enabled=True))
    store.set_user_grade(other, "123456", 2)
    assert store.policy("", "123456", scope="qq:qqbot")["group_key"] == KEY
    store.set_user_grade(other, "123456", 4)
    assert store.policy("", "123456", scope="qq:qqbot")["grade"] == 1
    assert store.policy(other, "123456")["grade"] == 4


@pytest.mark.parametrize("foreign", ["qq:otherbot:12345", "telegram:qqbot:12345"])
def test_cross_scope_primary_rejected_before_save_with_same_numeric_user(tmp_path, foreign):
    store = setup_store(tmp_path, grade=1)
    store.upsert_group(dict(key=foreign, level_system_enabled=True))
    store.upsert_user(dict(group_key=foreign, qq="123456", grade=4))
    before = store.read()
    with pytest.raises(GroupPolicyError, match="同一平台和机器人"):
        store.upsert_user(dict(group_key=KEY, qq="123456", grade=1, primary_group=foreign))
    assert store.read() == before
    assert store.policy("", "123456", scope="qq:qqbot")["grade"] == 1
    assert store.policy("", "123456", scope=foreign.rsplit(":", 1)[0])["grade"] == 4


def test_all_registered_commands_and_aliases_are_silent_for_grade0_admin_unaffected(tmp_path):
    """An added @command/alias automatically becomes part of this regression."""
    setup_store(tmp_path, grade=0, safety=False)
    bridge = Harness(tmp_path)
    guard = bind_main("group_command_guard", bridge)
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    commands = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and ast.unparse(decorator.func) == "filter.command":
                commands.add(ast.literal_eval(decorator.args[0]))
                for keyword in decorator.keywords:
                    if keyword.arg == "alias":
                        commands.update(ast.literal_eval(keyword.value))
    assert len(commands) >= 60
    assert {"ajob", "画廊", "画风画廊", "跑图帮助", "awatermark", "打上水印", "asavestyle"} <= commands
    async def verify():
        for name in sorted(commands):
            for text in (name, "/" + name, "/" + name + " fixture"):
                ev = event()
                ev.message_str = text
                await guard(ev)
                assert ev.stop_event.call_count == 1, text
                ev.send.assert_not_awaited()
                admin = event(admin=True)
                admin.message_str = text
                await guard(admin)
                admin.stop_event.assert_not_called()
                admin.send.assert_not_awaited()
    asyncio.run(verify())


@pytest.mark.parametrize("text", [
    "来张好图混沌五连抽 G/N", "来张好图混沌五连 G/N", "来张好图混沌时刻 G/N",
    "来张好图五连抽 G/N", "来张好图抄五张 G/N", "来张好图抽一抽 G/N",
    "来张好图抄一抄角色=A", "收藏1,2", "举报2,4", "重跑一张1,3", "/aecho1,5",
])
def test_natural_and_numbered_routes_silent_for_grade0(tmp_path, text):
    setup_store(tmp_path, grade=0, safety=False)
    bridge = Harness(tmp_path)
    ev = event()
    ev.message_str = text
    asyncio.run(bind_main("group_command_guard", bridge)(ev))
    ev.stop_event.assert_called_once()
    ev.send.assert_not_awaited()


def test_registry_auto_discovers_future_alias_and_does_not_intercept_regular_chat(tmp_path):
    future = tmp_path / "main.py"
    future.write_text((ROOT / "main.py").read_text(encoding="utf-8").replace(
        '@filter.command("amenu")', '@filter.command("future_command", alias={"未来新增别名"})'), encoding="utf-8")
    info = future.stat()
    commands, _ = registered_group_commands(str(future), info.st_mtime_ns, info.st_size)
    assert {"future_command", "未来新增别名"} <= commands
    assert not Harness._group_request_matches("今天晚饭吃什么")
    assert not Harness._group_request_matches("画廊今天开门吗")
