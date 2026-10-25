import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.favorite_bridge import publish_favorite_bridge
from astr_auto_anima_hub.prompt_favorites import save_favorite
from astrbot_plugin_comfy_bridge.personal_prompt_runtime import personal_prompts


class FavoriteBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(plugin_data_dir=self.root / "plugin_data",
                                 admin_token="secret-admin", lite_token="secret-lite",
                                 legacy_lite_qq="123456")

    def test_bridge_has_no_secrets_or_content_and_unchanged_startup_does_not_rewrite(self):
        path = publish_favorite_bridge(self.settings)
        raw, mtime = path.read_bytes(), path.stat().st_mtime_ns
        self.assertNotIn(b"secret", raw)
        self.assertEqual(set(json.loads(raw)),
                         {"schema", "legacy_qq", "users_path", "favorites_path"})
        self.assertFalse(self.settings.prompt_favorites_path.exists())
        publish_favorite_bridge(self.settings)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(path.read_bytes(), raw)

    def test_revoked_or_invalid_binding_overwrites_stale_bridge(self):
        path = publish_favorite_bridge(self.settings)
        for changes in ({"legacy_lite_qq": ""}, {"lite_token": ""}, {"legacy_lite_qq": "invalid"}):
            publish_favorite_bridge(replace(self.settings, **changes))
            self.assertEqual(json.loads(path.read_text("utf-8"))["legacy_qq"], "")
        publish_favorite_bridge(replace(self.settings, legacy_lite_qq="654321"))
        self.assertEqual(json.loads(path.read_text("utf-8"))["legacy_qq"], "654321")

    def test_custom_paths_and_full_prompt_remain_read_only_and_owner_isolated(self):
        settings = replace(self.settings, lite_users_override=self.root / "external/users.json",
                           prompt_favorites_override=self.root / "external/favorites.sqlite3")
        save_favorite(settings.prompt_favorites_path, AuthPrincipal(role="user", subject="legacy-owner"),
                      {"id": "source", "prompt": "garden", "safety_code": "N"}, addition="rain")
        save_favorite(settings.prompt_favorites_path, AuthPrincipal(role="admin", subject="administrator"),
                      {"id": "admin", "prompt": "admin private", "safety_code": "N"})
        before = settings.prompt_favorites_path.read_bytes()
        publish_favorite_bridge(settings)
        rows = personal_prompts(settings.plugin_data_dir, "123456")
        self.assertEqual([r["prompt"] for r in rows], ["rain, garden"])
        self.assertEqual(personal_prompts(settings.plugin_data_dir, "654321"), [])
        self.assertEqual(settings.prompt_favorites_path.read_bytes(), before)
        self.assertFalse((settings.hub_state_dir / "prompt_favorites.sqlite3").exists())

    def test_real_app_startup_publishes_binding_and_api_agrees_with_plugin(self):
        save_favorite(self.settings.prompt_favorites_path, AuthPrincipal(role="user", subject="legacy-owner"),
                      {"id": "source", "prompt": "garden", "safety_code": "N"}, addition="rain")
        with TestClient(create_app(self.settings)) as client:
            response = client.get("/api/v1/lite/prompts?source=P", headers={
                "Authorization": "Bearer " + self.settings.lite_token})
            self.assertEqual(response.status_code, 200, response.text)
            rows = personal_prompts(self.settings.plugin_data_dir, "123456")
            self.assertEqual(response.json()["total"], len(rows))
            self.assertEqual(response.json()["items"][0]["prompt"], rows[0]["prompt"])

    def test_failed_atomic_replace_preserves_old_binding(self):
        path = publish_favorite_bridge(self.settings)
        before = path.read_bytes()
        with patch("astr_auto_anima_hub.favorite_bridge.os.replace", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                publish_favorite_bridge(replace(self.settings, legacy_lite_qq="654321"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".favorite_reader_*")), [])
