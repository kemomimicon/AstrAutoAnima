import sys
import tempfile
import types
import unittest
import json
from pathlib import Path


def install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    event_filter = types.ModuleType("astrbot.api.event.filter")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")
    quoted = types.ModuleType("astrbot.core.utils.quoted_message.onebot_client")
    aiohttp = types.ModuleType("aiohttp")

    def decorator(*_args, **_kwargs):
        return lambda function: function

    class PermissionType:
        ADMIN = "admin"

    class EventMessageType:
        ALL = "all"

    class FakeFilter:
        command = staticmethod(decorator)
        event_message_type = staticmethod(decorator)
        permission_type = staticmethod(decorator)
        llm_tool = staticmethod(decorator)

    FakeFilter.PermissionType = PermissionType

    class FakeLogger:
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    class Star:
        def __init__(self, context):
            self.context = context

    class Context:
        pass

    class AstrMessageEvent:
        pass

    class MessageChain:
        def message(self, _text):
            return self

        def file_image(self, _path):
            return self

    class Image:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Reply:
        def __init__(self, chain=None):
            self.chain = chain or []

    class OneBotClient:
        def __init__(self, _event):
            self._call_action = None

    class ClientError(Exception):
        pass

    aiohttp.ClientError = ClientError
    aiohttp.ClientResponse = object
    aiohttp.ClientSession = object
    aiohttp.ClientTimeout = object

    api.AstrBotConfig = dict
    api.logger = FakeLogger()
    event.AstrMessageEvent = AstrMessageEvent
    event.MessageChain = MessageChain
    event.filter = FakeFilter
    event_filter.EventMessageType = EventMessageType
    star.Context = Context
    star.Star = Star
    components.Image = Image
    components.Reply = Reply
    quoted.OneBotClient = OneBotClient

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.event.filter": event_filter,
            "astrbot.api.star": star,
            "astrbot.api.message_components": components,
            "astrbot.core": types.ModuleType("astrbot.core"),
            "astrbot.core.utils": types.ModuleType("astrbot.core.utils"),
            "astrbot.core.utils.quoted_message": types.ModuleType(
                "astrbot.core.utils.quoted_message"
            ),
            "astrbot.core.utils.quoted_message.onebot_client": quoted,
            "aiohttp": aiohttp,
        }
    )


install_astrbot_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_comfy_bridge.main import ComfyWorkflowBridge  # noqa: E402


class FakeEvent:
    unified_msg_origin = "bot:GroupMessage:12345"

    def __init__(self):
        self.sent = []
        self.stopped = False

    def get_session_id(self):
        return "12345"

    def get_sender_id(self):
        return "67890"

    def plain_result(self, text):
        return text

    async def send(self, message):
        self.sent.append(message)

    def should_call_llm(self, _value):
        pass

    def stop_event(self):
        self.stopped = True

    def is_admin(self):
        return False


class MainImportTests(unittest.TestCase):
    def test_plugin_imports_and_pending_key_is_session_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                },
            )
        self.assertEqual(
            plugin._pending_key(FakeEvent()),
            ("bot:GroupMessage:12345", "67890"),
        )

    def test_task_scheduler_overrides_preset_and_rejects_unknown_value(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                },
            )
            preset, overrides = plugin._sampler_overrides(
                {"sampler_preset": "2m_sde", "scheduler": "karras"}
            )
            self.assertEqual(preset, "2m_sde")
            self.assertEqual(overrides["sampler_name"], "dpmpp_2m_sde")
            self.assertEqual(overrides["scheduler"], "karras")
            with self.assertRaisesRegex(Exception, "调度器选项"):
                plugin._sampler_overrides({"scheduler": "unknown"})


class FakeImageResolver:
    async def resolve(self, _event):
        return "/tmp/input.png"


class PendingImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_request_is_claimed_once_and_timeout_is_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                    "image_wait_seconds": 60,
                },
            )
            event = FakeEvent()
            await plugin._begin_pending_image(
                event, {"style": "staryfs"}, "extra tags"
            )
            self.assertEqual(len(plugin._pending_images), 1)
            plugin._image_resolver = FakeImageResolver()
            captured = []

            async def fake_reverse(
                _event, path, options, extra, preset, categories, reverse_only
            ):
                captured.append(
                    (path, options, extra, preset, categories, reverse_only)
                )

            plugin._handle_reverse_generation = fake_reverse
            self.assertTrue(await plugin._capture_pending_image(event))
            self.assertEqual(plugin._pending_images, {})
            self.assertTrue(event.stopped)
            self.assertEqual(
                captured,
                [
                    (
                        "/tmp/input.png",
                        {"style": "staryfs"},
                        "extra tags",
                        "full",
                        (),
                        False,
                    )
                ],
            )
            await plugin.terminate()

    async def test_reverse_body_supports_chinese_preset_and_generation_options(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                },
            )
            extra, options, preset, categories, reverse_only = plugin._parse_reverse_body(
                "模式=场景 角色=6ctmika 画风=staryfs rainy night"
            )
            self.assertEqual(preset, "scene")
            self.assertEqual(options["character"], "6ctmika")
            self.assertEqual(options["style"], "staryfs")
            self.assertEqual(extra, "rainy night")
            self.assertEqual(categories, ())
            self.assertFalse(reverse_only)

            extra, options, preset, categories, reverse_only = plugin._parse_reverse_body(
                "角色=6ctmika 模式=完整"
            )
            self.assertEqual(options["style"], "当前画风")
            self.assertEqual(options["character"], "6ctmika")


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_agent_tool_does_not_start_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                    "agent_tools_enabled": False,
                },
            )
            result = [
                item
                async for item in plugin.anima_generate_image(
                    FakeEvent(), "1girl, solo"
                )
            ]
            self.assertEqual(result, ["AstrAutoAnima 自主绘图工具当前已关闭。"])

    async def test_agent_tool_uses_its_own_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            preset_path = Path(directory) / "presets.json"
            preset_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "styles": {"默认画风": {"loras": [], "prompt": ""}},
                        "characters": {
                            "默认角色": {"lora": None, "prompt": "1girl"}
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "preset_store_path": str(preset_path),
                    "max_concurrency": 1,
                    "agent_tools_enabled": True,
                    "agent_tool_group_enabled": True,
                    "agent_tool_default_character": "默认角色",
                    "agent_tool_default_style": "默认画风",
                    "agent_tool_default_ratio": "9:16",
                    "agent_tool_default_quality": "quick",
                    "agent_tool_default_sampler": "2m",
                    "agent_tool_default_scheduler": "karras",
                    "agent_tool_user_cooldown_seconds": 0,
                },
            )
            delivered = []

            async def fake_deliver(_event, **kwargs):
                delivered.append(kwargs)
                return True

            plugin._deliver_generation = fake_deliver
            result = [
                item
                async for item in plugin.anima_generate_image(
                    FakeEvent(), "1girl, solo, outdoors"
                )
            ]
            self.assertEqual(len(delivered), 1)
            self.assertEqual(delivered[0]["options"]["character"], "默认角色")
            self.assertEqual(delivered[0]["options"]["style"], "默认画风")
            self.assertEqual(delivered[0]["options"]["ratio"], "9:16")
            self.assertTrue(delivered[0]["strict_no_style"])
            self.assertIn("图片已生成并发送", result[0])


class FiveDrawBatchTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _plans():
        return [
            (
                {"id": f"B-{index}", "prompt": f"scene {index}"},
                {"character": "铃兰", "style": "默认画风", "ratio": "2:3"},
                {},
            )
            for index in range(1, 6)
        ]

    async def test_ordinary_five_draw_uses_2_2_1_micro_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                    "five_draw_batch_enabled": True,
                    "five_draw_micro_batch_size": 2,
                },
            )
            calls = []

            async def fake_deliver(_event, **kwargs):
                calls.append(kwargs)
                return True

            plugin._deliver_generation = fake_deliver
            successes = await plugin._deliver_random_draw_plans(
                FakeEvent(),
                draw_plans=self._plans(),
                user_prompt="extra",
                quality="quality",
                chaos=False,
            )
            self.assertEqual(successes, 5)
            self.assertEqual(
                [len(call["batch_prompts"]) for call in calls if call.get("batch_prompts")],
                [2, 2],
            )
            self.assertNotIn("batch_prompts", calls[-1])
            self.assertTrue(all(not call["send_errors"] for call in calls[:-1]))

    async def test_failed_micro_batch_falls_back_only_that_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                    "five_draw_batch_enabled": True,
                    "five_draw_micro_batch_size": 2,
                    "five_draw_batch_fallback_sequential": True,
                },
            )
            calls = []

            async def fake_deliver(_event, **kwargs):
                calls.append(kwargs)
                batch = kwargs.get("batch_prompts")
                return not (batch and "scene 3" in batch[0])

            plugin._deliver_generation = fake_deliver
            event = FakeEvent()
            successes = await plugin._deliver_random_draw_plans(
                event,
                draw_plans=self._plans(),
                user_prompt="",
                quality="",
                chaos=False,
            )
            self.assertEqual(successes, 5)
            self.assertEqual(
                [len(call["batch_prompts"]) for call in calls if call.get("batch_prompts")],
                [2, 2],
            )
            fallback_calls = [call for call in calls if not call.get("batch_prompts")]
            self.assertEqual(len(fallback_calls), 3)
            self.assertTrue(any("自动改为逐张生成" in text for text in event.sent))

    async def test_chaos_five_draw_remains_sequential(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = ComfyWorkflowBridge(
                object(),
                {
                    "input_dir": str(Path(directory) / "inputs"),
                    "max_concurrency": 1,
                    "five_draw_batch_enabled": True,
                },
            )
            calls = []

            async def fake_deliver(_event, **kwargs):
                calls.append(kwargs)
                return True

            plugin._deliver_generation = fake_deliver
            successes = await plugin._deliver_random_draw_plans(
                FakeEvent(),
                draw_plans=self._plans(),
                user_prompt="",
                quality="",
                chaos=True,
            )
            self.assertEqual(successes, 5)
            self.assertEqual(len(calls), 5)
            self.assertTrue(all("batch_prompts" not in call for call in calls))


if __name__ == "__main__":
    unittest.main()
