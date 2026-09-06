import json
import unittest

from preset_runtime import (
    apply_lora_plan,
    parse_character_definition,
    parse_generation_directives,
    parse_style_definition,
    resolve_presets,
)
from workflow_runtime import (
    WorkflowError,
    describe_workflow,
    extract_command_prompt,
    extract_output_images,
    extract_reverse_result,
    history_failed,
    prepare_prompt_batch_workflow,
    prepare_workflow,
    prepare_reverse_workflow,
)


def sample_workflow():
    return {
        "11": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old positive", "clip": ["49", 1]},
        },
        "12": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old negative", "clip": ["49", 1]},
        },
        "19": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "model": ["49", 0]},
        },
        "49": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "characters/test.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.7,
                "model": ["44", 0],
                "clip": ["45", 0],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "aimg"},
        },
    }


def style_workflow():
    workflow = sample_workflow()
    del workflow["49"]
    previous_model = ["44", 0]
    previous_clip = ["45", 0]
    for node_id in ("46", "47", "48", "49"):
        workflow[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": f"old/{node_id}.safetensors",
                "strength_model": 0.5,
                "strength_clip": 0.5,
                "model": previous_model,
                "clip": previous_clip,
            },
        }
        previous_model = [node_id, 0]
        previous_clip = [node_id, 1]
    workflow["11"]["inputs"]["clip"] = ["49", 1]
    workflow["12"]["inputs"]["clip"] = ["49", 1]
    workflow["19"]["inputs"]["model"] = ["49", 0]
    return workflow


class WorkflowRuntimeTests(unittest.TestCase):
    def test_history_failure_does_not_require_completed_flag(self):
        record = {
            "status": {
                "completed": False,
                "status_str": "error",
                "messages": [["execution_error", {"exception_message": "boom"}]],
            }
        }
        self.assertTrue(history_failed(record))

    def test_running_history_is_not_failed(self):
        self.assertFalse(
            history_failed(
                {"status": {"completed": False, "status_str": "running", "messages": []}}
            )
        )

    def test_prepare_prompt_batch_workflow_reuses_clip_and_sets_latent_batch(self):
        template = {
            "11": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "old", "clip": ["49", 1]},
            },
            "28": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 1024, "height": 1536, "batch_size": 1},
            },
        }
        result = prepare_prompt_batch_workflow(
            template,
            positive_node_id="11",
            latent_node_id="28",
            prompts=["first prompt", "second prompt"],
        )
        self.assertEqual(result["28"]["inputs"]["batch_size"], 2)
        self.assertEqual(result["11"]["class_type"], "AnimaPromptBatchEncode")
        self.assertEqual(result["11"]["inputs"]["clip"], ["49", 1])
        self.assertEqual(
            json.loads(result["11"]["inputs"]["prompts_json"]),
            ["first prompt", "second prompt"],
        )

    def test_prepare_reverse_workflow_injects_image_preset_and_source(self):
        template = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "7": {
                "class_type": "AnimaReverseCompiler",
                "inputs": {"preset": "full"},
            },
            "8": {
                "class_type": "AnimaReverseResultSaver",
                "inputs": {
                    "qq_user_id": "",
                    "session_type": "unknown",
                    "session_id": "",
                    "role_preset": "",
                    "style_preset": "",
                    "storage_root": "/workspace/old",
                    "save_thumbnail": False,
                },
            },
        }
        prepared = prepare_reverse_workflow(
            template,
            image_name="incoming/a.png",
            preset="scene",
            qq_user_id="10001",
            session_type="group",
            session_id="20002",
            role_preset="角色A",
            style_preset="画风B",
            storage_root="/workspace/reverse_history",
            save_thumbnail=True,
        )
        self.assertEqual(prepared["1"]["inputs"]["image"], "incoming/a.png")
        self.assertEqual(prepared["7"]["inputs"]["preset"], "scene")
        self.assertEqual(prepared["8"]["inputs"]["qq_user_id"], "10001")
        self.assertEqual(prepared["8"]["inputs"]["session_type"], "group")
        self.assertEqual(prepared["8"]["inputs"]["role_preset"], "角色A")
        self.assertTrue(prepared["8"]["inputs"]["save_thumbnail"])
        self.assertEqual(template["1"]["inputs"]["image"], "old.png")

    def test_extract_reverse_result_reads_explicit_history_fields(self):
        record = {
            "outputs": {
                "8": {
                    "text": ["/workspace/rev.json"],
                    "reverse_id": ["rev-1"],
                    "anima_prompt": ["1girl, rain"],
                    "structured_json": ["{\"schema_version\":\"1.0\"}"],
                    "safety_level": ["normal"],
                }
            }
        }
        result = extract_reverse_result(record)
        self.assertEqual(result["anima_prompt"], "1girl, rain")
        self.assertEqual(result["safety_level"], "normal")
        self.assertEqual(result["reverse_id"], "rev-1")

    def test_extract_reverse_result_rejects_old_saver_node(self):
        with self.assertRaisesRegex(WorkflowError, "没有 anima_prompt"):
            extract_reverse_result(
                {"outputs": {"8": {"text": ["/workspace/rev.json"]}}}
            )

    def test_extracts_multiline_prompt_and_removes_compatibility_token(self):
        message = "/aimg 无优化\nscore_9, highres, detailed\n1girl, solo"
        self.assertEqual(
            extract_command_prompt(message, "无优化"),
            "score_9, highres, detailed\n1girl, solo",
        )

    def test_uses_raw_full_prompt_instead_of_first_parsed_token(self):
        self.assertEqual(
            extract_command_prompt("/aimg one girl in rain", "one"),
            "one girl in rain",
        )

    def test_generation_directives_are_removed_from_prompt(self):
        prompt, options = parse_generation_directives(
            "角色=狐娘 画风=雨夜 角色权重=0.8 画风倍率=1.2\n1girl, rain"
        )
        self.assertEqual(prompt, "1girl, rain")
        self.assertEqual(options["character"], "狐娘")
        self.assertEqual(options["style"], "雨夜")
        self.assertEqual(options["character_strength"], 0.8)
        self.assertEqual(options["style_scale"], 1.2)

    def test_admin_definitions_parse_loras_and_prompt(self):
        name, style = parse_style_definition(
            "雨夜 a.safetensors|0.6|0.5;b.safetensors|0.2|0.2 "
            "--prompt wet, night --match 雨夜|下雨"
        )
        self.assertEqual(name, "雨夜")
        self.assertEqual(len(style["loras"]), 2)
        self.assertEqual(style["prompt"], "wet, night")
        self.assertEqual(style["match"], ["雨夜", "下雨"])

        role_name, role = parse_character_definition(
            "狐娘 chars/fox.safetensors|0.8|0.7 --prompt fox ears, red eyes"
        )
        self.assertEqual(role_name, "狐娘")
        self.assertEqual(role["lora"]["strength_clip"], 0.7)

    def test_style_plan_reuses_slots_and_bypasses_unused_tail(self):
        workflow = style_workflow()
        style = {
            "loras": [
                {"name": "new/a.safetensors", "strength_model": 0.6, "strength_clip": 0.5},
                {"name": "new/b.safetensors", "strength_model": 0.2, "strength_clip": 0.2},
            ]
        }
        plan = apply_lora_plan(
            workflow,
            style=style,
            character=None,
            style_slot_ids=["46", "47", "48", "49"],
            positive_node_id="11",
            negative_node_id="12",
            sampler_node_id="19",
            character_node_id="900001",
            options={},
        )
        self.assertEqual(len(plan["style_loras"]), 2)
        self.assertNotIn("48", workflow)
        self.assertNotIn("49", workflow)
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["47", 1])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["47", 0])

    def test_character_plan_inserts_runtime_node_and_uses_override(self):
        workflow = style_workflow()
        character = {
            "lora": {
                "name": "chars/fox.safetensors",
                "strength_model": 0.7,
                "strength_clip": 0.6,
            }
        }
        plan = apply_lora_plan(
            workflow,
            style=None,
            character=character,
            style_slot_ids=["46", "47", "48", "49"],
            positive_node_id="11",
            negative_node_id="12",
            sampler_node_id="19",
            character_node_id="900001",
            options={"character_strength": 0.9},
        )
        self.assertEqual(workflow["900001"]["inputs"]["model"], ["49", 0])
        self.assertEqual(workflow["900001"]["inputs"]["clip"], ["49", 1])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["900001", 0])
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["900001", 1])
        self.assertEqual(plan["character_lora"]["strength_model"], 0.9)

    def test_resolve_style_by_match_string(self):
        presets = {
            "styles": {"雨夜": {"loras": [], "match": ["下雨"]}},
            "characters": {},
        }
        style, character, style_name, character_name = resolve_presets(
            "1girl, 下雨, street", {}, presets
        )
        self.assertIsNotNone(style)
        self.assertIsNone(character)
        self.assertEqual(style_name, "雨夜")
        self.assertEqual(character_name, "")

    def test_unknown_character_can_be_reserved_as_text(self):
        style, character, style_name, character_name = resolve_presets(
            "garden",
            {"character": "frieren_(sousou_no_frieren)"},
            {"styles": {}, "characters": {}},
            allow_character_text_fallback=True,
        )
        self.assertIsNone(style)
        self.assertIsNone(character)
        self.assertEqual(style_name, "")
        self.assertEqual(character_name, "frieren_(sousou_no_frieren)")

    def test_empty_style_bypasses_every_lora_slot(self):
        workflow = style_workflow()
        apply_lora_plan(
            workflow,
            style={"loras": []},
            character=None,
            style_slot_ids=["46", "47", "48", "49"],
            positive_node_id="11",
            negative_node_id="12",
            sampler_node_id="19",
            character_node_id="900001",
            options={},
        )
        self.assertNotIn("46", workflow)
        self.assertNotIn("47", workflow)
        self.assertNotIn("48", workflow)
        self.assertNotIn("49", workflow)
        self.assertEqual(workflow["19"]["inputs"]["model"], ["44", 0])
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["45", 0])

    def test_prepare_preserves_lora_and_replaces_only_configured_inputs(self):
        template = sample_workflow()
        prepared, seed = prepare_workflow(
            template,
            prompt="1girl, solo",
            positive_node_id="11",
            negative_node_id="12",
            negative_prompt="low quality",
            positive_prefix="masterpiece",
            positive_suffix="white background",
            sampler_node_id="19",
            randomize_seed=False,
            fixed_seed=42,
        )

        self.assertEqual(
            prepared["11"]["inputs"]["text"],
            "masterpiece, 1girl, solo, white background",
        )
        self.assertEqual(prepared["12"]["inputs"]["text"], "low quality")
        self.assertEqual(prepared["19"]["inputs"]["seed"], 42)
        self.assertEqual(prepared["49"], template["49"])
        self.assertEqual(template["11"]["inputs"]["text"], "old positive")
        self.assertEqual(seed, 42)

    def test_missing_prompt_node_is_rejected(self):
        with self.assertRaisesRegex(WorkflowError, "找不到节点"):
            prepare_workflow(
                sample_workflow(), prompt="x", positive_node_id="999"
            )

    def test_describe_workflow_reports_lora_and_output_nodes(self):
        summary = describe_workflow(sample_workflow())
        self.assertEqual(summary["lora_count"], 1)
        self.assertEqual(summary["loras"][0]["node_id"], "49")
        self.assertEqual(summary["output_nodes"], ["9"])

    def test_extract_output_images_deduplicates_entries(self):
        image = {"filename": "a.png", "subfolder": "x", "type": "output"}
        record = {
            "outputs": {
                "9": {"images": [image, image]},
                "10": {"images": [{"filename": "b.png"}]},
            }
        }
        self.assertEqual(
            extract_output_images(record),
            [
                image,
                {"filename": "b.png", "subfolder": "", "type": "output"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
