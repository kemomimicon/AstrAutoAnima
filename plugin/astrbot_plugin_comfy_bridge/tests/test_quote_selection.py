import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from astrbot_plugin_comfy_bridge.job_runtime import JobStore
from astrbot_plugin_comfy_bridge.quote_selection_runtime import parse_selection
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class SelectionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_selection('1,3,5'), ([1,3,5], ''))
        self.assertEqual(parse_selection('2，4,2 原因'), ([2,4], '原因'))
        self.assertEqual(parse_selection('1, 3 原因'), ([1,3], '原因'))
        for body in ['0', '6', '1,', '1/2', '1,2a']:
            with self.subTest(body=body), self.assertRaises(WorkflowError): parse_selection(body)

    def test_group_cross_job_positions_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JobStore(root / 'store')
            image = root / 'test.png'
            image.write_bytes(b'image')
            group = 'a' * 32
            parents = []
            for positions in [[1,2], [3,4], [5]]:
                job = store.create_job(workflow_type='quick', workflow_version='1', profile='', source={},
                    input_data={'draw_group': group, 'draw_positions': positions})
                for position in positions:
                    asset = store.register_asset(image, asset_type='result', job_id=job['job_id'], source='test')
                    job['result']['assets'].append(asset['asset_id'])
                store.save_job(job)
                for index, position in enumerate(positions):
                    store.record_delivery(str(position), 'qq-scope', job['job_id'], index)
                parents.append(job)
            selected = store.selected_draws(parents[1], [1,3,5], 'qq-scope')
            self.assertEqual([x[0] for x in selected], [1,3,5])
            self.assertEqual([x[1]['job_id'] for x in selected], [p['job_id'] for p in parents])
            self.assertEqual([x[2] for x in selected], [0,0,0])
            with self.assertRaises(WorkflowError): store.selected_draws(parents[0], [1], 'another-group')
            with self.assertRaises(WorkflowError): store.selected_draws({'input':{}}, [1], 'qq-scope')

    def test_missing_position_does_not_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JobStore(root / 'store')
            image = root / 'test.png'
            image.write_bytes(b'image')
            job = store.create_job(workflow_type='quick', workflow_version='1', profile='', source={},
                input_data={'draw_group': 'b'*32, 'draw_positions': [3]})
            asset = store.register_asset(image, asset_type='result', job_id=job['job_id'], source='test')
            job['result']['assets'] = [asset['asset_id']]
            store.save_job(job)
            store.record_delivery('123', 'scope', job['job_id'], 0)
            self.assertEqual(store.selected_draws(job, [3], 'scope')[0][0], 3)
            with self.assertRaises(WorkflowError): store.selected_draws(job, [1,3], 'scope')


class NumberedRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_space_commands(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'natural_random_picture_route')
        method.decorator_list=[]
        ns={'AstrMessageEvent': object}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'route', 'exec'), ns)
        bridge=SimpleNamespace(_handle_quoted_selection=AsyncMock())
        for text, name, body in [('收藏1,3,5','afavorite','1,3,5'), ('举报2,4 原因','areport','2,4 原因'),
            ('看看串1,2','aecho','1,2'), ('查看画风5','astyle','5'), ('/afavorite 1,3','afavorite','1,3'),
            ('重跑一张2,3','aremake','2,3'), ('取消收藏1,5','aunfavorite','1,5')]:
            event=SimpleNamespace(message_str=text)
            await ns['natural_random_picture_route'](bridge, event)
            bridge._handle_quoted_selection.assert_awaited_with(event,name,body)

    async def test_validates_all_selections_before_mutation_and_clears_cache(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_handle_quoted_selection')
        ns={'__package__':'astrbot_plugin_comfy_bridge', 'WorkflowError': WorkflowError, 'delivery_scope':lambda event:'scope'}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'select', 'exec'), ns)
        job={'input':{}}
        store=SimpleNamespace(selected_draws=Mock(return_value=[(1,job,0),(3,job,1)]))
        seen=[]
        async def favorite(event, reason): seen.append(event._aaa_selected_quote[1])
        bridge=SimpleNamespace(_quoted_job=AsyncMock(return_value=(job,0)),_job_store=lambda:store,afavorite=favorite)
        event=SimpleNamespace(message_str='收藏1,3',stop_event=Mock(),should_call_llm=Mock(),send=AsyncMock(),plain_result=lambda s:s)
        await ns['_handle_quoted_selection'](bridge,event,'afavorite','1,3')
        self.assertEqual(seen,[0,1])
        self.assertEqual(event.message_str,'收藏1,3')
        self.assertFalse(hasattr(event,'_aaa_selected_quote'))
        store.selected_draws.side_effect=WorkflowError('第5张缺失')
        seen.clear()
        await ns['_handle_quoted_selection'](bridge,event,'afavorite','1,5')
        self.assertEqual(seen,[])
