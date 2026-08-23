from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from preset_runtime import (  # noqa: E402
    apply_lora_plan,
    parse_generation_directives,
    parse_text_character_definition,
    preset_prompt,
)
from prompt_pool_runtime import select_random_prompts  # noqa: E402
from workflow_runtime import (  # noqa: E402
    WorkflowError,
    prepare_workflow,
    resolve_canvas_size,
)


class CanvasTests(unittest.TestCase):
    def test_ratio(self) -> None:
        self.assertEqual(resolve_canvas_size({"ratio": "16:9"}), (1536, 864))

    def test_explicit_size(self) -> None:
        prompt, options = parse_generation_directives("尺寸=1280x960 rainy street")
        self.assertEqual(prompt, "rainy street")
        self.assertEqual(resolve_canvas_size(options), (1280, 960))

    def test_rejects_unaligned_size(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "32 的倍数"):
            resolve_canvas_size({"size": "1000x1000"})

    def test_writes_latent_node(self) -> None:
        workflow = {
            "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 0]}},
            "19": {"class_type": "KSampler", "inputs": {"seed": 1}},
            "28": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1536, "batch_size": 1}},
        }
        result, _ = prepare_workflow(
            workflow,
            prompt="test",
            positive_node_id="11",
            sampler_node_id="19",
            latent_node_id="28",
            width=1536,
            height=864,
        )
        self.assertEqual(result["28"]["inputs"]["width"], 1536)
        self.assertEqual(result["28"]["inputs"]["height"], 864)


class TextCharacterTests(unittest.TestCase):
    def test_text_character_has_no_lora(self) -> None:
        name, character = parse_text_character_definition(
            "builtin_role --prompt character tag, fixed clothes"
        )
        self.assertEqual(name, "builtin_role")
        self.assertIsNone(character["lora"])
        self.assertIn("character tag", preset_prompt(None, character))
        workflow = {}
        result = apply_lora_plan(
            workflow,
            style=None,
            character=character,
            style_slot_ids=[],
            positive_node_id="11",
            negative_node_id="12",
            sampler_node_id="19",
            character_node_id="900001",
            options={},
        )
        self.assertNotIn("900001", workflow)
        self.assertIsNone(result["character_lora"])


class DynamicLoraTests(unittest.TestCase):
    def test_dynamic_chain_supports_more_than_four(self) -> None:
        workflow = {
            "1": {"class_type": "BaseModel", "inputs": {}},
            "2": {"class_type": "BaseClip", "inputs": {}},
            "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["46", 1]}},
            "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["46", 1]}},
            "19": {"class_type": "KSampler", "inputs": {"model": ["46", 0], "seed": 1}},
            "46": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["1", 0], "clip": ["2", 0], "lora_name": "old", "strength_model": 1.0, "strength_clip": 1.0},
            },
            "47": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["46", 0], "clip": ["46", 1], "lora_name": "old2", "strength_model": 1.0, "strength_clip": 1.0},
            },
        }
        style = {
            "loras": [
                {"name": f"style-{i}.safetensors", "strength_model": 0.5, "strength_clip": 0.5}
                for i in range(6)
            ]
        }
        result = apply_lora_plan(
            workflow,
            style=style,
            character=None,
            style_slot_ids=["46", "47"],
            positive_node_id="11",
            negative_node_id="12",
            sampler_node_id="19",
            character_node_id="900001",
            options={},
            style_mode="dynamic",
            dynamic_style_node_id_start=900100,
        )
        self.assertEqual(len(result["style_loras"]), 6)
        self.assertNotIn("46", workflow)
        self.assertNotIn("47", workflow)
        self.assertEqual(workflow["19"]["inputs"]["model"], ["900105", 0])
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["900105", 1])


class FiveDrawTests(unittest.TestCase):
    def test_selects_five_distinct_records(self) -> None:
        pool = {
            "prompts": [
                {
                    "id": f"discord-{index}",
                    "prompt": f"public test prompt {index}",
                    "source_code": "D",
                    "safety_code": "N",
                    "safety_level": "normal",
                    "enabled": True,
                }
                for index in range(5)
            ]
        }
        items, _, _ = select_random_prompts(
            pool, 5, source_codes=["D"], safety_codes=["N"]
        )
        self.assertEqual(len(items), 5)
        self.assertEqual(len({item["id"] for item in items}), 5)


if __name__ == "__main__":
    unittest.main()
