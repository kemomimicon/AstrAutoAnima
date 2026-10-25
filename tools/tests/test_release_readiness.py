"""Regression coverage for non-destructive extension updates and packaged entrypoints."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import deploy_project as deploy
import deployment_support as paths
import easy_installer as easy
import extension_installer as extensions


class ReleaseReadinessTests(unittest.TestCase):
    def make_comfy(self, root):
        comfy = root / 'ComfyUI'; comfy.mkdir(); (comfy / 'main.py').write_text('# fixture')
        return comfy

    def test_extension_entry_routes_away_from_full_deployment(self):
        with patch.object(extensions, 'launch_gui', return_value=17) as gui, patch.object(deploy, 'deploy') as full:
            self.assertEqual(deploy.wizard(extension='reverse_wd', smoke=True), 17)
            gui.assert_called_once_with('reverse_wd', smoke=True); full.assert_not_called()

    def test_preflight_external_only_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); comfy = self.make_comfy(root)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
            plan = extensions.prepare('reverse_wd', str(comfy))
            self.assertEqual(plan.components, set())
            self.assertEqual(plan.external, {'booru_tagger_node','wd_eva02_model'})
            self.assertFalse(plan.install_external_requirements)
            self.assertEqual(before, sorted(p.relative_to(root).as_posix() for p in root.rglob('*')))

    def test_extension_apply_never_changes_runtime_sentinels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); comfy = self.make_comfy(root)
            sentinels = [root / 'hub_config.json', root / 'plugin.py', root / 'prompt_pool.json', comfy / 'workflow.json']
            for file in sentinels: file.write_bytes(b'keep-private-fixture')
            def install(plan, unused, log):
                self.assertEqual(plan.components, set())
                (plan.comfyui_root / 'models').mkdir()
                (plan.comfyui_root / 'models/fixture.txt').write_text('simulated model')
            with patch.object(extensions.socket, 'create_connection', side_effect=OSError), patch.object(extensions.shutil, 'which', return_value='fixture'), \
                 patch.object(extensions, 'install_external', side_effect=install), patch.object(deploy, 'deploy') as full, patch.object(easy, 'execute_plan') as legacy:
                extensions.execute('reverse_wd', str(comfy), consent=True, stopped=True, log=lambda _: None)
                full.assert_not_called(); legacy.assert_not_called()
            for file in sentinels: self.assertEqual(file.read_bytes(), b'keep-private-fixture')
            self.assertFalse((root / 'runtime-env.json').exists())

    def test_consent_and_active_port_prevent_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy = self.make_comfy(Path(tmp))
            with patch.object(extensions, 'install_external') as install:
                for kwargs in ({}, {'consent':True}, {'consent':True,'stopped':True,'port':0}):
                    with self.assertRaises(ValueError): extensions.execute('reverse_wd', str(comfy), **kwargs)
                with patch.object(extensions.socket, 'create_connection'):
                    with self.assertRaisesRegex(ValueError, '仍有服务'): extensions.execute('reverse_wd', str(comfy), consent=True, stopped=True)
                install.assert_not_called(); self.assertFalse((comfy / 'custom_nodes').exists())

    def test_malicious_manifest_target_stops_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy = self.make_comfy(Path(tmp))
            for target in ('../hub/config.json', '/outside', 'models/../../outside', 'custom_nodes\\bad', 'C:/outside'):
                with patch.object(extensions, 'component_selection', return_value=[{'id':'bad','kind':'git','target':target}]):
                    with self.assertRaises(ValueError): extensions.prepare('reverse_wd', str(comfy))

    def test_newer_or_ambiguous_runtime_blocked_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); astro = root / 'astro'; hub = root / 'hub'
            file = astro / 'data/plugins/astrbot_plugin_comfy_bridge/metadata.yaml'; file.parent.mkdir(parents=True)
            for version in ('0.9.0-beta.1', '0.5.2-beta.9', '0.5.2-beta.1-other', 'unknown'):
                file.write_text('version: ' + version)
                with self.assertRaises(ValueError): deploy.guard_runtime_versions(deploy.Plan(str(root), astrbot=str(astro)), root)
                self.assertEqual(file.read_text(), 'version: ' + version)
            file.write_text('version: 0.4.0'); hub.mkdir()
            hf = hub / 'pyproject.toml'; hf.write_text('version = "0.9.0b1"')
            with self.assertRaises(ValueError): deploy.guard_runtime_versions(deploy.Plan(str(root), astrbot=str(astro)), root)

    def test_same_and_older_runtime_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); astro = root / 'astro'; file = astro / 'data/plugins/astrbot_plugin_comfy_bridge/metadata.yaml'
            file.parent.mkdir(parents=True)
            for version in ('0.4.0', '0.5.0-beta.2-remake.2-notile.1'):
                file.write_text('version: ' + version)
                deploy.guard_runtime_versions(deploy.Plan(str(root), astrbot=str(astro)), root)

    def test_incomplete_package_rejected_before_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(deploy, 'ROOT', Path(tmp)):
            with self.assertRaisesRegex(ValueError, '部署包不完整'): deploy.validate(deploy.Plan('not-used'))

    def test_git_residue_not_treated_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'custom_nodes/node'; target.mkdir(parents=True)
            plan = easy.InstallPlan(root, root, root, root)
            item = {'target':'custom_nodes/node','url':'https://example.invalid/node.git','commit':'a'*40}
            with patch.object(easy.shutil, 'which', return_value='git'), patch.object(easy, 'run_checked') as run:
                with self.assertRaisesRegex(easy.InstallError, '无法确认完整Git'): easy.install_git_component(item, plan, lambda _:None)
                run.assert_not_called(); self.assertTrue(target.exists())
                (target / '.git').mkdir(); (target / '__init__.py').touch()
                with patch.object(easy.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout='b'*40)):
                    with self.assertRaisesRegex(easy.InstallError, '提交与清单不匹配'): easy.install_git_component(item, plan, lambda _:None)
                with patch.object(easy.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout='a'*40)):
                    self.assertEqual(easy.install_git_component(item, plan, lambda _:None), target)
                run.assert_not_called()

    def test_reparse_attribute_rejected_without_python312_api(self):
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_file_attributes=0x400)), patch.object(Path, 'is_symlink', return_value=False):
            with self.assertRaises(ValueError): paths.no_links(Path('fixture'))


if __name__ == '__main__': unittest.main()
