import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy_project import Plan, configured_anima_workflow, configure, prepare_comfy_source

ROOT = Path(__file__).resolve().parents[2]


class AcceptanceInstallFixTests(unittest.TestCase):
    def test_selected_models_generate_complete_hq_and_refine_without_placeholder_loras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flows = root / 'comfy/user/default/workflows'
            shutil.copytree(ROOT / 'comfyui/workflows', flows)
            quick = {n: {'inputs': {key: name}} for n, key, name in (
                ('1', 'unet_name', 'my-model.safetensors'), ('2', 'clip_name', 'my-clip.safetensors'),
                ('3', 'vae_name', 'my-vae.safetensors'))}
            (flows / 'AAA_Quick_Local_api.json').write_text(json.dumps(quick), encoding='utf-8')
            configure(Plan(str(root)), root, root / 'astro', root / 'comfy')
            config_path = root / 'astro/data/config/astrbot_plugin_comfy_bridge_config.json'
            config = json.loads(config_path.read_text('utf-8'))
            for key in ('hq_workflow_path', 'refine_workflow_path'):
                path = Path(config[key]); graph = json.loads(path.read_text('utf-8'))
                self.assertEqual(graph['44']['inputs']['unet_name'], 'my-model.safetensors')
                self.assertFalse(any(n['class_type'] == 'LoraLoader' for n in graph.values()))
                for node in graph.values():
                    for value in node['inputs'].values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                            self.assertIn(value[0], graph)
                path.write_text('{"my":"customized"}', encoding='utf-8')
            before = config_path.read_bytes()
            configure(Plan(str(root)), root, root / 'astro', root / 'comfy')
            self.assertEqual(config_path.read_bytes(), before)
            self.assertEqual(json.loads(Path(config['hq_workflow_path']).read_text()), {'my': 'customized'})

    def test_real_lora_is_kept_and_templates_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            flows = Path(directory)
            graph = json.loads((ROOT / 'comfyui/workflows/Anima_HQ_Txt2Img_Beta_api.json').read_text('utf-8'))
            graph['46']['inputs']['lora_name'] = 'styles/my-style.safetensors'
            source = flows / 'template.json'; source.write_text(json.dumps(graph), encoding='utf-8')
            original = source.read_bytes()
            quick = {n: {'inputs': {k: 'selected'}} for n, k in (('1','unet_name'),('2','clip_name'),('3','vae_name'))}
            path = configured_anima_workflow(flows, quick, source.name, 'configured.json')
            result = json.loads(path.read_text('utf-8'))
            self.assertEqual(result['46']['inputs']['lora_name'], 'styles/my-style.safetensors')
            self.assertEqual(source.read_bytes(), original)

    def test_clone_failure_uses_verified_archive_and_preserves_partial_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); comfy = root / 'ComfyUI'; comfy.mkdir()
            (comfy / 'partial.txt').write_text('preserve', encoding='utf-8')
            def download(url, target, log, **kwargs):
                self.assertEqual(kwargs['expected_sha256'], '85ed01bf9c737c42f5e36b6935c872fb1a1691041914ebe632c653ef5430b071')
                target.parent.mkdir(parents=True)
                with zipfile.ZipFile(target, 'w') as z:
                    z.writestr('ComfyUI-0.21.1/main.py', '# source')
                    z.writestr('ComfyUI-0.21.1/requirements.txt', '')
            with patch('deploy_project.run', side_effect=ValueError('clone failed')), patch('easy_installer.download_file', side_effect=download):
                prepare_comfy_source(comfy, root, Plan(str(root)), lambda _: None)
            self.assertTrue((comfy / 'main.py').is_file())
            backups = list(root.glob('ComfyUI.clone-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'partial.txt').read_text(), 'preserve')

    def test_wd_only_template_has_no_unavailable_caption_nodes(self):
        graph = json.loads((ROOT / 'comfyui/workflows/Anima_WD_Only_Reverse_api.json').read_text('utf-8'))
        self.assertEqual(len(graph), 5)
        for field in ('ct_tags', 'ct_general', 'ct_rating', 'ct_character', 'joy_caption'):
            self.assertEqual(graph['7']['inputs'][field], '')


if __name__ == '__main__':
    unittest.main()
