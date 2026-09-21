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
        body, selection = parse_group_selector("角色=6ctmika 雨夜")
        self.assertEqual(body, "角色=6ctmika 雨夜")
        self.assertEqual(selection["source_codes"], ["B", "G", "D", "P"])
        self.assertEqual(selection["safety_codes"], ["N", "H"])

    def test_pair(self) -> None:
        body, selection = parse_group_selector("C/H 角色=6ctmika 雨夜")
        self.assertEqual(body, "角色=6ctmika 雨夜")
        self.assertEqual(selection["source_codes"], ["C"])
        self.assertEqual(selection["safety_codes"], ["H"])

    def test_single_safety_uses_default_sources(self) -> None:
        body, selection = parse_group_selector("S prompt")
        self.assertEqual(body, "prompt")
        self.assertEqual(selection["source_codes"], ["B", "G", "D", "P"])
        self.assertEqual(selection["safety_codes"], ["S"])

    def test_k_pool_is_explicit_and_supports_sexual_toggle(self) -> None:
        body, selection = parse_group_selector("K/S 角色=adult scene")
        self.assertEqual(body, "角色=adult scene")
        self.assertEqual(selection["source_codes"], ["K"])
        self.assertEqual(selection["safety_codes"], ["S"])

    def test_p_pool_can_be_selected_directly(self) -> None:
        _, selection = parse_group_selector("P prompt")
        self.assertEqual(selection["source_codes"], ["P"])
        self.assertEqual(selection["safety_codes"], ["N", "H"])

    def test_custom_group_can_follow_fixed_selector(self) -> None:
        body, selection = parse_group_selector("B/N @rainy 角色=test 夜景")
        self.assertEqual(body, "角色=test 夜景")
        self.assertEqual(selection["source_codes"], ["B"])
        self.assertEqual(selection["safety_codes"], ["N"])
        self.assertEqual(selection["custom_groups"], ["rainy"])

    def test_custom_group_can_precede_fixed_selector(self) -> None:
        body, selection = parse_group_selector("@夜景+雨天 D/H prompt")
        self.assertEqual(body, "prompt")
        self.assertEqual(selection["source_codes"], ["D"])
        self.assertEqual(selection["safety_codes"], ["H"])
        self.assertEqual(selection["custom_groups"], ["夜景", "雨天"])

    def test_custom_group_selection_requires_every_group(self) -> None:
        pool = {
            "prompts": [
                {
                    "id": "one",
                    "prompt": "first",
                    "enabled": True,
                    "source_code": "B",
                    "safety_code": "N",
                    "safety_level": "normal",
                    "custom_groups": ["rain", "night"],
                },
                {
                    "id": "two",
                    "prompt": "second",
                    "enabled": True,
                    "source_code": "B",
                    "safety_code": "N",
                    "safety_level": "normal",
                    "custom_groups": ["rain"],
                },
            ]
        }
        item, _, _ = select_random_prompt(
            pool,
            source_codes=["B"],
            safety_codes=["N"],
            custom_groups=["rain", "night"],
        )
        self.assertEqual(item["id"], "one")

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
        cls.pool_path = PLUGIN / "data" / "anima_random_prompt_pool.json"
        cls.pool = load_prompt_pool(cls.pool_path)
        if not cls.pool.get("prompts"):
            raise unittest.SkipTest("Private corpus statistics excluded from public release; synthetic pool tests run separately")

    def test_catalog_stats(self) -> None:
        stats = prompt_pool_stats(self.pool)
        self.assertEqual(stats["total"], 23063)
        self.assertEqual(stats["enabled"], 22495)
        self.assertEqual(stats["sources"]["B"], 450)
        self.assertEqual(stats["sources"]["G"], 4000)
        self.assertEqual(stats["sources"]["D"], 13897)
        self.assertEqual(stats["sources"]["C"], 4716)
        self.assertEqual(stats["safety_codes"]["H"], 1476)
        self.assertEqual(stats["safety_codes"]["S"], 5441)

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
            self.assertEqual(migrated["catalog_revision"], 2026091006)
            self.assertTrue((target.parent / "pool.pre-0.2.6.json").is_file())

    def test_default_sources_do_not_include_codex(self) -> None:
        for _ in range(20):
            item, _, _ = select_random_prompt(self.pool)
            self.assertIn(item["source_code"], {"B", "G", "D", "P"})
            self.assertNotEqual(item["safety_code"], "S")

    def test_bundled_kp_pool_is_isolated_and_paired(self) -> None:
        pool = load_prompt_pool(PLUGIN / "data" / "kp_prompt_pool.json")
        stats = prompt_pool_stats(pool)
        self.assertEqual(stats["total"], 154)
        self.assertEqual(stats["enabled"], 154)
        self.assertEqual(stats["sources"]["K"], 154)
        self.assertEqual(stats["safety_codes"]["N"], 77)
        self.assertEqual(stats["safety_codes"]["S"], 77)
        self.assertTrue(all(item["source_code"] == "K" for item in pool["prompts"]))
        self.assertEqual(pool["upstream"]["excluded"], [])
        self.assertEqual(len(pool["upstream"]["archive_files"]), 16)


if __name__ == "__main__":
    unittest.main()
