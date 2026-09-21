import copy
import unittest
from astrbot_plugin_comfy_bridge.multi_person_runtime import parse_scene, render_scene, strip_standard_loras
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class MultiPersonTests(unittest.TestCase):
    def test_scene(self):
        scene = parse_scene("人物1：Alice | red hair | standing on the left\n人物2：Bob | black hair | sitting on the right\n场景：a park\n互动：Character A waves to Character B")
        prompt = render_scene(scene)
        self.assertIn("Exactly 2 people", prompt)
        self.assertIn("Character B: Bob", prompt)
        self.assertIn("Scene: a park", prompt)

    def test_reject_single(self):
        with self.assertRaises(WorkflowError):
            parse_scene("人物1：Alice | red hair | standing")

    def test_lora_chain(self):
        graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
                 "2": {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1]}},
                 "3": {"class_type": "LoraLoader", "inputs": {"model": ["2", 0], "clip": ["2", 1]}},
                 "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 1]}}}
        original = copy.deepcopy(graph)
        strip_standard_loras(graph)
        self.assertEqual(graph["4"]["inputs"]["clip"], ["1", 1])
        self.assertNotIn("2", graph)
        self.assertIn("2", original)

    def test_unknown_lora_rejected(self):
        with self.assertRaises(WorkflowError):
            strip_standard_loras({"1": {"class_type": "PowerLoraLoader", "inputs": {}}})

    def test_cycle_rejected(self):
        with self.assertRaises(WorkflowError):
            strip_standard_loras({"1": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0]}}})
