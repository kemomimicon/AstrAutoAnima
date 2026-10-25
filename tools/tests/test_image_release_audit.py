import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "image_release_audit.py"
spec = importlib.util.spec_from_file_location("image_release_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImageReleaseAuditTests(unittest.TestCase):
    def test_no_mutation_or_secret_values_in_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            secret = "aah_admin_" + "x" * 40
            path = root / "runtime-env.local.json"
            path.write_text('{"token":"' + secret + '"}', encoding="utf-8")
            before = path.read_bytes()
            result = module.audit([root])
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn(secret, str(result))
            self.assertFalse(result["release_approved"])
            self.assertTrue(result["read_only"])
            self.assertIn("credential_or_runtime_config", [f["category"] for f in result["findings"]])
            self.assertIn("credential_pattern", [f["category"] for f in result["findings"]])

    def test_archives_models_databases_and_skipped_environment_are_not_silently_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ("old.zip", "sample.safetensors", "studio.db", "picture.png"):
                (root / name).write_bytes(b"fixture")
            (root / ".venv").mkdir()
            result = module.audit([root])
            self.assertEqual(len(result["findings"]), 3)
            self.assertEqual(len(result["incomplete_or_manual_review"]), 2)

    def test_missing_root_is_incomplete_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = module.audit([Path(directory).resolve() / "missing"])
            self.assertTrue(result["incomplete_or_manual_review"])
            self.assertFalse(result["release_approved"])

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "outside.txt"
            target.write_text("unchanged", encoding="utf-8")
            scan = root / "scan"
            scan.mkdir()
            try:
                (scan / "linked.txt").symlink_to(target)
            except OSError:
                self.skipTest("OS account cannot create test symlinks")
            result = module.audit([scan])
            self.assertTrue(result["incomplete_or_manual_review"])
            self.assertEqual(target.read_text(), "unchanged")

    def test_empty_directory_is_only_scoped_result_not_release_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            result = module.audit([Path(directory).resolve()])
            self.assertEqual(result["findings"], [])
            self.assertFalse(result["release_approved"])
