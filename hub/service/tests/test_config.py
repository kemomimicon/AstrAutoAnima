from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from astr_auto_anima_hub.config import Settings


class SettingsTests(unittest.TestCase):
    def test_derived_paths(self) -> None:
        settings = Settings(
            admin_token="x" * 32,
            plugin_data_dir=Path("/tmp/plugin-data"),
            comfyui_root=Path("/tmp/ComfyUI"),
        )
        self.assertEqual(
            settings.prompt_pool_path,
            Path("/tmp/plugin-data/anima_random_prompt_pool.json"),
        )
        self.assertEqual(settings.preset_path, Path("/tmp/plugin-data/presets.json"))
        self.assertEqual(settings.output_dir, Path("/tmp/ComfyUI/output"))

    def test_rejects_short_admin_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 32"):
            Settings(admin_token="short").validate_for_startup()

    def test_explicit_data_file_overrides(self) -> None:
        settings = Settings(
            admin_token="x" * 32,
            prompt_pool_override=Path("/custom/prompts.json"),
            preset_override=Path("/custom/presets.json"),
        )
        self.assertEqual(settings.prompt_pool_path, Path("/custom/prompts.json"))
        self.assertEqual(settings.preset_path, Path("/custom/presets.json"))

    def test_rejects_invalid_lite_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "AAH_LITE_TOKEN"):
            Settings(
                admin_token="a" * 32,
                lite_token="short",
            ).validate_for_startup()
        with self.assertRaisesRegex(ValueError, "AAH_LITE_TOKEN_QQ"):
            Settings(
                admin_token="a" * 32,
                lite_token="b" * 32,
                legacy_lite_qq="not-a-qq",
            ).validate_for_startup()
        with self.assertRaisesRegex(ValueError, "must differ"):
            Settings(
                admin_token="a" * 32,
                lite_token="a" * 32,
            ).validate_for_startup()

    def test_web_root_requires_built_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web_root = Path(temporary) / "web"
            web_root.mkdir()
            settings = Settings(admin_token="a" * 32, web_root=web_root)
            with self.assertRaisesRegex(ValueError, "AAH_WEB_ROOT"):
                settings.validate_for_startup()

            (web_root / "index.html").write_text("web app", encoding="utf-8")
            settings.validate_for_startup()


if __name__ == "__main__":
    unittest.main()
