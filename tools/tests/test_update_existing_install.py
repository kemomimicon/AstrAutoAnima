from pathlib import Path
import hashlib
import importlib.util
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import update_existing_install as updater


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='aaa-upgrade-');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.install=self.base/'existing install 中文';self.plugin=self.install/'astro/data/plugins/astrbot_plugin_comfy_bridge';self.hub=self.install/'hub';self.comfy=self.install/'comfy'
        self.put(self.plugin/'metadata.yaml',b'version: 0.5.0-beta.2\n');self.put(self.plugin/'main.py',b'OLD_PLUGIN=True\n')
        self.put(self.plugin/'data/anima_random_prompt_pool.json',b'{"prompts":[{"id":"user"}]}')
        self.put(self.plugin/'.env',b'personal-value-not-to-change')
        self.put(self.hub/'pyproject.toml',b'version = "0.5.0b2"\n');self.put(self.hub/'src/astr_auto_anima_hub/__init__.py',b'old=True\n')
        self.put(self.hub/'.env',b'personal-hub-value');self.put(self.hub/'resources/own.sqlite3',b'user-db')
        self.put(self.comfy/'main.py',b'# existing comfy');self.put(self.comfy/'models/loras/own.safetensors',b'user-model')
        self.put(self.comfy/'user/default/workflows/Anima_HQ_Txt2Img_Beta_api.json',b'custom-model-bindings')
        self.put(self.install/'.aaa-managed-install',b'')
        env={'AAH_PLUGIN_DIR':str(self.plugin),'AAH_PLUGIN_DATA_DIR':str(self.install/'astro/data/plugin_data/astrbot_plugin_comfy_bridge'),'AAH_COMFYUI_ROOT':str(self.comfy),'AAH_ADMIN_TOKEN':'fixture-personal-token'+'x'*32,'AAH_ASTRBOT_API_KEY':'fixture-personal-key'}
        self.put(self.install/'runtime-env.json',json.dumps(env).encode())
        services=[{'name':'Hub','cwd':str(self.hub),'command':[sys.executable,'-m','astr_auto_anima_hub'],'port':6278},{'name':'ComfyUI','cwd':str(self.comfy),'command':[sys.executable,'main.py'],'port':8188}]
        self.put(self.install/'services.json',json.dumps(services).encode())
        self.payload=self.base/'patch/payload'
        entries={'plugin/main.py':b'NEW_PLUGIN=True\n','plugin/metadata.yaml':b'version: 0.5.2-beta.1\n',
           'plugin/data/anima_random_prompt_pool.json':b'{"prompts":[]}',
           'plugin/data/new-default.json':b'{}','hub/pyproject.toml':b'version = "0.5.2b1"\n',
           'hub/src/astr_auto_anima_hub/__init__.py':b'__version__="0.5.2-beta.1"\n',
           'hub-requirements.txt':b'fastapi>=0.115,<1\n','web/index.html':b'NEW_WEB',
           'node/nodes.py':b'NEW_NODE=True\n','workflows/new.json':b'{"public":true}',
           'runtime/deploy_project.py':b'NEW_HELPER=True\n','runtime/project_components.py':b'NEW_COMPONENT_HELPER=True\n'}
        for name,data in entries.items():self.put(self.payload/name,data)
        self.freeze_payload()
        self.plan=updater.Plan(str(self.install),str(self.plugin),str(self.hub),sys.executable,str(self.hub/'web'),str(self.comfy),backup_root=str(self.install/'aaa_update_backups'),ports=())
        self.real_probe=updater.probe
        self.probe=patch.object(updater,'probe',return_value=[]);self.probe.start();self.addCleanup(self.probe.stop)

    def put(self,path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    def freeze_payload(self):
        rows=[{'path':p.relative_to(self.payload).as_posix(),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in self.payload.rglob('*') if p.is_file()]
        self.put(self.payload.parent/'payload-manifest.json',json.dumps({'files':rows}).encode())
    def apply(self):return updater.apply(self.plan,payload=self.payload,confirm_stopped=True,log=lambda _:None)
    def snapshot(self):return {p.relative_to(self.install).as_posix():p.read_bytes() for p in self.install.rglob('*') if p.is_file()}

    def test_preflight_is_read_only(self):
        before=self.snapshot();state,_=updater.prepare(self.plan,self.payload)
        self.assertTrue(state['operations']);self.assertEqual(before,self.snapshot())

    def test_upgrade_preserves_user_data_keys_models_and_workflow(self):
        original={str(p):p.read_bytes() for p in [self.install/'runtime-env.json',self.install/'services.json',self.hub/'.env',self.plugin/'.env',self.plugin/'data/anima_random_prompt_pool.json',self.hub/'resources/own.sqlite3',self.comfy/'models/loras/own.safetensors',self.comfy/'user/default/workflows/Anima_HQ_Txt2Img_Beta_api.json']}
        backup=self.apply();self.assertTrue(backup.is_dir())
        for p,value in original.items():self.assertEqual(Path(p).read_bytes(),value,p)
        self.assertEqual((self.plugin/'main.py').read_bytes(),b'NEW_PLUGIN=True\n')
        self.assertEqual((self.hub/'web/index.html').read_bytes(),b'NEW_WEB')
        self.assertTrue((self.install/'project_components.py').is_file())
        self.assertTrue((self.comfy/'user/default/workflows/AAA_Update_0.5.2-1.44/new.json').is_file())

    def test_existing_updated_template_is_preserved(self):
        p=self.comfy/'user/default/workflows/AAA_Update_0.5.2-1.44/new.json';self.put(p,b'customized-template')
        self.apply();self.assertEqual(p.read_bytes(),b'customized-template')

    def test_code_rollback_restores_old_files_and_removes_only_new_files(self):
        before=self.snapshot();backup=self.apply();updater.rollback(backup,log=lambda _:None,payload=self.payload)
        for rel,data in before.items():self.assertEqual((self.install/rel).read_bytes(),data,rel)
        self.assertFalse((self.plugin/'data/new-default.json').exists())
        self.assertFalse((self.install/'project_components.py').exists())

    def test_rollback_refuses_changed_code(self):
        backup=self.apply();(self.plugin/'main.py').write_bytes(b'user-change-after-upgrade')
        with self.assertRaises(ValueError):updater.rollback(backup,log=lambda _:None,payload=self.payload)
        self.assertEqual((self.plugin/'main.py').read_bytes(),b'user-change-after-upgrade')

    def test_tampered_rollback_target_refused(self):
        backup=self.apply();path=backup/'update-state.json';state=json.loads(path.read_text());state['operations'][0]['target']=str(self.install/'runtime-env.json');path.write_text(json.dumps(state))
        before=(self.install/'runtime-env.json').read_bytes()
        with self.assertRaises(ValueError):updater.rollback(backup,log=lambda _:None,payload=self.payload)
        self.assertEqual((self.install/'runtime-env.json').read_bytes(),before)

    def test_modified_patch_refused_before_backups(self):
        (self.payload/'plugin/main.py').write_bytes(b'TAMPERED=True')
        with self.assertRaises(ValueError):self.apply()
        self.assertFalse((self.install/'aaa_update_backups').exists())

    def test_active_port_refused_before_changes(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));s.listen();self.plan.ports=(s.getsockname()[1],)
            with self.assertRaises(ValueError):self.apply()
        self.assertEqual((self.plugin/'main.py').read_bytes(),b'OLD_PLUGIN=True\n')

    def test_missing_dependency_needs_explicit_network_opt_in(self):
        with patch.object(updater,'probe',return_value=['cryptography']),patch.object(updater.subprocess,'run') as run:
            with self.assertRaises(ValueError):self.apply()
            run.assert_not_called()
        self.assertFalse((self.install/'aaa_update_backups').exists())

    def test_missing_stop_confirmation_prevents_changes(self):
        with self.assertRaises(ValueError):updater.apply(self.plan,payload=self.payload)
        self.assertEqual((self.plugin/'main.py').read_bytes(),b'OLD_PLUGIN=True\n')

    def test_newer_beta_is_not_downgraded(self):
        (self.plugin/'metadata.yaml').write_text('version: 0.5.2-beta.2\n')
        with self.assertRaises(ValueError):self.apply()

    def test_managed_loader_masks_credentials_and_reads_other_profile_ports(self):
        self.put(self.install/'services.local.json',json.dumps([{'name':'Hub','port':16378}]).encode())
        plan=updater.managed(self.install)
        self.assertEqual(plan.plugin_dir,str(self.plugin));self.assertIn(16378,plan.ports)
        self.assertNotIn('fixture-personal-token',json.dumps(updater.asdict(plan)))

    def test_atomic_failure_rolls_back_code(self):
        real=updater.write_atomic;failed=False
        def faulty(path,data,mode=0o644):
            nonlocal failed
            if Path(path)==self.plugin/'main.py' and data==b'NEW_PLUGIN=True\n' and not failed:
                failed=True;raise OSError('simulated copy error')
            return real(path,data,mode)
        with patch.object(updater,'write_atomic',side_effect=faulty),self.assertRaises(OSError):self.apply()
        self.assertEqual((self.plugin/'main.py').read_bytes(),b'OLD_PLUGIN=True\n')
        self.assertEqual((self.hub/'pyproject.toml').read_bytes(),b'version = "0.5.0b2"\n')

    def test_parent_path_escape_refused(self):
        with self.assertRaises(ValueError):updater.safe(self.install/'..'/'other')

    def test_actual_python_probe_and_noneditable_source_guard(self):
        self.assertEqual(self.real_probe(sys.executable,'',[]),[])
        with self.assertRaises(ValueError):self.real_probe(sys.executable,self.hub/'src',[])

    def test_supported_legacy_version_families(self):
        for value in ['0.3.4-beta.3','0.4.0','0.5.0-beta.2','0.5.1-beta.2']:
            with self.subTest(version=value):
                (self.plugin/'metadata.yaml').write_text('version: '+value+'\n')
                state,_=updater.prepare(self.plan,self.payload)
                self.assertEqual(state['old_versions']['plugin'],value)

    def test_weak_old_token_is_not_silently_changed_or_deployed(self):
        p=self.install/'runtime-env.json';env=json.loads(p.read_text());env['AAH_ADMIN_TOKEN']='short';p.write_text(json.dumps(env));before=p.read_bytes()
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(p.read_bytes(),before);self.assertFalse((self.install/'aaa_update_backups').exists())


if __name__=='__main__':unittest.main()
