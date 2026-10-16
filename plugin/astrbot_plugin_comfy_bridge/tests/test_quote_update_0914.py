import ast
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_comfy_bridge.replay_runtime import quoted_style_preset, copy_context
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives, load_presets, save_presets
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError, extract_command_body


class QuoteUpdateTests(unittest.IsolatedAsyncioTestCase):
    def parent(self):
        return {'job_id': 'original', 'workflow': {'type': 'quick_txt2img_v1', 'profile': ''},
                'input': {'prompt': 'original scene', 'generation_options': {'character': 'A', 'style': 'ink', 'ratio': '1:1'},
                          'source_entries': [{'id': 'G-2', 'prompt': 'raw entry'}],
                          'preset_snapshot': {'style': {'loras': [], 'prompt': 'ink, fine lines'}, 'character': {'prompt': 'A'}}},
                'model': {'lora_stack': [{'kind': 'style', 'name': 'ink.safetensors', 'strength_model': 0.8, 'strength_clip': 0.6},
                                         {'kind': 'character', 'name': 'a.safetensors', 'strength_model': 1, 'strength_clip': 1}]}}

    def bind(self, name, bridge):
        tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text('utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ComfyWorkflowBridge')
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        method.decorator_list = []
        ns = dict(globals(), __package__='astrbot_plugin_comfy_bridge', AstrMessageEvent=object,
                  compile_prompt=lambda text, *a, **kw: text, current_text_provider_id=AsyncMock(return_value=''))
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<test>', 'exec'), ns)
        return MethodType(ns[name], bridge)

    def test_saved_style_format_only_style_and_finite_weights(self):
        job = self.parent()
        value = quoted_style_preset(job)
        self.assertEqual(value, {'loras': [{'name': 'ink.safetensors', 'strength_model': 0.8, 'strength_clip': 0.6}],
                                'prompt': 'ink, fine lines', 'match': []})
        job['model']['lora_stack'][0]['strength_model'] = float('nan')
        with self.assertRaises(WorkflowError): quoted_style_preset(job)
        del job['input']['preset_snapshot']
        with self.assertRaises(WorkflowError): quoted_style_preset(job)

    async def test_admin_save_and_conflict_and_non_admin(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'presets.json'
            save_presets(path, {'styles': {}, 'characters': {}})
            event = SimpleNamespace(stop_event=Mock(), should_call_llm=Mock(), message_str='/asavestyle saved',
                                    plain_result=lambda t: t, send=AsyncMock())
            bridge = SimpleNamespace(_event_is_admin=lambda e: True, _quoted_job=AsyncMock(return_value=(self.parent(), 0)),
                                     config={}, _preset_path=lambda: path)
            method = self.bind('asavestyle', bridge)
            await method(event)
            self.assertEqual(load_presets(path)['styles']['saved'], quoted_style_preset(self.parent()))
            await method(event)
            self.assertIn('同名预设', event.send.await_args.args[0])
            bridge._event_is_admin = lambda e: False
            event.message_str = '/asavestyle denied'
            await method(event)
            self.assertNotIn('denied', load_presets(path)['styles'])

    async def test_modified_remake_options_seed_and_source_id(self):
        event = SimpleNamespace(plain_result=lambda t: t, send=AsyncMock())
        bridge = SimpleNamespace(_character_dictionary_path=lambda: Path('unused'),
                                 _deliver_generation=AsyncMock(), _safety_input=AsyncMock(), config={}, context=None)
        method = self.bind('_remake_modified', bridge)
        original = self.parent()
        await method(event, original, 0, '角色=B 比例=9:16', 987)
        call = bridge._deliver_generation.await_args.kwargs
        self.assertEqual(call['options']['character'], 'B')
        self.assertEqual(call['options']['ratio'], '9:16')
        self.assertEqual(call['options']['_fixed_seed'], 987)
        self.assertIn('_copy_style', call['options'])
        self.assertNotIn('_copy_character', call['options'])
        self.assertEqual(call['options']['_source_entries'][0]['id'], 'G-2')
        self.assertEqual(call['parent_job_id'], 'original')
        self.assertEqual(original['input']['generation_options']['character'], 'A')
        with self.assertRaisesRegex(WorkflowError, '文本Provider'):
            await method(event, original, 0, '把场景改成雨夜', 987)

    async def test_hq_chain_preserved_and_seedvr_not_silently_rebuilt(self):
        event = SimpleNamespace(plain_result=lambda t: t, send=AsyncMock())
        bridge = SimpleNamespace(_character_dictionary_path=lambda: Path('unused'), _deliver_generation=AsyncMock())
        method = self.bind('_remake_modified', bridge)
        parent = self.parent()
        parent['enhance'] = {'hq_replay_full_chain': True}
        parent['workflow']['type'] = 'seedvr2_refine_v1'
        await method(event, parent, 0, '比例=9:16', 4)
        self.assertEqual(bridge._deliver_generation.await_args.kwargs['workflow_type'], 'hq_txt2img_anima_v1')
        parent['enhance'] = {}
        with self.assertRaisesRegex(WorkflowError, '独立 SeedVR2'):
            await method(event, parent, 0, '角色=B', 4)
