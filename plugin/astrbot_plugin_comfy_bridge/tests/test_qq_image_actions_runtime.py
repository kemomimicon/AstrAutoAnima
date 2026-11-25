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
        ns = {'logger': Mock(), '__package__': 'astrbot_plugin_comfy_bridge'}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'action', 'exec'), ns)
        event = SimpleNamespace(should_call_llm=Mock(), stop_event=Mock(), send=AsyncMock(), plain_result=lambda text: text)
        bridge = SimpleNamespace(_quoted_job=AsyncMock(side_effect=WorkflowError('必须引用图片')))
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action', new_callable=AsyncMock) as send:
            await ns['_qq_image_action'](bridge, event, 'favorite')
            send.assert_not_awaited()
        self.assertIn('必须引用图片', event.send.await_args.args[0])

    def action_fixture(self, send_effect=None):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        methods = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                   and n.name in {'_qq_image_action', '_handle_quoted_selection'}]
        ns = {'logger': Mock(), '__package__': 'astrbot_plugin_comfy_bridge',
              'WorkflowError': WorkflowError, 'delivery_scope': lambda event: 'scope'}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'action', 'exec'), ns)
        event = SimpleNamespace(should_call_llm=Mock(), stop_event=Mock(),
            send=AsyncMock(side_effect=send_effect), plain_result=lambda text: text,
            message_str='收藏1,3')
        job = {'job_id': 'job1', 'result': {'assets': ['first', 'second']}}
        bridge = SimpleNamespace(_quoted_job=AsyncMock(return_value=(job, 0)),
            _character_dictionary_path=lambda: Path('/unused/characters.json'), config={})
        return ns, event, bridge, job

    async def test_saved_but_ack_timeout_does_not_resubmit_or_claim_failure(self):
        ns, event, bridge, _ = self.action_fixture([RuntimeError('sendMsg Timeout'), None])
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                   new_callable=AsyncMock, return_value='已收藏可复用提示词') as submit:
            await ns['_qq_image_action'](bridge, event, 'favorite')
        submit.assert_awaited_once()
        messages = [call.args[0] for call in event.send.await_args_list]
        self.assertEqual(len(messages), 2)
        self.assertIn('收藏已保存', messages[-1])
        self.assertIn('无需重复提交', messages[-1])
        self.assertFalse(any('操作未完成' in text or 'sendMsg Timeout' in text for text in messages))

    async def test_both_notices_fail_without_escaping_or_retrying_mutation(self):
        ns, event, bridge, _ = self.action_fixture(RuntimeError('transport unavailable'))
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                   new_callable=AsyncMock, return_value='已收藏') as submit:
            await ns['_qq_image_action'](bridge, event, 'favorite')
        submit.assert_awaited_once()
        self.assertEqual(event.send.await_count, 2)

    async def test_real_save_error_is_not_reported_as_success_even_if_notice_fails(self):
        ns, event, bridge, _ = self.action_fixture(RuntimeError('transport unavailable'))
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                   new_callable=AsyncMock, side_effect=WorkflowError('旧任务缺少可靠快照')) as submit:
            await ns['_qq_image_action'](bridge, event, 'favorite')
        submit.assert_awaited_once()
        event.send.assert_awaited_once()
        self.assertIn('操作未完成：旧任务缺少可靠快照', event.send.await_args.args[0])
        self.assertNotIn('已保存', event.send.await_args.args[0])

    async def test_success_sends_only_original_confirmation(self):
        ns, event, bridge, _ = self.action_fixture()
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                   new_callable=AsyncMock, return_value='已经收藏') as submit:
            await ns['_qq_image_action'](bridge, event, 'favorite')
        submit.assert_awaited_once()
        event.send.assert_awaited_once_with('已经收藏')

    async def test_unfavorite_and_report_notices_reflect_completed_action(self):
        for action, label in [('unfavorite', '已取消收藏'), ('report', '举报已提交')]:
            with self.subTest(action=action):
                ns, event, bridge, _ = self.action_fixture([RuntimeError('timeout'), None])
                with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                           new_callable=AsyncMock, return_value='完成') as submit:
                    await ns['_qq_image_action'](bridge, event, action)
                submit.assert_awaited_once()
                self.assertTrue(event.send.await_args.args[0].startswith(label))

    async def test_multiselect_continues_after_failed_ack_without_resubmission(self):
        ns, event, bridge, job = self.action_fixture(RuntimeError('send timeout'))
        bridge._job_store = lambda: SimpleNamespace(selected_draws=Mock(
            return_value=[(1, job, 0), (3, job, 1)]))
        async def quoted(event):
            return getattr(event, '_aaa_selected_quote', (job, 0))
        bridge._quoted_job = quoted
        async def favorite(event, reason):
            await ns['_qq_image_action'](bridge, event, 'favorite', reason)
        bridge.afavorite = favorite
        with patch('astrbot_plugin_comfy_bridge.qq_image_actions_runtime.submit_action',
                   new_callable=AsyncMock, return_value='已收藏') as submit:
            await ns['_handle_quoted_selection'](bridge, event, 'afavorite', '1,3')
        self.assertEqual([c.args[4] for c in submit.await_args_list], [0, 1])
        self.assertEqual(event.send.await_count, 4)
        self.assertEqual(event.message_str, '收藏1,3')
        self.assertFalse(hasattr(event, '_aaa_selected_quote'))

    def test_report_reason_body(self):
        for prefix in ['举报', '举报图片', '/areport', '/举报']:
            self.assertEqual(extract_command_body(prefix + ' 构图异常', command='areport'), '构图异常')
