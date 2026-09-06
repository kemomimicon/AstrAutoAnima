from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.install_character_dictionary import (
    _backup_output,
    _validate_characters,
    _validate_translations,
)


class InstallCharacterDictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_validate_character_jsonl(self) -> None:
        source = self.root / "characters.jsonl"
        source.write_text(
            "\n".join(
                json.dumps({"name": f"character_{index}"}) for index in range(3)
            ),
            encoding="utf-8",
        )
        self.assertEqual(_validate_characters(source, minimum_records=3), 3)

    def test_validate_character_jsonl_rejects_missing_tag(self) -> None:
        source = self.root / "characters.jsonl"
        source.write_text('{"copyright":"test"}\n', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "name/tag"):
            _validate_characters(source, minimum_records=1)

    def test_validate_translation_sqlite(self) -> None:
        source = self.root / "tag.sqlite"
        connection = sqlite3.connect(source)
        connection.execute(
            "CREATE TABLE tags (name TEXT, category INTEGER, cn_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO tags VALUES (?, ?, ?)",
            [("a", 4, "甲"), ("b", 4, "乙"), ("c", 0, "丙")],
        )
        connection.commit()
        connection.close()
        self.assertEqual(_validate_translations(source, minimum_records=2), 2)

    def test_backup_output(self) -> None:
        output = self.root / "character_dictionary.json"
        output.write_text("old", encoding="utf-8")
        backup = _backup_output(output)
        self.assertIsNotNone(backup)
        self.assertEqual(backup.read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
