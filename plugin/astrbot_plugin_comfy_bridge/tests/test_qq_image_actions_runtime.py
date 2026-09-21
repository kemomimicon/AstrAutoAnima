import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_comfy_bridge.qq_image_actions_runtime import submit_action
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_body


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *args): pass


class QQActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_uses_event_identity_and_selected_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = SimpleNamespace(get_platform_name=lambda: 'aiocqhttp', get_sender_id=lambda: '123456')
            response = SimpleNamespace(status=200, json=AsyncMock(return_value={'message': '已举报'}))
            session = SimpleNamespace(post=Mock(return_value=Context(response)))
            with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.aiohttp.ClientTimeout', return_value=None), patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.aiohttp.ClientSession', return_value=Context(session)) as factory:
                result = await submit_action(root, 'http://127.0.0.1:6278', event,
                    {'job_id': 'job_1', 'result': {'assets': ['first', 'second']}}, 1, 'report', '构图奇怪')
            self.assertEqual(result, '已举报')
            tickets = list((root / 'hub_state' / 'qq_image_actions').glob('*.json'))
            data = json.loads(tickets[0].read_text(encoding='utf-8'))
            self.assertEqual(data['qq'], '123456')
            self.assertEqual(data['asset_id'], 'second')
            self.assertEqual(data['reason'], '构图奇怪')
            self.assertFalse(factory.call_args.kwargs['trust_env'])
            self.assertFalse(session.post.call_args.kwargs['allow_redirects'])
            response.status = 404
            with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.aiohttp.ClientTimeout', return_value=None), patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.aiohttp.ClientSession', return_value=Context(session)):
                with self.assertRaisesRegex(WorkflowError, 'Hub 尚未更新'):
                    await submit_action(root, 'http://127.0.0.1:6278', event,
                        {'job_id': 'job_1', 'result': {'assets': ['first']}}, 0, 'favorite')

    async def test_external_hub_and_overlong_reason_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            event = SimpleNamespace(get_platform_name=lambda: 'aiocqhttp', get_sender_id=lambda: '123456')
            with self.assertRaises(WorkflowError):
                await submit_action(Path(directory), 'https://example.com', event, {}, 0, 'report')
            with self.assertRaises(WorkflowError):
                await submit_action(Path(directory), 'http://127.0.0.1:6278', event, {}, 0, 'report', 'a'*501)
            self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_without_authorized_quote_no_action_is_submitted(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_qq_image_action')
        ns = {'logger': Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'action', 'exec'), ns)
        event = SimpleNamespace(should_call_llm=Mock(), stop_event=Mock(), send=AsyncMock(), plain_result=lambda text: text)
        bridge = SimpleNamespace(_quoted_job=AsyncMock(side_effect=WorkflowError('必须引用图片')))
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action', new_callable=AsyncMock) as send:
            await ns['_qq_image_action'](bridge, event, 'favorite')
            send.assert_not_awaited()
        self.assertIn('必须引用图片', event.send.await_args.args[0])

    def test_report_reason_body(self):
        for prefix in ['举报', '举报图片', '/areport', '/举报']:
            self.assertEqual(extract_command_body(prefix + ' 构图异常', command='areport'), '构图异常')
