"""Only tiny temporary catalogs are installed; never use the real local catalog."""
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_project as deployer
import gufeng_resource as resource
import package_gufeng_resource as packager


class GuFengResourceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.source = self.base / 'upstream'
        (self.source / 'data').mkdir(parents=True)
        with closing(sqlite3.connect(self.source / 'data/cards.sqlite3')) as db, db:
            db.execute('CREATE TABLE cards (id TEXT PRIMARY KEY, prompt TEXT)')
            db.execute('INSERT INTO cards VALUES (?, ?)', ('test-only', 'moonlit pavilion'))
        self.digest = resource.sha256_file(self.source / 'data/cards.sqlite3')
        (self.source / 'data/catalog_manifest.json').write_text(json.dumps({
            'version': resource.CATALOG_VERSION, 'catalog_sha256': self.digest,
        }), 'utf-8')
        (self.source / 'README.md').write_text('Fixture upstream attribution.\n', 'utf-8')
        (self.source / 'SOURCES.md').write_text('Fixture source terms pending review.\n', 'utf-8')
        self.stack.enter_context(patch.object(resource, 'CATALOG_SHA256', self.digest))
        self.stack.enter_context(patch.object(packager, 'CATALOG_SHA256', self.digest))
        self.archive = self.base / resource.MODULE_NAME
        self.manifest = packager.build_candidate(self.source, self.archive, apply=True, log=lambda _: None)

    def test_packager_copies_only_allowlisted_files_and_preserves_attribution(self):
        (self.source / 'unrelated-private.txt').write_text('Do not package this fixture', 'utf-8')
        another = self.base / 'another.zip'
        packager.build_candidate(self.source, another, apply=True, log=lambda _: None)
        with zipfile.ZipFile(another) as archive:
            self.assertEqual(set(archive.namelist()), set(resource.FILES) | {resource.MANIFEST})
            self.assertEqual(archive.read('SOURCES.md'), (self.source / 'SOURCES.md').read_bytes())
            manifest = json.loads(archive.read(resource.MANIFEST))
        self.assertIs(manifest['private_candidate'], True)
        self.assertEqual(manifest['redistribution_status'], 'pending-source-review')

    def test_packager_preflight_never_writes_and_cannot_output_into_public_release(self):
        target = self.base / 'dry-run' / 'output.zip'
        packager.build_candidate(self.source, target, log=lambda _: None)
        self.assertFalse(target.parent.exists())
        with patch.object(packager, 'RELEASE_ROOT', self.base / 'public'):
            with self.assertRaisesRegex(ValueError, '公开'):
                packager.build_candidate(self.source, self.base / 'public/module.zip', apply=True)
        with self.assertRaisesRegex(ValueError, '已存在'):
            packager.build_candidate(self.source, self.archive, apply=True)

    def test_repeated_install_reuses_bytes_and_metadata_without_duplicate_database(self):
        root = self.base / 'install'
        path = resource.install_module(self.archive, root, lambda _: None)
        stamp = path.stat().st_mtime_ns
        self.assertEqual(path, root / 'hub/resources/gufeng/cards.sqlite3')
        self.assertEqual(resource.install_module(self.archive, root, lambda _: None), path)
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.assertEqual(list(root.rglob('cards.sqlite3')), [path])
        self.assertEqual((path.parent / 'SOURCES.md').read_bytes(), (self.source / 'SOURCES.md').read_bytes())
        self.assertEqual((path.parent / 'catalog_manifest.json').read_bytes(),
                         (self.source / 'data/catalog_manifest.json').read_bytes())
        self.assertFalse((root / 'runtime-env.local.json').exists())

    def test_conflicting_catalog_stops_without_overwriting_any_files(self):
        root = self.base / 'install'
        target = root / 'hub/resources/gufeng/cards.sqlite3'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'keep-existing-catalog')
        with self.assertRaisesRegex(ValueError, '冲突'):
            resource.install_module(self.archive, root, lambda _: None)
        self.assertEqual(target.read_bytes(), b'keep-existing-catalog')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_conflicting_user_configuration_stops_before_install(self):
        root = self.base / 'install'
        root.mkdir()
        environment = root / 'runtime-env.local.json'
        original = json.dumps({resource.ENV_KEY: str(self.base / 'user-catalog.sqlite3'), 'keep': 'setting'})
        environment.write_text(original, 'utf-8')
        with self.assertRaisesRegex(ValueError, '不覆盖'):
            resource.install_module(self.archive, root, lambda _: None)
        self.assertEqual(environment.read_text('utf-8'), original)
        self.assertFalse((root / 'hub').exists())

    def test_tampered_archive_stops_before_target_creation(self):
        tampered = self.base / 'tampered.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(tampered, 'w') as destination:
            for name in source.namelist():
                raw = source.read(name)
                destination.writestr(name, b'x' * len(raw) if name == 'data/cards.sqlite3' else raw)
        root = self.base / 'install'
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            resource.install_module(tampered, root, lambda _: None)
        self.assertFalse(root.exists())

    def test_missing_attribution_and_extra_zip_paths_are_rejected(self):
        for index, omitted in enumerate(('SOURCES.md', None)):
            archive = self.base / f'invalid-{index}.zip'
            with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(archive, 'w') as destination:
                for name in source.namelist():
                    if name != omitted:
                        destination.writestr(name, source.read(name))
                if omitted is None:
                    destination.writestr('../outside.txt', 'do not extract')
            with self.assertRaisesRegex(ValueError, '清单'):
                resource.inspect_module(archive)
        self.assertFalse((self.base / 'outside.txt').exists())

    def test_directory_module_and_no_space_preflight(self):
        (self.source / resource.MANIFEST).write_text(json.dumps(self.manifest), 'utf-8')
        resource.inspect_module(self.source)
        disk = type('Disk', (), {'free': 1})()
        root = self.base / 'install'
        with patch.object(resource.shutil, 'disk_usage', return_value=disk):
            with self.assertRaisesRegex(ValueError, '空间不足'):
                resource.install_module(self.source, root)
        self.assertFalse(root.exists())

    def test_link_target_is_rejected(self):
        root = self.base / 'install'
        target = root / 'hub/resources/gufeng'
        target.parent.mkdir(parents=True)
        external = self.base / 'user-directory'
        external.mkdir()
        try:
            target.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, '链接|联接'):
            resource.install_module(self.archive, root)
        self.assertEqual(list(external.iterdir()), [])

    def test_option_requires_explicit_selection_and_cli_flags_are_applied(self):
        plan = deployer.Plan(str(self.base / 'install'), gufeng_module=str(self.archive))
        with self.assertRaisesRegex(ValueError, '显式'):
            resource.selected_module(plan, deployer.ROOT)
        plan_file = self.base / 'plan.json'
        plan_file.write_text(json.dumps({'destination': str(self.base / 'install')}), 'utf-8')
        argv = ['deploy_project.py', '--plan', str(plan_file), '--install-gufeng',
                '--gufeng-module', str(self.archive), '--apply']
        with patch.object(sys, 'argv', argv), patch.object(deployer, 'validate'), patch.object(deployer, 'deploy') as deploy:
            deployer.main()
        applied = deploy.call_args.args[0]
        self.assertIs(applied.install_gufeng, True)
        self.assertEqual(applied.gufeng_module, str(self.archive))

    def prepare_deployment(self):
        root, astro, comfy = self.base / 'install', self.base / 'astro', self.base / 'comfy'
        (root / 'hub').mkdir(parents=True)
        (root / deployer.MARKER).touch()
        (comfy / 'user/default/workflows').mkdir(parents=True)
        (comfy / 'main.py').touch()
        (astro / 'data/config').mkdir(parents=True)
        for environment in (root / 'hub', comfy, astro):
            executable = deployer.python_at(environment / '.venv')
            executable.parent.mkdir(parents=True)
            executable.touch()
        (deployer.python_at(astro / '.venv').parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')).touch()
        self.stack.enter_context(patch.object(deployer, 'port_open', return_value=False))
        self.stack.enter_context(patch.object(deployer, 'start_services', return_value=[]))
        runner = self.stack.enter_context(patch.object(deployer, 'run'))
        return root, astro, comfy, runner

    def test_local_to_full_reinstall_preserves_library_settings_and_only_one_catalog(self):
        root, astro, comfy, runner = self.prepare_deployment()
        local = deployer.Plan(str(root), deployment_profile='local', comfyui=str(comfy),
                              install_gufeng=True, gufeng_module=str(self.archive))
        deployer.deploy(local, lambda _: None)
        local_environment = json.loads((root / 'runtime-env.local.json').read_text('utf-8'))
        catalog = root / 'hub/resources/gufeng/cards.sqlite3'
        self.assertEqual(local_environment[resource.ENV_KEY], str(catalog))
        local_environment['MY_USER_SETTING'] = 'keep'
        deployer.json_write(root / 'runtime-env.local.json', local_environment)
        pool = root / 'data/local/anima_random_prompt_pool.json'
        pool.write_text('{"prompts":[{"id":"my-user-entry"}]}', 'utf-8')
        preset = root / 'data/local/presets.json'
        preset.write_text('{"characters":{"mine":{}},"styles":{}}', 'utf-8')
        stamp = catalog.stat().st_mtime_ns
        full = deployer.Plan(str(root), deployment_profile='full', astrbot=str(astro), comfyui=str(comfy))
        # A later unchecked selection preserves the already installed local module.
        deployer.deploy(full, lambda _: None)
        full.install_gufeng = True
        full.gufeng_module = str(self.archive)
        deployer.deploy(full, lambda _: None)
        runner.assert_not_called()
        self.assertEqual(json.loads((root / 'runtime-env.local.json').read_text('utf-8')), local_environment)
        self.assertEqual(json.loads(pool.read_text('utf-8'))['prompts'][0]['id'], 'my-user-entry')
        self.assertIn('mine', json.loads(preset.read_text('utf-8'))['characters'])
        self.assertEqual(list(root.rglob('cards.sqlite3')), [catalog])
        self.assertEqual(catalog.stat().st_mtime_ns, stamp)
        for filename in ('runtime-env.full.json', 'runtime-env.json'):
            full_environment = json.loads((root / filename).read_text('utf-8'))
            self.assertNotIn(resource.ENV_KEY, full_environment)
            self.assertEqual(full_environment['AAH_EXECUTION_MODE'], 'remote')
        self.assertTrue((root / 'Start-Local.cmd' if os.name == 'nt' else root / 'Start-Local.sh').is_file())
        self.assertFalse((root / '.deploy.lock').exists())

    def test_fresh_full_install_enables_only_local_environment(self):
        root, astro, comfy, runner = self.prepare_deployment()
        full = deployer.Plan(str(root), deployment_profile='full', astrbot=str(astro), comfyui=str(comfy),
                             install_gufeng=True, gufeng_module=str(self.archive))
        deployer.deploy(full, lambda _: None)
        runner.assert_not_called()
        local = json.loads((root / 'runtime-env.local.json').read_text('utf-8'))
        self.assertIn(resource.ENV_KEY, local)
        self.assertNotIn(resource.ENV_KEY, json.loads((root / 'runtime-env.full.json').read_text('utf-8')))


if __name__ == '__main__':
    unittest.main()
