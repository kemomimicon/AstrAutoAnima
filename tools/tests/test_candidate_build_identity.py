"""Prevent a new public build from silently reverting to build41 or older."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CandidateBuildIdentityTests(unittest.TestCase):
    def test_public_release_build_identity_matches_client_and_recording_docs(self):
        # The test executes inside a staged public tree, not a private runtime.
        manifest_path = ROOT / 'release-manifest.json'
        if not manifest_path.is_file():
            self.skipTest('Run this check in the prepared public release tree')
        manifest = json.loads(manifest_path.read_text('utf-8-sig'))
        build = manifest['public_build']
        self.assertGreater(build, 43)
        self.assertTrue(manifest['catalog_outfits_build43_included'])
        version = manifest['release'] + '+' + str(build)
        client = (ROOT / 'clients/flutter/pubspec.yaml').read_text('utf-8-sig')
        actual = re.search(r'^version:\s*(\S+)', client, re.M)
        self.assertIsNotNone(actual)
        self.assertEqual(actual[1], version)
        self.assertEqual(manifest['components']['astr_auto_anima_hub_client'], version)
        for name in ('LINUX_RECORDING_CHECKLIST.txt', 'INTEGRATED_PATCHES.txt'):
            title = (ROOT / 'docs' / name).read_text('utf-8-sig').splitlines()[0]
            self.assertIn(version, title)


if __name__ == '__main__':
    unittest.main()
