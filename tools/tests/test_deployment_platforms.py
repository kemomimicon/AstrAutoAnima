import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy_project import Plan, validate, checked_root, start_services, json_write, ROOT, MARKER
from deployment_support import (clean_path, comfy_root, astrbot_root, discover_python,
    windows_start_script, install_anima_master, configure_anima_master, AM_COMMIT,
    download_base_models, host_platform)


class PlatformTests(unittest.TestCase):
    def test_quotes_trimmed_but_stray_quote_rejected(self):
        self.assertEqual(clean_path('"example"'), 'example')
        with self.assertRaisesRegex(ValueError, '无效引号'):
            clean_path('example"')

    def test_missing_install_target_is_allowed_and_dot_is_normalized(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'new-install'
            self.assertEqual(checked_root(str(root / '.')), root.resolve())
            self.assertFalse(root.exists())

    def test_platform_mismatch_stops_before_writes(self):
        with self.assertRaisesRegex(ValueError, '操作系统'):
            validate(Plan('unused', platform='linux' if host_platform() == 'windows' else 'windows'))

    def test_comfy_portable_discovery(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / 'ComfyUI').mkdir()
            (root / 'ComfyUI/main.py').touch()
            (root / 'python_embeded').mkdir()
            (root / 'python_embeded/python.exe').touch()
            comfy = comfy_root(t)
            self.assertEqual(comfy, (root / 'ComfyUI').resolve())
            # Windows runners may expose TEMP through an 8.3 alias (RUNNER~1).
            # Compare the actual file, not two spellings of the same location.
            self.assertTrue(discover_python(comfy, portable=True).samefile(root / 'python_embeded/python.exe'))

    def test_data_folder_and_desktop_default(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / '.astrbot/data').mkdir(parents=True)
            with patch('pathlib.Path.home', return_value=home):
                expected = (home / '.astrbot').resolve()
                self.assertEqual(astrbot_root('', 'desktop'), expected)
                self.assertEqual(astrbot_root(str(home / '.astrbot/data'), 'desktop'), expected)

    def test_missing_python_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, 'Python'):
                discover_python(Path(t))

    def test_desktop_never_spawns_cli(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / MARKER).touch()
            json_write(root / 'runtime-env.json', {})
            json_write(root / 'services.json', [{'name':'AstrBot', 'mode':'desktop', 'port':6185}])
            with patch('deploy_project.port_open', return_value=False), patch('subprocess.Popen') as spawn:
                self.assertIn('手动打开', start_services(root, lambda _: None)[0])
                spawn.assert_not_called()

    def test_model_catalog_has_exact_hashes_and_allowed_destinations(self):
        profile = json.loads((ROOT / 'tools/model_catalog.json').read_text('utf-8'))['profiles']['anima-base-1.0']
        self.assertEqual(len(profile['files']), 3)
        for item in profile['files']:
            self.assertEqual(len(item['sha256']), 64)
            self.assertTrue(item['url'].startswith('https://huggingface.co/circlestone-labs/Anima/'))
            self.assertNotIn('..', Path(item['target']).parts)

    def test_explicit_local_models_are_not_downloaded(self):
        plan = Plan('unused', unet='a', clip='b', vae='c')
        with patch('easy_installer.download_file') as download:
            download_base_models(ROOT, Path('unused'), plan, lambda _: None)
            download.assert_not_called()

    def test_model_profile_downloads_to_expected_directories(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            catalog = {'profiles': {'anima-base-1.0': {'files': [
                {'field': key, 'filename': key + '.safetensors', 'size': 3,
                 'url': 'https://example.invalid/' + key, 'sha256': 'test-hash',
                 'target': 'models/' + folder + '/' + key + '.safetensors'}
                for key, folder in [('unet', 'diffusion_models'), ('clip', 'text_encoders'), ('vae', 'vae')]
            ]}}}
            (base / 'tools').mkdir()
            (base / 'tools/model_catalog.json').write_text(json.dumps(catalog), encoding='utf-8')
            def download(url, target, log, **kwargs):
                self.assertEqual(kwargs['expected_sha256'], 'test-hash')
                target.parent.mkdir(parents=True)
                target.write_bytes(b'abc')
            plan = Plan('unused')
            with patch('easy_installer.download_file', side_effect=download):
                download_base_models(base, base / 'comfy', plan, lambda _: None)
            for key, folder in [('unet', 'diffusion_models'), ('clip', 'text_encoders'), ('vae', 'vae')]:
                self.assertEqual(Path(getattr(plan, key)).parent.name, folder)

    def test_am_new_install_checks_archive_and_installs_expected_root(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            def download(url, target, log, **kwargs):
                self.assertEqual(len(kwargs['expected_sha256']), 64)
                target.parent.mkdir(parents=True)
                with zipfile.ZipFile(target, 'w') as z:
                    prefix = 'anima-master-' + AM_COMMIT + '/'
                    z.writestr(prefix + 'metadata.yaml', 'version: "0.7.1"')
                    z.writestr(prefix + 'main.py', '# fixture')
            from deploy_project import copy_source
            with patch('easy_installer.download_file', side_effect=download):
                installed = install_anima_master(root / 'astro', root, lambda _: None, copy_source)
            self.assertTrue((installed / 'main.py').is_file())
            with patch('easy_installer.download_file') as again:
                install_anima_master(root / 'astro', root, lambda _: None, copy_source)
                again.assert_not_called()

    def test_resume_download_rejects_link_without_touching_external_file(self):
        from easy_installer import download_file
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            private = root / 'keep.txt'
            private.write_text('keep')
            partial = root / 'model.part'
            try:
                partial.symlink_to(private)
            except OSError:
                self.skipTest('Symlink creation not permitted on this runner')
            with patch('easy_installer.run_checked') as run:
                with self.assertRaisesRegex(ValueError, '链接'):
                    download_file('https://example.invalid/model', root / 'model', lambda _: None)
                run.assert_not_called()
            self.assertEqual(private.read_text(), 'keep')

    def test_am_existing_newer_not_downgraded(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            plugin = root / 'data/plugins/astrbot_plugin_anima_master'
            plugin.mkdir(parents=True)
            (plugin / 'metadata.yaml').write_text('version: "0.9.1"')
            with patch('easy_installer.download_file') as download:
                with self.assertRaisesRegex(ValueError, '降级'):
                    install_anima_master(root, root, lambda _: None, lambda *_: None)
                download.assert_not_called()

    def test_am_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            def fake_download(url, target, log, **kwargs):
                target.parent.mkdir(parents=True)
                with zipfile.ZipFile(target, 'w') as z:
                    z.writestr('anima-master-' + AM_COMMIT + '/../outside.py', 'no')
            with patch('easy_installer.download_file', side_effect=fake_download):
                with self.assertRaisesRegex(ValueError, 'ZIP'):
                    install_anima_master(root / 'astro', root, lambda _: None, lambda *_: None)
            self.assertFalse((root / 'outside.py').exists())

    def test_am_preserves_existing_credentials_and_workflow(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            astro = root / 'astro'
            cfg = astro / 'data/config/astrbot_plugin_anima_master_config.json'
            json_write(cfg, {'anima_master_comfyui_connection': {'custom_workflow_path': 'my.json'}, 'private': 'keep'})
            configure_anima_master(astro, root / 'comfy', root, json_write)
            result = json.loads(cfg.read_text('utf-8'))
            self.assertEqual(result['private'], 'keep')
            self.assertEqual(result['anima_master_comfyui_connection']['custom_workflow_path'], 'my.json')
            self.assertEqual(len(list((root / 'am-config-backups').glob('*.json'))), 1)

    def test_bootstrap_is_ascii_for_legacy_powershell(self):
        content = (ROOT / 'tools/bootstrap_windows.ps1').read_bytes()
        content.decode('ascii')
        for codepage in ('utf-8', 'gbk', 'cp1252'):
            self.assertEqual(content.decode(codepage), content.decode('ascii'))

    def test_cli_error_is_utf8_even_under_ascii_console(self):
        with tempfile.TemporaryDirectory() as t:
            result = subprocess.run([sys.executable, str(ROOT / 'tools/deploy_project.py'),
                '--plan', str(Path(t) / 'missing.json')], capture_output=True,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'ascii'})
            self.assertEqual(result.returncode, 1)
            self.assertIn('部署失败', result.stderr.decode('utf-8'))
            self.assertNotIn(b'UnicodeEncodeError', result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Windows native argv regression')
    def test_real_cmd_start_with_chinese_spaces_and_parentheses(self):
        with tempfile.TemporaryDirectory(prefix='AAA 跑图 (test) ') as t:
            root = Path(t)
            script = windows_start_script()
            # Use the real running interpreter, not a guessed third-party environment.
            script = script.replace('if not exist "hub\\.venv\\Scripts\\python.exe" goto :missing\r\n', '')
            script = script.replace('"hub\\.venv\\Scripts\\python.exe"', '"' + sys.executable + '"')
            (root / 'Start.cmd').write_text(script, encoding='ascii', newline='')
            (root / 'deploy_project.py').write_text('import sys,pathlib\nassert sys.argv[1:]==["--start","."]\nassert pathlib.Path.cwd().name.startswith("AAA ")\nprint("ARGV_OK")\n', encoding='utf-8')
            result = subprocess.run(['cmd.exe','/d','/c', str(root / 'Start.cmd')], input='\n', capture_output=True, text=True, errors='replace', timeout=20)
            self.assertIn('ARGV_OK', result.stdout, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 parser')
    def test_native_powershell_parse(self):
        script = str(ROOT / 'tools/bootstrap_windows.ps1').replace("'", "''")
        command = "$t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('" + script + "',[ref]$t,[ref]$e); if($e.Count){exit 1}"
        result = subprocess.run(['powershell.exe','-NoProfile','-Command',command], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 native stderr')
    def test_missing_python_or_tk_probe_does_not_abort_bootstrap(self):
        text = (ROOT / 'tools/bootstrap_windows.ps1').read_text('ascii')
        function = text[text.index('function Find-ProjectPython'):text.index('$projectPython = Find-ProjectPython')]
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t) / 'missing-tk.cmd'
            fake.write_text('@echo off\necho Expected missing Tk 1>&2\nexit /b 1\n', encoding='ascii')
            fake_name = str(fake).replace("'", "''")
            command = ("$ErrorActionPreference='Stop'; "
                       "function Get-Command { param($Name,$ErrorAction) "
                       "if ($Name -eq 'python') { [pscustomobject]@{Source='" + fake_name + "'} } };\n" + function +
                       "\n$result=Find-ProjectPython; if($null -ne $result){exit 2}; "
                       "if($ErrorActionPreference -ne 'Stop'){exit 3}; Write-Output PROBE_OK")
            result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'PROBE_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
