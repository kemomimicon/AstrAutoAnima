import json
import tempfile
import unittest
from pathlib import Path
from astrbot_plugin_comfy_bridge.prompt_compiler_runtime import compile_prompt, category
from astrbot_plugin_comfy_bridge.kp_dynamic_runtime import _safety_for_text
from astrbot_plugin_comfy_bridge.prompt_pool_runtime import select_random_prompt
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class CompilerTests(unittest.TestCase):
    def test_identity_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "characters.json"
            path.write_text(json.dumps({"characters": [{"tag": "hatsune_miku", "copyright": ["vocaloid"], "enabled": False}]}), encoding="utf-8")
            result = compile_prompt("hatsune miku, vocaloid, fox ears, fluffy tail, red hair, :d, standing, park", path, strip_identity=True)
            self.assertEqual(result, ":d, standing, park")

    def test_order(self):
        self.assertEqual(compile_prompt("standing, 1girl, best quality, :d, standing"), "best quality, 1girl, standing, :d")

    def test_emoticons(self):
        for value in (":d", ";d", ":3"):
            self.assertEqual(category(value), "action")

    def test_k_leaks(self):
        for tag in ("peeing", "holding_dildo", "fully clothed, nude"):
            self.assertNotEqual(_safety_for_text(tag), "N")
            with self.assertRaises(WorkflowError):
                select_random_prompt({"prompts": [{"id": "kp-a01-safe", "source_code": "K", "safety_code": "N", "prompt": tag}]}, source_codes=["K"], safety_codes=["N"])
        self.assertEqual(_safety_for_text("peeking around a corner"), "N")
