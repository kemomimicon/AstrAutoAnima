import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_comfy_bridge.prompt_snapshot_runtime import image_prompt_snapshot
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_prompt
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives


def method(name):
    tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text('utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    ns = dict(globals(), __package__='astrbot_plugin_comfy_bridge', AstrMessageEvent=object)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-entry>', 'exec'), ns)
    return ns[name]


class ActualPromptCommands(unittest.IsolatedAsyncioTestCase):
    async def test_aecho_direct_chinese_reverse_copy_remake_and_five(self):
        for mode in ['direct', 'chinese', 'reverse', 'copy', 'remake', 'five']:
            with self.subTest(mode=mode):
                final = f'{mode}, character trigger, style trigger, rainy street, view from above'
                data = {'compiled_prompt': final, 'negative': 'bad hands'}
                if mode == 'five':
                    data.update(batch_prompts=['wrong first', final], source_entries=[
                        {'id': 'first', 'prompt': 'wrong source'},
                        {'id': 'second', 'prompt': 'old source', 'user_addition': 'rainy street'}])
                job = {'job_id': 'job_test', 'input': data, 'result': {'assets': ['a', 'b']}}
                event = SimpleNamespace(should_call_llm=Mock(), stop_event=Mock(),
                                        plain_result=lambda t: t, send=AsyncMock())
                bridge = SimpleNamespace(_quoted_job=AsyncMock(return_value=(job, 1 if mode == 'five' else 0)),
                                         _job_store=lambda: SimpleNamespace(get_job=Mock()))
                await method('aecho')(bridge, event)
                text = ''.join(call.args[0] for call in event.send.await_args_list)
                self.assertIn(final, text)
                self.assertIn('bad hands', text)
                self.assertNotIn('wrong first', text)

    async def test_actual_aimg_delegates_suite_and_options_to_common_pipeline(self):
        event = SimpleNamespace(message_str='/aimg 角色=Alice 画风=__hub_suite_123 rain',
                                should_call_llm=Mock(), plain_result=lambda t: t)
        bridge = SimpleNamespace(_deliver_generation=AsyncMock(return_value=True))
        outputs = [r async for r in method('aimg')(bridge, event)]
        self.assertEqual(outputs, [])
        args = bridge._deliver_generation.await_args.kwargs
        self.assertEqual(args['prompt'], 'rain')
        self.assertEqual(args['options']['style'], '__hub_suite_123')

    def test_never_fall_back_to_first_batch_or_raw_input(self):
        with self.assertRaises(ValueError):
            image_prompt_snapshot({'input': {'batch_prompts': ['first']}}, 1)
        self.assertFalse(image_prompt_snapshot({'input': {'prompt': 'uncompiled'}})['available'])

    def test_hq_inherits_base_but_unindexed_legacy_batch_refine_is_rejected(self):
        base = {'job_id': 'base', 'input': {'compiled_prompt': 'actual'}, 'result': {'assets': ['a']}}
        upscale = {'job_id': 'up', 'workflow': {'type': 'seedvr2_refine_v1'},
                   'enhance': {'hq_base_job_id': 'base'}, 'input': {'compiled_prompt': 'not used'}}
        result = image_prompt_snapshot(upscale, load_job=lambda _: base)
        self.assertEqual(result['positive'], 'actual')
        self.assertIn('不使用文本', result['stage'])
        base['result']['assets'].append('b')
        with self.assertRaises(ValueError):
            image_prompt_snapshot(upscale, load_job=lambda _: base)

    def test_hub_and_plugin_reader_are_identical(self):
        root = Path(__file__).parents[3]
        self.assertEqual((root / 'plugin/astrbot_plugin_comfy_bridge/prompt_snapshot_runtime.py').read_bytes(),
                         (root / 'hub/service/src/astr_auto_anima_hub/prompt_snapshots.py').read_bytes())
