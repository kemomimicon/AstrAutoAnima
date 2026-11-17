import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_main_import import ComfyWorkflowBridge, FakeEvent
from astrbot_plugin_comfy_bridge.next_generation_runtime import TURBO, SNAPREF

class NextCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.presets = root / 'presets.json'
        self.presets.write_text(json.dumps({'styles': {}, 'characters': {'Alice': {'prompt':'alice, red hair'}, 'Bob': {'prompt':'bob, black hair'}}}), encoding='utf-8')
        self.plugin = ComfyWorkflowBridge(object(), {'input_dir':str(root/'inputs'), 'preset_store_path':str(self.presets),
            'character_dictionary_path':str(root/'dictionary.json'), 'job_store_path':str(root/'jobs'),
            'default_sampler_name':'er_sde', 'default_sampler_cfg':5, 'default_sampler_steps':30})
        self.plugin._safety_input = AsyncMock()
        self.plugin._safety_policy = lambda event: SimpleNamespace(fingerprint='test')
        self.plugin._deliver_generation = AsyncMock()
        self.plugin._image_resolver = SimpleNamespace(resolve=AsyncMock(return_value='reference.png'))
        self.event = FakeEvent()

    async def test_turbo_handler(self):
        self.event.message_str = '/aturbo a garden'
        await self.plugin.aturbo(self.event)
        kw = self.plugin._deliver_generation.call_args.kwargs
        self.assertEqual(kw['workflow_type'], TURBO)
        self.assertEqual(kw['prompt'], 'a garden')
        self.assertTrue(self.event.stopped)

    async def test_ref_handler_mode_image_and_missing_input(self):
        self.event.message_str = '/aref cs a garden'
        await self.plugin.aref(self.event)
        kw = self.plugin._deliver_generation.call_args.kwargs
        self.assertEqual(kw['workflow_type'], SNAPREF)
        self.assertEqual(kw['options']['_ref_mode'], 'cs')
        self.assertEqual(kw['source_image_path'], 'reference.png')
        self.plugin._deliver_generation.reset_mock()
        self.plugin._image_resolver.resolve.return_value = None
        await self.plugin.aref(self.event)
        self.plugin._deliver_generation.assert_not_called()

    async def test_multi_preview_no_gpu_no_preset_mutation(self):
        original = self.presets.read_bytes()
        self.event.message_str = '/amulti 预览\n人物1：Alice | | on the left\n人物2：Bob | | on the right\n场景：a park'
        await self.plugin.amulti(self.event)
        self.assertIn('alice, red hair, on the left.', self.event.sent[0])
        self.plugin._deliver_generation.assert_not_called()
        self.event.message_str = self.event.message_str.replace('预览', '预设')
        await self.plugin.amulti(self.event)
        kw = self.plugin._deliver_generation.call_args.kwargs
        self.assertEqual(kw['workflow_type'], 'preset_multi_anima_v1')
        self.assertTrue(kw['options']['_compiled_prompt'])
        self.assertEqual(len(kw['options']['_multi_snapshot']), 2)
        self.assertEqual(self.presets.read_bytes(), original)

    async def test_generation_keeps_template_sampling_without_global_overrides(self):
        class Captured(Exception): pass
        for kind in (TURBO, SNAPREF, 'preset_multi_anima_v1'):
            with patch('astrbot_plugin_comfy_bridge.main.prepare_workflow', side_effect=Captured) as prepare:
                with self.assertRaises(Captured):
                    await self.plugin._generate('a garden', {}, workflow_type=kind, event=self.event)
                kw = prepare.call_args.kwargs
                self.assertEqual(kw['sampler_overrides'], {'cfg':1.0} if kind == TURBO else {})

    def test_new_registry_falls_back_without_editing_old_registry(self):
        for kind in (TURBO, SNAPREF, 'preset_multi_anima_v1'):
            definition, path = self.plugin._workflow_definition(kind)
            self.assertEqual(definition.workflow_id, kind)
            self.assertTrue(path.is_file())

    async def test_reference_generation_upload_binds_image_before_submit(self):
        class Captured(Exception): pass
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
        image = Path(self.temp.name) / 'reference.png'
        image.write_bytes(b'reference fixture')
        self.plugin._upload_reverse_image = AsyncMock(return_value='remote/unique.png')
        self.plugin._submit_workflow = AsyncMock(side_effect=Captured)
        with patch('astrbot_plugin_comfy_bridge.main.aiohttp.ClientTimeout', return_value=None), \
             patch('astrbot_plugin_comfy_bridge.main.aiohttp.ClientSession', return_value=Session()):
            with self.assertRaises(Captured):
                await self.plugin._generate('a garden', {'_ref_mode':'cs'}, workflow_type=SNAPREF,
                    event=self.event, source_image_path=str(image), strict_no_style=True)
        graph = self.plugin._submit_workflow.call_args.args[1]
        self.assertEqual(graph['1']['inputs']['image'], 'remote/unique.png')
        self.assertEqual(graph['60']['inputs']['mode'], 'cs')
        self.assertEqual(graph['19']['inputs']['model'], ['60',0])
        self.assertFalse(any(n.get('class_type') == 'LoraLoader' for n in graph.values()))
        # A person LoRA carried into a follow-up graph must survive restoration.
        with patch('astrbot_plugin_comfy_bridge.main.aiohttp.ClientTimeout', return_value=None), \
             patch('astrbot_plugin_comfy_bridge.main.aiohttp.ClientSession', return_value=Session()):
            with self.assertRaises(Captured):
                await self.plugin._generate('alice, on the left.\n\nbob, on the right.',
                    {'_compiled_prompt': True, '_restore_lora_stack': [
                        {'name': 'loras\\alice.safetensors', 'strength_model': .7, 'strength_clip': .4, 'kind':'person'}]},
                    workflow_type=TURBO, event=self.event)
        graph = self.plugin._submit_workflow.call_args.args[1]
        self.assertEqual(graph['910000']['inputs']['lora_name'], 'loras\\alice.safetensors')
        self.assertEqual(graph['11']['inputs']['text'], 'alice, on the left.\n\nbob, on the right.')
