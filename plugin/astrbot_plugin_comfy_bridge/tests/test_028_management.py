from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from preset_runtime import (  # noqa: E402
    clear_preset_trigger,
    load_presets,
    update_preset_trigger,
)
from prompt_pool_runtime import (  # noqa: E402
    add_prompt_entry,
    decode_group_code_token,
    delete_prompt_entry,
    ensure_prompt_pool,
    export_prompt_entries,
    filter_prompt_entries,
    get_prompt_entry,
    import_prompt_entries,
    load_prompt_pool,
    require_source_safety_selector,
    update_prompt_entry,
)


class SelectorAndFilterTests(unittest.TestCase):
    def test_decodes_partial_and_full_selectors(self) -> None:
        self.assertEqual(decode_group_code_token("C/H"), (["C"], ["H"]))
        self.assertEqual(decode_group_code_token("B"), (["B"], []))
        self.assertEqual(require_source_safety_selector("D/S"), ("D", "S"))
        self.assertIsNone(decode_group_code_token("rainy"))

    def test_filters_by_group_and_keyword(self) -> None:
        pool = {
            "prompts": [
                {"id": "a", "prompt": "rainy street", "source_code": "B", "safety_code": "N"},
                {"id": "b", "prompt": "sunny beach", "source_code": "D", "safety_code": "H"},
            ]
        }
        result = filter_prompt_entries(
            pool, source_codes=["B"], safety_codes=["N"], keyword="RAINY"
        )
        self.assertEqual([item["id"] for item in result], ["a"])


class PromptPoolMutationTests(unittest.TestCase):
    def _base_pool(self) -> dict:
        return {
            "schema_version": 2,
            "catalog_revision": 1,
            "prompts": [
                {
                    "id": "base-1",
                    "name": "base",
                    "enabled": True,
                    "weight": 1,
                    "prompt": "1girl, solo, rainy street",
                    "source_group": "basic",
                    "source_code": "B",
                    "safety_level": "normal",
                    "safety_code": "N",
                }
            ],
        }

    def test_add_update_delete_and_tombstone_survives_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pool.json"
            bundled = root / "bundled.json"
            trash = root / "trash.json"
            path.write_text(json.dumps(self._base_pool()), encoding="utf-8")

            entry, backup = add_prompt_entry(
                path, prompt="new prompt", source_code="R", safety_code="H"
            )
            self.assertTrue(backup and backup.is_file())
            updated, _ = update_prompt_entry(
                path,
                entry["id"],
                prompt="updated prompt",
                source_code="C",
                safety_code="S",
            )
            self.assertEqual(updated["source_code"], "C")
            self.assertEqual(updated["safety_level"], "sexual")

            deleted, _ = delete_prompt_entry(path, trash, "base-1", actor="admin")
            self.assertEqual(deleted["id"], "base-1")
            self.assertEqual(len(json.loads(trash.read_text(encoding="utf-8"))["deleted"]), 1)

            newer = self._base_pool()
            newer["catalog_revision"] = 2
            bundled.write_text(json.dumps(newer), encoding="utf-8")
            ensure_prompt_pool(path, bundled)
            merged = load_prompt_pool(path)
            self.assertNotIn("base-1", {item["id"] for item in merged["prompts"]})
            self.assertIn("base-1", merged["deleted_prompt_ids"])

    def test_import_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pool.json"
            incoming = root / "incoming.json"
            exported = root / "exported.json"
            path.write_text(json.dumps(self._base_pool()), encoding="utf-8")
            incoming.write_text(
                json.dumps(
                    {
                        "prompts": [
                            {
                                "id": "incoming-1",
                                "prompt": "imported prompt",
                                "source_code": "D",
                                "safety_code": "H",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            added, skipped, _ = import_prompt_entries(path, incoming)
            self.assertEqual((added, skipped), (1, 0))
            item = get_prompt_entry(load_prompt_pool(path), "incoming-1")
            self.assertEqual(item["safety_level"], "nsfw")
            export_prompt_entries(exported, [item], selector="D/H")
            payload = json.loads(exported.read_text(encoding="utf-8"))
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["selector"], "D/H")


class TriggerMutationTests(unittest.TestCase):
    def test_update_and_clear_trigger_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presets.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "styles": {"ink": {"loras": [], "prompt": "old", "match": ["old"]}},
                        "characters": {"hero": {"lora": None, "prompt": "hero tag"}},
                    }
                ),
                encoding="utf-8",
            )
            update_preset_trigger(path, "画风", "ink", "match", "ink|水墨")
            update_preset_trigger(path, "角色", "hero", "prompt", "new hero tag")
            data = load_presets(path)
            self.assertEqual(data["styles"]["ink"]["match"], ["ink", "水墨"])
            self.assertEqual(data["characters"]["hero"]["prompt"], "new hero tag")
            clear_preset_trigger(path, "画风", "ink", "prompt")
            self.assertEqual(load_presets(path)["styles"]["ink"]["prompt"], "")
            clear_preset_trigger(path, "角色", "hero", "all")
            self.assertNotIn("hero", load_presets(path)["characters"])


if __name__ == "__main__":
    unittest.main()
