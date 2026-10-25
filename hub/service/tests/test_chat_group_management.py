import asyncio
import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.auth import AuthPrincipal, SYSTEM_ADMIN
from astr_auto_anima_hub.chat_groups import group_store
from astr_auto_anima_hub.remote_jobs import RemoteJobError, RemoteJobManager
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest


class ChatGroupManagementTests(unittest.TestCase):
    def setUp(self):
        try:
            from .test_api import ApiTests
        except ImportError:
            from test_api import ApiTests
        self.fixture = ApiTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.settings = replace(self.fixture.settings, astrbot_api_key="fixture-only")
        self.client = self.fixture.client
        self.headers = self.fixture.headers
        self.key = "qq:examplebot:123456"
        self.group = dict(key=self.key, platform="qq", bot_id="examplebot", group_id="123456",
                          name="Test group", enabled=True, level_system_enabled=True,
                          safety_mode=None, daily_limit=2, cooldown_seconds=0)
        self.settings.delivery_targets_path.write_text(json.dumps({"targets": [
            {"id": "group", "label": "Group", "umo": "examplebot:GroupMessage:123456"}]}), encoding="utf-8")
        self.user = AuthPrincipal(role="user", subject="bound-user", qq="654321")
        self.store = group_store(self.settings)

    def enable(self, grade=1):
        self.store.upsert_group(self.group)
        self.store.upsert_user({"group_key": self.key, "qq": self.user.qq, "grade": grade,
                                "primary_group": self.key})
        self.store.set_enabled(True)

    def test_read_and_capabilities_are_authenticated_and_do_not_create_database(self):
        for endpoint in ("/api/v1/capabilities", "/api/v1/admin/chat-groups"):
            self.assertIn(self.client.get(endpoint).status_code, (401, 403))
        caps = self.client.get("/api/v1/capabilities", headers=self.headers)
        self.assertEqual(caps.json()["execution_mode"], "remote")
        self.assertTrue(caps.json()["features"]["chat_groups"])
        self.assertEqual(caps.json()["chat_group_platforms"], ["qq"])
        response = self.client.get("/api/v1/admin/chat-groups", headers=self.headers)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(self.store.path.exists())
        self.assertIn(self.client.get("/api/v1/admin/chat-groups", headers=self.fixture.user_headers).status_code, (401, 403))

    def test_unverified_platform_policies_are_not_presented_as_enforced(self):
        for platform in ("telegram", "discord"):
            value = {**self.group, "platform": platform, "key": f"{platform}:examplebot:123456"}
            response = self.client.put("/api/v1/admin/chat-groups/groups/" + value['key'], headers=self.headers, json=value)
            self.assertEqual(response.status_code, 422)
        self.assertFalse(self.store.path.exists())

    def test_per_entity_updates_preserve_other_groups_and_need_delete_confirmation(self):
        endpoint = "/api/v1/admin/chat-groups"
        first = self.client.put(f"{endpoint}/groups/{self.key}", headers=self.headers, json=self.group)
        self.assertEqual(first.status_code, 200, first.text)
        other = {**self.group, "key": "qq:second:123456", "bot_id": "second", "name": "Other bot"}
        self.assertEqual(self.client.put(f"{endpoint}/groups/{other['key']}", headers=self.headers, json=other).status_code, 200)
        changed = {**self.group, "name": "Changed"}
        self.assertEqual(self.client.put(f"{endpoint}/groups/{self.key}", headers=self.headers, json=changed).status_code, 200)
        state = self.client.get(endpoint, headers=self.headers).json()
        self.assertEqual({g['name'] for g in state['groups']}, {"Other bot", "Changed"})
        user = dict(group_key=self.key, qq=self.user.qq, grade=2, primary_group="")
        response = self.client.put(f"{endpoint}/users", headers=self.headers, json=user)
        self.assertEqual(response.status_code, 200, response.text)
        query = dict(group_key=self.key, qq=self.user.qq)
        self.assertEqual(self.client.delete(f"{endpoint}/users", headers=self.headers, params=query).status_code, 422)
        self.assertEqual(self.client.delete(f"{endpoint}/users", headers=self.headers, params={**query, "confirmed": True}).status_code, 200)

    def test_local_mode_rejects_all_writes_and_platform_switches_without_creating_state(self):
        local = TestClient(create_app(replace(self.settings, execution_mode="local")))
        caps = local.get("/api/v1/capabilities", headers=self.headers).json()
        self.assertTrue(caps['features']['local_generation'])
        self.assertFalse(caps['features']['chat_groups'])
        self.assertFalse(local.get("/api/v1/admin/chat-groups", headers=self.headers).json()['available'])
        for path, body in (("config", {"enabled": True}),
                           ("groups/" + self.key, self.group),
                           ("users", {"group_key": self.key, "qq": self.user.qq, "grade": 1})):
            self.assertEqual(local.put("/api/v1/admin/chat-groups/" + path, headers=self.headers, json=body).status_code, 409)
        self.assertEqual(local.put("/api/v1/admin/platform-switchboard", headers=self.headers,
                                  json={"qq": True, "telegram": False, "discord": False}).status_code, 409)
        self.assertFalse(self.store.path.exists())

    def test_server_enforces_unknown_user_quota_and_private_primary_without_client_flags(self):
        self.enable()
        async def run():
            manager = RemoteJobManager(self.settings)
            manager._run = AsyncMock()
            payload = RemoteJobCreateRequest(target_id="group", kind="direct", prompt="landscape")
            with self.assertRaises(RemoteJobError):
                manager.create(payload, AuthPrincipal(role="user", subject="unknown", qq="123999"))
            self.assertEqual(manager._jobs, {})
            for _ in range(2):
                manager.create(payload, self.user)
            with self.assertRaises(RemoteJobError):
                manager.create(payload, self.user)
            with self.assertRaises(RemoteJobError):
                manager.create(payload.model_copy(update={"target_id": "self-private"}), self.user)
            self.assertEqual(len(manager._jobs), 2)
            await asyncio.gather(*tuple(manager._tasks))
        asyncio.run(run())

    def test_reservation_is_shared_idempotent_and_bound_to_trusted_identity(self):
        self.enable()
        async def run():
            manager = RemoteJobManager(self.settings)
            manager._run = AsyncMock()
            job = manager.create(RemoteJobCreateRequest(target_id="group", kind="random", five_draw=True), self.user)
            context = manager._group_contexts[job.id]
            self.assertEqual(context["request_id"], "hub:" + job.id)
            self.assertTrue(self.store.reserve(self.key, self.user.qq, context["request_id"])["already_reserved"])
            with closing(sqlite3.connect(self.store.path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM admissions").fetchone()[0], 1)
            await asyncio.gather(*tuple(manager._tasks))
        asyncio.run(run())

    def test_group_safety_override_and_trusted_bridge_ticket_when_global_safety_is_off(self):
        self.group['safety_mode'] = True
        self.enable(grade=3)
        async def run():
            manager = RemoteJobManager(self.settings)
            captured = {}
            async def fake_collect(job_id, command, username, **kwargs):
                self.assertTrue(username.startswith("aaa_safe_"))
                ticket = self.settings.plugin_data_dir / "safety/tickets" / (username.removeprefix("aaa_safe_") + ".json")
                captured.update(json.loads(ticket.read_text(encoding="utf-8")))
                return ["Generated"], [], []
            manager._chat_and_collect = fake_collect
            job = manager.create(RemoteJobCreateRequest(target_id="group", kind="direct", prompt="landscape", deliver_to_im=False), self.user)
            self.assertTrue(manager._job_safety_policy(job.id).enabled)
            await asyncio.gather(*tuple(manager._tasks))
            self.assertEqual(captured['qq'], self.user.qq)
            self.assertEqual(captured['group_key'], self.key)
            self.assertEqual(captured['group_request_id'], 'hub:' + job.id)
            self.assertFalse(captured['admin_exempt'])
            reloaded = RemoteJobManager(self.settings)
            self.assertTrue(reloaded._job_safety_policy(job.id).enabled)
            with self.assertRaises(RemoteJobError):
                reloaded._require_approved(b"unapproved", job.id)
            reloaded._credit_store().approve(b"approved", reloaded._job_safety_policy(job.id).fingerprint)
            reloaded._require_approved(b"approved", job.id)
        asyncio.run(run())

    def test_corrupt_database_rejects_generation_not_disable_permissions(self):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_bytes(b"not a sqlite database")
        response = self.client.get("/api/v1/admin/chat-groups", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        manager = RemoteJobManager(self.settings)
        with self.assertRaises(RemoteJobError):
            manager.create(RemoteJobCreateRequest(target_id="group", kind="direct", prompt="landscape"), self.user)

    def test_private_primary_group_cannot_cross_bot_identity(self):
        self.enable(grade=3)
        manager = RemoteJobManager(replace(self.settings, astrbot_bot_id="different-bot"))
        with self.assertRaises(RemoteJobError):
            manager.create(RemoteJobCreateRequest(target_id="self-private", kind="direct", prompt="landscape"), self.user)
        self.assertEqual(manager._jobs, {})

    def test_admin_without_qq_remains_exempt_and_disabled_module_legacy_is_unchanged(self):
        async def run():
            manager = RemoteJobManager(self.settings)
            manager._run = AsyncMock()
            payload = RemoteJobCreateRequest(target_id="group", kind="direct", prompt="landscape")
            manager.create(payload, AuthPrincipal(role="legacy_lite", subject="legacy"))
            self.enable()
            manager.create(payload, SYSTEM_ADMIN)
            await asyncio.gather(*tuple(manager._tasks))
        asyncio.run(run())
