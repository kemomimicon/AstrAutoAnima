from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.lora_catalog import list_style_loras, scan_loras, update_lora
from astr_auto_anima_hub.personal_styles import (
    delete_personal_style,
    list_personal_styles,
    write_personal_style,
)
from astr_auto_anima_hub.prompt_likes import promote_k_prompt
from astr_auto_anima_hub.remote_jobs import (
    RemoteJobError,
    _prompt_ids_from_plain,
    build_remote_command,
    load_delivery_targets,
)
from astr_auto_anima_hub.schemas import (
    LoraCatalogUpdateRequest,
    PersonalStyleLora,
    PersonalStyleWriteRequest,
    RemoteJobCreateRequest,
)


class KpLoraPersonalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        plugin = root / "plugin"
        plugin_data = root / "plugin_data"
        comfy = root / "ComfyUI"
        (plugin / "data").mkdir(parents=True)
        (plugin_data / "hub_state").mkdir(parents=True)
        (comfy / "models" / "loras" / "artist").mkdir(parents=True)
        (comfy / "models" / "loras" / "artist" / "ink.safetensors").write_bytes(b"lora")
        main_pool = {
            "catalog_revision": 1,
            "prompts": [
                {
                    "id": "good-001",
                    "name": "base",
                    "prompt": "1girl, solo",
                    "source_code": "B",
                    "source_group": "basic",
                    "safety_code": "N",
                    "safety_level": "normal",
                    "enabled": True,
                }
            ],
        }
        kp_pool = {
            "catalog_revision": 1,
            "prompts": [
                {
                    "id": "kp-h01-safe",
                    "name": "safe",
                    "prompt": "1woman, adult woman, rainy window",
                    "source_code": "K",
                    "source_group": "kprompt",
                    "safety_code": "N",
                    "safety_level": "normal",
                    "enabled": True,
                    "categories": ["kprompt"],
                }
            ],
        }
        (plugin_data / "anima_random_prompt_pool.json").write_text(json.dumps(main_pool), encoding="utf-8")
        (plugin / "data" / "kp_prompt_pool.json").write_text(json.dumps(kp_pool), encoding="utf-8")
        (plugin_data / "presets.json").write_text(json.dumps({"version": 1, "styles": {}, "characters": {}}), encoding="utf-8")
        targets = root / "targets.json"
        targets.write_text(json.dumps({"targets": [{"id": "private", "label": "Private", "kind": "private", "umo": "bot:FriendMessage:12345", "allow_safety": ["N", "H", "S"]}]}), encoding="utf-8")
        self.settings = Settings(
            admin_token="a" * 32,
            plugin_dir=plugin,
            plugin_data_dir=plugin_data,
            comfyui_root=comfy,
            delivery_targets_override=targets,
        )
        self.user = AuthPrincipal(role="user", subject="qq-12345", qq="12345")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_k_selector_and_prompt_id_capture(self) -> None:
        target = load_delivery_targets(self.settings.delivery_targets_path)[0]
        command, safety = build_remote_command(
            RemoteJobCreateRequest(target_id="private", kind="random", pool_filter="K/S"),
            target,
        )
        self.assertEqual(command, "来张好图抄一抄 K/S")
        self.assertEqual(safety, "S")
        with self.assertRaisesRegex(RemoteJobError, "on its own"):
            build_remote_command(
                RemoteJobCreateRequest(target_id="private", kind="random", pool_filter="K/P"),
                target,
            )
        self.assertEqual(_prompt_ids_from_plain(["完成｜条目=kp-h01-safe"]), ["kp-h01-safe"])

    def test_like_promotes_k_record_to_p_idempotently(self) -> None:
        first = promote_k_prompt(self.settings, "kp-h01-safe", self.user)
        second = promote_k_prompt(self.settings, "kp-h01-safe", self.user)
        self.assertEqual(first.action, "liked")
        self.assertEqual(second.action, "already_liked")
        pool = json.loads(self.settings.prompt_pool_path.read_text(encoding="utf-8"))
        liked = [item for item in pool["prompts"] if item.get("source_code") == "P"]
        self.assertEqual(len(liked), 1)
        self.assertEqual(liked[0]["liked_from"], "kp-h01-safe")

    def test_lora_scan_classify_and_personal_three_slot_storage(self) -> None:
        scanned = scan_loras(self.settings, "admin:test")
        self.assertEqual(scanned.items[0].path, "artist/ink.safetensors")
        updated = update_lora(
            self.settings,
            "artist/ink.safetensors",
            LoraCatalogUpdateRequest(
                display_name="Ink Artist",
                category="style",
                recommended_prompt="ink lines",
            ),
            scanned.revision,
            "admin:test",
        )
        styles = list_style_loras(self.settings)
        self.assertEqual(styles.items[0].display_name, "Ink Artist")
        payload = PersonalStyleWriteRequest(
            name="My Ink",
            prompt="soft colors",
            loras=[PersonalStyleLora(path="artist/ink.safetensors", strength=0.8)],
        )
        saved = write_personal_style(
            self.settings, self.user, 1, payload, "missing"
        )
        self.assertEqual(saved.items[0].style_key.startswith("__hub_personal_"), True)
        presets = json.loads(self.settings.preset_path.read_text(encoding="utf-8"))
        hidden = presets["styles"][saved.items[0].style_key]
        self.assertTrue(hidden["hidden"])
        self.assertEqual(hidden["loras"][0]["strength_model"], 0.8)
        deleted = delete_personal_style(
            self.settings, self.user, 1, saved.revision
        )
        self.assertEqual(deleted.items, [])
        self.assertEqual(list_personal_styles(self.settings, self.user).items, [])
        self.assertTrue(updated.revision)

    def test_rescan_removes_missing_lora_from_personal_slot(self) -> None:
        scanned = scan_loras(self.settings, "admin:test")
        update_lora(
            self.settings,
            "artist/ink.safetensors",
            LoraCatalogUpdateRequest(
                display_name="Ink Artist",
                category="style",
            ),
            scanned.revision,
            "admin:test",
        )
        saved = write_personal_style(
            self.settings,
            self.user,
            1,
            PersonalStyleWriteRequest(
                name="My Ink",
                loras=[
                    PersonalStyleLora(
                        path="artist/ink.safetensors",
                        strength=0.8,
                    )
                ],
            ),
            "missing",
        )
        (self.settings.lora_root / "artist" / "ink.safetensors").unlink()
        scan_loras(self.settings, "admin:test")
        current = list_personal_styles(self.settings, self.user)
        self.assertEqual(current.items, [])
        self.assertGreater(current.revision, saved.revision)


if __name__ == "__main__":
    unittest.main()
