import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import studio_optional as tool


class StudioInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def studio(self, version='0.25.0'):
        target = self.root / 'studio-existing'
        (target / 'studio').mkdir(parents=True)
        (target / 'studio/__init__.py').write_text(f'__version__ = "{version}"\n')
        return target

    def test_default_preflight_does_not_fetch_or_create(self):
        target = self.root / 'new'
        with patch.object(tool, 'fetch') as fetch, patch.object(tool, 'bootstrap') as boot:
            self.assertEqual(tool.main(['--destination', str(target)]), 0)
        fetch.assert_not_called()
        boot.assert_not_called()
        self.assertFalse(target.exists())

    def test_apply_requires_license(self):
        with patch.object(tool, 'fetch') as fetch:
            with self.assertRaises(ValueError):
                tool.main(['--destination', str(self.root/'new'), '--apply'])
            fetch.assert_not_called()

    def test_refuses_existing_destination(self):
        with self.assertRaises(ValueError):
            tool.main(['--destination', str(self.studio())])

    def test_existing_install_never_fetches_or_installs(self):
        with patch.object(tool, 'fetch') as fetch, patch.object(tool, 'bootstrap') as boot:
            self.assertEqual(tool.main(['--existing', str(self.studio()), '--apply', '--accept-license']), 0)
            fetch.assert_not_called()
            boot.assert_not_called()

    def test_existing_newer_version_not_downgraded(self):
        with self.assertRaises(ValueError):
            tool.main(['--existing', str(self.studio('0.27.0'))])

    def test_refuses_relative_and_parent_traversal(self):
        for path in (Path('relative'), self.root / 'x/../y'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                tool.no_links(path)

    def test_symlink_is_rejected(self):
        source = self.root / 'source'
        source.mkdir()
        alias = self.root / 'alias'
        try:
            alias.symlink_to(source, target_is_directory=True)
        except OSError:
            self.skipTest('host cannot create symlinks')
        with self.assertRaises(ValueError):
            tool.no_links(alias)

    def test_registry_preserves_other_extensions_and_backups(self):
        root = self.root / 'extensions'
        root.mkdir()
        before = {'schema_version': 1, 'extensions': {'example': {'version': '1.0', 'enabled': False}}}
        (root/'active.json').write_text(json.dumps(before))
        tool.install_connector(root, {'web/index.html': b'fixture'})
        after = json.loads((root/'active.json').read_text())
        self.assertEqual(after['extensions']['example'], before['extensions']['example'])
        self.assertTrue(after['extensions'][tool.COMPONENT_ID]['enabled'])
        self.assertEqual(len(list(root.glob('active.before-studio-*.json'))), 1)
        with self.assertRaises(ValueError):
            tool.install_connector(root, {'web/index.html': b'changed'})
        self.assertEqual((root/'packages'/tool.COMPONENT_ID/tool.CONNECTOR/'web/index.html').read_bytes(), b'fixture')

    def test_registry_corruption_is_not_overwritten(self):
        root = self.root/'extensions'
        root.mkdir()
        (root/'active.json').write_text('{broken')
        with self.assertRaises(ValueError):
            tool.registry_state(root)
        self.assertEqual((root/'active.json').read_text(), '{broken')

    def test_subprocess_bootstrap_only_builds_in_selected_cwd(self):
        root = self.studio()
        with patch.object(tool.subprocess, 'run') as run:
            tool.bootstrap(root)
        command = run.call_args.args[0]
        self.assertEqual(command[-1], 'build')
        self.assertNotIn('--reinstall', command)
        self.assertEqual(run.call_args.kwargs['cwd'], root)

    def test_archive_traversal_and_duplicate_names_rejected(self):
        for index, names in enumerate((['../outside'], ['C:/outside'], ['a\\b'], ['a', 'A'])):
            with self.subTest(names=names):
                resource = self.root/str(index)
                resource.mkdir()
                archive = resource/f'AAA_Studio025_Connector-{tool.CONNECTOR}.zip'
                with zipfile.ZipFile(archive, 'w') as out:
                    for name in names:
                        out.writestr(name, b'fixture')
                (resource/'package.json').write_text(json.dumps({
                    'connector_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))
                with self.assertRaises(ValueError):
                    tool.read_connector(resource)

    def test_archive_hash_checked_before_extraction(self):
        resource = self.root/'resource'
        resource.mkdir()
        (resource/f'AAA_Studio025_Connector-{tool.CONNECTOR}.zip').write_bytes(b'bad archive')
        (resource/'package.json').write_text(json.dumps({'connector_sha256': '0'*64}))
        with self.assertRaisesRegex(ValueError, '校验失败'):
            tool.read_connector(resource)


if __name__ == '__main__':
    unittest.main()
