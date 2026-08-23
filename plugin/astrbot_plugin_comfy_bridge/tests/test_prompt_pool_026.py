from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from prompt_pool_runtime import (  # noqa: E402
    apply_protected_character_policy,
    ensure_prompt_pool,
    load_prompt_pool,
    parse_group_selector,
    prompt_pool_stats,
    select_random_prompt,
)


class GroupSelectorTests(unittest.TestCase):
    def test_defaults(self) -> None:
        body, selection = parse_group_selector("角色=demo_character 雨夜")
        self.assertEqual(body, "角色=demo_character 雨夜")
        self.assertEqual(selection["source_codes"], ["B", "G", "D"])
        self.assertEqual(selection["safety_codes"], ["N", "H"])

    def test_pair(self) -> None:
        body, selection = parse_group_selector("C/H 角色=demo_character 雨夜")
        self.assertEqual(body, "角色=demo_character 雨夜")
        self.assertEqual(selection["source_codes"], ["C"])
        self.assertEqual(selection["safety_codes"], ["H"])

    def test_single_safety_uses_default_sources(self) -> None:
        body, selection = parse_group_selector("S prompt")
        self.assertEqual(body, "prompt")
        self.assertEqual(selection["source_codes"], ["B", "G", "D"])
        self.assertEqual(selection["safety_codes"], ["S"])

    def test_protected_character_forces_nh(self) -> None:
        _, selection = parse_group_selector("C/S prompt")
        selection = apply_protected_character_policy(
            selection, "MyOC", "someone, myoc\nthird"
        )
        self.assertEqual(selection["source_codes"], ["C"])
        self.assertEqual(selection["safety_codes"], ["N", "H"])
        self.assertTrue(selection["protected_fallback"])


class PoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.pool_path = Path(cls.temp.name) / "bundled.json"
        prompts = [
            {"id": "good-001", "prompt": "basic normal", "source_code": "B", "source_group": "basic", "safety_code": "N", "safety_level": "normal", "enabled": True},
            {"id": "basic-h", "prompt": "basic h", "source_code": "B", "source_group": "basic", "safety_code": "H", "safety_level": "nsfw", "enabled": True},
            {"id": "generate-n", "prompt": "generated normal", "source_code": "G", "source_group": "generate", "safety_code": "N", "safety_level": "normal", "enabled": True},
            {"id": "generate-h", "prompt": "generated h", "source_code": "G", "source_group": "generate", "safety_code": "H", "safety_level": "nsfw", "enabled": True},
            {"id": "discord-s", "prompt": "discord s", "source_code": "D", "source_group": "discord", "safety_code": "S", "safety_level": "sexual", "enabled": True},
            {"id": "codex-n", "prompt": "codex normal", "source_code": "C", "source_group": "codex", "safety_code": "N", "safety_level": "normal", "enabled": True},
        ]
        prompts.extend(
            {"id": f"discord-n-{index}", "prompt": f"discord normal {index}", "source_code": "D", "source_group": "discord", "safety_code": "N", "safety_level": "normal", "enabled": True}
            for index in range(5)
        )
        cls.pool_path.write_text(
            json.dumps({"schema_version": 2, "catalog_revision": 2, "release_version": "test", "quality_presets": {"general": {"prompt": "test quality"}}, "replace_source_codes_on_upgrade": [], "prompts": prompts}),
            encoding="utf-8",
        )
        cls.pool = load_prompt_pool(cls.pool_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_catalog_stats(self) -> None:
        stats = prompt_pool_stats(self.pool)
        self.assertEqual(stats["total"], 11)
        self.assertEqual(stats["enabled"], 11)
        self.assertEqual(stats["sources"]["B"], 2)
        self.assertEqual(stats["sources"]["G"], 2)
        self.assertEqual(stats["sources"]["D"], 6)
        self.assertEqual(stats["sources"]["C"], 1)
        self.assertEqual(stats["safety_codes"]["H"], 2)
        self.assertEqual(stats["safety_codes"]["S"], 1)

    def test_explicit_reverse_group_reports_error(self) -> None:
        with self.assertRaisesRegex(Exception, "暂无可用提示词"):
            select_random_prompt(
                self.pool, source_codes=["R"], safety_codes=["N", "H"]
            )

    def test_codex_is_available_when_explicit(self) -> None:
        item, _, _ = select_random_prompt(
            self.pool, source_codes=["C"], safety_codes=["N"]
        )
        self.assertEqual(item["source_code"], "C")
        self.assertEqual(item["safety_code"], "N")

    def test_generate_nsfw_filter(self) -> None:
        item, _, _ = select_random_prompt(
            self.pool, source_codes=["G"], safety_codes=["H"]
        )
        self.assertEqual(item["source_code"], "G")
        self.assertEqual(item["safety_code"], "H")

    def test_discord_sexual_requires_explicit_filter(self) -> None:
        item, _, _ = select_random_prompt(
            self.pool, source_codes=["D"], safety_codes=["S"]
        )
        self.assertEqual(item["source_code"], "D")
        self.assertEqual(item["safety_code"], "S")

    def test_migrates_old_pool_and_preserves_edit(self) -> None:
        old = {
            "schema_version": 1,
            "quality_presets": {"general": {"prompt": "custom quality"}},
            "prompts": [
                {
                    "id": "good-001",
                    "enabled": False,
                    "weight": 7,
                    "prompt": self.pool["prompts"][0]["prompt"],
                    "safety_level": "normal",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pool.json"
            target.write_text(json.dumps(old), encoding="utf-8")
            ensure_prompt_pool(target, self.pool_path)
            migrated = load_prompt_pool(target)
            first = next(item for item in migrated["prompts"] if item["id"] == "good-001")
            self.assertFalse(first["enabled"])
            self.assertEqual(first["weight"], 7)
            self.assertEqual(first["source_code"], "B")
            self.assertEqual(migrated["quality_presets"]["general"]["prompt"], "custom quality")
            self.assertEqual(migrated["catalog_revision"], 2)
            self.assertTrue((target.parent / "pool.pre-0.2.6.json").is_file())

    def test_default_sources_do_not_include_codex(self) -> None:
        for _ in range(20):
            item, _, _ = select_random_prompt(self.pool)
            self.assertIn(item["source_code"], {"B", "G", "D"})
            self.assertNotEqual(item["safety_code"], "S")


if __name__ == "__main__":
    unittest.main()
