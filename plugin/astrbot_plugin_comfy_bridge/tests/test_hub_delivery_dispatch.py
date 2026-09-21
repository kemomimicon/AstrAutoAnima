import ast
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class HubDeliveryDispatchTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
        methods = [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name in {'aaa_hub_deliver', 'natural_random_picture_route'}]
        command = next(n for n in methods if n.name == 'aaa_hub_deliver')
        self.assertTrue(any(isinstance(n, ast.Call) and any(isinstance(a, ast.Constant) and a.value == 'aaa_hub_deliver' for a in n.args) for n in command.decorator_list))
        for node in methods:
            node.decorator_list = []
        ns = {'AstrMessageEvent': object, 'WorkflowError': WorkflowError, 'logger': Mock(), '__package__': 'astrbot_plugin_comfy_bridge'}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'hub_dispatch', 'exec'), ns)
        bridge = SimpleNamespace(context=object(), _job_store=Mock(), _character_dictionary_path=lambda: Path('/tmp/data/dictionary.json'), _capture_pending_image=AsyncMock(return_value=False))
        for node in methods:
            setattr(bridge, node.name, MethodType(ns[node.name], bridge))
        return bridge

    def event(self, text, platform='webchat'):
        return SimpleNamespace(message_str=text, stop_event=Mock(), should_call_llm=Mock(), send=AsyncMock(), plain_result=lambda text: text, get_platform_name=lambda: platform)

    async def test_wake_prefix_stripped_or_preserved(self):
        for prefix in ('/', ''):
            bridge = self.bridge()
            token = 'a' * 32
            event = self.event(prefix + 'aaa_hub_deliver ' + token)
            with patch('astrbot_plugin_comfy_bridge.hub_delivery_runtime.deliver_ticket', new_callable=AsyncMock) as deliver:
                await bridge.natural_random_picture_route(event)
                await bridge.aaa_hub_deliver(event, token)
                deliver.assert_awaited_once()
                self.assertEqual(deliver.await_args.args[-1], token)
            event.should_call_llm.assert_called_with(False)
            event.stop_event.assert_called()
            bridge._capture_pending_image.assert_not_awaited()

    async def test_registered_command_argument_fallback(self):
        bridge = self.bridge()
        event = self.event('')
        with patch('astrbot_plugin_comfy_bridge.hub_delivery_runtime.deliver_ticket', new_callable=AsyncMock) as deliver:
            await bridge.aaa_hub_deliver(event, 'b' * 32)
            self.assertEqual(deliver.await_args.args[-1], 'b' * 32)

    async def test_failure_never_falls_through_to_llm(self):
        bridge = self.bridge()
        event = self.event('aaa_hub_deliver invalid')
        with patch('astrbot_plugin_comfy_bridge.hub_delivery_runtime.deliver_ticket', new_callable=AsyncMock, side_effect=WorkflowError('bad ticket')):
            await bridge.natural_random_picture_route(event)
        event.should_call_llm.assert_called_with(False)
        self.assertIn('图片投递失败', event.send.await_args.args[0])

    async def test_qq_cannot_invoke_internal_delivery(self):
        bridge = self.bridge()
        event = self.event('aaa_hub_deliver ' + 'a' * 32, 'aiocqhttp')
        with patch('astrbot_plugin_comfy_bridge.hub_delivery_runtime.deliver_ticket', new_callable=AsyncMock) as deliver:
            await bridge.natural_random_picture_route(event)
            deliver.assert_not_awaited()
        event.should_call_llm.assert_called_with(False)

    async def test_similar_text_not_intercepted(self):
        bridge = self.bridge()
        await bridge.natural_random_picture_route(self.event('aaa_hub_delivery notes'))
        bridge._capture_pending_image.assert_awaited_once()
