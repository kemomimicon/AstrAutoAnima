import copy
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_comfy_bridge.next_generation_runtime import (
    TURBO, SNAPREF, ref_mode, set_reference, render_preset_scene,
    validate_mode_options, apply_explicit_loras, replay_reference,
)
from astrbot_plugin_comfy_bridge.duo_profile_runtime import load_catalog, new_profile
from astrbot_plugin_comfy_bridge.multi_person_runtime import parse_scene
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives
from astrbot_plugin_comfy_bridge.workflow_registry import load_workflow_registry, validate_workflow_nodes
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError

ROOT = Path(__file__).resolve().parents[1]
SCENE = '人物1：Alice | | on the left\n人物2：Bob::coat | | on the right\n场景：a park\n互动：holding hands'


class NextGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.presets = {'characters': {
            'Alice': {'prompt': 'alice, red hair, fox ears', 'lora': {'name': 'loras\\Alice.safetensors'}},
            'Bob': {'prompt': 'bob, white shirt', 'variants': [{'id': 'coat', 'name': 'coat', 'prompt': 'bob, blue coat'}]},
        }, 'styles': {}}
        self.path = self.root / 'presets.json'
        self.path.write_text(json.dumps(self.presets), encoding='utf-8')

    def profile(self):
        p = new_profile(load_catalog(self.path), 'Alice')
        p['features']['hair'] = {'text': 'long red hair', 'source': 'user', 'confirmed': True}
        return p

    def save_profile(self, p, published=True):
        (self.root / 'catalog.json').write_text(json.dumps({'items': [
            {'id': 'alice-card', 'character': 'Alice', 'variant': 'default', 'profile': p, 'published': published}
        ]}), encoding='utf-8')

    def test_preset_variant_paragraphs_loras_no_mutation(self):
        before = copy.deepcopy(self.presets)
        text, snapshots, loras = render_preset_scene(parse_scene(SCENE), self.presets, self.root)
        self.assertEqual(text, 'alice, red hair, fox ears, on the left.\n\nbob, blue coat, on the right.\n\nExactly 2 people, holding hands, a park.')
        self.assertEqual(loras[0]['name'], 'loras\\Alice.safetensors')
        self.assertEqual(snapshots[1]['variant'], 'coat')
        self.assertNotIn('white shirt', text)
        self.assertEqual(before, self.presets)
        self.assertFalse((self.root / 'catalog.json').exists())

    def test_only_published_confirmed_profile_applies(self):
        p = self.profile()
        self.save_profile(p, False)
        text, _, _ = render_preset_scene(parse_scene(SCENE), self.presets, self.root)
        self.assertNotIn('long red hair', text)
        self.save_profile(p)
        text, snapshots, _ = render_preset_scene(parse_scene(SCENE), self.presets, self.root)
        self.assertIn('long red hair', text)
        self.assertEqual(snapshots[0]['feature_id'], 'alice-card')
        p['features']['hair']['confirmed'] = False
        self.save_profile(p)
        with self.assertRaisesRegex(WorkflowError, '未确认'):
            render_preset_scene(parse_scene(SCENE), self.presets, self.root)

    def test_stale_prompt_or_lora_rejected(self):
        p = self.profile()
        for field, value in [('selected_prompt', 'changed'), ('lora', None)]:
            changed = copy.deepcopy(p)
            changed['source'][field] = value
            self.save_profile(changed)
            with self.assertRaisesRegex(WorkflowError, '旧预设'):
                render_preset_scene(parse_scene(SCENE), self.presets, self.root)

    def test_curated_identity_replaces_original_only_when_confirmed(self):
        p = self.profile()
        p.update(composition_mode='curated', identity_text='alice_token', identity_confirmed=True)
        self.save_profile(p)
        text, _, _ = render_preset_scene(parse_scene(SCENE), self.presets, self.root)
        self.assertTrue(text.startswith('alice_token, long red hair, on the left.'))
        self.assertEqual(json.loads(self.path.read_text())['characters'], self.presets['characters'])

    def test_bad_profile_and_missing_character_report_workflow_error(self):
        self.save_profile({'bad': True})
        with self.assertRaises(WorkflowError):
            render_preset_scene(parse_scene(SCENE), self.presets, self.root)
        with self.assertRaisesRegex(WorkflowError, '不存在'):
            render_preset_scene(parse_scene(SCENE.replace('Alice', 'Unknown')), self.presets, self.root)

    def test_workflows_are_identical_and_registered(self):
        registry = load_workflow_registry(ROOT / 'data/next_workflow_registry.json')
        for ident in registry.ids():
            definition = registry.resolve(ident)
            path = ROOT / definition.workflow_file
            graph = json.loads(path.read_text())
            validate_workflow_nodes(graph, definition)
            self.assertEqual(path.read_bytes(), (ROOT.parents[1] / 'comfyui/workflows' / path.name).read_bytes())
            if ident == TURBO:
                self.assertEqual(graph['19']['inputs']['cfg'], 1)
                self.assertEqual(graph['19']['inputs']['steps'], 10)
                self.assertEqual(graph['44']['inputs']['unet_name'], 'anima-turbo-v1.1.safetensors')

    def test_ref_modes_and_graph_input(self):
        self.assertEqual(ref_mode('角色画风 a garden'), ('a garden', 'cs'))
        self.assertEqual(ref_mode('a garden'), ('a garden', 'char'))
        graph = json.loads((ROOT / 'data/workflows/Anima_SnapRef_api.json').read_text())
        set_reference(graph, {}, 'uploaded/ref.png', 'char')
        self.assertEqual(graph['1']['inputs']['image'], 'uploaded/ref.png')
        self.assertEqual(graph['19']['inputs']['model'], ['60', 0])
        self.assertEqual(graph['60']['inputs']['strength'], 0)
        graph['60']['class_type'] = 'LoraLoader'
        with self.assertRaises(WorkflowError):
            set_reference(graph, {}, 'ref.png', 'char')

    def test_mode_options_actual_command_aliases(self):
        _, options = parse_generation_directives('CFG=6 a garden')
        with self.assertRaisesRegex(WorkflowError, 'CFG=1'):
            validate_mode_options(TURBO, options)
        validate_mode_options(TURBO, {'sampler_cfg': 1})
        with self.assertRaises(WorkflowError):
            validate_mode_options(SNAPREF, {'character': 'Alice'})

    def test_explicit_lora_paths_and_wiring(self):
        graph = json.loads((ROOT / 'data/workflows/Anima_Preset_Multi_api.json').read_text())
        mapping = {'sampler': '19', 'positive': '11', 'negative': '12'}
        entries = [{'name': 'loras\\Alice.safetensors', 'strength_model': .7, 'model': ['evil', 0]},
                   {'name': 'bob.safetensors', 'strength_model': .4, 'strength_clip': .2}]
        before = copy.deepcopy(entries)
        plan = apply_explicit_loras(graph, mapping, entries)
        self.assertEqual(graph['910000']['inputs']['lora_name'], entries[0]['name'])
        self.assertEqual(graph['910000']['inputs']['model'], ['44', 0])
        self.assertEqual(graph['910001']['inputs']['model'], ['910000', 0])
        self.assertEqual(graph['12']['inputs']['clip'], ['910001', 1])
        self.assertEqual(plan['style_loras'][1]['node_id'], '910001')
        self.assertEqual(before, entries)
        with self.assertRaises(WorkflowError):
            apply_explicit_loras(graph, mapping, [{'name':'bad', 'strength_model':float('nan')}])

    def test_reference_replay_reads_original_asset_and_rejects_changed_bytes(self):
        from types import SimpleNamespace
        from astrbot_plugin_comfy_bridge.job_runtime import sha256_file
        image = self.root / 'ref.png'
        image.write_bytes(b'original reference')
        asset = {'type':'source', 'path':str(image), 'sha256':sha256_file(image)}
        store = SimpleNamespace(get_asset=lambda ident: asset)
        graph = json.loads((ROOT / 'data/workflows/Anima_SnapRef_api.json').read_text())
        path, mapping, mode = replay_reference(store, {'input':{'image_asset_id':'ref'}}, graph)
        self.assertEqual(path, str(image))
        set_reference(graph, mapping, 'fresh.png', mode)
        self.assertEqual(graph['1']['inputs']['image'], 'fresh.png')
        image.write_bytes(b'other image')
        with self.assertRaisesRegex(WorkflowError, '变化'):
            replay_reference(store, {'input':{'image_asset_id':'ref'}}, graph)
