from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.schemas import (
    GpuMetrics,
    MemoryMetrics,
    WorkstationMetrics,
)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        plugin_dir = root / "plugin"
        plugin_data = root / "plugin_data"
        comfy = root / "ComfyUI"
        plugin_dir.mkdir()
        plugin_data.mkdir()
        (comfy / "output").mkdir(parents=True)
        (plugin_dir / "metadata.yaml").write_text(
            "name: astrbot_plugin_comfy_bridge\nversion: 0.2.8\n",
            encoding="utf-8",
        )
        (plugin_data / "anima_random_prompt_pool.json").write_text(
            json.dumps(
                {
                    "catalog_revision": 9,
                    "prompts": [
                        {
                            "id": "discord-0001",
                            "prompt": "rainy street",
                            "source_code": "D",
                            "safety_code": "N",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plugin_data / "presets.json").write_text(
            json.dumps({"styles": {}, "characters": {}}), encoding="utf-8"
        )
        (plugin_data / "character_dictionary.json").write_text(
            json.dumps(
                {
                    "characters": [
                        {
                            "tag": "hatsune_miku",
                            "aliases": ["初音未来", "hatsune miku"],
                            "copyright": ["vocaloid"],
                            "gender": ["1girl"],
                            "appearance": ["aqua hair", "twintails"],
                            "post_count": 100,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (plugin_data / "delivery_targets.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "id": "main-group",
                            "label": "Main group",
                            "kind": "group",
                            "umo": "examplebot:GroupMessage:123456",
                            "allow_safety": ["N", "H"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.user_token = "bound-user-token-0123456789-0123456789"
        (plugin_data / "lite_users.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "users": [
                        {
                            "id": "qq-987654",
                            "label": "Bound tester",
                            "qq": "987654",
                            "token_sha256": hashlib.sha256(
                                self.user_token.encode("utf-8")
                            ).hexdigest(),
                            "allow_group": True,
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        settings = Settings(
            admin_token="test-token-0123456789-0123456789",
            lite_token="lite-token-0123456789-01234567890",
            legacy_lite_qq="123456789",
            astrbot_url="http://127.0.0.1:1",
            comfyui_url="http://127.0.0.1:1",
            request_timeout_seconds=0.1,
            plugin_dir=plugin_dir,
            plugin_data_dir=plugin_data,
            comfyui_root=comfy,
            delivery_targets_override=plugin_data / "delivery_targets.json",
            lite_users_override=plugin_data / "lite_users.json",
        )
        self.client = TestClient(create_app(settings))
        self.settings = settings
        self.headers = {"Authorization": f"Bearer {settings.admin_token}"}
        self.lite_headers = {"Authorization": f"Bearer {settings.lite_token}"}
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}

    def revision_headers(self, revision: str) -> dict[str, str]:
        return {**self.headers, "If-Match": revision, "X-Device-Name": "unit-test"}

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_public_health(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_serves_web_app_without_shadowing_api(self) -> None:
        web_root = Path(self.temp.name) / "web"
        web_root.mkdir()
        (web_root / "index.html").write_text(
            "<title>AstrAutoAnima</title>", encoding="utf-8"
        )
        with TestClient(create_app(replace(self.settings, web_root=web_root))) as client:
            page = client.get("/")
            health = client.get("/api/v1/health")
        self.assertEqual(page.status_code, 200)
        self.assertIn("AstrAutoAnima", page.text)
        self.assertEqual(health.status_code, 200)

    def test_protected_endpoint_rejects_missing_token(self) -> None:
        response = self.client.get("/api/v1/prompts")
        self.assertEqual(response.status_code, 401)

    def test_prompt_and_preset_endpoints(self) -> None:
        prompt_response = self.client.get(
            "/api/v1/prompts?source=D&safety=N", headers=self.headers
        )
        preset_response = self.client.get("/api/v1/presets", headers=self.headers)
        self.assertEqual(prompt_response.status_code, 200)
        self.assertEqual(prompt_response.json()["items"][0]["id"], "discord-0001")
        self.assertEqual(preset_response.status_code, 200)

    def test_lite_token_can_only_read_lite_endpoints(self) -> None:
        prompt_response = self.client.get(
            "/api/v1/lite/prompts?source=D&safety=N",
            headers=self.lite_headers,
        )
        preset_response = self.client.get(
            "/api/v1/lite/presets", headers=self.lite_headers
        )
        admin_read = self.client.get("/api/v1/prompts", headers=self.lite_headers)
        admin_write = self.client.post(
            "/api/v1/prompts",
            headers={**self.lite_headers, "If-Match": "invalid"},
            json={"prompt": "must not be created"},
        )
        self.assertEqual(prompt_response.status_code, 200)
        self.assertEqual(prompt_response.json()["items"][0]["id"], "discord-0001")
        self.assertEqual(preset_response.status_code, 200)
        self.assertEqual(admin_read.status_code, 401)
        self.assertEqual(admin_write.status_code, 401)

    def test_lite_endpoints_reject_missing_token_and_allow_admin(self) -> None:
        missing = self.client.get("/api/v1/lite/presets")
        admin = self.client.get("/api/v1/lite/presets", headers=self.headers)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(admin.status_code, 200)

    def test_lite_character_dictionary_searches_chinese_and_english(self) -> None:
        chinese = self.client.get(
            "/api/v1/lite/characters?query=初音未来",
            headers=self.lite_headers,
        )
        english = self.client.get(
            "/api/v1/lite/characters?query=hatsune",
            headers=self.user_headers,
        )
        missing_auth = self.client.get("/api/v1/lite/characters?query=miku")
        self.assertEqual(chinese.status_code, 200)
        self.assertTrue(chinese.json()["available"])
        self.assertEqual(chinese.json()["items"][0]["tag"], "hatsune_miku")
        self.assertEqual(
            chinese.json()["items"][0]["weak_prompt"],
            "hatsune_miku, vocaloid",
        )
        self.assertIn("aqua hair", chinese.json()["items"][0]["strong_prompt"])
        self.assertEqual(english.status_code, 200)
        self.assertEqual(english.json()["total"], 1)
        self.assertEqual(missing_auth.status_code, 401)

    def test_admin_character_overrides_and_per_user_favorites(self) -> None:
        admin = self.client.get(
            "/api/v1/admin/characters?query=初音未来",
            headers=self.headers,
        )
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(admin.json()["items"][0]["tag"], "hatsune_miku")
        revision = admin.json()["revision"]

        updated = self.client.patch(
            "/api/v1/admin/characters/hatsune_miku",
            headers=self.revision_headers(revision),
            json={"aliases": ["初音未来", "葱娘"], "post_count": 321},
        )
        self.assertEqual(updated.status_code, 200)

        searched = self.client.get(
            "/api/v1/lite/characters?query=葱娘",
            headers=self.user_headers,
        )
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["items"][0]["post_count"], 321)
        self.assertTrue(searched.json()["items"][0]["overridden"])

        favorites = self.client.get(
            "/api/v1/lite/character-favorites",
            headers=self.user_headers,
        )
        self.assertEqual(favorites.status_code, 200)
        saved = self.client.put(
            "/api/v1/lite/character-favorites/hatsune_miku",
            headers={**self.user_headers, "If-Match": favorites.json()["revision"]},
            json={"name": "我的葱娘", "mode": "strong"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["items"][0]["name"], "我的葱娘")
        self.assertEqual(saved.json()["items"][0]["mode"], "strong")

        other_user = self.client.get(
            "/api/v1/lite/character-favorites",
            headers=self.lite_headers,
        )
        self.assertEqual(other_user.status_code, 200)
        self.assertEqual(other_user.json()["items"], [])

        disabled = self.client.delete(
            "/api/v1/admin/characters/hatsune_miku",
            headers=self.revision_headers(updated.json()["revision"]),
        )
        self.assertEqual(disabled.status_code, 200)
        hidden = self.client.get(
            "/api/v1/lite/characters?query=葱娘",
            headers=self.user_headers,
        )
        self.assertEqual(hidden.json()["items"], [])
        filtered_favorites = self.client.get(
            "/api/v1/lite/character-favorites",
            headers=self.user_headers,
        )
        self.assertEqual(filtered_favorites.json()["items"], [])

    def test_admin_manages_bound_user_tokens_without_exposing_hashes(self) -> None:
        unauthorized = self.client.get(
            "/api/v1/admin/lite-users", headers=self.lite_headers
        )
        self.assertEqual(unauthorized.status_code, 401)

        initial = self.client.get(
            "/api/v1/admin/lite-users", headers=self.headers
        )
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["items"][0]["qq"], "987654")
        self.assertNotIn("token_sha256", initial.text)
        self.assertNotIn(self.user_token, initial.text)

        created = self.client.post(
            "/api/v1/admin/lite-users",
            headers=self.revision_headers(initial.json()["revision"]),
            json={
                "qq": "123456789",
                "label": "New member",
                "allow_group": True,
            },
        )
        self.assertEqual(created.status_code, 200)
        issued = created.json()
        token = issued["token"]
        self.assertTrue(token.startswith("aah_u_"))
        self.assertEqual(issued["user"]["label"], "New member")
        self.assertNotIn("token_sha256", created.text)

        user_headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(
            self.client.get(
                "/api/v1/lite/presets", headers=user_headers
            ).status_code,
            200,
        )

        duplicate = self.client.post(
            "/api/v1/admin/lite-users",
            headers=self.revision_headers(issued["revision"]),
            json={"qq": "123456789"},
        )
        self.assertEqual(duplicate.status_code, 409)

        disabled = self.client.patch(
            "/api/v1/admin/lite-users/123456789",
            headers=self.revision_headers(issued["revision"]),
            json={"enabled": False, "allow_group": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(
            self.client.get(
                "/api/v1/lite/presets", headers=user_headers
            ).status_code,
            401,
        )

        rotated = self.client.post(
            "/api/v1/admin/lite-users/123456789/rotate",
            headers=self.revision_headers(disabled.json()["revision"]),
        )
        self.assertEqual(rotated.status_code, 200)
        new_token = rotated.json()["token"]
        self.assertNotEqual(new_token, token)
        self.assertEqual(
            self.client.get(
                "/api/v1/lite/presets",
                headers={"Authorization": f"Bearer {new_token}"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/lite/presets", headers=user_headers
            ).status_code,
            401,
        )

        deleted = self.client.delete(
            "/api/v1/admin/lite-users/123456789",
            headers=self.revision_headers(rotated.json()["revision"]),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(any(self.settings.trash_dir.rglob("*.json")))
        self.assertTrue(self.settings.audit_log_path.is_file())
        server_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                self.settings.lite_users_path,
                self.settings.audit_log_path,
                *self.settings.backup_dir.rglob("*.json"),
                *self.settings.trash_dir.rglob("*.json"),
            ]
            if path.is_file()
        )
        self.assertNotIn(token, server_text)
        self.assertNotIn(new_token, server_text)

    def test_lite_delivery_targets_hide_umo_and_job_validation(self) -> None:
        targets = self.client.get(
            "/api/v1/lite/delivery-targets", headers=self.lite_headers
        )
        self.assertEqual(targets.status_code, 200)
        self.assertEqual(targets.json()["targets"][0]["id"], "main-group")
        self.assertNotIn("umo", targets.json()["targets"][0])
        self.assertEqual(targets.json()["targets"][1]["id"], "self-private")

        rejected = self.client.post(
            "/api/v1/lite/jobs",
            headers=self.lite_headers,
            json={
                "target_id": "main-group",
                "kind": "random",
                "pool_filter": "C/S",
            },
        )
        self.assertEqual(rejected.status_code, 422)

        history = self.client.get(
            "/api/v1/lite/jobs", headers=self.lite_headers
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["items"], [])
        self.assertEqual(history.json()["total"], 0)

        missing_image = self.client.get(
            "/api/v1/lite/jobs/missing/images/missing",
            headers=self.lite_headers,
        )
        self.assertEqual(missing_image.status_code, 404)

    def test_bound_user_only_sees_group_and_own_private_target(self) -> None:
        response = self.client.get(
            "/api/v1/lite/delivery-targets", headers=self.user_headers
        )
        self.assertEqual(response.status_code, 200)
        targets = response.json()["targets"]
        self.assertEqual([target["id"] for target in targets], ["main-group", "self-private"])
        self.assertEqual(targets[1]["kind"], "private")
        self.assertNotIn("umo", targets[1])

    def test_status_is_offline_when_both_services_are_offline(self) -> None:
        response = self.client.get(
            "/api/v1/workstation/status", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "offline")
        by_name = {item["name"]: item for item in payload["probes"]}
        self.assertEqual(by_name["comfy_bridge_plugin"]["status"], "online")
        self.assertEqual(by_name["astrbot"]["status"], "offline")

    def test_admin_can_read_live_workstation_metrics(self) -> None:
        sample = WorkstationMetrics(
            collected_at=datetime.now(timezone.utc),
            cpu_percent=37.5,
            cpu_logical_count=32,
            load_average_1m=2.25,
            load_average_5m=1.75,
            load_average_15m=1.5,
            memory=MemoryMetrics(
                total_bytes=64 * 1024**3,
                used_bytes=20 * 1024**3,
                available_bytes=44 * 1024**3,
                utilization_percent=31.25,
            ),
            gpus=[
                GpuMetrics(
                    index=0,
                    name="NVIDIA GeForce RTX 5090",
                    utilization_percent=82,
                    memory_total_mib=32607,
                    memory_used_mib=16384,
                    memory_free_mib=16223,
                    memory_utilization_percent=50.25,
                    temperature_c=61,
                )
            ],
        )
        with patch(
            "astr_auto_anima_hub.app.collect_system_metrics",
            return_value=sample,
        ):
            response = self.client.get(
                "/api/v1/workstation/metrics", headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cpu_percent"], 37.5)
        self.assertEqual(payload["memory"]["used_bytes"], 20 * 1024**3)
        self.assertEqual(payload["gpus"][0]["memory_total_mib"], 32607)

        unauthorized = self.client.get(
            "/api/v1/workstation/metrics", headers=self.lite_headers
        )
        self.assertEqual(unauthorized.status_code, 401)

    def test_prompt_create_update_conflict_export_and_delete(self) -> None:
        initial = self.client.get("/api/v1/prompts", headers=self.headers).json()
        create_response = self.client.post(
            "/api/v1/prompts",
            headers=self.revision_headers(initial["revision"]),
            json={
                "name": "new scene",
                "prompt": "1girl, solo, moonlit garden",
                "source_code": "B",
                "safety_code": "N",
                "categories": ["night", "night"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        prompt_id = created["resource"]

        stale_response = self.client.patch(
            f"/api/v1/prompts/{prompt_id}",
            headers=self.revision_headers(initial["revision"]),
            json={"enabled": False},
        )
        self.assertEqual(stale_response.status_code, 409)

        update_response = self.client.patch(
            f"/api/v1/prompts/{prompt_id}",
            headers=self.revision_headers(created["revision"]),
            json={"enabled": False, "safety_code": "H"},
        )
        self.assertEqual(update_response.status_code, 200)

        export_response = self.client.get(
            "/api/v1/prompts/export?query=moonlit", headers=self.headers
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.json()["count"], 1)

        delete_response = self.client.delete(
            f"/api/v1/prompts/{prompt_id}",
            headers=self.revision_headers(update_response.json()["revision"]),
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(self.settings.audit_log_path.is_file())
        self.assertTrue(any(self.settings.backup_dir.rglob("*.json")))
        self.assertTrue(any(self.settings.trash_dir.rglob("*.json")))

    def test_prompt_write_requires_revision(self) -> None:
        response = self.client.post(
            "/api/v1/prompts",
            headers=self.headers,
            json={"prompt": "test"},
        )
        self.assertEqual(response.status_code, 428)

    def test_prompt_bulk_import(self) -> None:
        revision = self.client.get(
            "/api/v1/prompts", headers=self.headers
        ).json()["revision"]
        response = self.client.post(
            "/api/v1/prompts/import",
            headers=self.revision_headers(revision),
            json={
                "prompts": [
                    {"prompt": "first imported prompt", "source_code": "D"},
                    {"prompt": "second imported prompt", "safety_code": "H"},
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)

    def test_preset_create_rename_and_delete(self) -> None:
        revision = self.client.get(
            "/api/v1/presets", headers=self.headers
        ).json()["revision"]
        create_response = self.client.post(
            "/api/v1/presets/style",
            headers=self.revision_headers(revision),
            json={
                "name": "watercolor",
                "prompt": "watercolor style",
                "match": ["@watercolor"],
                "loras": [
                    {
                        "name": "anima_lora/watercolor.safetensors",
                        "strength_model": 0.8,
                        "strength_clip": 0.8,
                    }
                ],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        update_response = self.client.put(
            "/api/v1/presets/style/watercolor",
            headers=self.revision_headers(create_response.json()["revision"]),
            json={
                "name": "watercolor-v2",
                "prompt": "watercolor illustration",
                "match": ["@watercolor"],
                "loras": [
                    {
                        "name": "anima_lora/watercolor.safetensors",
                        "strength_model": 1.0,
                        "strength_clip": 1.0,
                    }
                ],
            },
        )
        self.assertEqual(update_response.status_code, 200)
        delete_response = self.client.delete(
            "/api/v1/presets/style/watercolor-v2",
            headers=self.revision_headers(update_response.json()["revision"]),
        )
        self.assertEqual(delete_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
