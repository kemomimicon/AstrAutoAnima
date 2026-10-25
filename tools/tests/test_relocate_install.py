"""No production data, no downloads, no service startup; fixtures only."""
import ast
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relocate_install as r


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else r.encode_json(value))


def fixture(base):
    old, root = base / '旧 下载' / 'install', base / 'QQ-comfyui'
    put(root / r.MARKER, b'')
    put(root / 'Start.cmd', b'@echo off\r\n')
    put(root / 'hub/pyproject.toml', b'[project]\nname="astr-auto-anima-hub"\n')
    put(root / 'hub/.venv/Scripts/python.exe', b'fake-python')
    put(root / 'astrbot/.venv/Scripts/python.exe', b'fake-python')
    put(root / 'astrbot/.venv/Scripts/astrbot.exe', b'embedded-old-interpreter-stays-untouched')
    put(root / 'services.json', [
        {'name': 'Hub', 'cwd': str(old / 'hub'), 'command': [str(old / 'hub/.venv/Scripts/python.exe'), '-m', 'astr_auto_anima_hub'], 'port': 6278},
        {'name': 'AstrBot', 'cwd': str(old / 'astrbot'), 'command': [str(old / 'astrbot/.venv/Scripts/astrbot.exe'), 'run', '--port', '6185'], 'port': 6185}])
    put(root / 'runtime-env.json', {'AAH_ADMIN_TOKEN': 'test-private-value', 'AAH_ASTRBOT_API_KEY': str(old / 'secret-like-string'),
        'AAH_PLUGIN_DIR': str(old / 'astrbot/data/plugins/astrbot_plugin_comfy_bridge'),
        'AAH_PLUGIN_DATA_DIR': str(old / 'astrbot/data/plugin_data/astrbot_plugin_comfy_bridge'),
        'AAH_COMFYUI_ROOT': str(base / 'external-comfy'), 'AAH_ASTRBOT_URL': 'http://127.0.0.1:6185'})
    put(root / 'last-plan.json', {'destination': str(old), 'astrbot': str(old / 'astrbot'), 'api_key': 'test-do-not-touch',
                                  'unet': str(old / 'models/test.safetensors')})
    put(root / 'astrbot/data/config/astrbot_plugin_comfy_bridge_config.json', {
        'prompt_pool_path': str(old / 'astrbot/data/plugin_data/pool.json'),
        'output_dir': str(old / 'astrbot/data/plugin_data/outputs'), 'fixed_negative_prompt': str(old / 'keep-this-text'),
        'workflow_registry_path': 'data/workflow_registry.json'})
    put(root / 'astrbot/data/plugins/astrbot_plugin_comfy_bridge/data/workflow_registry.json', {
        'workflows': [{'workflow_file': str(old / 'flow.json'), 'prompt': str(old / 'not-path')}]})
    put(root / 'astrbot/data/config/astrbot_plugin_anima_master_config.json', {
        'anima_master_comfyui_connection': {'custom_workflow_path': str(old / 'flow.json'), 'api_key': 'keep'}})
    put(root / 'astrbot/data/plugin_data/pool.json', {'prompts': [{'text': str(old / 'user-content')}]})
    put(root / 'models/test.safetensors', b'unchanged-model-fixture')
    put(root / 'hub/.venv/Lib/site-packages/__editable__.hub.pth', (str(old / 'hub/src') + '\n').encode())
    put(root / 'hub/.venv/Lib/site-packages/__editable___hub_finder.py',
        ('# generated\nMAPPING = {"astr_auto_anima_hub": ' + repr(str(old / 'hub/src/astr_auto_anima_hub')) + '}\n').encode())
    return old, root


@unittest.skipUnless(sys.platform == 'win32', 'Windows path/runtime relocation')
class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='AAA relocation 中文 ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.old, self.root = fixture(self.base)

    def test_exact_boundary_and_mixed_separators(self):
        mapper = r.PathMap([self.old], self.root)
        self.assertEqual(mapper(str(self.old / 'hub').replace('\\', '/').upper()), str(self.root / 'HUB'))
        self.assertEqual(mapper(str(self.old) + '-other/hub'), str(self.old) + '-other/hub')
        self.assertEqual(mapper('https://example.com/' + str(self.old)), 'https://example.com/' + str(self.old))
        with self.assertRaises(r.RepairError): mapper(str(self.old) + '/../../outside')

    def test_preview_has_no_secret_values_and_no_writes(self):
        before = (self.root / 'runtime-env.json').read_bytes()
        plan = r.prepare_repair(self.root)
        self.assertNotIn('test-private-value', plan.preview())
        self.assertEqual(before, (self.root / 'runtime-env.json').read_bytes())
        self.assertFalse(list(self.root.glob('path-backup_*')))

    def test_backup_repair_preserves_secrets_models_and_pool(self):
        protected = [self.root / 'models/test.safetensors', self.root / 'astrbot/data/plugin_data/pool.json',
                     self.root / 'astrbot/.venv/Scripts/astrbot.exe']
        unchanged = {p: p.read_bytes() for p in protected}
        original_env = r.read_json(self.root / 'runtime-env.json')
        plan = r.prepare_repair(self.root)
        with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime'):
            backup = r.apply_repair(plan, lambda _: None)
        for p, data in unchanged.items(): self.assertEqual(data, p.read_bytes())
        after = r.read_json(self.root / 'runtime-env.json')
        for key in ('AAH_ADMIN_TOKEN', 'AAH_ASTRBOT_API_KEY', 'AAH_COMFYUI_ROOT', 'AAH_ASTRBOT_URL'):
            self.assertEqual(original_env[key], after[key])
        self.assertEqual(r.read_json(backup / 'originals/runtime-env.json'), original_env)
        for change in plan.changes:
            self.assertEqual((backup / 'originals' / change.path.relative_to(self.root)).read_bytes(), change.before)
        services = r.read_json(self.root / 'services.json')
        self.assertEqual(services[1]['command'][1:3], ['-c', r.ASTRO_RUNNER])
        self.assertFalse(r.prepare_repair(self.root).changes, 'second run must be idempotent')

    def test_runtime_failure_rolls_back(self):
        plan = r.prepare_repair(self.root)
        with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime', side_effect=r.RepairError('probe failed')):
            with self.assertRaises(r.RepairError): r.apply_repair(plan, lambda _: None)
        for change in plan.changes: self.assertEqual(change.path.read_bytes(), change.before)
        self.assertEqual(len(list(self.root.glob('path-backup_*'))), 1)
        self.assertFalse((self.root / '.aaa-path-repair.lock').exists())

    def test_ansi_indices_preserve_encoding_backup_and_line_endings(self):
        site = self.root / 'hub/.venv/Lib/site-packages'
        originals = {
            site / 'legacy.pth': ('# 中文注释\r\n' + str(self.old / 'hub/src') + '\r\n').encode('cp936'),
            site / 'legacy.egg-link': (str(self.old / 'hub') + '\r\n.\r\n').encode('cp936'),
            self.root / 'hub/.venv/pyvenv.cfg': ('# 中文\r\nhome = ' + str(self.old / 'python') + '\r\n').encode('cp936'),
        }
        for path, data in originals.items(): put(path, data)
        with patch.object(r.locale, 'getencoding', return_value='cp936'):
            plan = r.prepare_repair(self.root)
            with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime'):
                backup = r.apply_repair(plan, lambda _: None)
            self.assertFalse(r.prepare_repair(self.root).changes)
        for path, data in originals.items():
            expected = data.decode('cp936').replace(str(self.old), str(self.root)).encode('cp936')
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual((backup / 'originals' / path.relative_to(self.root)).read_bytes(), data)

    def test_utf8_bom_indices_and_python_source_preserved(self):
        site = self.root / 'hub/.venv/Lib/site-packages'
        index = site / 'bom.pth'
        finder = site / '__editable___bom_finder.py'
        put(index, ('# 注释\r\n' + str(self.old / 'hub/src') + '\r\n').encode('utf-8-sig'))
        put(finder, ('# 注释\r\nMAPPING = {"hub": ' + repr(str(self.old / 'hub/src')) + '}\r\n').encode('utf-8-sig'))
        plan = r.prepare_repair(self.root)
        replacements = {c.path: c.after for c in plan.changes}
        for path in (index, finder):
            self.assertTrue(replacements[path].startswith(b'\xef\xbb\xbf'))
            self.assertIn('# 注释\r\n', replacements[path].decode('utf-8-sig'))
        self.assertIn(str(self.root / 'hub/src'), replacements[index].decode('utf-8-sig'))

    def test_python_source_encoding_cookie_and_unicode_new_path(self):
        original = ('# coding: cp936\r\n# 中文注释\r\nMAPPING = {"hub": ' + repr(str(self.old / 'hub/src')) + '}\r\n').encode('cp936')
        mapper = r.PathMap([self.old], self.base / '新🚚目录')
        after = r.map_python_literals(original, mapper, 'finder.py')
        self.assertIn('# 中文注释\r\n', after.decode('cp936'))
        tree = ast.parse(after.decode('cp936'))
        self.assertEqual(ast.literal_eval(tree.body[0].value)['hub'], str(self.base / '新🚚目录/hub/src'))
        self.assertEqual(r.map_python_literals(after, mapper, 'finder.py'), after)

    def test_unknown_encoding_names_file_without_leaking_content_or_writes(self):
        index = self.root / 'hub/.venv/Lib/site-packages/broken.pth'
        put(index, b'test-private-value\x81')
        before = (self.root / 'services.json').read_bytes()
        with patch.object(r.locale, 'getencoding', return_value='cp936'):
            with self.assertRaises(r.RepairError) as exc: r.prepare_repair(self.root)
        self.assertIn(str(index), str(exc.exception))
        self.assertNotIn('test-private-value', str(exc.exception))
        self.assertEqual((self.root / 'services.json').read_bytes(), before)
        self.assertFalse(list(self.root.glob('path-backup_*')))

    def test_bad_python_source_encoding_is_file_specific(self):
        with self.assertRaises(r.RepairError) as exc:
            r.map_python_literals(b'# coding: no-such-encoding\nprivate-value', lambda v: v, 'bad_finder.py')
        self.assertIn('bad_finder.py', str(exc.exception))
        self.assertNotIn('private-value', str(exc.exception))

    def test_unrepresentable_legacy_destination_fails_without_loss(self):
        with self.assertRaises(r.RepairError) as exc:
            r.encode_environment_text('new🚚path', 'cp936', 'legacy.pth')
        self.assertIn('legacy.pth', str(exc.exception))
        self.assertIn('cp936', str(exc.exception))

    def test_ansi_runtime_failure_rolls_back_exact_original_bytes(self):
        index = self.root / 'hub/.venv/Lib/site-packages/legacy.pth'
        data = (str(self.old / 'hub/src') + '\r\n# 中文\r\n').encode('cp936')
        put(index, data)
        with patch.object(r.locale, 'getencoding', return_value='cp936'):
            plan = r.prepare_repair(self.root)
        with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime', side_effect=r.RepairError('probe failed')):
            with self.assertRaises(r.RepairError): r.apply_repair(plan, lambda _: None)
        self.assertEqual(index.read_bytes(), data)
        for change in plan.changes: self.assertEqual(change.path.read_bytes(), change.before)

    def test_partial_write_failure_rolls_back(self):
        plan = r.prepare_repair(self.root)
        write = r.atomic_write
        counter = [0]
        def fail_once(path, content):
            counter[0] += 1
            if counter[0] == 2: raise OSError('simulated write failure')
            write(path, content)
        with patch.object(r, 'assert_idle'), patch.object(r, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError): r.apply_repair(plan, lambda _: None)
        for change in plan.changes: self.assertEqual(change.path.read_bytes(), change.before)

    def test_concurrent_edit_stops_before_backup(self):
        plan = r.prepare_repair(self.root)
        put(self.root / 'runtime-env.json', {'user': 'edited-after-preview'})
        with patch.object(r, 'assert_idle'):
            with self.assertRaises(r.RepairError): r.apply_repair(plan, lambda _: None)
        self.assertFalse(list(self.root.glob('path-backup_*')))

    def test_backup_verification_failure_does_not_write(self):
        plan = r.prepare_repair(self.root)
        read = r.read_bytes
        def corrupt(path):
            return b'bad-backup' if 'originals' in Path(path).parts else read(path)
        with patch.object(r, 'assert_idle'), patch.object(r, 'read_bytes', side_effect=corrupt):
            with self.assertRaises(r.RepairError): r.apply_repair(plan, lambda _: None)
        for change in plan.changes: self.assertEqual(change.path.read_bytes(), change.before)

    def test_running_service_refused(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            plan = r.prepare_repair(self.root)
            plan.services[0]['port'] = listener.getsockname()[1]
            with self.assertRaises(r.RepairError): r.apply_repair(plan, lambda _: None)
        self.assertFalse(list(self.root.glob('path-backup_*')))

    def test_marker_missing_or_duplicate_json_or_missing_binary(self):
        marker = self.root / r.MARKER
        marker.rename(self.root / 'saved-marker')
        with self.assertRaises(r.RepairError): r.prepare_repair(self.root)
        (self.root / 'saved-marker').rename(marker)
        put(self.root / 'runtime-env.json', b'{"x":1,"x":2}')
        with self.assertRaises(r.RepairError): r.prepare_repair(self.root)

    def test_inventory_nested_existing_and_disk_full(self):
        for target in (self.root, self.root / 'child', self.base):
            with self.assertRaises(r.RepairError): r.migration_inventory(self.root, target)
        with patch.object(r.shutil, 'disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(r.RepairError): r.migration_inventory(self.root, self.base / 'new')

    def test_reparse_point_refused(self):
        original = Path.lstat
        def reparse(path):
            result = original(path)
            if path == self.root / 'models':
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaises(r.RepairError): r.migration_inventory(self.root, self.base / 'new')

    def test_migration_preserves_source_and_data(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        dest = self.base / '新 install'
        with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime'):
            r.migrate_install(self.root, dest, lambda _: None)
        for p, content in before.items(): self.assertEqual(content, (self.root / p).read_bytes())
        for p in ('models/test.safetensors', 'astrbot/data/plugin_data/pool.json'):
            self.assertEqual((dest / p).read_bytes(), before[Path(p)])
        self.assertEqual(r.read_json(dest / 'services.json')[0]['cwd'], str(dest / 'hub'))
        self.assertFalse((dest / '.aaa-migration-incomplete').exists())

    def test_existing_empty_destination_with_ansi_source(self):
        index = self.root / 'hub/.venv/Lib/site-packages/legacy.pth'
        put(index, (str(self.old / 'hub/src') + '\r\n# 中文\r\n').encode('cp936'))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        dest = self.base / '已建空目录 空格'
        dest.mkdir()
        with patch.object(r.locale, 'getencoding', return_value='cp936'), patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime'):
            backup = r.migrate_install(self.root, dest, lambda _: None)
        self.assertIsNotNone(backup)
        for p, data in before.items(): self.assertEqual(data, (self.root / p).read_bytes())
        for p in ('models/test.safetensors', 'astrbot/data/plugin_data/pool.json'):
            self.assertEqual((dest / p).read_bytes(), before[Path(p)])
        original_env = json.loads(before[Path('runtime-env.json')])
        new_env = r.read_json(dest / 'runtime-env.json')
        for key in ('AAH_ADMIN_TOKEN', 'AAH_ASTRBOT_API_KEY'):
            self.assertEqual(original_env[key], new_env[key])
        relative = index.relative_to(self.root)
        self.assertEqual((backup / 'originals' / relative).read_bytes(), before[relative])
        self.assertIn(str(dest / 'hub/src'), (dest / relative).read_bytes().decode('cp936'))
        self.assertFalse((dest / '.aaa-migration-incomplete').exists())

    def test_nonempty_hidden_file_and_file_destination_refused_untouched(self):
        dest = self.base / 'occupied'
        dest.mkdir()
        sentinel = dest / '.do-not-touch'
        put(sentinel, b'preserve this')
        for target in (dest, sentinel):
            with self.assertRaises(r.RepairError): r.migrate_install(self.root, target, lambda _: None)
        self.assertEqual(list(dest.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'preserve this')

    def test_destination_populated_during_preflight_refused(self):
        dest = self.base / 'race'
        dest.mkdir()
        def busy(_): put(dest / 'someone-elses-file', b'do not replace')
        with patch.object(r, 'assert_idle', side_effect=busy):
            with self.assertRaises(r.RepairError): r.migrate_install(self.root, dest, lambda _: None)
        self.assertEqual([p.name for p in dest.iterdir()], ['someone-elses-file'])
        self.assertEqual((dest / 'someone-elses-file').read_bytes(), b'do not replace')

    def test_bad_encoding_does_not_write_to_selected_empty_directory(self):
        dest = self.base / 'still-empty'; dest.mkdir()
        put(self.root / 'hub/.venv/Lib/site-packages/invalid.pth', b'\x81')
        with patch.object(r.locale, 'getencoding', return_value='cp936'):
            with self.assertRaises(r.RepairError): r.migrate_install(self.root, dest, lambda _: None)
        self.assertEqual(list(dest.iterdir()), [])

    def test_existing_empty_reparse_destination_refused(self):
        dest = self.base / 'pretend-junction'; dest.mkdir()
        original = Path.lstat
        def reparse(path):
            result = original(path)
            if path == dest:
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaises(r.RepairError): r.migrate_install(self.root, dest, lambda _: None)
        self.assertEqual(list(dest.iterdir()), [])

    def test_failed_migration_keeps_source_and_marks_destination(self):
        dest = self.base / 'failed-copy'
        with patch.object(r, 'assert_idle'), patch.object(r, 'check_runtime', side_effect=r.RepairError('bad Python')):
            with self.assertRaises(r.RepairError): r.migrate_install(self.root, dest, lambda _: None)
        self.assertTrue((dest / '.aaa-migration-incomplete').exists())
        self.assertTrue((self.root / 'models/test.safetensors').is_file())
        with self.assertRaises(r.RepairError): r.prepare_repair(dest)

    def test_real_venv_migration_repairs_pth_import(self):
        # Keep the runtime fixture representable by its real Windows locale;
        # synthetic CP936/Chinese fixtures above exercise decoding separately.
        runtime_temp = tempfile.TemporaryDirectory(prefix='AAA-runtime-')
        self.addCleanup(runtime_temp.cleanup)
        runtime_base = Path(runtime_temp.name)
        native_encoding = r.locale.getencoding()
        try:
            '中文'.encode(native_encoding)
            suffix = ' 中文'
        except UnicodeEncodeError:
            suffix = ''
        source, dest = runtime_base / ('real source' + suffix), runtime_base / ('real moved' + suffix)
        source.mkdir()
        dest.mkdir()  # Match the user's folder-picker-created empty directory.
        put(source / r.MARKER, b''); put(source / 'Start.cmd', b'@echo off')
        put(source / 'hub/pyproject.toml', b'[project]\nname="astr-auto-anima-hub"')
        put(source / 'hub/src/astr_auto_anima_hub/__init__.py', b'# harmless test module\n')
        result = subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(source / 'hub/.venv')], capture_output=True)
        self.assertEqual(result.returncode, 0)
        put(source / 'hub/.venv/Lib/site-packages/test-editable.pth', (str(source / 'hub/src') + '\r\n').encode(native_encoding))
        put(source / 'runtime-env.json', {'AAH_ADMIN_TOKEN': 'test-unchanged'})
        put(source / 'services.json', [{'name': 'Hub', 'cwd': str(source / 'hub'),
            'command': [str(source / 'hub/.venv/Scripts/python.exe'), '-m', 'astr_auto_anima_hub'], 'port': 6278}])
        with patch.object(r, 'assert_idle'), patch.object(r.locale, 'getencoding', return_value=native_encoding):
            r.migrate_install(source, dest, lambda _: None)
        r.check_runtime(r.prepare_repair(dest))
        self.assertTrue((source / 'hub/.venv/Scripts/python.exe').is_file())
        exe = os.environ.get('AAA_RELOCATION_TEST_EXE')
        if exe:
            # Test the shipped EXE, not just the source module: reintroduce stale
            # references in THIS disposable fixture and verify real repair/probe.
            put(dest / 'services.json', r.read_json(source / 'services.json'))
            put(dest / 'hub/.venv/Lib/site-packages/test-editable.pth', (str(source / 'hub/src') + '\r\n').encode(native_encoding))
            result = subprocess.run([exe, '--repair', str(dest), '--confirm'], timeout=50,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(r.read_json(dest / 'services.json')[0]['cwd'], str(dest / 'hub'))
            r.check_runtime(r.prepare_repair(dest))


if __name__ == '__main__': unittest.main()
