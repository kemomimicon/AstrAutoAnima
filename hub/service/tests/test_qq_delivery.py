import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, Mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_comfy_bridge.job_runtime import JobStore
from astrbot_plugin_comfy_bridge.hub_delivery_runtime import deliver_ticket
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astr_auto_anima_hub.qq_delivery import deliver_image


class DeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_image_to_onebot_receipt_and_scoped_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(plugin_data_dir=root, hub_state_dir=root / 'hub_state')
            store = JobStore(root / 'job_store')
            job = store.create_job(workflow_type='quick', workflow_version='1', profile='',
                source={'platform': 'webchat', 'session_id': 'hub_job_test'}, input_data={})
            image = root / 'image.png'
            Image.new('RGB', (2, 2), 'blue').save(image)
            asset = store.register_asset(image, asset_type='result', job_id=job['job_id'], source='test')
            job['result']['assets'] = [asset['asset_id']]
            store.save_job(job)
            bot = SimpleNamespace(call_action=AsyncMock(side_effect=[{'user_id': 999}, {'data': {'message_id': 123}}]))
            adapter = SimpleNamespace(meta=lambda: SimpleNamespace(name='aiocqhttp'), get_client=lambda: bot)
            context = SimpleNamespace(get_platform_inst=lambda ident: adapter if ident == 'qq' else None)
            # Exercise plugin dispatch after AstrBot's wake-prefix normalization,
            # not a direct call to the delivery worker (which missed the regression).
            tree = ast.parse((Path(__file__).resolve().parents[3] / 'plugin/astrbot_plugin_comfy_bridge/main.py').read_text(encoding='utf-8'))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
            methods = [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name in {'aaa_hub_deliver', 'natural_random_picture_route'}]
            for method in methods:
                method.decorator_list = []
            ns = dict(AstrMessageEvent=object, WorkflowError=WorkflowError, logger=Mock(), __package__='astrbot_plugin_comfy_bridge')
            exec(compile(ast.Module(body=methods, type_ignores=[]), 'delivery_routes', 'exec'), ns)
            bridge = SimpleNamespace(context=context, _job_store=lambda: store, _character_dictionary_path=lambda: root / 'dictionary.json')
            for method in methods:
                setattr(bridge, method.name, MethodType(ns[method.name], bridge))
            tokens = []
            async def handler(request):
                body = json.loads(request.content)
                token = body['message'].split()[-1]
                tokens.append(token)
                event = SimpleNamespace(message_str=body['message'].removeprefix('/'),
                    get_platform_name=lambda: 'webchat', stop_event=Mock(), should_call_llm=Mock(),
                    send=AsyncMock(), plain_result=lambda text: text)
                await bridge.natural_random_picture_route(event)
                await bridge.aaa_hub_deliver(event, token)
                event.should_call_llm.assert_called_with(False)
                return httpx.Response(200, text='data: {"type":"plain","data":"done"}\n\n')
            async with httpx.AsyncClient(base_url='http://local', transport=httpx.MockTransport(handler)) as client:
                result = await deliver_image(settings, client, 'qq:GroupMessage:456', '完成', asset['sha256'], [job['job_id']])
            self.assertEqual(result['status'], 'sent')
            found = store.parent_for_message('123', 'qq:GroupMessage:456\0' + '999')
            self.assertEqual(found[0]['job_id'], job['job_id'])
            self.assertEqual(found[1], 0)
            self.assertIsNone(store.parent_for_message('123', 'qq:GroupMessage:777\0' + '999'))
            self.assertIsNone(store.parent_for_message('123', 'qq:GroupMessage:456\0' + '998'))
            self.assertEqual(bot.call_action.await_args.kwargs['group_id'], 456)
            with self.assertRaises(ValueError):
                await deliver_ticket(context, store, root, tokens[0])
            self.assertEqual(bot.call_action.await_count, 2)
            async with httpx.AsyncClient(base_url='http://local', transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ValueError):
                    await deliver_image(settings, client, 'qq:GroupMessage:456', '', asset['sha256'], ['unrelated-job'])

    async def test_expired_capability_cannot_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tickets = root / 'hub_state' / 'qq_deliveries'
            tickets.mkdir(parents=True)
            token = 'a' * 32
            (tickets / (token + '.json')).write_text(json.dumps({'action': 'deliver', 'expires_at': 0}))
            with self.assertRaises(ValueError):
                await deliver_ticket(None, None, root, token)
            result = json.loads((tickets / (token + '.result.json')).read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'failed')
