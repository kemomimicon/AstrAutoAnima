import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_comfy_bridge.tests.test_main_import import ComfyWorkflowBridge
from astrbot_plugin_comfy_bridge.image_runtime import EventImageResolver
from astrbot_plugin_comfy_bridge import image_runtime
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.telegram_menu_runtime import (
    CANCEL, CONFIRM, EDIT, LAUNCH, MODES, SKIP, Draft, chat_and_thread,
)


class _Markup:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _Event:
    def __init__(self, text="", *, group=False, reply=""):
        self.message_str = text
        self.unified_msg_origin = "telegram:GroupMessage:-100123" if group else "telegram:FriendMessage:123"
        self._group = group
        self._reply = reply
        self.message_obj = types.SimpleNamespace(message_id="42", self_id="mybot")
        self.client = types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=99)))
        self.send = AsyncMock()
        self.stopped = False

    def get_platform_name(self):
        return "telegram"

    def get_session_id(self):
        return "-100123#7" if self._group else "123"

    def get_sender_id(self):
        return "456"

    def get_messages(self):
        return [type("Reply", (), {"id": self._reply})()] if self._reply else []

    def plain_result(self, text):
        return text

    def should_call_llm(self, _value):
        pass

    def stop_event(self):
        self.stopped = True


class TelegramMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = sys.modules.get("telegram")
        sys.modules["telegram"] = types.SimpleNamespace(
            ReplyKeyboardMarkup=_Markup, ReplyKeyboardRemove=_Markup,
        )
        self.bridge = object.__new__(ComfyWorkflowBridge)
        self.bridge._telegram_menu_drafts = {}
        self.bridge._platform_admit = Mock()

    def tearDown(self):
        if self.previous is None:
            del sys.modules["telegram"]
        else:
            sys.modules["telegram"] = self.previous

    async def test_private_text_mode_and_confirm_dispatch(self):
        async def aimg(event, body):
            self.assertEqual(body, "角色=星空 夜景")
            self.assertEqual(event.message_str, "/aimg 角色=星空 夜景")
            yield "generated"

        self.bridge.aimg = aimg
        for text in (LAUNCH, "🖌 普通生图", "角色=星空 夜景", CONFIRM):
            event = _Event(text)
            await self.bridge.telegram_menu_route(event)
            self.assertTrue(event.stopped)
        self.assertEqual(event.message_str, CONFIRM)
        event.send.assert_awaited_once_with("generated")
        self.assertFalse(self.bridge._telegram_menu_drafts)

    async def test_group_free_text_requires_reply_to_menu_prompt(self):
        selected = _Event("🖌 普通生图", group=True)
        await self.bridge.telegram_menu_route(selected)
        sent = selected.client.send_message.await_args.kwargs
        self.assertEqual(sent["chat_id"], -100123)
        self.assertEqual(sent["message_thread_id"], 7)
        self.assertEqual(sent["reply_to_message_id"], 42)
        self.assertTrue(sent["reply_markup"].kwargs["selective"])
        draft = next(iter(self.bridge._telegram_menu_drafts.values()))
        self.assertEqual(draft.prompt_message_id, "99")
        unrelated = _Event("rainy street", group=True)
        await self.bridge.telegram_menu_route(unrelated)
        self.assertFalse(unrelated.stopped)
        self.assertEqual(draft.stage, "input")
        response = _Event("/@mybot rainy street", group=True, reply="99")
        await self.bridge.telegram_menu_route(response)
        self.assertEqual(draft.body, "rainy street")
        self.assertEqual(draft.stage, "confirm")

    async def test_optional_mode_can_skip_and_cancel(self):
        await self.bridge.telegram_menu_route(_Event("🎲 抽一抽"))
        await self.bridge.telegram_menu_route(_Event(SKIP))
        draft = next(iter(self.bridge._telegram_menu_drafts.values()))
        self.assertEqual(draft.body, "")
        self.assertEqual(draft.stage, "confirm")
        await self.bridge.telegram_menu_route(_Event(CANCEL))
        self.assertFalse(self.bridge._telegram_menu_drafts)

    async def test_image_mode_keeps_source_through_confirmation(self):
        self.bridge._quoted_job = AsyncMock(side_effect=WorkflowError("not a tracked image"))
        self.bridge._image_resolver = types.SimpleNamespace(resolve=AsyncMock(return_value="/tmp/test.png"))
        async def aip(event, body):
            self.assertEqual(body, "雨夜")
            self.assertEqual(event._aaa_menu_source_image, "/tmp/test.png")
        self.bridge.aip = aip
        await self.bridge.telegram_menu_route(_Event("📷 反推生图"))
        picture = _Event("雨夜")
        await self.bridge.telegram_menu_route(picture)
        self.assertEqual(next(iter(self.bridge._telegram_menu_drafts.values())).stage, "confirm")
        await self.bridge.telegram_menu_route(_Event(EDIT))
        edited = _Event("雨夜")
        await self.bridge.telegram_menu_route(edited)
        self.assertEqual(next(iter(self.bridge._telegram_menu_drafts.values())).image_path, "/tmp/test.png")
        confirmed = _Event(CONFIRM)
        await self.bridge.telegram_menu_route(confirmed)
        self.assertFalse(hasattr(confirmed, "_aaa_menu_source_image"))
        self.assertFalse(self.bridge._telegram_menu_drafts)

    async def test_other_group_user_does_not_take_draft(self):
        await self.bridge.telegram_menu_route(_Event("🖌 普通生图", group=True))
        other = _Event("some text", group=True, reply="99")
        other.get_sender_id = lambda: "999"
        await self.bridge.telegram_menu_route(other)
        self.assertFalse(other.stopped)
        self.assertEqual(len(self.bridge._telegram_menu_drafts), 1)

    def test_mode_coverage_and_topic(self):
        self.assertEqual(len(MODES), 13)
        self.assertEqual(chat_and_thread(_Event(group=True)), (-100123, 7))
        self.assertTrue(Draft("x", "input", 0).expired(601))

    async def test_telegram_image_document_is_accepted(self):
        class File:
            def __init__(self, path):
                self.name = "original.png"
                self.file = str(path)
                self.url = ""
        previous = getattr(image_runtime.Comp, "File", None)
        image_runtime.Comp.File = File
        try:
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "original.png"
                source.write_bytes(b"png-test")
                event = _Event()
                event.get_messages = lambda: [File(source)]
                resolver = EventImageResolver(Path(directory) / "inputs", Mock())
                saved = await resolver.resolve(event)
                self.assertEqual(Path(saved).read_bytes(), b"png-test")
                self.assertNotEqual(Path(saved), source)
        finally:
            if previous is None:
                del image_runtime.Comp.File
            else:
                image_runtime.Comp.File = previous


if __name__ == "__main__":
    unittest.main()
