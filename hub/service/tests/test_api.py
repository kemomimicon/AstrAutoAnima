from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings


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
        (plugin_data / "delivery_targets.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "id": "main-group",
                            "label": "Main group",
                            "kind": "group",
                            "umo": "demo-bot:GroupMessage:123456",
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
