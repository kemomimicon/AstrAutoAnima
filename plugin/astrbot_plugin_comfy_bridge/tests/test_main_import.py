import sys
import tempfile
import types
import unittest
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
                event, {"style": "demo_style"}, "extra tags"
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
                        {"style": "demo_style"},
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
                "模式=场景 角色=demo_character 画风=demo_style rainy night"
            )
            self.assertEqual(preset, "scene")
            self.assertEqual(options["character"], "demo_character")
            self.assertEqual(options["style"], "demo_style")
            self.assertEqual(extra, "rainy night")
            self.assertEqual(categories, ())
            self.assertFalse(reverse_only)


if __name__ == "__main__":
    unittest.main()
