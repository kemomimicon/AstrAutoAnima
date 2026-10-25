import ast
import asyncio
import copy
import secrets
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
from astrbot_plugin_comfy_bridge.prompt_pool_runtime import (
    parse_group_selector, compose_random_body, apply_protected_character_policy,
    describe_selection,
)
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives


class RemoteVTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Unit dispatch uses a synthetic provider, never a production catalog.
        available = patch('astrbot_plugin_comfy_bridge.gufeng_catalog_runtime.gufeng_available', return_value=True)
        available.start()
        self.addCleanup(available.stop)
    def bridge(self, private=True):
        tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text('utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
        methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name in {'_execute_random_picture', '_random_prompt_pool'}]
        ns = dict(globals(), Any=object, AstrMessageEvent=object, logger=Mock(),
                  __package__='astrbot_plugin_comfy_bridge')
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'v-routing', 'exec'), ns)
        bridge = SimpleNamespace(config={}, _safety_guard=Mock(), _safety_applies=lambda e: False,
            _is_private_event=lambda e: private, _prompt_pool_path=lambda: Path('/test/data/pool.json'),
            _random_quality_prompt=lambda p: '', _deliver_random_draw_plans=AsyncMock(return_value=1))
        for method in methods:
            setattr(bridge, method.name, MethodType(ns[method.name], bridge))
        return bridge

    async def test_real_dispatch_preserves_options_and_no_main_pool(self):
        bridge = self.bridge()
        event = SimpleNamespace(get_sender_id=lambda:'123456', send=AsyncMock(), plain_result=lambda x:x)
        card = {'template_id':'V:cn-1', 'prompt':'river, mountain', 'selection_seed':2,
                'provenance':{'mode':'full', 'origin':'cn'}}
        original = copy.deepcopy(card)
        with patch('astrbot_plugin_comfy_bridge.gufeng_catalog_runtime.draw_gufeng', return_value=card) as draw:
            await bridge._execute_random_picture(event, 'V 角色=Alice 画风=Ink 比例=16:9 起手=1boy sunset', draw_count=5)
        self.assertEqual(draw.call_count, 5)
        args = bridge._deliver_random_draw_plans.await_args.kwargs
        self.assertEqual(len(args['draw_plans']), 5)
        self.assertEqual(args['random_subject_tag'], '1boy')
        self.assertEqual(args['user_prompt'], 'sunset')
        selected, options, selection = args['draw_plans'][0]
        self.assertEqual(options['character'], 'Alice')
        self.assertEqual(options['style'], 'Ink')
        self.assertEqual(options['ratio'], '16:9')
        self.assertEqual(selected['id'], 'V:cn-1')
        self.assertEqual(selected['prompt_provenance']['safety_review'], 'deployment_catalog_policy')
        self.assertEqual(selection['safety_codes'], ['N'])
        self.assertEqual(card, original)

    async def test_reject_mixed_group_safe_grade_chaos_and_public(self):
        for body, private, chaos in [('V/D', True, False), ('V/N/S', True, False),
                ('V/H', True, False), ('V @test', True, False), ('V', True, True)]:
            bridge = self.bridge(private)
            event = SimpleNamespace(get_sender_id=lambda:'123456', send=AsyncMock(), plain_result=lambda x:x)
            with patch('astrbot_plugin_comfy_bridge.gufeng_catalog_runtime.draw_gufeng') as draw:
                await bridge._execute_random_picture(event, body, chaos=chaos)
            draw.assert_not_called()
            bridge._deliver_random_draw_plans.assert_not_awaited()
            self.assertIn('抽取失败', event.send.await_args.args[0])

    async def test_group_safe_mode_accepts_normal_and_legacy_v_selectors(self):
        for body in ('V', 'V/N', 'V/S'):
            bridge = self.bridge(private=False)
            bridge._safety_applies = lambda e: True
            bridge._platform_admit = Mock()
            event = SimpleNamespace(get_sender_id=lambda:'123456', send=AsyncMock(), plain_result=lambda x:x)
            card = {'template_id':'V:cn-1', 'prompt':'river', 'selection_seed':2, 'provenance':{}}
            with patch('astrbot_plugin_comfy_bridge.gufeng_catalog_runtime.draw_gufeng', return_value=card):
                await bridge._execute_random_picture(event, body)
            bridge._platform_admit.assert_called_once_with(event)
            bridge._safety_guard.assert_called_once_with(event)
            selected, _, selection = bridge._deliver_random_draw_plans.await_args.kwargs['draw_plans'][0]
            self.assertEqual(selected['safety_code'], 'N')
            self.assertEqual(selection['safety_codes'], ['N'])

    def test_prefix_is_per_draw_never_mutates_catalog(self):
        item = {'source_code':'V', 'prompt':'river, mountain'}
        for tag in ('', '1girl', '1boy', '1woman', '1man', 'none'):
            text = compose_random_body('sunset', item, subject_tag=tag)
            self.assertIn('solo', text)
            self.assertIn('sunset', text)
            if tag == 'none': self.assertNotIn('1girl', text)
            else: self.assertIn(tag or '1girl', text)
        self.assertEqual(item['prompt'], 'river, mountain')
        # Parsing is syntax-only. Deployment policy supplies V's actual level later.
        self.assertFalse(parse_group_selector('V')[1]['explicit_safety'])
        from astrbot_plugin_comfy_bridge.prompt_catalog_policy import apply_catalog_policy
        self.assertEqual(apply_catalog_policy(Path('/test/data'), parse_group_selector('V')[1],
                                              private=True)['safety_codes'], ['N'])
        self.assertNotIn('V', parse_group_selector('')[1]['source_codes'])

    def test_provider_identical_to_tested_local_provider(self):
        root = Path(__file__).resolve().parents[3]
        self.assertEqual((root/'plugin/astrbot_plugin_comfy_bridge/gufeng_catalog_runtime.py').read_text('utf-8').strip(),
            (root/'hub/service/src/astr_auto_anima_hub/local_gufeng.py').read_text('utf-8').strip())
