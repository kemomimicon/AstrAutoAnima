"""App HTTP -> Hub ticket -> actual plugin parsing/P selection, no real GPU/IM."""
import ast
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.favorite_bridge import publish_favorite_bridge
from astr_auto_anima_hub.prompt_favorites import save_favorite
from astr_auto_anima_hub.remote_jobs import RemoteJobManager
from astrbot_plugin_comfy_bridge import personal_prompt_runtime
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.prompt_pool_runtime import (
    parse_group_selector, load_prompt_pool, select_random_prompts,
    apply_protected_character_policy, describe_selection,
)
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives


class AppPersonalDrawChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        targets = self.root / "targets.json"
        targets.write_text(json.dumps({"targets": [{"id": "main-group", "label": "主要跑图群",
            "kind": "group", "umo": "bot:GroupMessage:111111", "allow_safety": ["N", "H"]}]}))
        self.settings = Settings(plugin_data_dir=self.root / "data",
            admin_token="a" * 32, lite_token="b" * 32, legacy_lite_qq="123456",
            astrbot_url="http://astrbot.test", astrbot_api_key="abk_test",
            delivery_targets_override=targets)
        for owner in ("legacy-owner", "administrator"):
            for i in range(6):
                save_favorite(self.settings.prompt_favorites_path,
                    AuthPrincipal(role="user", subject=owner),
                    {"id": f"{owner}-{i}", "prompt": f"{owner} garden {i}", "safety_code": "N"},
                    addition="rain")
        self.settings.prompt_pool_path.write_text(json.dumps({"prompts": [
            {"id": "public", "prompt": "landscape", "source_code": "D", "safety_code": "N"}]}))
        publish_favorite_bridge(self.settings)
        self.before = self.settings.prompt_favorites_path.read_bytes()
        tree = ast.parse(Path(personal_prompt_runtime.__file__).with_name("main.py").read_text("utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ComfyWorkflowBridge")
        methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name in {"_execute_random_picture", "_random_prompt_pool"}]
        ns = dict(globals(), Any=object, AstrMessageEvent=object, logger=Mock(),
                  __package__="astrbot_plugin_comfy_bridge")
        exec(compile(ast.Module(body=methods, type_ignores=[]), "real-app-draw", "exec"), ns)
        self.plugin = SimpleNamespace(config={}, _platform_admit=Mock(), _safety_guard=Mock(),
            _safety_applies=lambda e: False, _is_private_event=lambda e: False,
            _prompt_pool_path=lambda: self.settings.prompt_pool_path,
            _random_quality_prompt=lambda p: "",
            _deliver_random_draw_plans=AsyncMock(return_value=1))
        for method in methods:
            setattr(self.plugin, method.name, MethodType(ns[method.name], self.plugin))
        self.tickets = []
        self.chat = []

        async def transport(request):
            if request.url.path == "/api/v1/chat":
                payload = json.loads(request.content)
                self.chat.append(payload)
                sender, session = payload["username"], payload["session_id"]
                ticket = self.settings.plugin_data_dir / "safety/tickets" / (sender.removeprefix("aaa_safe_") + ".json")
                self.tickets.append(json.loads(ticket.read_text()))
                event = SimpleNamespace(get_platform_name=lambda: "webchat",
                    get_sender_id=lambda: sender,
                    get_session_id=lambda: f"webchat!{sender}!{session}",
                    send=AsyncMock(), plain_result=lambda text: text)
                command = payload["message"]
                self.assertIsInstance(command, str)
                five = command.startswith("来张好图五连抽 ")
                prefix = "来张好图五连抽 " if five else "来张好图抽一抽 "
                await self.plugin._execute_random_picture(event, command.removeprefix(prefix),
                                                          draw_count=5 if five else 1)
                errors = [c.args[0] for c in event.send.await_args_list if "抽取失败" in c.args[0]]
                self.assertEqual(errors, [])
                return httpx.Response(200, text=(
                    'data: {"type":"plain","data":"生成完成"}\n\n'
                    'data: {"type":"attachment_saved","data":{"id":"fixture","type":"image"}}\n\n'
                    'data: {"type":"end","data":""}\n\n'),
                    headers={"content-type": "text/event-stream"})
            if request.url.path == "/api/v1/file":
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfixture",
                    headers={"content-disposition": 'attachment; filename="result.png"'})
            raise AssertionError(f"Unexpected external action: {request.url}")

        self.manager = RemoteJobManager(self.settings, transport=httpx.MockTransport(transport))
        self.app = create_app(self.settings)
        self.app.state.remote_jobs = self.manager

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.temp.cleanup()

    async def submit(self, *, admin=False, pool="P/N", five=True):
        token = self.settings.admin_token if admin else self.settings.lite_token
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                    base_url="http://test") as client:
            response = await client.post("/api/v1/lite/jobs",
                headers={"Authorization": "Bearer " + token},
                json={"kind": "random", "target_id": "main-group", "deliver_to_im": False,
                      "five_draw": five, "pool_filter": pool, "character": "海风",
                      "character_mode": False, "style": "il2", "lighting_key": "lighting_soft_diffuse"})
            self.assertEqual(response.status_code, 202, response.text)
            await asyncio.gather(*tuple(self.manager._tasks))
            job = self.manager.get(response.json()["id"])
            self.assertEqual(job.status, "succeeded", job.message)
        self.assertEqual(self.settings.prompt_favorites_path.read_bytes(), self.before)
        self.assertEqual(list((self.settings.plugin_data_dir / "safety/tickets").glob("*.json")), [])
        return self.plugin._deliver_random_draw_plans.await_args.kwargs

    async def test_actual_app_PN_five_draw_reads_legacy_owner_not_webchat_name(self):
        args = await self.submit()
        self.assertEqual(len(args["draw_plans"]), 5)
        for item, options, selection in args["draw_plans"]:
            self.assertIn("legacy-owner", item["prompt"])
            self.assertIn("rain", item["prompt"])
            self.assertEqual(options["character"], "海风")
            self.assertEqual(options["style"], "il2")
            self.assertEqual(selection["safety_codes"], ["N"])
        self.assertEqual(self.tickets[0]["favorites_owner"], "legacy-owner")
        self.assertNotIn("legacy-owner", self.chat[0]["username"])

    async def test_admin_reads_admin_not_legacy_collection(self):
        args = await self.submit(admin=True, five=False)
        self.assertIn("administrator", args["draw_plans"][0][0]["prompt"])
        self.assertEqual(self.tickets[0]["favorites_owner"], "administrator")

    async def test_implicit_default_sources_also_have_owner_capability(self):
        await self.submit(pool="N", five=False)
        self.assertEqual(self.tickets[0]["favorites_owner"], "legacy-owner")
