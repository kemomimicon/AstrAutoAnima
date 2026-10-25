"""A published frozen source archive must retain its own manifest validity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def builder():
    spec = importlib.util.spec_from_file_location(
        "frozen_archive_builder", ROOT / "scripts/build_release_archives.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenArchiveTests(unittest.TestCase):
    def test_exact_bytes_and_manifest_survive_zip_readback(self):
        build = builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = b'{"schema": 1}\r\n'
            source = root / "sample.json"
            source.write_bytes(content)
            manifest = root / "candidate-source-manifest.json"
            manifest.write_text(json.dumps({"sample.json": {
                "sha256": hashlib.sha256(content).hexdigest()}}), encoding="utf-8")
            archive = root / "source.zip"
            build.write_zip(archive, [(source, "release/sample.json"),
                                     (manifest, "release/candidate-source-manifest.json")],
                            preserve_bytes=True)
            with zipfile.ZipFile(archive) as bundle:
                rows = json.loads(bundle.read("release/candidate-source-manifest.json"))
                self.assertEqual(bundle.read("release/sample.json"), content)
                for name, row in rows.items():
                    self.assertEqual(hashlib.sha256(bundle.read("release/" + name)).hexdigest(),
                                     row["sha256"])

    def test_frozen_shell_must_already_have_unix_line_endings(self):
        build = builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shell = root / "start.sh"
            shell.write_bytes(b"#!/bin/sh\r\nexit 0\r\n")
            with self.assertRaisesRegex(ValueError, "before freezing"):
                build.write_zip(root / "bad.zip", [(shell, "start.sh")], preserve_bytes=True)

    def test_nonfrozen_legacy_archive_still_normalizes(self):
        build = builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.py"
            source.write_bytes(b"x = 1\r\n")
            build.write_zip(root / "legacy.zip", [(source, "sample.py")])
            with zipfile.ZipFile(root / "legacy.zip") as bundle:
                self.assertEqual(bundle.read("sample.py"), b"x = 1\n")
