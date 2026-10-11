import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parents[1])]
from deploy_project import Plan, quick_workflow
from preset_runtime import apply_lora_plan
from workflow_runtime import WorkflowError


class SlotlessStyleReleaseTests(unittest.TestCase):
    def setUp(self):
        self.graph = {
            '1': {'class_type': 'UNETLoader', 'inputs': {}},
            '2': {'class_type': 'CLIPLoader', 'inputs': {}},
            '11': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': 'test'}},
            '12': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': ''}},
            '19': {'class_type': 'KSampler', 'inputs': {'model': ['1', 0], 'seed': 123, 'steps': 30, 'cfg': 5}},
        }
        self.args = dict(style={'loras': [{'name': 'test.safetensors', 'strength_model': .7, 'strength_clip': .6}]},
                         character=None, style_slot_ids=[], positive_node_id='11', negative_node_id='12',
                         sampler_node_id='19', character_node_id='900001', options={}, style_mode='dynamic')

    def test_empty_and_stale_slots_build_chain(self):
        for slots in ([], ['46', '47', '48', '49']):
            with self.subTest(slots=slots):
                graph = copy.deepcopy(self.graph)
                result = apply_lora_plan(graph, **dict(self.args, style_slot_ids=slots))
                self.assertEqual(graph['900100']['inputs']['model'], ['1', 0])
                self.assertEqual(graph['900100']['inputs']['clip'], ['2', 0])
                self.assertEqual(graph['19']['inputs']['model'], ['900100', 0])
                self.assertEqual(graph['11']['inputs']['clip'], ['900100', 1])
                self.assertEqual(graph['12']['inputs']['clip'], ['900100', 1])
                self.assertEqual(result['style_loras'][0]['strength_clip'], .6)
                self.assertEqual(graph['19']['inputs']['seed'], 123)

    def test_actual_deployer_nine_node_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for name in ('unet', 'clip', 'vae'):
                path = root / (name + '.safetensors')
                path.write_bytes(b'test fixture only')
                files.append(str(path))
            graph = quick_workflow(Plan(str(root), unet=files[0], clip=files[1], vae=files[2]), root/'comfy', lambda _: None)
            self.assertEqual(len(graph), 9)
            original = copy.deepcopy(graph)
            apply_lora_plan(graph, **self.args)
            self.assertEqual(len(graph), 10)
            for nid in ('1', '2', '3', '8', '9', '28'):
                self.assertEqual(graph[nid], original[nid])
            for key in ('steps', 'cfg', 'scheduler', 'sampler_name', 'seed'):
                self.assertEqual(graph['19']['inputs'][key], original['19']['inputs'][key])

    def test_character_follows_style(self):
        apply_lora_plan(self.graph, **dict(self.args, character={'lora': {'name': 'role.safetensors'}}))
        self.assertEqual(self.graph['900001']['inputs']['model'], ['900100', 0])
        self.assertEqual(self.graph['900001']['inputs']['clip'], ['900100', 1])
        self.assertEqual(self.graph['19']['inputs']['model'], ['900001', 0])
        self.assertEqual(self.graph['12']['inputs']['clip'], ['900001', 1])

    def test_no_style_no_change(self):
        original = copy.deepcopy(self.graph)
        apply_lora_plan(self.graph, **dict(self.args, style=None))
        self.assertEqual(original, self.graph)

    def test_empty_style_keeps_base_links(self):
        original = copy.deepcopy(self.graph)
        apply_lora_plan(self.graph, **dict(self.args, style={'loras': []}))
        self.assertEqual(original, self.graph)

    def test_invalid_links_rejected_before_mutation(self):
        for link in (None, [], ['missing', 0], ['1', -1], ['1', True], ['1', '0'], ['1', 0, 1]):
            with self.subTest(link=link):
                graph = copy.deepcopy(self.graph)
                graph['19']['inputs']['model'] = link
                before = copy.deepcopy(graph)
                with self.assertRaises(WorkflowError):
                    apply_lora_plan(graph, **self.args)
                self.assertEqual(graph, before)

    def test_negative_clip_mismatch_not_silently_replaced(self):
        self.graph['12']['inputs']['clip'] = ['1', 0]
        with self.assertRaisesRegex(WorkflowError, '不一致'):
            apply_lora_plan(self.graph, **self.args)
        self.assertNotIn('900100', self.graph)

    def test_existing_unconfigured_lora_must_not_double_stack(self):
        for kind in ('LoraLoader', 'LoraLoaderModelOnly', 'Power Lora Loader (rgthree)'):
            with self.subTest(kind=kind):
                graph = copy.deepcopy(self.graph)
                graph['50'] = {'class_type': kind, 'inputs': {}}
                with self.assertRaisesRegex(WorkflowError, '实际节点 ID'):
                    apply_lora_plan(graph, **self.args)

    def test_partial_slots_are_not_ignored(self):
        self.graph['46'] = {'class_type': 'LoraLoader', 'inputs': {'model': ['1', 0], 'clip': ['2', 0]}}
        with self.assertRaisesRegex(WorkflowError, '槽位配置与工作流不一致'):
            apply_lora_plan(self.graph, **dict(self.args, style_slot_ids=['46', '47']))

    def test_fixed_requires_slots(self):
        with self.assertRaisesRegex(WorkflowError, '固定画风模式'):
            apply_lora_plan(self.graph, **dict(self.args, style_mode='fixed'))

    def test_node_collision_does_not_overwrite_existing_node(self):
        self.graph['900100'] = {'class_type': 'SaveImage', 'inputs': {}}
        original = copy.deepcopy(self.graph)
        with self.assertRaisesRegex(WorkflowError, '冲突'):
            apply_lora_plan(self.graph, **self.args)
        self.assertEqual(original, self.graph)

    def test_six_loras_and_limit(self):
        style = {'loras': [{'name': f'test_{i}.safetensors'} for i in range(6)]}
        apply_lora_plan(self.graph, **dict(self.args, style=style))
        self.assertEqual(self.graph['19']['inputs']['model'], ['900105', 0])
        fresh = {'1': {'class_type': 'UNETLoader', 'inputs': {}}}
        with self.assertRaisesRegex(WorkflowError, '上限'):
            apply_lora_plan(fresh, **dict(self.args, style=style, max_dynamic_style_loras=5))


if __name__ == '__main__':
    unittest.main()
