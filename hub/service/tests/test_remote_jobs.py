from __future__ import annotations

import json
import tempfile
import unittest
import asyncio
import base64
from pathlib import Path

import httpx

from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.remote_jobs import (
    RemoteJobError,
    build_remote_command,
    list_delivery_targets,
    load_delivery_targets,
    RemoteJobManager,
    visible_delivery_targets,
)
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest


class RemoteJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "targets.json"
        self.path.write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "id": "main-group",
                            "label": "Main group",
                            "kind": "group",
                            "umo": "demo-bot:GroupMessage:123456",
                            "allow_safety": ["N", "H"],
                        },
                        {
                            "id": "owner-private",
                            "label": "Owner",
                            "kind": "private",
                            "umo": "demo-bot:FriendMessage:654321",
                            "allow_safety": ["N", "H", "S"],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.settings = Settings(
            admin_token="a" * 32,
            lite_token="b" * 32,
            delivery_targets_override=self.path,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_public_target_list_hides_umo(self) -> None:
        result = list_delivery_targets(self.settings)
        payload = result.model_dump()
        self.assertEqual(len(payload["targets"]), 2)
        self.assertNotIn("umo", payload["targets"][0])

    def test_bound_user_gets_only_group_and_own_private_target(self) -> None:
        principal = AuthPrincipal(
            role="user",
            subject="qq-987654",
            label="Tester",
            qq="987654",
        )
        manager = RemoteJobManager(self.settings)
        targets = manager.targets(principal).model_dump()["targets"]
        self.assertEqual([target["id"] for target in targets], ["main-group", "self-private"])
        private = next(
            record
            for record in visible_delivery_targets(self.settings, principal)
            if record.public.id == "self-private"
        )
        self.assertEqual(private.umo, "your-bot-id:FriendMessage:987654")

    def test_group_random_defaults_to_normal(self) -> None:
        target = load_delivery_targets(self.path)[0]
        command, safety = build_remote_command(
            RemoteJobCreateRequest(
                target_id="main-group",
                kind="random",
                character="demo_character",
            ),
            target,
        )
        self.assertEqual(command, "来张好图抄一抄 N 角色=demo_character")
        self.assertEqual(safety, "N")

    def test_sampler_preset_is_forwarded_before_prompt(self) -> None:
        target = load_delivery_targets(self.path)[1]
        command, safety = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="direct",
                sampler="2m_sde",
                steps=36,
                cfg=5.5,
                prompt="1girl, solo",
            ),
            target,
        )
        self.assertEqual(
            command,
            "/aimg 采样器=2m_sde 步数=36 CFG=5.5 1girl, solo",
        )
        self.assertEqual(safety, "N")

        chaos_command, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="chaos",
                sampler="2m_sde_gpu",
            ),
            target,
        )
        self.assertEqual(
            chaos_command,
            "来张好图混沌时刻 N 采样器=2m_sde_gpu",
        )

    def test_chinese_and_reverse_commands_reuse_generation_presets(self) -> None:
        group, private = load_delivery_targets(self.path)
        chinese, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="main-group",
                kind="chinese",
                character="demo_character",
                style="demo_style",
                ratio="2:3",
                prompt="雨夜里撑伞",
            ),
            group,
        )
        self.assertEqual(
            chinese,
            "/aicn 角色=demo_character 画风=demo_style 比例=2:3 雨夜里撑伞",
        )
        reverse, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="reverse",
                reverse_preset="scene",
                character="demo_character_2",
                style="demo_style",
                prompt="transparent umbrella",
            ),
            private,
        )
        self.assertEqual(
            reverse,
            "/aip 模式=scene 角色=demo_character_2 画风=demo_style transparent umbrella",
        )

        reverse_multi, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="reverse",
                reverse_categories=["scene", "action", "composition"],
                reverse_only=True,
            ),
            private,
        )
        self.assertEqual(
            reverse_multi,
            "/aip 仅反推 分类=场景,动作,构图",
        )

    def test_reverse_delivery_rejects_group_target(self) -> None:
        group = load_delivery_targets(self.path)[0]
        with self.assertRaisesRegex(RemoteJobError, "private target"):
            build_remote_command(
                RemoteJobCreateRequest(
                    target_id="main-group",
                    kind="reverse",
                ),
                group,
            )

    def test_group_accepts_h_rejects_s_and_private_accepts_s(self) -> None:
        group, private = load_delivery_targets(self.path)
        group_command, group_safety = build_remote_command(
            RemoteJobCreateRequest(
                target_id="main-group",
                kind="random",
                pool_filter="D/H",
            ),
            group,
        )
        self.assertEqual(group_command, "来张好图抄一抄 D/H")
        self.assertEqual(group_safety, "H")
        with self.assertRaisesRegex(RemoteJobError, "does not allow"):
            build_remote_command(
                RemoteJobCreateRequest(
                    target_id="main-group",
                    kind="random",
                    pool_filter="C/S",
                ),
                group,
            )
        command, safety = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="chaos",
                pool_filter="C/S",
            ),
            private,
        )
        self.assertEqual(command, "来张好图混沌时刻 C/S")
        self.assertEqual(safety, "S")

    def test_direct_requires_prompt(self) -> None:
        target = load_delivery_targets(self.path)[1]
        with self.assertRaisesRegex(RemoteJobError, "requires a prompt"):
            build_remote_command(
                RemoteJobCreateRequest(
                    target_id="owner-private",
                    kind="direct",
                ),
                target,
            )

    def test_hq_and_refine_commands_forward_profiles_and_enhancement(self) -> None:
        target = load_delivery_targets(self.path)[1]
        hq, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="hq",
                profile="beauty",
                character="demo_character",
                style="demo_style",
                ratio="2:3",
                sampler="2m_sde_gpu",
                steps=38,
                cfg=4.5,
                scale=1.5,
                denoise=0.3,
                prompt="rainy street",
            ),
            target,
        )
        self.assertEqual(
            hq,
            "/ahq beauty 角色=demo_character 画风=demo_style 比例=2:3 "
            "采样器=2m_sde_gpu 步数=38 CFG=4.5 放大=1.5 重绘=0.3 rainy street",
        )

        refine, _ = build_remote_command(
            RemoteJobCreateRequest(
                target_id="owner-private",
                kind="refine",
                profile="medium",
                parent_job_id="job_20260821_test",
                scale=1.5,
                denoise=0.35,
            ),
            target,
        )
        self.assertEqual(
            refine,
            "/arefine medium 放大=1.5 重绘=0.35 任务=job_20260821_test",
        )

    def test_refine_without_source_requires_parent_job(self) -> None:
        target = load_delivery_targets(self.path)[1]
        payload = RemoteJobCreateRequest(
            target_id="owner-private",
            kind="refine",
            profile="light",
        )
        with self.assertRaisesRegex(RemoteJobError, "requires a source image"):
            from astr_auto_anima_hub.remote_jobs import _decode_source_image

            _decode_source_image(payload)

class RemoteJobManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.image = root / "result.png"
        self.image.write_bytes(b"fake-png")
        self.targets = root / "targets.json"
        self.targets.write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "id": "private",
                            "label": "Private",
                            "kind": "private",
                            "umo": "demo-bot:FriendMessage:123456",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.sent_payload: dict = {}
        self.chat_payload: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/chat":
                self.chat_payload = json.loads(request.content)
                command_part = self.chat_payload.get("message", "")
                if isinstance(command_part, list):
                    command_part = command_part[0].get("text", "")
                if "仅反推" in str(command_part):
                    body = (
                        'data: {"type":"plain","data":"场景：rainy street\\n动作：sitting\\n安全级别：normal\\n合并提示词：rainy street, sitting\\n反推记录：rev_test"}\n\n'
                        + 'data: {"type":"end","data":""}\n\n'
                    )
                else:
                    body = (
                        'data: {"type":"plain","data":"生成完成｜任务=test"}\n\n'
                        + "data: "
                        + json.dumps(
                            {
                                "type": "attachment_saved",
                                "data": {
                                    "id": "existing-attachment",
                                    "type": "image",
                                },
                            }
                        )
                        + "\n\n"
                        + 'data: {"type":"end","data":""}\n\n'
                    )
                return httpx.Response(
                    200,
                    text=body,
                    headers={"content-type": "text/event-stream"},
                )
            if request.url.path == "/api/v1/file":
                if request.method == "GET":
                    return httpx.Response(
                        200,
                        content=b"\x89PNG\r\n\x1a\nfake-png",
                        headers={
                            "content-type": "application/octet-stream",
                            "content-disposition": 'attachment; filename="result.png"',
                        },
                    )
                return httpx.Response(
                    200, json={"data": {"attachment_id": "attachment-1"}}
                )
            if request.url.path == "/generated.png":
                return httpx.Response(
                    200,
                    content=b"remote-png",
                    headers={"content-type": "image/png"},
                )
            if request.url.path == "/api/v1/im/message":
                self.sent_payload = json.loads(request.content)
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404)

        self.settings = Settings(
            admin_token="a" * 32,
            lite_token="b" * 32,
            astrbot_api_key="abk_test",
            astrbot_url="http://astrbot.test",
            delivery_targets_override=self.targets,
            plugin_data_dir=root / "plugin_data",
        )
        self.manager = RemoteJobManager(
            self.settings, transport=httpx.MockTransport(handler)
        )

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.temp.cleanup()

    async def test_chat_image_is_uploaded_and_sent_to_target(self) -> None:
        job = self.manager.create(
            RemoteJobCreateRequest(
                target_id="private",
                kind="direct",
                prompt="1girl, solo",
            )
        )
        for _ in range(50):
            current = self.manager.get(job.id)
            if current and current.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        current = self.manager.get(job.id)
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "succeeded")
        self.assertEqual(
            self.sent_payload["umo"], "demo-bot:FriendMessage:123456"
        )
        self.assertEqual(
            self.sent_payload["message"][-1],
            {"type": "image", "attachment_id": "existing-attachment"},
        )
        self.assertEqual(len(current.images), 1)
        stored = self.manager.get_image(job.id, current.images[0].id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored[1].read_bytes(), b"\x89PNG\r\n\x1a\nfake-png")

    async def test_history_persists_and_isolated_by_user(self) -> None:
        owner = AuthPrincipal(
            role="user",
            subject="owner-1",
            label="Owner",
            qq="123456",
        )
        stranger = AuthPrincipal(
            role="user",
            subject="owner-2",
            label="Stranger",
            qq="654321",
        )
        job = self.manager.create(
            RemoteJobCreateRequest(
                target_id="self-private",
                kind="direct",
                prompt="1girl, solo",
            ),
            owner,
        )
        for _ in range(50):
            current = self.manager.get(job.id, owner)
            if current and current.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        current = self.manager.get(job.id, owner)
        self.assertEqual(current.status, "succeeded")
        self.assertEqual(self.manager.list(owner).total, 1)
        self.assertEqual(self.manager.list(stranger).total, 0)
        self.assertIsNone(self.manager.get(job.id, stranger))
        self.assertIsNone(
            self.manager.get_image(job.id, current.images[0].id, stranger)
        )

        reloaded = RemoteJobManager(self.settings)
        try:
            persisted = reloaded.get(job.id, owner)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.status, "succeeded")
            self.assertEqual(len(persisted.images), 1)
            self.assertIsNotNone(
                reloaded.get_image(job.id, persisted.images[0].id, owner)
            )
        finally:
            await reloaded.shutdown()

    async def test_data_uri_and_http_media_references_can_be_uploaded(self) -> None:
        async with self.manager._client() as client:
            data_attachment = await self.manager._upload_reference(
                client,
                "data:image/png;base64,ZmFrZS1wbmc=",
            )
            http_attachment = await self.manager._upload_reference(
                client,
                "http://media.test/generated.png",
            )
        self.assertEqual(data_attachment, "attachment-1")
        self.assertEqual(http_attachment, "attachment-1")

    async def test_reverse_source_image_is_uploaded_into_chat_message(self) -> None:
        source = b"\x89PNG\r\n\x1a\nreverse-source"
        job = self.manager.create(
            RemoteJobCreateRequest(
                target_id="private",
                kind="reverse",
                reverse_preset="raw",
                character="demo_character",
                style="demo_style",
                source_image_name="source.png",
                source_image_data=(
                    "data:image/png;base64," + base64.b64encode(source).decode("ascii")
                ),
            )
        )
        for _ in range(50):
            current = self.manager.get(job.id)
            if current and current.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        current = self.manager.get(job.id)
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "succeeded")
        self.assertEqual(
            self.chat_payload["message"],
            [
                {
                    "type": "plain",
                    "text": "/aip 模式=raw 角色=demo_character 画风=demo_style",
                },
                {"type": "image", "attachment_id": "attachment-1"},
            ],
        )

    async def test_reverse_multiselect_only_is_forwarded_to_chat(self) -> None:
        source = b"\x89PNG\r\n\x1a\nreverse-source"
        job = self.manager.create(
            RemoteJobCreateRequest(
                target_id="private",
                kind="reverse",
                reverse_categories=["scene", "action", "safety"],
                reverse_only=True,
                source_image_name="source.png",
                source_image_data=(
                    "data:image/png;base64," + base64.b64encode(source).decode("ascii")
                ),
            )
        )
        for _ in range(50):
            current = self.manager.get(job.id)
            if current and current.status in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(
            self.chat_payload["message"][0],
            {
                "type": "plain",
                "text": "/aip 仅反推 分类=场景,动作,安全",
            },
        )
        current = self.manager.get(job.id)
        self.assertEqual(current.status, "succeeded")
        self.assertEqual(self.sent_payload["message"][0]["type"], "plain")
        self.assertIn("反推记录：rev_test", self.sent_payload["message"][0]["text"])
        self.assertEqual(len(self.sent_payload["message"]), 1)


if __name__ == "__main__":
    unittest.main()
