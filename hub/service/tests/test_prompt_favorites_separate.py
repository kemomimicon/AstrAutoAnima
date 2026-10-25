import json
import tempfile
import unittest
from pathlib import Path

from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.prompt_favorites import list_favorites
from astr_auto_anima_hub.prompt_favorites_migration import migrate_legacy_favorites
from astr_auto_anima_hub.prompt_likes import promote_k_prompt, remove_prompt_favorite
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.repositories import RepositoryError


class SeparateFavoritesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.plugin_data = root / "plugin_data"
        self.plugin_data.mkdir()
        self.settings = Settings(plugin_data_dir=self.plugin_data)
        self.user = AuthPrincipal(role="user", subject="user-a")
        self.other = AuthPrincipal(role="user", subject="user-b")
        self.pool = self.settings.prompt_pool_path
        self.pool.write_text(json.dumps({"prompts": [
            {"id": "good-1", "prompt": "1girl, street", "source_code": "B"},
            {"id": "good-2", "prompt": "1girl, street", "source_code": "B"},
        ]}), encoding="utf-8")

    def test_complete_text_dedup_and_isolation(self):
        before = self.pool.read_bytes()
        first = promote_k_prompt(self.settings, "good-1", self.user, addition="rainy night")
        duplicate = promote_k_prompt(self.settings, "good-2", self.user, addition=" rainy   night ")
        variant = promote_k_prompt(self.settings, "good-1", self.user, addition="sunny day")
        self.assertEqual(duplicate.action, "already_liked")
        self.assertEqual(duplicate.saved_prompt_id, first.saved_prompt_id)
        self.assertNotEqual(variant.saved_prompt_id, first.saved_prompt_id)
        self.assertEqual(self.pool.read_bytes(), before)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.user).total, 2)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.other).total, 0)
        with self.assertRaises(RepositoryError):
            remove_prompt_favorite(self.settings, "good-1", self.user)
        remove_prompt_favorite(self.settings, first.saved_prompt_id, self.user)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.user).total, 1)

    def test_legacy_migration_dry_run_and_verified_removal(self):
        legacy = json.loads(self.pool.read_text())
        legacy["prompts"].extend([
            {"id": "liked-old-1", "liked_from": "good-1", "liked_by": "user-a",
             "prompt": "old favorite", "source_code": "P"},
            {"id": "liked-old-2", "liked_from": "good-2", "liked_by": "user-a",
             "prompt": "old favorite", "source_code": "P"},
        ])
        self.pool.write_text(json.dumps(legacy), encoding="utf-8")
        before = self.pool.read_bytes()
        preview = migrate_legacy_favorites(self.pool, self.settings.prompt_favorites_path)
        self.assertEqual(preview["legacy_rows"], 2)
        self.assertEqual(self.pool.read_bytes(), before)
        self.assertFalse(self.settings.prompt_favorites_path.exists())
        result = migrate_legacy_favorites(
            self.pool, self.settings.prompt_favorites_path, apply=True, remove_embedded=True,
        )
        self.assertEqual(result["removed"], 2)
        self.assertEqual(list_favorites(self.settings.prompt_favorites_path, self.user).total, 1)
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        self.assertEqual(len(json.loads(self.pool.read_text())["prompts"]), 2)


if __name__ == "__main__":
    unittest.main()
