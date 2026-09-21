import ast
import copy
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, Mock
from PIL import Image
from test_delivery_tracking import DeliveryTests
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_body
from astrbot_plugin_comfy_bridge.replay_runtime import replay_workflow
from astrbot_plugin_comfy_bridge.delivery_runtime import send_tracked_image, delivery_scope
from astrbot_plugin_comfy_bridge.safety_runtime import positive_texts


@asynccontextmanager
async def context(**kwargs):
    yield object()


class QQRemakeTests(DeliveryTests):
    async def test_chinese_route_to_batch_replay_and_new_quote(self):
        class Reply:
            id = '789'
        reply = Reply()
        event = SimpleNamespace(
            message_str='重跑一张', message_obj=SimpleNamespace(self_id='999'),
            unified_msg_origin='qq:GroupMessage:123', get_messages=lambda: [reply],
            should_call_llm=Mock(), stop_event=Mock(),
            get_platform_name=lambda: 'aiocqhttp', get_group_id=lambda: '123', get_sender_id=lambda: '456',
            bot=SimpleNamespace(call_action=AsyncMock(return_value={'message_id': 990})),
            plain_result=lambda text: text, image_result=lambda path: path, send=AsyncMock())
        second = self.store.register_asset(self.path, asset_type='result', job_id=self.job['job_id'], source='test')
        self.job['result']['assets'].append(second['asset_id'])
        self.job['input'] = {'batch_prompts': ['first compiled', 'second compiled'], 'raw_batch_prompts': ['first', 'second'],
            'source_entries': [{'id': 'G-1', 'prompt': 'first'}, {'id': 'G-2', 'prompt': 'second'}]}
        self.job['sampling'] = {'seed': 1}
        self.job['workflow_snapshot'] = {
            '1': {'class_type': 'KSampler', 'inputs': {'seed': 1}},
            '2': {'class_type': 'AnimaPromptBatchEncode', 'inputs': {'prompts_json': '["first compiled","second compiled"]'}},
            '3': {'class_type': 'EmptyLatentImage', 'inputs': {'batch_size': 2}}}
        self.store.save_job(self.job)
        self.store.record_delivery('789', delivery_scope(event), self.job['job_id'], 1)
        output = self.root / 'new.png'
        Image.new('RGB', (8, 8), 'blue').save(output)
        bridge = SimpleNamespace(
            config={}, _job_store=lambda: self.store, _event_source=lambda event: self.source,
            _image_resolver=SimpleNamespace(_raw_segments=lambda event: [], resolve=AsyncMock()),
            _safety_guard=Mock(), _safety_policy=lambda: SimpleNamespace(fingerprint='same'),
            _safety_input=AsyncMock(), _safety_applies=lambda event: False,
            _safety_outputs=AsyncMock(side_effect=lambda event, paths: paths),
            _generation_slot=lambda event: context(), _timeout_seconds=lambda: 5,
            _character_dictionary_path=lambda: self.root / 'dictionary.json',
            _submit_workflow=AsyncMock(return_value='comfy-id'), _wait_for_history=AsyncMock(return_value={}),
            _download_images=AsyncMock(return_value=[output]),
            _capture_pending_image=AsyncMock(), aecho=AsyncMock(), astyle=AsyncMock(), acopy=AsyncMock())
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
        methods = [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name in {'aremake', '_quoted_job', 'natural_random_picture_route'}]
        for method in methods: method.decorator_list = []
        ns = dict(globals(), __package__='astrbot_plugin_comfy_bridge', AstrMessageEvent=object,
            Comp=SimpleNamespace(Reply=Reply), logger=Mock(),
            aiohttp=SimpleNamespace(ClientSession=context, ClientTimeout=lambda **kw: kw),
            extract_output_images=lambda record: [{'filename': 'new.png'}])
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'remake', 'exec'), ns)
        bridge._quoted_job = MethodType(ns['_quoted_job'], bridge)
        bridge.aremake = MethodType(ns['aremake'], bridge)
        await ns['natural_random_picture_route'](bridge, event)
        bridge._capture_pending_image.assert_not_awaited()
        bridge._image_resolver.resolve.assert_not_awaited()
        graph = bridge._submit_workflow.await_args.args[1]
        self.assertEqual(graph['2']['inputs']['prompts_json'], '["second compiled"]')
        self.assertEqual(graph['3']['inputs']['batch_size'], 1)
        self.assertNotEqual(graph['1']['inputs']['seed'], 1)
        reply.id = '990'
        new_job, index = await bridge._quoted_job(event)
        self.assertEqual(index, 0)
        self.assertEqual(new_job['input']['source_entries'][0]['id'], 'G-2')
        self.assertEqual(new_job['input']['raw_batch_prompts'], ['second'])
        self.assertNotEqual(new_job['job_id'], self.job['job_id'])
        self.assertEqual(new_job['status'], 'completed')

    def test_chinese_command_body_and_alias_boundary(self):
        self.assertEqual(extract_command_body('重跑一张', '', 'aremake'), '')
        self.assertEqual(extract_command_body('/重跑一张', '', 'aremake'), '')
        self.assertEqual(extract_command_body('抄一抄 角色=A', '', 'acopy'), '角色=A')
