from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub import local_gufeng
from astr_auto_anima_hub.local_gufeng import GufengError, draw_gufeng, gufeng_available
from gufeng_fixture import create_gufeng_fixture, insert_gufeng_card, open_fixture_db


class LocalGufengTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # URI escaping must handle spaces, hash signs and non-ASCII paths.
        self.catalog_dir = self.root / "中华 cards #1"
        self.catalog_dir.mkdir()
        self.path = self.catalog_dir / "cards.sqlite3"
        self.manifest = self.catalog_dir / "catalog_manifest.json"
        create_gufeng_fixture(self.path)

    def tearDown(self):
        local_gufeng._inspect_catalog.cache_clear()
        local_gufeng._candidate_ids.cache_clear()
        self.temp.cleanup()

    def _replace_tags(self, tags):
        with open_fixture_db(self.path) as db:
            db.execute("UPDATE full SET tags_json=? WHERE origin='cn'", (json.dumps(tags),))

    def test_settings_opt_in(self):
        with patch.dict(os.environ, {"AAH_LOCAL_GUFENG_CATALOG_PATH": ""}):
            self.assertIsNone(Settings.from_env().local_gufeng_catalog_path)
        with patch.dict(os.environ, {"AAH_LOCAL_GUFENG_CATALOG_PATH": " " + str(self.path) + " "}):
            self.assertEqual(Settings.from_env().local_gufeng_catalog_path, self.path)

    def test_seed_reproducible_and_only_chinese_full_cards(self):
        rows = [draw_gufeng(self.path, seed) for seed in range(25)]
        self.assertEqual(rows[7], draw_gufeng(self.path, 7))
        self.assertEqual(len({row["template_id"] for row in rows}), 2)
        for seed, row in enumerate(rows):
            self.assertTrue(row["template_id"].startswith("V:"))
            self.assertLessEqual(len(row["template_id"]), 300)
            self.assertEqual(row["selection_seed"], seed)
            self.assertEqual(row["provenance"]["origin"], "cn")
            self.assertEqual(row["provenance"]["mode"], "full")
            self.assertNotIn("foreign", row["prompt"])

    def test_preserves_real_ids_version_and_source_evidence(self):
        row = draw_gufeng(self.path, 2)
        provenance = row["provenance"]
        self.assertEqual(row["template_id"], "V:" + provenance["catalog_id"])
        self.assertEqual(provenance["catalog_version"], "0.4.0")
        self.assertEqual(provenance["catalog_sha256"], "a" * 64)
        self.assertEqual(provenance["source_sha256"], "b" * 64)
        self.assertEqual(provenance["grounded_quotes"], ["明月"])
        self.assertEqual(provenance["source_text"], "山中明月。")
        self.assertEqual(provenance["source_start"], 0)
        self.assertEqual(provenance["source_end"], 5)
        self.assertEqual(provenance["source_license"], "MIT")
        self.assertEqual(provenance["source_url"], "https://example.test/poem")
        self.assertEqual(provenance["quality"], "mechanical_candidate")
        self.assertEqual(row["scene_zh"], "雾中远山与明月。")

    def test_identity_meta_duplicates_and_nonenglish_cleaned(self):
        self._replace_tags([
            "1girl", "solo", "(solo:1.2)", "[solo]", "2boys", "female_focus", "mature male", "old woman",
            "loli", "1other", "multiple others", "3girls, lake", "  Mist   Valley ",
            "mist_valley", "LAKE", "poetic illustration", "air (visual novel)",
            "明月", 42, "person", "figure", "silhouette",
        ])
        self.assertEqual(draw_gufeng(self.path, 0)["prompt"],
                         "lake, Mist Valley, person, figure, silhouette")

    def test_does_not_add_people_to_landscape(self):
        self._replace_tags(["mountain", "lake", "moon"])
        self.assertEqual(draw_gufeng(self.path, 0)["prompt"], "mountain, lake, moon")

    def test_all_identity_tags_rejected(self):
        self._replace_tags(["1girl", "solo"])
        with self.assertRaisesRegex(GufengError, "视觉标签"):
            draw_gufeng(self.path, 0)

    def test_long_catalog_id_has_bounded_stable_template_id(self):
        with open_fixture_db(self.path) as db:
            db.execute("DELETE FROM full")
            insert_gufeng_card(db, "long:" + "x" * 400, "cn", ["mountain"])
        row = draw_gufeng(self.path, 0)
        self.assertLessEqual(len(row["template_id"]), 300)
        self.assertEqual(row["provenance"]["catalog_id"], "long:" + "x" * 400)
        self.assertEqual(row, draw_gufeng(self.path, 0))

    def test_arbitrary_catalog_ids_remain_safe_in_single_segment_routes(self):
        card_id = "painter:中华/poem?#fragment"
        with open_fixture_db(self.path) as db:
            db.execute("DELETE FROM full")
            insert_gufeng_card(db, card_id, "cn", ["mountain"])
        row = draw_gufeng(self.path, 0)
        self.assertEqual(row["provenance"]["catalog_id"], card_id)
        self.assertRegex(row["template_id"], r"^V:sha256:[0-9a-f]{64}$")

    def test_readonly_connection_no_writes_or_network(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with local_gufeng._connect(local_gufeng._files(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM full")
        with patch("socket.create_connection", side_effect=AssertionError("unexpected network")):
            self.assertTrue(gufeng_available(self.path))
            draw_gufeng(self.path, 0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertEqual({p.name for p in self.catalog_dir.iterdir()}, {"cards.sqlite3", "catalog_manifest.json"})

    def test_available_does_not_load_all_candidate_ids(self):
        with patch.object(local_gufeng, "_candidate_ids", side_effect=AssertionError("full scan")):
            self.assertTrue(gufeng_available(self.path))

    def test_candidate_scan_only_once_for_unchanged_catalog(self):
        statements = []
        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            self.assertTrue(str(args[0]).endswith("?mode=ro"))
            self.assertTrue(kwargs["uri"])
            db = real_connect(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        with patch.object(local_gufeng.sqlite3, "connect", side_effect=connect):
            draw_gufeng(self.path, 0)
            draw_gufeng(self.path, 10)
        self.assertEqual(sum(sql == "SELECT id FROM full WHERE origin='cn'" for sql in statements), 1)
        self.assertFalse(any("COUNT(" in sql or "OFFSET" in sql for sql in statements))

    def test_thread_safe_reproducibility(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: draw_gufeng(self.path, 42), range(12)))
        self.assertTrue(all(row == rows[0] for row in rows))

    def test_manifest_revision_invalidates_cached_metadata(self):
        self.assertEqual(draw_gufeng(self.path, 0)["provenance"]["catalog_version"], "0.4.0")
        self.manifest.write_text(json.dumps({"version": "0.4.1-test"}), encoding="utf-8")
        self.assertEqual(draw_gufeng(self.path, 0)["provenance"]["catalog_version"], "0.4.1-test")

    def test_missing_path_and_missing_manifest_are_unavailable(self):
        self.assertFalse(gufeng_available(None))
        missing = self.root / "missing.sqlite3"
        self.assertFalse(gufeng_available(missing))
        with self.assertRaises(GufengError):
            draw_gufeng(missing, 0)
        self.assertFalse(missing.exists())
        self.manifest.unlink()
        self.assertFalse(gufeng_available(self.path))
        with self.assertRaisesRegex(GufengError, "catalog_manifest"):
            draw_gufeng(self.path, 0)

    def test_invalid_sqlite_or_schema_rejected(self):
        invalid = self.catalog_dir / "broken.sqlite3"
        invalid.write_bytes(b"not a sqlite database")
        self.assertFalse(gufeng_available(invalid))
        with self.assertRaises(GufengError):
            draw_gufeng(invalid, 0)
        with open_fixture_db(self.path) as db:
            db.execute("ALTER TABLE full RENAME COLUMN tags_json TO tags_invalid")
        self.assertFalse(gufeng_available(self.path))
        with self.assertRaisesRegex(GufengError, "字段"):
            draw_gufeng(self.path, 0)

    def test_no_chinese_candidates_rejected(self):
        with open_fixture_db(self.path) as db:
            db.execute("DELETE FROM full WHERE origin='cn'")
        self.assertFalse(gufeng_available(self.path))
        with self.assertRaisesRegex(GufengError, "中华候选"):
            draw_gufeng(self.path, 0)

    def test_broken_source_and_quotes_rejected(self):
        with open_fixture_db(self.path) as db:
            db.execute("UPDATE full SET grounded_quotes_json=?", (json.dumps(["不存在"]),))
        with self.assertRaisesRegex(GufengError, "引文"):
            draw_gufeng(self.path, 0)
        with open_fixture_db(self.path) as db:
            db.execute("DELETE FROM source")
        with self.assertRaisesRegex(GufengError, "来源索引"):
            draw_gufeng(self.path, 0)

    def test_missing_or_blank_source_attribution_rejected(self):
        with open_fixture_db(self.path) as db:
            db.execute("UPDATE provenance SET license=' '")
        with self.assertRaisesRegex(GufengError, "署名或许可"):
            draw_gufeng(self.path, 0)
        with open_fixture_db(self.path) as db:
            db.execute("DELETE FROM provenance")
        with self.assertRaisesRegex(GufengError, "署名或许可"):
            draw_gufeng(self.path, 0)

    def test_bad_json_manifest_and_seed_use_domain_errors(self):
        for seed in (True, "1", None):
            with self.assertRaises(GufengError):
                draw_gufeng(self.path, seed)
        with open_fixture_db(self.path) as db:
            db.execute("UPDATE full SET tags_json='not json'")
        with self.assertRaises(GufengError):
            draw_gufeng(self.path, 0)
        self.manifest.write_text("{}", encoding="utf-8")
        self.assertFalse(gufeng_available(self.path))
        with self.assertRaisesRegex(GufengError, "版本"):
            draw_gufeng(self.path, 0)


if __name__ == "__main__":
    unittest.main()
