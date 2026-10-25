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
from prompt_pool_runtime import load_prompt_pool, select_random_prompts  # noqa: E402
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
    def test_quick_workflow_builds_dynamic_style_without_legacy_slots(self) -> None:
        for configured_slots in ([], ["46", "47", "48", "49"]):
            with self.subTest(configured_slots=configured_slots):
                workflow = {
                    "1": {"class_type": "UNETLoader", "inputs": {}},
                    "2": {"class_type": "CLIPLoader", "inputs": {}},
                    "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
                    "12": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
                    "19": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
                }
                result = apply_lora_plan(
                    workflow,
                    style={"loras": [{"name": "my-style.safetensors", "strength_model": 0.8}]},
                    character=None,
                    style_slot_ids=configured_slots,
                    positive_node_id="11",
                    negative_node_id="12",
                    sampler_node_id="19",
                    character_node_id="900001",
                    options={},
                    style_mode="dynamic",
                )
                self.assertEqual(workflow["900100"]["inputs"]["model"], ["1", 0])
                self.assertEqual(workflow["900100"]["inputs"]["clip"], ["2", 0])
                self.assertEqual(workflow["19"]["inputs"]["model"], ["900100", 0])
                self.assertEqual(workflow["11"]["inputs"]["clip"], ["900100", 1])
                self.assertEqual(workflow["12"]["inputs"]["clip"], ["900100", 1])
                self.assertEqual(len(result["style_loras"]), 1)

    def test_quick_workflow_dynamic_style_then_character_lora(self) -> None:
        workflow = {
            "1": {"class_type": "UNETLoader", "inputs": {}},
            "2": {"class_type": "CLIPLoader", "inputs": {}},
            "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0]}},
            "12": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0]}},
            "19": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
        }
        apply_lora_plan(
            workflow,
            style={"loras": [{"name": "style.safetensors"}]},
            character={"lora": {"name": "character.safetensors"}},
            style_slot_ids=[], positive_node_id="11", negative_node_id="12",
            sampler_node_id="19", character_node_id="900001", options={},
            style_mode="dynamic",
        )
        self.assertEqual(workflow["900001"]["inputs"]["model"], ["900100", 0])
        self.assertEqual(workflow["900001"]["inputs"]["clip"], ["900100", 1])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["900001", 0])
        self.assertEqual(workflow["12"]["inputs"]["clip"], ["900001", 1])

    def test_partial_or_broken_dynamic_sources_fail_without_guessing(self) -> None:
        workflow = {
            "1": {"class_type": "UNETLoader", "inputs": {}},
            "2": {"class_type": "CLIPLoader", "inputs": {}},
            "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0]}},
            "19": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
        }
        common = dict(
            style={"loras": [{"name": "style.safetensors"}]}, character=None,
            positive_node_id="11", negative_node_id="12", sampler_node_id="19",
            character_node_id="900001", options={}, style_mode="dynamic",
        )
        with self.assertRaisesRegex(WorkflowError, "定位基础 MODEL/CLIP"):
            apply_lora_plan({**workflow, "11": {"class_type": "CLIPTextEncode", "inputs": {}}},
                            style_slot_ids=[], **common)
        partial = dict(workflow)
        partial["46"] = {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["2", 0]}}
        with self.assertRaisesRegex(WorkflowError, "槽位配置与工作流不一致"):
            apply_lora_plan(partial, style_slot_ids=["46", "47"], **common)
        with self.assertRaisesRegex(WorkflowError, "包含 LoRA 节点"):
            apply_lora_plan(partial, style_slot_ids=[], **common)

    def test_fixed_mode_still_requires_real_slots(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "真实存在的 LoRA 槽位"):
            apply_lora_plan({}, style={"loras": []}, character=None, style_slot_ids=[],
                            positive_node_id="11", negative_node_id="12", sampler_node_id="19",
                            character_node_id="900001", options={}, style_mode="fixed")

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
        pool = {"prompts": [{"id": f"sample-{i}", "prompt": f"tree {i}", "source_code": "D", "safety_code": "N", "enabled": True} for i in range(8)]}
        items, _, _ = select_random_prompts(
            pool, 5, source_codes=["D"], safety_codes=["N"]
        )
        self.assertEqual(len(items), 5)
        self.assertEqual(len({item["id"] for item in items}), 5)


if __name__ == "__main__":
    unittest.main()
