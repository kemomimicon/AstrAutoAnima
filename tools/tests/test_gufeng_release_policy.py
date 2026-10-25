import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def load_script(name):
    spec = importlib.util.spec_from_file_location('gufeng_test_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuFengPublicPolicyTests(unittest.TestCase):
    def test_git_visible_private_module_is_rejected_before_reading(self):
        builder = load_script('build_release_archives')
        with tempfile.TemporaryDirectory() as temporary:
            result = type('Result', (), {'stdout': 'optional/gufeng/private.zip\0'})()
            with patch.object(builder, 'ROOT', Path(temporary)), patch.object(builder.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(ValueError, 'Unreviewed'):
                    builder.public_files()

    def test_frozen_candidate_payload_is_rejected_before_reading(self):
        builder = load_script('build_release_archives')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'candidate-source-manifest.json').write_text(json.dumps({
                'optional/gufeng/data/cards.sqlite3': {'sha256': 'not-read'},
            }), 'utf-8')
            with patch.object(builder, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Unreviewed'):
                builder.public_files()

    def test_public_writer_rejects_before_creating_archive(self):
        builder = load_script('build_release_archives')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'public.zip'
            with self.assertRaisesRegex(ValueError, 'Unreviewed'):
                builder.write_zip(output, [(root / 'unread.zip', 'release/optional/gufeng/module.zip')])
            self.assertFalse(output.exists())

    def test_zip_verification_rejects_nested_module_and_allows_public_declaration(self):
        verifier = load_script('verify_release_archives')
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'candidate.zip'
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr('release/optional/gufeng/module.zip', b'not-an-actual-module')
                out.writestr('release/optional/gufeng/README.md', 'Public documentation')
                out.writestr('release/optional/gufeng/package.json', '{}')
            problems = verifier.check(archive)
            self.assertEqual(len(problems), 1)
            self.assertIn('unreviewed GuFeng', problems[0])

    def test_privacy_scan_rejects_even_tiny_optional_zip(self):
        scanner = load_script('privacy_scan')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'optional/gufeng/module.zip'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'small fixture')
            self.assertTrue(any('unreviewed GuFeng' in finding for finding in scanner.scan(root)))


if __name__ == '__main__':
    unittest.main()
