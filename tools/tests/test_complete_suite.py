import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from verify_complete_suite import verify

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_complete_suite as builder


class CompleteSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aaa-suite-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'components' / 'sample.zip'
        self.file.parent.mkdir()
        self.file.write_bytes(b'public-test-data')
        self.entry = {'path': 'components/sample.zip', 'size': self.file.stat().st_size,
                      'sha256': hashlib.sha256(self.file.read_bytes()).hexdigest()}

    def save(self, entries):
        (self.root / 'suite-manifest.json').write_text(json.dumps({'files': entries}), encoding='utf-8')

    def test_complete_verification(self):
        self.save([self.entry])
        before = self.file.read_bytes()
        self.assertEqual(verify(self.root), 1)
        self.assertEqual(self.file.read_bytes(), before)

    def test_tampered_content_rejected(self):
        self.save([self.entry])
        self.file.write_bytes(b'x' * self.entry['size'])
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_missing_file_rejected(self):
        self.save([{**self.entry, 'path': 'components/missing.zip'}])
        with self.assertRaises(OSError):
            verify(self.root)

    def test_unsafe_paths_rejected(self):
        for name in ('../outside.zip', '/outside.zip', 'C:/outside.zip', 'components\\sample.zip'):
            with self.subTest(name=name):
                self.save([{**self.entry, 'path': name}])
                with self.assertRaises(ValueError):
                    verify(self.root)

    def test_duplicates_rejected(self):
        self.save([self.entry, self.entry])
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_empty_manifest_rejected(self):
        self.save([])
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_original_asset_set_required(self):
        text = ''.join(f'{"a" * 64}  {name}\n' for name in builder.ASSETS)
        self.assertEqual(set(builder.read_manifest(text.encode())), set(builder.ASSETS))
        with self.assertRaises(ValueError):
            builder.read_manifest(text.splitlines()[0].encode())
        with self.assertRaises(ValueError):
            builder.read_manifest((text + text.splitlines()[0]).encode())

    def test_wrong_baseline_rejected(self):
        (self.root / 'SHA256SUMS.txt').write_text('unexpected', encoding='utf-8')
        with self.assertRaises(ValueError):
            builder.build(self.root, self.root / 'new-output')
        self.assertFalse((self.root / 'new-output').exists())


if __name__ == '__main__':
    unittest.main()
