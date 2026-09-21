import unittest
from astrbot_plugin_comfy_bridge.chaos_runtime import choose_chaos_style
from astrbot_plugin_comfy_bridge.replay_runtime import replay_workflow, copy_context
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class ChaosReplayTests(unittest.TestCase):
    def test_copy_context_inherits_and_overrides(self):
        original = {"input": {"prompt": "sitting", "raw_batch_prompts": ["first", "second"],
            "generation_options": {"character": "A", "style": "ink", "ratio": "9:16", "_ticket": "secret"},
            "preset_snapshot": {"style": {"loras": [{"name": "ink", "strength_model": 0.8}]}}},
            "sampling": {"steps": 30, "cfg": 6, "sampler_name": "er_sde"}}
        prompt, options = copy_context(original,1,{"character": "B", "ratio": "1:1", "steps": 40})
        self.assertEqual(prompt,"second")
        self.assertEqual(options["character"],"B")
        self.assertEqual(options["style"],"ink")
        self.assertEqual(options["steps"],40)
        self.assertEqual(options["sampler"],"er_sde")
        self.assertEqual(options["_copy_style"]["loras"][0]["strength_model"],0.8)
        self.assertNotIn("_ticket",options)
        _, changed = copy_context(original,0,{"style":"new"})
        self.assertNotIn("_copy_style",changed)
        self.assertEqual(original["input"]["generation_options"]["character"],"A")

    def test_copy_missing_prompt_requires_reverse(self):
        with self.assertRaises(WorkflowError):
            copy_context({},0,{})
    def test_budgets(self):
        catalog = {"entries": {f"style{i}.safetensors": {"category": "style", "present": True, "recommended_prompt": "same_trigger, unique"} for i in range(8)}}
        for _ in range(200):
            style = choose_chaos_style(catalog)
            loras = style["loras"]
            self.assertTrue(3 <= len(loras) <= 5)
            self.assertTrue(.7 <= loras[0]["strength_model"] <= .9)
            self.assertLessEqual(round(sum(item["strength_model"] for item in loras[1:]), 2), 1.5)
            self.assertTrue(all(.1 <= item["strength_model"] <= .6 for item in loras[1:]))
            self.assertEqual(style["prompt"], "same_trigger, unique")
            self.assertEqual(len({item["name"] for item in loras}), len(loras))

    def test_missing_catalog(self):
        with self.assertRaises(WorkflowError):
            choose_chaos_style({"entries": {}})

    def test_batch_replay(self):
        job = {"sampling": {"seed": 1}, "input": {"batch_prompts": ["first", "second"]}, "workflow_snapshot": {
            "1": {"class_type": "KSampler", "inputs": {"seed": 1}},
            "2": {"class_type": "AnimaPromptBatchEncode", "inputs": {"prompts_json": '["first","second"]'}},
            "3": {"class_type": "EmptyLatentImage", "inputs": {"batch_size": 2}}}}
        graph, seed, output = replay_workflow(job, 1)
        self.assertNotEqual(seed, 1)
        self.assertEqual(output, 0)
        self.assertEqual(graph["2"]["inputs"]["prompts_json"], '["second"]')
        self.assertEqual(graph["3"]["inputs"]["batch_size"], 1)
        self.assertEqual(job["workflow_snapshot"]["1"]["inputs"]["seed"], 1)
