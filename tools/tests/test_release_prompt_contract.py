"""Release must not lose fixes while adapting the private source to public paths."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleasePromptContractTests(unittest.TestCase):
    def test_paired_shared_runtime_files_identical(self):
        plugin = ROOT / "plugin/astrbot_plugin_comfy_bridge"
        hub = ROOT / "hub/service/src/astr_auto_anima_hub"
        for left, right in (
            ("prompt_snapshot_runtime.py", "prompt_snapshots.py"),
            ("preset_lock.py", "preset_lock.py"),
            ("group_policy_runtime.py", "group_policy_runtime.py"),
        ):
            with self.subTest(module=left):
                self.assertEqual((plugin / left).read_bytes(), (hub / right).read_bytes())

    def test_build39_routes_and_modules_included(self):
        hub = ROOT / "hub/service/src/astr_auto_anima_hub"
        for name in ("image_prompts.py", "preset_queue.py"):
            self.assertTrue((hub / name).is_file())
        app = (hub / "app.py").read_text("utf-8")
        for route in ("/api/v1/admin/preset-submissions",
                      "/api/v1/lite/jobs/{job_id}/images/{image_id}/prompt"):
            self.assertIn(route, app)

    def test_seedvr2_dependency_contract_matches_actual_native_workflow(self):
        base = ROOT / "comfyui"
        manifest = json.loads((base / "dependency_manifest.json").read_text())
        declared = {name for row in manifest["custom_nodes"] for name in row["required_class_types"]}
        graph = json.loads((base / "workflows/Anima_SeedVR2_Refine_Beta_api.json").read_text(encoding="utf-8"))
        needed = {row["class_type"] for row in graph.values() if row["class_type"].startswith("SeedVR2")}
        self.assertTrue(needed)
        self.assertEqual(needed - declared, set())

    def test_image_docs_and_review_gate_included(self):
        for name in ("SERVER_IMAGE_PREPARATION.txt", "SERVER_ACCEPTANCE.txt",
                     "RECORDING_OUTLINE.txt", "RELEASE_READINESS.txt"):
            self.assertTrue((ROOT / "docs" / name).is_file())
        manifest = json.loads((ROOT / "release-manifest.json").read_text())
        self.assertFalse(manifest["image_clone_acceptance"])
        self.assertEqual(manifest["prompt_preset_fix_review"], "build39")
