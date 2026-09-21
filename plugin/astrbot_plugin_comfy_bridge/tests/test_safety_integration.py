import ast
import asyncio
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

@asynccontextmanager
async def fake_session(**kwargs):
    yield object()

aiohttp = SimpleNamespace(ClientSession=fake_session, ClientTimeout=lambda **kwargs: kwargs)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from safety_runtime import Policy, CreditStore, PriorityGate, match_rules, validate_audit, RANDOM_REVIEW
from workflow_runtime import WorkflowError
from prompt_pool_runtime import compose_random_body


class MessageChain:
    def message(self, text):
        return text


namespace = dict(globals(), __file__=str(ROOT / "safety_bridge.py"))
tree = ast.parse((ROOT / "safety_bridge.py").read_text(encoding="utf-8"))
tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
exec(compile(tree, "safety_bridge.py", "exec"), namespace)
SafetyBridge = namespace["SafetyBridge"]


class Harness(SafetyBridge):
    def __init__(self, root, scope="both", enabled=True):
        self.root = Path(root)
        self.config = {"safety_mode_enabled": enabled, "safety_review_scope": scope,
                       "safety_admin_umos": "qq:FriendMessage:999999"}
        self.context = SimpleNamespace(send_message=AsyncMock(return_value=True))
        self._safety_setup(1)
        self.tags = "solo, sitting"

    def _character_dictionary_path(self):
        return self.root / "character_dictionary.json"

    def _output_dir(self):
        path = self.root / "outputs"
        path.mkdir(exist_ok=True)
        return path

    async def _upload_reverse_image(self, session, path):
        return "audit.png"

    async def _submit_workflow(self, session, workflow):
        self.nonce = workflow["4"]["inputs"]["nonce"]
        return "audit-id"

    async def _wait_for_history(self, session, prompt_id):
        return {"outputs": {"4": {"aaa_safety": [{"nonce":self.nonce,"status":"ok","tags":self.tags}]}}}


def event(sender="123456", origin="qq:FriendMessage:123456"):
    return SimpleNamespace(get_sender_id=lambda: sender, unified_msg_origin=origin,
                           message_obj=SimpleNamespace(message_id="100"))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Harness(self.temp.name)
        self.event = event()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_input_repeated_root_only_once(self):
        for _ in range(5):
            with self.assertRaises(WorkflowError):
                await self.bridge._safety_input(self.event, "penis")
        self.assertEqual(self.bridge._safety_store.score("123456"),9)

    async def test_admin_event_exempt_without_approval_or_credit_reset(self):
        self.event.is_admin = lambda: True
        self.event.role = "admin"
        for i in range(10):
            self.bridge._safety_store.block(str(i), "123456", "input", [])
        self.bridge.config["safety_admin_umos"] = ""
        await self.bridge._safety_input(self.event, "nude")
        image = self.bridge.root / "admin.png"
        image.write_bytes(b"admin-image")
        self.bridge.tags = "nude"
        self.assertEqual(await self.bridge._safety_outputs(self.event, [image]), [image])
        self.assertEqual(self.bridge._safety_priority(self.event), 0)
        self.assertEqual(self.bridge._safety_store.score("123456"), 0)
        self.assertFalse(self.bridge._safety_store.approved(image.read_bytes(), self.bridge._safety_policy().fingerprint))

    async def test_hub_admin_exemption_requires_ticket_not_webchat_role(self):
        ev = event("123456", "webchat:FriendMessage:test")
        ev.is_admin = lambda: True
        self.assertFalse(self.bridge._safety_admin_exempt(ev))
        token = uuid.uuid4().hex
        tickets = self.bridge._safety_root_dir / "tickets"
        tickets.mkdir()
        path = tickets / f"{token}.json"
        data = {"qq": "", "root": "job", "admin_exempt": True, "expires": time.time()+60}
        path.write_text(json.dumps(data))
        ev.get_sender_id = lambda: f"aaa_safe_{token}"
        await self.bridge._safety_input(ev, "nude")
        data["expires"] = time.time()-1
        path.write_text(json.dumps(data))
        self.assertFalse(self.bridge._safety_admin_exempt(ev))
        with self.assertRaises(WorkflowError):
            await self.bridge._safety_input(ev, "nude")

    async def test_user_role_string_cannot_grant_exemption(self):
        self.event.role = "admin"
        self.event.is_admin = lambda: False
        with self.assertRaises(WorkflowError):
            await self.bridge._safety_input(self.event, "nude")

    async def test_output_fail_closed_without_penalty(self):
        image = self.bridge.root / "test.png"
        image.write_bytes(b"image")
        self.bridge.tags = ""
        with self.assertRaises(WorkflowError):
            await self.bridge._safety_outputs(self.event,[image])
        self.assertEqual(self.bridge._safety_store.score("123456"),10)
        self.assertFalse((self.bridge.root / "outputs").exists())

    async def test_output_block_no_approval(self):
        image = self.bridge.root / "test.png"
        image.write_bytes(b"image")
        self.bridge.tags = "solo, nipples"
        with self.assertRaises(WorkflowError):
            await self.bridge._safety_outputs(self.event,[image])
        self.assertEqual(self.bridge._safety_store.score("123456"),9)
        self.assertFalse(self.bridge._safety_store.approved(b"image",self.bridge._safety_policy().fingerprint))

    async def test_mode_scope_and_approval(self):
        self.bridge.config["safety_review_scope"] = "output"
        await self.bridge._safety_input(self.event,"penis")
        self.bridge.config["safety_review_scope"] = "input"
        self.bridge.tags = "penis"
        image = self.bridge.root / "test.png"
        image.write_bytes(b"image")
        paths = await self.bridge._safety_outputs(self.event,[image])
        self.assertTrue(paths[0].is_file())
        self.assertTrue(self.bridge._safety_store.approved(b"image",self.bridge._safety_policy().fingerprint))

    async def test_disabled_ignores_zero_credit(self):
        for i in range(10):
            self.bridge._safety_store.block(str(i),"123456","input",[])
        with self.assertRaises(WorkflowError):
            self.bridge._safety_guard(self.event)
        self.bridge.config["safety_mode_enabled"] = False
        await self.bridge._safety_input(self.event,"penis")
        self.assertEqual(self.bridge._safety_priority(self.event),0)

    async def test_trusted_hub_ticket_not_self_reported_qq(self):
        with self.assertRaises(WorkflowError):
            self.bridge._safety_identity(event("123456","webchat:FriendMessage:fake"))
        token = uuid.uuid4().hex
        tickets = self.bridge._safety_root_dir / "tickets"
        tickets.mkdir()
        (tickets/f"{token}.json").write_text(json.dumps({"qq":"123456","root":"server-root","expires":time.time()+10}))
        self.assertEqual(self.bridge._safety_identity(event(f"aaa_safe_{token}","webchat:FriendMessage:fake")),("123456","server-root"))

    async def test_credit_notifications_durable(self):
        for i in range(10):
            self.bridge._safety_store.block(str(i),"123456","output",[])
        await self.bridge._safety_notices()
        self.assertEqual(self.bridge.context.send_message.await_count,2)
        await self.bridge._safety_notices()
        self.assertEqual(self.bridge.context.send_message.await_count,2)

    async def test_s_group_block_in_every_scope(self):
        from prompt_pool_runtime import parse_group_selector
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        klass = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="ComfyWorkflowBridge")
        method = next(n for n in klass.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_execute_random_picture")
        ns = dict(globals(), AstrMessageEvent=object, Any=object, parse_group_selector=parse_group_selector)
        exec(compile(ast.Module(body=[method],type_ignores=[]),"selection","exec"),ns)
        self.event.send = AsyncMock()
        self.event.plain_result = lambda text: text
        for scope in ["input","output","both"]:
            self.bridge.config["safety_review_scope"] = scope
            await ns[method.name](self.bridge,self.event,"S",draw_count=5)
        self.assertEqual(self.bridge._safety_store.score("123456"),9)
        self.assertEqual(self.event.send.await_count,3)

    async def test_non_s_five_sequential_no_penalty_and_zero_stops_remainder(self):
        import secrets
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=="ComfyWorkflowBridge")
        method = next(n for n in klass.body if isinstance(n, ast.AsyncFunctionDef) and n.name=="_deliver_random_draw_plans")
        module = ast.Module(body=[method],type_ignores=[])
        ns = dict(globals(), AstrMessageEvent=object, Any=object, secrets=secrets)
        exec(compile(module,"draw", "exec"),ns)
        bridge = self.bridge
        calls=[]
        async def generate(event, **kwargs):
            self.assertNotIn("batch_prompts",kwargs)
            calls.append(kwargs)
            return True
        bridge._deliver_generation=generate
        plans=[({"id":str(i),"prompt":"solo"},{},{}) for i in range(5)]
        self.assertEqual(await ns[method.name](bridge,self.event,draw_plans=plans,user_prompt="",quality="",chaos=False),5)
        self.assertEqual(len(calls),5)
        self.assertEqual([c['options']['_draw_positions'] for c in calls], [[1],[2],[3],[4],[5]])
        self.assertEqual(len({c['options']['_draw_group'] for c in calls}), 1)
        for i in range(9):
            bridge._safety_store.block(f"old{i}", "123456", "input", [])
        self.event.send = AsyncMock()
        self.event.plain_result = lambda text: text
        calls.clear()
        async def reject(event, **kwargs):
            calls.append(kwargs)
            try:
                await bridge._safety_input(event, "penis")
            except WorkflowError:
                return False
        bridge._deliver_generation = reject
        self.assertEqual(await ns[method.name](bridge,self.event,draw_plans=plans,user_prompt="",quality="",chaos=False),0)
        self.assertEqual(len(calls),5)
        self.assertEqual(bridge._safety_store.score("123456"),1)
        self.assertFalse(RANDOM_REVIEW.get())
        bridge._safety_store.block("last-direct", "123456", "input", [])
        calls.clear()
        self.assertEqual(await ns[method.name](bridge,self.event,draw_plans=plans,user_prompt="",quality="",chaos=True),0)
        self.assertEqual(len(calls),0)

    async def test_random_output_no_penalty_and_context_isolated(self):
        image = self.bridge.root / "test.png"
        image.write_bytes(b"test-image")
        self.bridge.tags = "nude"
        started, release = asyncio.Event(), asyncio.Event()
        async def generation(event, **kwargs):
            started.set()
            await release.wait()
            return await self.bridge._safety_outputs(event, [image])
        self.bridge._deliver_generation = generation
        random_task = asyncio.create_task(self.bridge._deliver_random_generation(self.event))
        await started.wait()
        direct = event()
        direct.message_obj.message_id = "different-root"
        with self.assertRaises(WorkflowError):
            await self.bridge._safety_input(direct, "nsfw")
        self.assertEqual(self.bridge._safety_store.score("123456"),9)
        release.set()
        with self.assertRaisesRegex(WorkflowError, "本次不扣分"):
            await random_task
        self.assertEqual(self.bridge._safety_store.score("123456"),9)
        self.assertFalse(self.bridge._safety_store.approved(b"test-image", self.bridge._safety_policy().fingerprint))
        self.assertFalse(RANDOM_REVIEW.get())
        with self.bridge._safety_store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE stage='output:no_penalty'").fetchone()[0],1)

    async def test_random_cancellation_restores_context(self):
        async def cancel(event, **kwargs):
            raise asyncio.CancelledError()
        self.bridge._deliver_generation = cancel
        with self.assertRaises(asyncio.CancelledError):
            await self.bridge._deliver_random_generation(self.event)
        self.assertFalse(RANDOM_REVIEW.get())


if __name__ == "__main__":
    unittest.main()
