import unittest
import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from astrbot_plugin_comfy_bridge.replay_runtime import hq_replay_job, replay_workflow
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_body


class HQTests(unittest.TestCase):
    def test_full_chain_replaces_stale_input(self):
        base = {'input': {'prompt': 'scene'}, 'model': {'style_name': 'original'}, 'workflow_snapshot': {
            '1': {'class_type': 'KSampler', 'inputs': {'seed': 7}},
            '2': {'class_type': 'VAEDecode', 'inputs': {'samples': ['1', 0]}},
            '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        final = {'enhance': {'hq_base_job_id': 'base'}, 'workflow_snapshot': {
            '1': {'class_type': 'LoadImage', 'inputs': {'image': 'old.png'}},
            '2': {'class_type': 'SeedVR2TilingUpscaler', 'inputs': {'image': ['1', 0], 'seed': 7}},
            '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        merged = hq_replay_job(SimpleNamespace(get_job=lambda ident: base), final)
        graph, seed, _ = replay_workflow(merged, 0)
        self.assertEqual(graph['final_2']['inputs']['image'], ['base_2', 0])
        self.assertEqual(graph['base_2']['inputs']['samples'], ['base_1', 0])
        self.assertEqual(graph['final_3']['inputs']['images'], ['final_2', 0])
        self.assertEqual(sum(n['class_type'] == 'SaveImage' for n in graph.values()), 1)
        self.assertNotIn('final_1', graph)
        self.assertEqual(graph['base_1']['inputs']['seed'], seed)
        self.assertEqual(graph['final_2']['inputs']['seed'], seed)
        self.assertEqual(merged['model']['style_name'], 'original')
        self.assertNotIn('hq_base_job_id', merged['enhance'])
        self.assertIn('hq_base_job_id', final['enhance'])

    def test_does_not_guess_legacy_or_refine_chain(self):
        job = {'parent_job_id': 'anything', 'enhance': {}}
        self.assertIs(hq_replay_job(None, job), job)

    def test_full_chain_keeps_detail_repair_between_base_and_seedvr2(self):
        base = {'input': {'prompt': 'scene'}, 'model': {}, 'workflow_snapshot': {
            '1': {'class_type': 'KSampler', 'inputs': {'seed': 7}},
            '2': {'class_type': 'VAEDecode', 'inputs': {'samples': ['1', 0]}},
            '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        detail = {'workflow_snapshot': {
            '1': {'class_type': 'LoadImage', 'inputs': {'image': 'base.png'}},
            '2': {'class_type': 'FaceDetailer', 'inputs': {'image': ['1', 0], 'seed': 8}},
            '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        final = {'enhance': {'hq_base_job_id': 'base', 'hq_detail_job_id': 'detail'}, 'workflow_snapshot': {
            '1': {'class_type': 'LoadImage', 'inputs': {'image': 'detail.png'}},
            '2': {'class_type': 'SeedVR2TilingUpscaler', 'inputs': {'image': ['1', 0], 'seed': 9}},
            '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0]}}}}
        store = SimpleNamespace(get_job=lambda ident: {'base': base, 'detail': detail}[ident])
        merged = hq_replay_job(store, final)
        graph, _, _ = replay_workflow(merged, 0)
        self.assertEqual(graph['detail_2']['inputs']['image'], ['base_2', 0])
        self.assertEqual(graph['final_2']['inputs']['image'], ['detail_2', 0])
        self.assertEqual(sum(n['class_type'] == 'SaveImage' for n in graph.values()), 1)
        self.assertNotIn('hq_detail_job_id', merged['enhance'])

    def test_all_alias_bodies(self):
        for command, alias in [('awatermark', '打上水印'), ('apalette', '随机画风调色盘'),
            ('aimg_random', '抽一抽'), ('aimg_random5', '五连抽'), ('aimg_chaos', '混沌时刻'),
            ('amulti', '多人图'), ('ahelp', '跑图格式')]:
            self.assertEqual(extract_command_body(alias + ' 参数', command=command), '参数')
            self.assertEqual(extract_command_body('/' + alias + ' 参数', command=command), '参数')


class AliasRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_slash_aliases_and_help_generator(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'natural_random_picture_route')
        method.decorator_list = []
        ns = {'AstrMessageEvent': object}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'routes', 'exec'), ns)
        aliases = [('打上水印', 'awatermark'), ('随机画风', 'apalette'), ('随机画风调色盘', 'apalette'),
                   ('抽一抽', 'aimg_random'), ('五连抽', 'aimg_random5'), ('混沌时刻', 'aimg_chaos'),
                   ('混沌五连', 'aimg_chaos5'), ('多人图', 'amulti'),
                   ('收藏', 'afavorite'), ('收藏提示词', 'afavorite'), ('取消收藏', 'aunfavorite'),
                   ('举报', 'areport'), ('举报图片', 'areport'), ('查看画廊', 'agallery'), ('画风画廊', 'agallery'), ('画廊', 'agallery')]
        bridge = SimpleNamespace(_capture_pending_image=AsyncMock(return_value=False))
        for _, name in aliases:
            setattr(bridge, name, AsyncMock())
        event = SimpleNamespace(stop_event=Mock(), send=AsyncMock())
        for phrase, name in aliases:
            event.message_str = phrase + '\t角色=A'
            await ns['natural_random_picture_route'](bridge, event)
            getattr(bridge, name).assert_awaited_with(event, '角色=A')
        async def help(event):
            yield 'help text'
        bridge.ahelp = help
        for phrase in ['跑图帮助', '跑图指令', '跑图格式']:
            event.message_str = phrase
            await ns['natural_random_picture_route'](bridge, event)
            event.send.assert_awaited_with('help text')
        bridge._capture_pending_image.assert_not_awaited()
        event.message_str = '随机画风格外好看'
        await ns['natural_random_picture_route'](bridge, event)
        bridge._capture_pending_image.assert_awaited_once()
