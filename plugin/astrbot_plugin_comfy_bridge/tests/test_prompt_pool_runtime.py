import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt_pool_runtime import (
    compose_random_body,
    load_prompt_pool,
    parse_group_selector,
    prompt_pool_stats,
    quality_prompt,
    select_random_prompt,
)
from preset_runtime import parse_generation_directives


class PromptPoolRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.pool = {
            "category_aliases": {
                "rain": ["雨夜", "rain"],
                "summer": ["夏日", "summer"],
            },
            "quality_presets": {
                "general": {"enabled": True, "prompt": "best quality"}
            },
            "prompts": [
                {
                    "id": "good-001",
                    "enabled": True,
                    "weight": 1,
                    "prompt": "1girl, solo, rainy street",
                    "categories": ["rain"],
                    "safety_level": "normal",
                },
                {
                    "id": "good-002",
                    "enabled": True,
                    "weight": 1,
                    "prompt": "1girl, solo, nude, bathing",
                    "categories": ["summer"],
                    "safety_level": "nsfw",
                },
                {
                    "id": "good-003",
                    "enabled": False,
                    "weight": 1,
                    "prompt": "duplicate",
                    "categories": ["rain"],
                    "safety_level": "sexual",
                },
            ],
        }

    def test_load_validates_three_internal_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_text(json.dumps(self.pool), encoding="utf-8")
            loaded = load_prompt_pool(path)
        self.assertEqual(len(loaded["prompts"]), 3)

    def test_random_selection_does_not_filter_nsfw_label(self):
        with patch("prompt_pool_runtime.secrets.randbelow", return_value=1):
            selected, matched, used_match = select_random_prompt(self.pool, "")
        self.assertEqual(selected["id"], "good-002")
        self.assertEqual(matched, [])
        self.assertFalse(used_match)

    def test_user_prompt_prefers_matching_category(self):
        selected, matched, used_match = select_random_prompt(self.pool, "雨夜")
        self.assertEqual(selected["id"], "good-001")
        self.assertEqual(matched, ["rain"])
        self.assertTrue(used_match)

    def test_quality_and_prompt_composition(self):
        self.assertEqual(quality_prompt(self.pool), "best quality")
        self.assertEqual(
            compose_random_body("holding umbrella", self.pool["prompts"][0]),
            "holding umbrella, 1girl, solo, rainy street",
        )

    def test_random_subject_tag_changes_only_the_drawn_entry(self):
        item = self.pool["prompts"][0]
        self.assertEqual(
            compose_random_body("holding umbrella", item, subject_tag="1boy"),
            "holding umbrella, 1boy, solo, rainy street",
        )
        self.assertEqual(
            compose_random_body("", item, subject_tag="none"),
            "solo, rainy street",
        )
        self.assertEqual(item["prompt"], "1girl, solo, rainy street")
        self.assertEqual(
            compose_random_body("", {"source_code": "K", "prompt": "1girl, solo"}, subject_tag="1man"),
            "1girl, solo",
        )
        self.assertEqual(
            compose_random_body("", {"prompt": "score_9, 1girl, solo"}, subject_tag="1man"),
            "score_9, 1girl, solo",
        )

    def test_random_command_reads_selector_before_subject_choice(self):
        body, selection = parse_group_selector("D/N 起手=1boy 角色=梅娅")
        prompt, options = parse_generation_directives(body)
        self.assertEqual(selection["source_codes"], ["D"])
        self.assertEqual(selection["safety_codes"], ["N"])
        self.assertEqual(prompt, "")
        self.assertEqual(options["random_subject_tag"], "1boy")
        self.assertEqual(options["character"], "梅娅")

    def test_stats_preserve_labels_and_disabled_duplicates(self):
        stats = prompt_pool_stats(self.pool)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["enabled"], 2)
        self.assertEqual(stats["labels"]["sexual"], 1)


if __name__ == "__main__":
    unittest.main()
