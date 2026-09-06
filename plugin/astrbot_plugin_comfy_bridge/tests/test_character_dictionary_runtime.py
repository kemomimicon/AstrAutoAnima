import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from character_dictionary_runtime import resolve_character
from tools.build_character_dictionary import _translation_sqlite


class CharacterDictionaryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "characters.json"
        self.path.write_text(
            json.dumps(
                {
                    "characters": [
                        {
                            "tag": "hatsune_miku",
                            "aliases": ["初音未来", "Hatsune Miku"],
                            "copyright": ["vocaloid"],
                            "gender": ["1girl"],
                            "appearance": ["aqua_hair", "twintails"],
                            "post_count": 10,
                        },
                        {
                            "tag": "hatsune_miku_(snow_princess)",
                            "base_tag": "hatsune_miku",
                            "is_variant": True,
                            "aliases": ["雪未来（雪公主）", "初音未来"],
                            "copyright": ["vocaloid"],
                            "post_count": 100,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_weak_mode_uses_identity_and_copyright_only(self):
        result = resolve_character(self.path, "初音未来", mode="弱")
        self.assertIsNotNone(result)
        self.assertEqual(result.prompt, "hatsune_miku, vocaloid")

    def test_strong_mode_adds_fixed_appearance(self):
        result = resolve_character(self.path, "Hatsune Miku", mode="strong")
        self.assertIsNotNone(result)
        self.assertEqual(
            result.prompt,
            "hatsune_miku, vocaloid, 1girl, aqua_hair, twintails",
        )

    def test_unknown_character_is_not_guessed(self):
        self.assertIsNone(resolve_character(self.path, "不存在的角色", mode="weak"))

    def test_shared_stripped_alias_prefers_base_character(self):
        result = resolve_character(self.path, "初音未来", mode="weak")
        self.assertIsNotNone(result)
        self.assertEqual(result.tag, "hatsune_miku")

    def test_full_variant_alias_still_selects_variant(self):
        result = resolve_character(self.path, "雪未来（雪公主）", mode="weak")
        self.assertIsNotNone(result)
        self.assertEqual(result.tag, "hatsune_miku_(snow_princess)")

    def test_admin_overlay_can_edit_and_disable_entries(self):
        edits = Path(self.temporary.name) / "character_dictionary_edits.json"
        edits.write_text(
            json.dumps(
                {
                    "entries": {
                        "hatsune_miku": {
                            "aliases": ["葱娘"],
                            "appearance": ["teal_hair"],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = resolve_character(
            self.path, "葱娘", mode="strong", edits_path=edits
        )
        self.assertIsNotNone(result)
        self.assertIn("teal_hair", result.prompt)

        edits.write_text(
            json.dumps(
                {"entries": {"hatsune_miku": {"disabled": True, "aliases": ["葱娘"]}}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.assertIsNone(
            resolve_character(self.path, "葱娘", mode="weak", edits_path=edits)
        )

    def test_translation_sqlite_reads_character_names_only(self):
        database = Path(self.temporary.name) / "tag.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE tags "
                "(name TEXT PRIMARY KEY, category INTEGER, cn_name TEXT)"
            )
            connection.executemany(
                "INSERT INTO tags VALUES (?, ?, ?)",
                [
                    ("hatsune_miku", 4, "初音未来 (VOCALOID)"),
                    ("vocaloid", 3, "歌声合成系列"),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(
            _translation_sqlite(database),
            {"hatsune_miku": ["初音未来 (VOCALOID)", "初音未来"]},
        )


if __name__ == "__main__":
    unittest.main()
