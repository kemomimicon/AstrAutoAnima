"""Regression tests for pending release gates and local document validation."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import check_autodl_image_materials as materials

ROOT = Path(__file__).resolve().parents[2]


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        names = list(materials.DOCS) + [
            "docs/PUBLICATION_0.5.2-1.44.md",
            "examples/autodl_image_acceptance.pending.json",
            "tools/autodl_public_image_20261025/public_probe.py",
            "tools/autodl_public_image_20261025/Open-AAA-Tunnel.ps1",
            "tools/autodl_public_image_20261025/Open-AAA-Tunnel.cmd",
        ]
        for name in names:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        self.pending = self.root / "examples/autodl_image_acceptance.pending.json"

    def alter_template(self, function):
        value = json.loads(self.pending.read_text("utf-8"))
        function(value)
        self.pending.write_text(json.dumps(value), encoding="utf-8")

    def test_unchanged_materials_pass(self):
        self.assertEqual(materials.check(self.root), [])

    def test_template_cannot_approve_release(self):
        self.alter_template(lambda v: v.update(public_release_approved=True))
        self.assertTrue(materials.check(self.root))

    def test_pending_gate_cannot_silently_disappear(self):
        self.alter_template(lambda v: v["gates"].pop("gpu_base_generation"))
        self.assertTrue(materials.check(self.root))

    def test_payload_identity_mismatch_is_rejected(self):
        self.alter_template(lambda v: v.update(payload_sha256="0" * 64))
        self.assertTrue(materials.check(self.root))

    def test_public_template_cannot_include_evidence(self):
        self.alter_template(lambda v: v.update(evidence={"private": "not public"}))
        self.assertTrue(materials.check(self.root))

    def test_missing_document_fails(self):
        (self.root / materials.DOCS[0]).unlink()
        self.assertTrue(materials.check(self.root))

    def test_broken_link_fails(self):
        doc = self.root / materials.DOCS[0]
        doc.write_text(doc.read_text("utf-8") + "\n[broken](NOT_PRESENT.md)\n", encoding="utf-8")
        self.assertTrue(materials.check(self.root))

    def test_unclosed_code_fence_fails(self):
        doc = self.root / materials.DOCS[0]
        doc.write_text(doc.read_text("utf-8") + "\n```bash\n", encoding="utf-8")
        self.assertTrue(materials.check(self.root))

    def test_probe_network_or_process_import_requires_review(self):
        source = self.root / "tools/autodl_public_image_20261025/public_probe.py"
        source.write_text(source.read_text("utf-8") + "\nimport subprocess\n", encoding="utf-8")
        self.assertTrue(materials.check(self.root))


if __name__ == "__main__":
    unittest.main()
