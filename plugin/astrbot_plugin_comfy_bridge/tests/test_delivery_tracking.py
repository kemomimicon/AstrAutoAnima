import tempfile
import ast
import re
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from PIL import Image, PngImagePlugin
from astrbot_plugin_comfy_bridge.job_runtime import JobStore
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.delivery_runtime import send_tracked_image, delivery_scope


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root / 'jobs')
        self.source = {'platform': 'qq', 'session_id': 'group:123', 'user_id': '456'}
        self.job = self.store.create_job(workflow_type='test', workflow_version='1', profile='', source=self.source, input_data={})
        self.path = self.root / 'out.png'
        meta = PngImagePlugin.PngInfo()
        meta.add_text('workflow', 'original')
        Image.new('RGB', (8, 8), 'red').save(self.path, pnginfo=meta)
        self.asset = self.store.register_asset(self.path, asset_type='result', job_id=self.job['job_id'], source='test')
        self.job['result']['assets'] = [self.asset['asset_id']]
        self.store.save_job(self.job)

    def tearDown(self):
        self.temp.cleanup()

    async def test_receipt_binds_message_and_session_without_duplicate_send(self):
        event = SimpleNamespace(bot=SimpleNamespace(call_action=AsyncMock(return_value={'message_id': 789})),
            get_platform_name=lambda: 'aiocqhttp', get_group_id=lambda: '123', get_sender_id=lambda: '456',
            unified_msg_origin='qq:GroupMessage:123', message_obj=SimpleNamespace(self_id='999'), send=AsyncMock())
        await send_tracked_image(event, self.path, self.store, self.job['job_id'], 0, Mock())
        event.send.assert_not_awaited()
        self.assertEqual(event.bot.call_action.await_args.args[0], 'send_group_msg')
        job, index = self.store.parent_for_message('789', delivery_scope(event))
        self.assertEqual((job['job_id'], index), (self.job['job_id'], 0))
        self.assertIsNone(self.store.parent_for_message('789', 'other-session'))

    async def test_quoted_job_uses_receipt_without_downloading_compressed_image(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_quoted_job')
        class Reply:
            id = '789'
        namespace = dict(globals(), Comp=SimpleNamespace(Reply=Reply))
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'quote', 'exec'), namespace)
        event = SimpleNamespace(unified_msg_origin='qq:GroupMessage:123', message_obj=SimpleNamespace(self_id='999'), get_messages=lambda: [Reply()])
        self.store.record_delivery('789', delivery_scope(event), self.job['job_id'], 0)
        resolver = SimpleNamespace(_raw_segments=lambda event: [], resolve=AsyncMock())
        bridge = SimpleNamespace(_job_store=lambda: self.store, _event_source=lambda event: self.source, _image_resolver=resolver)
        job, index = await namespace['_quoted_job'](bridge, event)
        resolver.resolve.assert_not_awaited()
        self.assertEqual((job['job_id'], index), (self.job['job_id'], 0))

    def test_metadata_only_change_matches_but_different_pixels_do_not(self):
        clean = self.root / 'clean.png'
        Image.new('RGB', (8, 8), 'red').save(clean)
        asset, job = self.store.parent_for_image(clean, self.source)
        self.assertEqual(asset['asset_id'], self.asset['asset_id'])
        self.assertEqual(job['job_id'], self.job['job_id'])
        self.assertEqual(self.store.parent_for_image(clean, {**self.source, 'session_id': 'other'}), (None, None))
        Image.new('RGB', (8, 8), 'blue').save(clean)
        self.assertEqual(self.store.parent_for_image(clean, self.source), (None, None))
