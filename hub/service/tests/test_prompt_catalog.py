import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from astr_auto_anima_hub.auth import AuthPrincipal, SYSTEM_ADMIN
from astr_auto_anima_hub.prompt_catalog import (
    CatalogWrite, SourcePolicy, catalog, config, config_path, write_catalog, validate_request,
)
from astr_auto_anima_hub.prompt_favorites import save_favorite
from astr_auto_anima_hub.prompt_groups import PromptGroupsWrite, write_groups, validate_selected_groups
from astr_auto_anima_hub.repositories import RepositoryError
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest


class CatalogTests(unittest.TestCase):
    def setUp(self):
        from test_api import ApiTests
        self.fixture = ApiTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.settings = self.fixture.settings
        self.client = self.fixture.client
        self.headers = self.fixture.headers
        self.url = "/api/v1/lite/prompt-catalog"
        self.pool([("G", "N")])

    def pool(self, entries):
        self.settings.prompt_pool_path.write_text(json.dumps({"prompts": [
            {"id": str(i), "prompt": "private fixture text", "source_code": c, "safety_code": s}
            for i, (c, s) in enumerate(entries)
        ]}), encoding="utf-8")

    def policy(self, code="G", **updates):
        row = SourcePolicy(id=code, name="自建词库", **updates)
        write_catalog(self.settings, CatalogWrite(sources=[row]), config(self.settings)["revision"], "test")
        return row

    def test_g_only_public_install_never_advertises_private_libraries(self):
        data = catalog(self.settings, SYSTEM_ADMIN)
        self.assertEqual([r["id"] for r in data["sources"]], ["G"])
        self.assertEqual([r["id"] for r in data["editable_sources"]], ["G"])
        self.assertNotIn("private fixture text", json.dumps(data))
        self.assertNotIn("国风", json.dumps(data, ensure_ascii=False))

    def test_catalog_auth_etag_revision_and_no_rescan(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        first = self.client.get(self.url, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        with patch("astr_auto_anima_hub.prompt_catalog.read_json_object",
                   side_effect=AssertionError("unchanged large pool reread")):
            response = self.client.get(self.url, headers={**self.headers, "If-None-Match": first.headers["etag"]})
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.pool([("G", "S")])
        second = self.client.get(self.url, headers={**self.headers, "If-None-Match": first.headers["etag"]})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["sources"][0]["safety_codes"], ["S"])

    def test_save_rename_disable_and_cas_no_client_update(self):
        before_pool = self.settings.prompt_pool_path.read_bytes()
        current = self.client.get(self.url, headers=self.headers).json()
        payload = {"sources": [SourcePolicy(id="G", name="朋友的田园库").model_dump()]}
        url = "/api/v1/admin/prompt-catalog"
        for headers in ({}, self.fixture.user_headers):
            self.assertIn(self.client.put(url, json=payload, headers=headers).status_code, (401, 403))
        saved = self.client.put(url, json=payload, headers={**self.headers, "If-Match": current["configuration"]["revision"]})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get(self.url, headers=self.fixture.user_headers).json()["sources"][0]["name"],
                         "朋友的田园库")
        self.assertEqual(self.client.put(url, json=payload, headers={**self.headers, "If-Match": "missing"}).status_code, 409)
        self.policy(enabled=False)
        self.assertEqual(catalog(self.settings, SYSTEM_ADMIN)["sources"], [])
        self.assertEqual(before_pool, self.settings.prompt_pool_path.read_bytes())

    def test_two_instances_different_names_and_grades(self):
        self.policy(safety_codes=["N"], default_safety="N")
        root = self.settings.plugin_data_dir / "second"
        root.mkdir()
        other = replace(self.settings, plugin_data_dir=root, prompt_pool_override=None)
        other.prompt_pool_path.write_text(json.dumps({"prompts": [
            {"id": "c", "prompt": "scene", "source_code": "C", "safety_code": "H"}]}))
        self.assertEqual([r["id"] for r in catalog(other, SYSTEM_ADMIN)["sources"]], ["C"])
        self.assertEqual(catalog(self.settings, SYSTEM_ADMIN)["sources"][0]["safety_codes"], ["N"])

    def test_favorite_directory_is_owner_scoped(self):
        one = AuthPrincipal(role="user", subject="one", qq="123456")
        two = AuthPrincipal(role="user", subject="two", qq="654321")
        save_favorite(self.settings.prompt_favorites_path, one,
                      {"id": "f", "prompt": "private garden", "safety_code": "S"})
        self.assertEqual(next(r for r in catalog(self.settings, one)["sources"] if r["id"] == "P")["safety_codes"], ["S"])
        self.assertNotIn("P", [r["id"] for r in catalog(self.settings, two)["sources"]])
        self.assertNotIn("configuration", catalog(self.settings, one))

    def test_policy_rejects_old_client_explicit_and_filters_defaults(self):
        self.policy(enabled=False)
        request = RemoteJobCreateRequest(target_id="x", kind="random", pool_filter="G/N")
        with self.assertRaises(RepositoryError):
            validate_request(self.settings, request, "group")
        default = validate_request(self.settings, request.model_copy(update={"pool_filter": ""}), "group")
        self.assertNotIn("G", default.pool_filter)
        self.policy(allow_group=False)
        with self.assertRaises(RepositoryError):
            validate_request(self.settings, request, "group")
        self.assertEqual(validate_request(self.settings, request, "private"), request)

    def test_v_is_physical_adapter_not_custom_group_named_v(self):
        from gufeng_fixture import create_gufeng_fixture
        write_groups(self.settings, PromptGroupsWrite(groups=[
            {"id": "v", "name": "我自己的分组", "allow_private": True}
        ]), "missing", "test")
        self.assertNotIn("V", [r["id"] for r in catalog(self.settings, SYSTEM_ADMIN)["sources"]])
        create_gufeng_fixture(self.settings.plugin_data_dir / "resources/gufeng/cards.sqlite3")
        self.policy("V", safety_codes=["S"], default_safety="S")
        value = next(r for r in catalog(self.settings, SYSTEM_ADMIN)["sources"] if r["id"] == "V")
        self.assertEqual(value["safety_codes"], ["S"])
        req = RemoteJobCreateRequest(kind="random", target_id="x", pool_filter="V")
        self.assertEqual(validate_request(self.settings, req, "private").safety_code, "S")
        with self.assertRaises(RepositoryError):
            validate_request(self.settings, req.model_copy(update={"pool_filter": "V,G"}), "private")
        from astr_auto_anima_hub.remote_jobs import build_remote_command, _TargetRecord, RemoteJobError
        from astr_auto_anima_hub.schemas import DeliveryTarget
        target = _TargetRecord(DeliveryTarget(id="x", label="x", kind="group"), "b:GroupMessage:123456", frozenset("NHS"))
        with self.assertRaises(RemoteJobError):
            build_remote_command(req, target, v_safety="S")

    def test_invalid_registry_fails_closed(self):
        path = config_path(self.settings)
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text('{"sources":[{"id":"ZZ","name":"oops"}]}')
        self.assertEqual(self.client.get(self.url, headers=self.headers).status_code, 503)
        with self.assertRaises(RepositoryError):
            validate_request(self.settings, RemoteJobCreateRequest(kind="random", target_id="x"), "group")

    def test_groups_renaming_preserves_id_and_rules(self):
        data = PromptGroupsWrite(groups=[{"id": "night", "name": "夜景", "allow_private": True,
                                         "allow_group": False, "safety_codes": ["N"]}])
        result = write_groups(self.settings, data, "missing", "test")
        with self.assertRaises(RepositoryError):
            validate_selected_groups(self.settings, ["night"], for_generation=True, safety="N")
        self.assertEqual(validate_selected_groups(self.settings, ["night"], private=True,
                                                 for_generation=True, safety="N"), ["night"])
        data.groups[0].name = "重新命名"
        write_groups(self.settings, data, result["revision"], "test")
        self.assertEqual(catalog(self.settings, SYSTEM_ADMIN)["groups"][0]["id"], "night")

    def test_qq_policy_agrees_with_hub_and_does_not_regrade_main_pool(self):
        from astrbot_plugin_comfy_bridge.prompt_catalog_policy import apply_catalog_policy
        from astrbot_plugin_comfy_bridge.prompt_pool_runtime import parse_group_selector
        from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError
        self.policy(safety_codes=["N"], allow_private=False)
        selection = parse_group_selector("G/N")[1]
        self.assertEqual(apply_catalog_policy(self.settings.plugin_data_dir, selection, private=False), selection)
        with self.assertRaises(WorkflowError):
            apply_catalog_policy(self.settings.plugin_data_dir, selection, private=True)
        with self.assertRaises(WorkflowError):
            apply_catalog_policy(self.settings.plugin_data_dir, parse_group_selector("G/S")[1], private=False)
