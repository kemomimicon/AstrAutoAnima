"""Local fixtures only; never open or change an actual cloud image."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.autodl_public_image_20261025 import public_probe as probe


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.image = self.base / "image"
        self.image.mkdir()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        self.manifest = {
            "schema": 1, "sha256": probe.EXPECTED_SHA,
            "compressed_bytes": 3, "unique_bytes": probe.EXPECTED_UNIQUE_BYTES,
            "entries": probe.EXPECTED_ENTRIES, "top_roots": sorted(probe.EXPECTED_ROOTS),
        }
        self.write_manifest()
        (self.image / "runtime.tar.gz").write_bytes(b"abc")
        for name in ("first_boot.py", "Start-Image.sh", "Show-Credentials.sh"):
            (self.image / name).write_text("not executed", encoding="utf-8")
        self.bytes_patch = patch.object(probe, "EXPECTED_BYTES", 3)
        self.bytes_patch.start()
        self.addCleanup(self.bytes_patch.stop)

    def write_manifest(self):
        (self.image / "payload-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def check(self, name, report):
        return next(c for c in report["checks"] if c["name"] == name)

    def test_readonly_status_is_never_public_approval(self):
        before = {p.relative_to(self.base).as_posix(): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        result = probe.probe(self.image, self.repo)
        self.assertEqual(result["status"], "structure_checked_acceptance_pending")
        self.assertFalse(result["public_release_approved"])
        self.assertEqual(self.check("archive_sha256", result)["state"], "pending")
        after = {p.relative_to(self.base).as_posix(): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_directory_fails_without_creating_it(self):
        target = self.base / "missing"
        self.assertEqual(probe.probe(target, self.repo)["status"], "failed")
        self.assertFalse(target.exists())

    def test_malformed_manifest_never_echoes_data(self):
        (self.image / "payload-manifest.json").write_text('{"private":"FAKE_TEST_SECRET"', encoding="utf-8")
        result = probe.probe(self.image, self.repo)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("FAKE_TEST_SECRET", json.dumps(result))

    def test_wrong_or_duplicate_roots_fail(self):
        for roots in (["../../elsewhere"], sorted(probe.EXPECTED_ROOTS) + ["aaa-install"]):
            self.manifest["top_roots"] = roots
            self.write_manifest()
            self.assertEqual(probe.probe(self.image, self.repo)["status"], "failed")

    def test_wrong_payload_size_fails(self):
        (self.image / "runtime.tar.gz").write_bytes(b"wrong")
        self.assertEqual(probe.probe(self.image, self.repo)["status"], "failed")

    def test_full_hash_wrong_fails(self):
        with contextlib.redirect_stderr(io.StringIO()):
            result = probe.probe(self.image, self.repo, True)
        self.assertEqual(self.check("archive_sha256", result)["state"], "fail")

    def test_full_hash_match_still_not_gpu_or_privacy_proof(self):
        import hashlib
        actual = hashlib.sha256(b"abc").hexdigest()
        self.manifest["sha256"] = actual
        self.write_manifest()
        with patch.object(probe, "EXPECTED_SHA", actual), contextlib.redirect_stderr(io.StringIO()):
            result = probe.probe(self.image, self.repo, True)
        self.assertEqual(self.check("archive_sha256", result)["state"], "pass")
        self.assertFalse(result["public_release_approved"])
        self.assertEqual(result["gpu_test"], "not performed")

    def test_no_repository_is_pending_not_automatic_clone(self):
        target = self.base / "no-repo"
        result = probe.probe(self.image, target)
        self.assertEqual(self.check("public_repository", result)["state"], "pending")
        self.assertFalse(target.exists())

    def test_missing_entry_fails(self):
        (self.image / "Start-Image.sh").unlink()
        self.assertEqual(probe.probe(self.image, self.repo)["status"], "failed")

    def test_permissions_error_does_not_expose_exception_text(self):
        out = io.StringIO()
        with patch.object(probe, "probe", side_effect=PermissionError("PRIVATE_PATH_TEST")), contextlib.redirect_stdout(out):
            code = probe.main([])
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE_PATH_TEST", out.getvalue())

    def test_linked_input_refused(self):
        # Mock this portable path guard so this test does not need Windows symlink privileges.
        with patch.object(probe, "unlinked", return_value=False):
            result = probe.probe(self.image, self.repo)
        self.assertEqual(result["status"], "failed")

    def test_large_manifest_refused(self):
        (self.image / "payload-manifest.json").write_bytes(b" " * (65536 + 1))
        self.assertEqual(probe.probe(self.image, self.repo)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
