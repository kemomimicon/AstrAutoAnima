import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy_project import Plan, validate, configure, quick_workflow, checked_root, start_services, MARKER, deploy, python_at


class DeploymentTests(unittest.TestCase):
    def test_downloads_require_explicit_dependency_consent(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, '允许安装依赖'):
                validate(Plan(str(Path(t) / 'new'), install_astrbot=True))

    def test_nonempty_unmanaged_directory_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'user-data').touch()
            with self.assertRaisesRegex(ValueError, '非空'):
                checked_root(t)

    def test_generated_paths_credentials_and_existing_settings(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            plan = Plan(t, api_key='test-credential', bot_id='demo')
            astro, comfy = root / 'astro', root / 'comfy'
            env = configure(plan, root, astro, comfy)
            self.assertEqual(env['AAH_ASTRBOT_API_KEY'], 'test-credential')
            self.assertGreaterEqual(len(env['AAH_ADMIN_TOKEN']), 32)
            saved = configure(Plan(t), root, astro, comfy)
            self.assertEqual(saved, env)
            cfg = json.loads((astro / 'data/config/astrbot_plugin_comfy_bridge_config.json').read_text('utf-8'))
            self.assertEqual(cfg['style_lora_node_ids'], '')
            self.assertIn('job_store_path', cfg)
            schema = json.loads((Path(__file__).resolve().parents[2] / 'plugin/astrbot_plugin_comfy_bridge/_conf_schema.json').read_text('utf-8'))
            self.assertTrue(set(cfg).issubset(schema), set(cfg) - set(schema))

    def test_quick_graph_only_contains_user_models(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            paths = []
            for name in ('unet', 'clip', 'vae'):
                p = root / (name + '.safetensors')
                p.write_bytes(b'unit-test-only')
                paths.append(str(p))
            graph = quick_workflow(Plan(t, unet=paths[0], clip=paths[1], vae=paths[2]), root / 'comfy', lambda _: None)
            self.assertEqual(graph['19']['inputs']['positive'], ['11', 0])
            self.assertFalse(any(n['class_type'] == 'LoraLoader' for n in graph.values()))
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value, list):
                        self.assertIn(value[0], graph)

    def test_existing_port_never_starts_duplicate(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / MARKER).touch()
            (root / 'runtime-env.json').write_text('{}')
            (root / 'services.json').write_text(json.dumps([{'name': 'Hub', 'port': 6278, 'health': 'http://127.0.0.1:6278/api/v1/health'}]))
            with patch('deploy_project.port_open', return_value=True), patch('deploy_project.health', return_value={'service': 'other'}), patch('subprocess.Popen') as spawn:
                result = start_services(root, lambda _: None)
                spawn.assert_not_called()
                self.assertIn('占用', result[0])

    def test_missing_models_stays_unconfigured(self):
        self.assertIsNone(quick_workflow(Plan('unused'), Path('unused'), lambda _: None))

    def test_new_astrbot_init_is_noninteractive_and_cwd_exists(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'install'
            calls = []
            def fake_run(command, log, cwd=None):
                if 'init' in command:
                    self.assertIn('--yes', command)
                    self.assertTrue(Path(cwd).is_dir())
                    calls.append(command)
                if 'clone' in command:
                    Path(command[-1]).mkdir(parents=True, exist_ok=True)
                    (Path(command[-1]) / 'main.py').write_text('# fixture')
            plan = Plan(str(root), install_astrbot=True, install_comfyui=True, install_dependencies=True)
            with (patch('deploy_project.sys.version_info', (3, 12)),
                  patch('deploy_project.shutil.which', return_value='git'),
                  patch('deploy_project.make_env', side_effect=lambda path, log: python_at(path)),
                  patch('deploy_project.port_open', return_value=False),
                  patch('deploy_project.run', side_effect=fake_run),
                  patch('deploy_project.start_services', return_value=[])):
                deploy(plan, lambda _: None)
            self.assertEqual(len(calls), 1)

    def test_full_offline_file_deployment_is_repeatable_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            root, astro, comfy = base / 'install', base / 'astro', base / 'comfy'
            (astro / 'data/config').mkdir(parents=True)
            comfy.mkdir()
            (comfy / 'main.py').write_text('# fixture')
            for environment in (astro, comfy):
                runtime = python_at(environment / '.venv')
                runtime.parent.mkdir(parents=True)
                runtime.touch()
            import os
            (python_at(astro / '.venv').parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')).touch()
            python = python_at(root / 'hub/.venv')
            python.parent.mkdir(parents=True)
            python.touch()
            (root / MARKER).touch()
            cfg_path = astro / 'data/config/astrbot_plugin_comfy_bridge_config.json'
            cfg_path.write_text(json.dumps({'workflow_path': 'keep-my-workflow.json', 'default_width': 768}))
            user_data = astro / 'data/plugin_data/astrbot_plugin_comfy_bridge'
            user_data.mkdir(parents=True)
            pool = user_data / 'anima_random_prompt_pool.json'
            pool.write_text('{"prompts": [{"id": "mine"}]}')
            plan = Plan(str(root), astrbot=str(astro), comfyui=str(comfy))
            with (patch('deploy_project.port_open', return_value=False), patch('deploy_project.run') as run,
                  patch('deploy_project.start_services', return_value=[])):
                deploy(plan, lambda _: None)
                token = json.loads((root / 'runtime-env.json').read_text())['AAH_ADMIN_TOKEN']
                deploy(plan, lambda _: None)
                run.assert_not_called()
            self.assertEqual(json.loads((root / 'runtime-env.json').read_text())['AAH_ADMIN_TOKEN'], token)
            self.assertEqual(json.loads(cfg_path.read_text())['workflow_path'], 'keep-my-workflow.json')
            self.assertEqual(json.loads(pool.read_text())['prompts'][0]['id'], 'mine')
            self.assertFalse((root / '.deploy.lock').exists())
            self.assertTrue((root / 'deploy_project.py').is_file())
