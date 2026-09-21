import unittest

from astrbot_plugin_comfy_bridge.preset_runtime import (
    parse_generation_directives, resolve_presets, select_character_variant, preset_prompt,
)
from astrbot_plugin_comfy_bridge.replay_runtime import copy_context
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class CharacterVariantTests(unittest.TestCase):
    def setUp(self):
        self.role = {"lora": {"name": "a.safetensors"}, "prompt": "identity, uniform",
                     "variants": [{"id": "hanfu", "name": "汉服", "category": "clothing", "prompt": "identity, hanfu"}]}

    def test_default_compatible(self):
        self.assertEqual(select_character_variant(self.role, ""), self.role)
        self.assertEqual(select_character_variant({"prompt": "legacy"}, "default"), {"prompt": "legacy"})

    def test_replace_not_append_and_do_not_mutate(self):
        selected = select_character_variant(self.role, "hanfu")
        self.assertEqual(preset_prompt({"prompt": "ink"}, selected), "ink, identity, hanfu")
        self.assertEqual(self.role["prompt"], "identity, uniform")
        selected["lora"]["name"] = "changed"
        self.assertEqual(self.role["lora"]["name"], "a.safetensors")

    def test_invalid_variant(self):
        for role, value in [(self.role, "missing"), (None, "hanfu")]:
            with self.assertRaises(WorkflowError):
                select_character_variant(role, value)

    def test_directive_and_resolution(self):
        prompt, options = parse_generation_directives("角色=A 造型=hanfu sitting")
        _, role, _, _ = resolve_presets(prompt, options, {"characters": {"A": self.role}})
        self.assertEqual(role["prompt"], "identity, hanfu")
        self.assertEqual(parse_generation_directives("造型=默认 sitting")[1]["character_variant"], "默认")

    def test_snapshot_reset_and_switch_character(self):
        saved = select_character_variant(self.role, "hanfu")
        self.assertEqual(select_character_variant(saved, "默认")["prompt"], "identity, uniform")
        job = {"input": {"prompt": "sitting", "generation_options": {"character": "A", "character_variant": "hanfu"},
                         "preset_snapshot": {"character": saved}}}
        _, same = copy_context(job, 0, {})
        self.assertEqual(same["character_variant"], "hanfu")
        _, changed = copy_context(job, 0, {"character": "B"})
        self.assertNotIn("character_variant", changed)
        self.assertNotIn("_copy_character", changed)


if __name__ == "__main__":
    unittest.main()
