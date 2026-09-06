from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

import kp_dynamic_runtime as dynamic  # noqa: E402
from prompt_pool_runtime import _merge_prompt_pools  # noqa: E402


class KPDynamicRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = json.loads(
            (PLUGIN / "data" / "kp_prompt_pool.json").read_text(encoding="utf-8")
        )
        cls.catalog = dynamic.load_kp_module_catalog(
            PLUGIN / "data" / "kp_dynamic_modules.json"
        )
        if not cls.pool.get("prompts"):
            raise unittest.SkipTest("公开发行版故意不附带 K 提示词语料")

    def test_catalog_covers_all_runtime_slots(self) -> None:
        expected = {
            "scene",
            "camera",
            "exposure",
            "wardrobe",
            "lighting",
            "pose",
            "expression",
            "style",
            "makeup",
            "hair",
            "detail",
            "marking",
            "prop",
            "persona",
        }
        self.assertEqual(set(self.catalog["modules"]), expected)
        for slot in expected:
            self.assertGreater(len(self.catalog["modules"][slot]), 20, slot)

    def test_normal_compositions_remain_normal(self) -> None:
        records = dynamic.assemble_dynamic_k_prompts(
            self.pool,
            self.catalog,
            20,
            safety_codes=["N"],
            preserve_character=True,
        )
        self.assertEqual(len({item["id"] for item in records}), 20)
        for item in records:
            self.assertEqual(item["safety_code"], "N")
            self.assertTrue(item["id"].startswith("kp-dyn-n-"))
            self.assertIsNone(dynamic._SEXUAL_RE.search(item["prompt"]))
            self.assertIsNone(dynamic._NSFW_RE.search(item["prompt"]))
            self.assertIsNone(dynamic._UNSAFE_CONTEXT_RE.search(item["prompt"]))

    def test_h_and_s_use_separate_safety_gates(self) -> None:
        for code, forbidden in (("H", dynamic._SEXUAL_RE), ("S", None)):
            records = dynamic.assemble_dynamic_k_prompts(
                self.pool,
                self.catalog,
                8,
                safety_codes=[code],
                preserve_character=False,
            )
            for item in records:
                self.assertEqual(item["safety_code"], code)
                self.assertIsNone(dynamic._UNSAFE_CONTEXT_RE.search(item["prompt"]))
                if forbidden is not None:
                    self.assertIsNone(forbidden.search(item["prompt"]))
                else:
                    self.assertIsNotNone(dynamic._SEXUAL_RE.search(item["prompt"]))

    def test_character_mode_omits_identity_changing_slots(self) -> None:
        item = dynamic.assemble_dynamic_k_prompt(
            self.pool,
            self.catalog,
            safety_codes=["N"],
            preserve_character=True,
            min_optional_modules=10,
            max_optional_modules=10,
        )
        slots = {part["slot"] for part in item["dynamic_components"]}
        self.assertTrue({"hair", "marking", "persona"}.isdisjoint(slots))

    def test_dynamic_history_is_bounded_and_likeable_by_id(self) -> None:
        records = dynamic.assemble_dynamic_k_prompts(
            self.pool, self.catalog, 3, safety_codes=["N"]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "kp_prompt_pool.json"
            path.write_text(json.dumps(self.pool), encoding="utf-8")
            count = dynamic.persist_dynamic_k_entries(path, records, history_limit=50)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(count, 3)
            by_id = {str(item["id"]): item for item in saved["prompts"]}
            for record in records:
                self.assertIn(record["id"], by_id)
                self.assertTrue(record["id"].startswith("kp-"))
                self.assertTrue(by_id[record["id"]]["runtime_generated"])

    def test_dynamic_history_survives_managed_k_catalog_upgrade(self) -> None:
        record = dynamic.assemble_dynamic_k_prompt(
            self.pool, self.catalog, safety_codes=["N"]
        )
        persistent = dict(self.pool)
        persistent["catalog_revision"] = 1
        persistent["prompts"] = [*self.pool["prompts"], record]
        bundled = dict(self.pool)
        bundled["catalog_revision"] = 2
        merged = _merge_prompt_pools(persistent, bundled)
        self.assertIn(record["id"], {item["id"] for item in merged["prompts"]})


if __name__ == "__main__":
    unittest.main()
