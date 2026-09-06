from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from hub_lite_user_manager import (  # noqa: E402
    ManagerError,
    add_users,
    load_registry,
    parse_qq_values,
    write_delivery,
)
from prompt_pool_manager import (  # noqa: E402
    empty_pool,
    group_definitions,
    load_pool,
    merge_records,
    remove_records,
    save_pool,
)


class HubUserManagerTests(unittest.TestCase):
    def test_append_and_rotate_tokens_without_storing_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "lite_users.json"
            delivery = root / "tokens.csv"
            issued, backup = add_users(registry, ["123456"], allow_group=False)
            self.assertIsNone(backup)
            self.assertTrue(issued[0][1].startswith("aah_u_"))
            payload = load_registry(registry)
            serialized = json.dumps(payload)
            self.assertNotIn(issued[0][1], serialized)
            self.assertFalse(payload["users"][0]["allow_group"])
            write_delivery(delivery, issued)
            with delivery.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["token"], issued[0][1])
            rotated, backup = add_users(
                registry, ["123456"], rotate_existing=True
            )
            self.assertIsNotNone(backup)
            self.assertNotEqual(rotated[0][1], issued[0][1])

    def test_rejects_duplicate_input(self) -> None:
        with self.assertRaises(ManagerError):
            parse_qq_values(["123456\n123456"])


class PromptPoolManagerTests(unittest.TestCase):
    def test_add_save_reload_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            pool = empty_pool()
            added, updated = merge_records(
                pool,
                [
                    {
                        "id": "example-001",
                        "name": "Example",
                        "source_code": "B",
                        "safety_code": "N",
                        "prompt": "1girl, solo, reading a book",
                    }
                ],
                overwrite=False,
            )
            self.assertEqual((added, updated), (1, 0))
            self.assertIsNone(save_pool(path, pool))
            loaded = load_pool(path)
            self.assertEqual(loaded["prompts"][0]["source_group"], "basic")
            self.assertEqual(remove_records(loaded, ["example-001"]), 1)
            self.assertIsNotNone(save_pool(path, loaded))
            self.assertEqual(load_pool(path)["prompts"], [])

    def test_import_overwrite_is_explicit(self) -> None:
        pool = empty_pool()
        merge_records(
            pool,
            [{"id": "same", "prompt": "first", "source_code": "B", "safety_code": "N"}],
            overwrite=False,
        )
        self.assertEqual(
            merge_records(
                pool,
                [{"id": "same", "prompt": "second", "source_code": "D", "safety_code": "H"}],
                overwrite=False,
            ),
            (0, 0),
        )
        self.assertEqual(pool["prompts"][0]["prompt"], "first")
        self.assertEqual(
            merge_records(
                pool,
                [{"id": "same", "prompt": "second", "source_code": "D", "safety_code": "H"}],
                overwrite=True,
            ),
            (0, 1),
        )
        self.assertEqual(pool["prompts"][0]["prompt"], "second")

    def test_custom_groups_round_trip_without_fixed_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.json"
            pool = empty_pool()
            pool["custom_group_definitions"] = [
                {"id": "风景", "name": "风景专题"},
                {"id": "night", "name": "夜景"},
            ]
            merge_records(
                pool,
                [
                    {
                        "id": "custom-001",
                        "prompt": "1girl, solo, city at night",
                        "source_code": "B",
                        "safety_code": "N",
                        "custom_groups": "风景|night",
                    }
                ],
                overwrite=False,
            )
            save_pool(path, pool)
            loaded = load_pool(path)
            self.assertEqual(
                [item["id"] for item in group_definitions(loaded)],
                ["风景", "night"],
            )
            self.assertEqual(
                loaded["prompts"][0]["custom_groups"], ["风景", "night"]
            )


if __name__ == "__main__":
    unittest.main()
