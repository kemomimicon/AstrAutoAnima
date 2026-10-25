import asyncio
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_comfy_bridge.tests.test_main_import import ComfyWorkflowBridge
from astrbot_plugin_comfy_bridge.discord_menu_runtime import Draft, draft_key, interaction_matches
from astrbot_plugin_comfy_bridge.image_runtime import EventImageResolver
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class _Event:
    def __init__(self, text="", *, sender="456", group=True):
        self.message_str = text
        self.unified_msg_origin = "discord:GroupMessage:123" if group else "discord:FriendMessage:123"
        self.message_obj = types.SimpleNamespace(type="group" if group else "friend")
        self.interaction_followup_webhook = types.SimpleNamespace(send=AsyncMock())
        self.send = AsyncMock()
        self.sender = sender
        self.stopped = False

    def get_platform_name(self):
        return "discord"

    def get_session_id(self):
        return "123"

    def get_group_id(self):
        return "123" if "Group" in self.unified_msg_origin else ""

    def get_sender_id(self):
        return self.sender

    def get_messages(self):
        return []

    def plain_result(self, text):
        return text

    def should_call_llm(self, _value):
        pass

    def stop_event(self):
        self.stopped = True


def _interaction(sender="456"):
    return types.SimpleNamespace(
        channel_id="123", user=types.SimpleNamespace(id=sender),
        response=types.SimpleNamespace(send_message=AsyncMock(), send_modal=AsyncMock()),
    )


class DiscordMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = object.__new__(ComfyWorkflowBridge)
        self.bridge._discord_menu_drafts = {}
        self.bridge._discord_menu_sources = {}
        self.bridge._discord_menu_tasks = set()
        self.bridge._platform_admit = Mock()

    async def test_private_group_menu_and_text_confirmation(self):
        event = _Event()
        with patch("astrbot_plugin_comfy_bridge.main.discord_mode_view", return_value="modes"):
            await self.bridge._discord_menu_open(event)
        calls = event.interaction_followup_webhook.send.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["delete_after"], 2)
        self.assertTrue(calls[1].kwargs["ephemeral"])
        self.assertEqual(calls[1].kwargs["view"], "modes")
        menu_id = self.bridge._discord_menu_sources[("123", "456")][0]

        selected = _interaction()
        with patch("astrbot_plugin_comfy_bridge.main.discord_prompt_modal", return_value="modal"):
            await self.bridge._discord_menu_select(selected, ("123", "456"), menu_id, "🖌 普通生图")
        selected.response.send_modal.assert_awaited_once_with("modal")
        draft_id = self.bridge._discord_menu_drafts[("123", "456")].draft_id

        entered = _interaction()
        with patch("astrbot_plugin_comfy_bridge.main.discord_confirm_view", return_value="confirm"):
            await self.bridge._discord_menu_text(entered, ("123", "456"), draft_id, "🖌 普通生图", "夜景")
        self.assertTrue(entered.response.send_message.await_args.kwargs["ephemeral"])
        self.assertEqual(entered.response.send_message.await_args.kwargs["view"], "confirm")

        async def aimg(received, body):
            self.assertEqual(body, "夜景")
            self.assertIsNone(received.interaction_followup_webhook)
            yield "generated"

        self.bridge.aimg = aimg
        confirmed = _interaction()
        await self.bridge._discord_menu_confirm(confirmed, ("123", "456"), draft_id)
        self.assertTrue(confirmed.response.send_message.await_args.kwargs["ephemeral"])
        await asyncio.gather(*self.bridge._discord_menu_tasks)
        event.send.assert_awaited_once_with("generated")
        self.assertEqual(event.message_str, "")
        self.assertIsNotNone(event.interaction_followup_webhook)
        self.assertFalse(self.bridge._discord_menu_drafts)
        self.assertFalse(self.bridge._discord_menu_sources)

    async def test_image_mode_requires_same_user_and_reply_for_job(self):
        source = _Event()
        self.bridge._discord_menu_sources[("123", "456")] = ("menu-a", source)
        other = _interaction("999")
        self.assertFalse(interaction_matches(other, ("123", "456")))
        self.assertEqual(draft_key(source), ("123", "456"))
        selected = _interaction()
        await self.bridge._discord_menu_select(selected, ("123", "456"), "menu-a", "🔁 重跑一张")
        self.assertEqual(self.bridge._discord_menu_drafts[("123", "456")].stage, "image")

        image = _Event("角色=星空")
        class Reply:
            pass
        image.get_messages = lambda: [Reply()]
        import astrbot_plugin_comfy_bridge.main as main
        original_reply = main.Comp.Reply
        main.Comp.Reply = Reply
        try:
            self.bridge._quoted_job = AsyncMock(return_value=({"result": {"assets": ["a"]}}, 0))
            with patch("astrbot_plugin_comfy_bridge.main.discord_confirm_view", return_value="confirm"):
                await self.bridge.discord_menu_image_route(image)
        finally:
            main.Comp.Reply = original_reply
        self.assertTrue(image.stopped)
        draft = self.bridge._discord_menu_drafts[("123", "456")]
        self.assertEqual(draft.stage, "confirm")
        self.assertIs(draft.image_event, image)
        self.assertEqual(draft.body, "角色=星空")
        self.assertTrue(source.interaction_followup_webhook.send.await_args.kwargs["ephemeral"])

    def test_expiry(self):
        self.assertTrue(Draft("x", time.monotonic() - 601, _Event()).expired())

    async def test_old_menu_and_old_confirmation_cannot_change_new_draft(self):
        event = _Event()
        with patch("astrbot_plugin_comfy_bridge.main.discord_mode_view", return_value="modes"):
            await self.bridge._discord_menu_open(event)
        key = ("123", "456")
        old_menu = self.bridge._discord_menu_sources[key][0]
        with patch("astrbot_plugin_comfy_bridge.main.discord_mode_view", return_value="modes"):
            await self.bridge._discord_menu_open(event)
        new_menu = self.bridge._discord_menu_sources[key][0]
        stale = _interaction()
        await self.bridge._discord_menu_select(stale, key, old_menu, "🖌 普通生图")
        self.assertFalse(self.bridge._discord_menu_drafts)
        self.assertTrue(stale.response.send_message.await_args.kwargs["ephemeral"])
        with patch("astrbot_plugin_comfy_bridge.main.discord_prompt_modal", return_value="modal"):
            await self.bridge._discord_menu_select(_interaction(), key, new_menu, "🖌 普通生图")
        old_draft_id = self.bridge._discord_menu_drafts[key].draft_id
        with patch("astrbot_plugin_comfy_bridge.main.discord_prompt_modal", return_value="modal"):
            await self.bridge._discord_menu_select(_interaction(), key, new_menu, "🖌 普通生图")
        current = self.bridge._discord_menu_drafts[key]
        await self.bridge._discord_menu_text(_interaction(), key, old_draft_id, "🖌 普通生图", "旧文字")
        await self.bridge._discord_menu_cancel(_interaction(), key, old_draft_id)
        await self.bridge._discord_menu_confirm(_interaction(), key, old_draft_id)
        self.assertIs(self.bridge._discord_menu_drafts[key], current)
        self.assertEqual(current.stage, "modal")
        self.assertFalse(current.claimed)

    async def test_old_discord_reply_attachment_can_be_resolved(self):
        attachment = types.SimpleNamespace(filename="old.png", content_type="image/png",
                                           url="https://cdn.example/old.png")
        quoted = types.SimpleNamespace(id=789, attachments=[attachment])
        channel = types.SimpleNamespace(id=123, fetch_message=AsyncMock(return_value=quoted))
        reference = types.SimpleNamespace(message_id=789, channel_id=123, resolved=None)
        event = _Event()
        event.message_obj.raw_message = types.SimpleNamespace(reference=reference, channel=channel)
        with tempfile.TemporaryDirectory() as directory:
            resolver = EventImageResolver(Path(directory), Mock())
            resolver._save_ref = AsyncMock(return_value=str(Path(directory) / "old.png"))
            result = await resolver.resolve(event)
        self.assertTrue(result.endswith("old.png"))
        channel.fetch_message.assert_awaited_once_with(789)
        resolver._save_ref.assert_awaited_once_with("https://cdn.example/old.png", "old.png")


if __name__ == "__main__":
    unittest.main()
