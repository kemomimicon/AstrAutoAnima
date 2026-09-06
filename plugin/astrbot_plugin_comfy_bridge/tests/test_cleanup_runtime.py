import os
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_comfy_bridge.cleanup_runtime import cleanup_old_output_images


class CleanupRuntimeTests(unittest.TestCase):
    def test_deletes_only_expired_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_image = root / "old.png"
            fresh_image = root / "fresh.webp"
            old_json = root / "record.json"

            old_image.write_bytes(b"old-image")
            fresh_image.write_bytes(b"fresh-image")
            old_json.write_text("{}", encoding="utf-8")

            now = 2_000_000.0
            old_time = now - 49 * 3600
            os.utime(old_image, (old_time, old_time))
            os.utime(old_json, (old_time, old_time))
            os.utime(fresh_image, (now, now))

            report = cleanup_old_output_images(root, 48, now=now)

            self.assertEqual(report.scanned, 2)
            self.assertEqual(report.deleted, 1)
            self.assertEqual(report.deleted_bytes, len(b"old-image"))
            self.assertTrue(fresh_image.exists())
            self.assertTrue(old_json.exists())
            self.assertFalse(old_image.exists())

    def test_ignores_symlinks_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.png"
            link = root / "link.png"
            target.write_bytes(b"image")
            old_time = 9_999_999.0 - 2 * 3600
            os.utime(target, (old_time, old_time))
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available")

            report = cleanup_old_output_images(root, 1, now=9_999_999.0)

            self.assertEqual(report.deleted, 1)
            self.assertTrue(link.is_symlink())

    def test_missing_directory_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            report = cleanup_old_output_images(missing, 48)
            self.assertEqual(report.scanned, 0)
            self.assertEqual(report.deleted, 0)


if __name__ == "__main__":
    unittest.main()
