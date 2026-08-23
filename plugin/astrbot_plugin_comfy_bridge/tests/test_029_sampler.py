from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from preset_runtime import parse_generation_directives  # noqa: E402
from prompt_pool_runtime import ensure_prompt_pool, load_prompt_pool  # noqa: E402
from workflow_runtime import WorkflowError, prepare_workflow  # noqa: E402


def template() -> dict:
    return {
        "11": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["1", 0]},
        },
        "19": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 30,
                "cfg": 5.0,
                "sampler_name": "er_sde",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
    }


class SamplerPresetTests(unittest.TestCase):
    def test_parses_chinese_and_english_sampler_directive(self) -> None:
        prompt, options = parse_generation_directives("采样器=dpm 1girl, solo")
        self.assertEqual(prompt, "1girl, solo")
        self.assertEqual(options["sampler_preset"], "dpm")
        prompt, options = parse_generation_directives("sampler=dpmpp_2m rainy street")
        self.assertEqual(prompt, "rainy street")
        self.assertEqual(options["sampler_preset"], "dpmpp_2m")
        prompt, options = parse_generation_directives(
            "采样器=2m_sde_gpu 步数=36 CFG=5.5 moonlit garden"
        )
        self.assertEqual(prompt, "moonlit garden")
        self.assertEqual(options["sampler_preset"], "2m_sde_gpu")
        self.assertEqual(options["sampler_steps"], "36")
        self.assertEqual(options["sampler_cfg"], "5.5")

    def test_default_keeps_existing_sampler_settings(self) -> None:
        workflow, _ = prepare_workflow(
            template(),
            prompt="test",
            positive_node_id="11",
            sampler_node_id="19",
            randomize_seed=False,
            fixed_seed=9,
        )
        inputs = workflow["19"]["inputs"]
        self.assertEqual(inputs["seed"], 9)
        self.assertEqual(inputs["sampler_name"], "er_sde")
        self.assertEqual(inputs["steps"], 30)
        self.assertEqual(inputs["cfg"], 5.0)
        self.assertEqual(inputs["scheduler"], "normal")

    def test_dpm_preset_overrides_only_selected_fields(self) -> None:
        workflow, _ = prepare_workflow(
            template(),
            prompt="test",
            positive_node_id="11",
            sampler_node_id="19",
            sampler_overrides={
                "sampler_name": "dpmpp_2m",
                "steps": 30,
                "cfg": 6.0,
                "scheduler": "normal",
            },
        )
        inputs = workflow["19"]["inputs"]
        self.assertEqual(inputs["sampler_name"], "dpmpp_2m")
        self.assertEqual(inputs["steps"], 30)
        self.assertEqual(inputs["cfg"], 6.0)
        self.assertEqual(inputs["scheduler"], "normal")
        self.assertEqual(inputs["denoise"], 1.0)

    def test_sde_preset_overrides_sampler_and_quality_settings(self) -> None:
        workflow, _ = prepare_workflow(
            template(),
            prompt="test",
            positive_node_id="11",
            sampler_node_id="19",
            sampler_overrides={
                "sampler_name": "dpmpp_2m_sde",
                "steps": 30,
                "cfg": 6.0,
                "scheduler": "normal",
            },
        )
        inputs = workflow["19"]["inputs"]
        self.assertEqual(inputs["sampler_name"], "dpmpp_2m_sde")
        self.assertEqual(inputs["steps"], 30)
        self.assertEqual(inputs["cfg"], 6.0)
        self.assertEqual(inputs["scheduler"], "normal")

    def test_gpu_sde_and_custom_steps_cfg_are_written(self) -> None:
        workflow, _ = prepare_workflow(
            template(),
            prompt="test",
            positive_node_id="11",
            sampler_node_id="19",
            sampler_overrides={
                "sampler_name": "dpmpp_2m_sde_gpu",
                "steps": 42,
                "cfg": 4.5,
                "scheduler": "normal",
            },
        )
        inputs = workflow["19"]["inputs"]
        self.assertEqual(inputs["sampler_name"], "dpmpp_2m_sde_gpu")
        self.assertEqual(inputs["steps"], 42)
        self.assertEqual(inputs["cfg"], 4.5)

    def test_missing_sampler_field_is_reported_before_submit(self) -> None:
        workflow = template()
        del workflow["19"]["inputs"]["scheduler"]
        with self.assertRaisesRegex(WorkflowError, "inputs.scheduler"):
            prepare_workflow(
                workflow,
                prompt="test",
                positive_node_id="11",
                sampler_node_id="19",
                sampler_overrides={"scheduler": "normal"},
            )


class ReplacementCatalogMigrationTests(unittest.TestCase):
    def test_discord_replacement_does_not_preserve_repacked_old_ids(self) -> None:
        def item(prompt_id: str, prompt: str) -> dict:
            return {
                "id": prompt_id,
                "prompt": prompt,
                "source_code": "D",
                "source_group": "discord",
                "safety_code": "N",
                "safety_level": "normal",
                "enabled": True,
            }

        persistent = {
            "schema_version": 2,
            "catalog_revision": 1,
            "deleted_prompt_ids": ["discord-0002"],
            "prompts": [
                item("discord-0001", "old prompt assigned to id 1"),
                item("discord-0999", "removed old catalog prompt"),
                item("custom-user-entry", "administrator custom prompt"),
            ],
        }
        bundled = {
            "schema_version": 2,
            "catalog_revision": 2,
            "replace_source_codes_on_upgrade": ["D"],
            "prompts": [
                item("discord-0001", "new prompt assigned to id 1"),
                item("discord-0002", "new prompt assigned to reused id 2"),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "persistent.json"
            source = root / "bundled.json"
            target.write_text(json.dumps(persistent), encoding="utf-8")
            source.write_text(json.dumps(bundled), encoding="utf-8")
            ensure_prompt_pool(target, source)
            result = load_prompt_pool(target)
            by_id = {record["id"]: record for record in result["prompts"]}
            self.assertEqual(by_id["discord-0001"]["prompt"], "new prompt assigned to id 1")
            self.assertIn("discord-0002", by_id)
            self.assertNotIn("discord-0999", by_id)
            self.assertIn("custom-user-entry", by_id)
            self.assertNotIn("discord-0002", result["deleted_prompt_ids"])


if __name__ == "__main__":
    unittest.main()
