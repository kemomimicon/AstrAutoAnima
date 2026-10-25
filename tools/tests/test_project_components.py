import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_components import component_catalog, initialize_local_data, prepare_components
from deploy_project import ROOT, json_write


class ProjectComponentsTests(unittest.TestCase):
    def test_same_builtins_in_both_install_modes_no_download(self):
        local, full = (component_catalog(p) for p in ('local', 'full'))
        self.assertEqual([x['id'] for x in local['components']],
                         [x['id'] for x in full['components']])
        self.assertFalse(next(x for x in local['components'] if x['id'] == 'chat_groups')['available'])
        self.assertTrue(next(x for x in full['components'] if x['id'] == 'chat_groups')['available'])
        self.assertFalse(next(x for x in full['components'] if x['id'] == 'chat_groups')['enabled_by_default'])
        self.assertFalse(next(x for x in full['components'] if x['id'] == 'studio_connector')['upstream_installed'])

    def test_prepare_twice_keeps_existing_files_and_does_not_start_programs(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen') as spawn:
            root = Path(directory)
            prepare_components(ROOT, root, 'local', json_write)
            entry = root / 'optional/prompt_importer/importer.py'
            before = (entry.read_bytes(), entry.stat().st_mtime_ns)
            prepare_components(ROOT, root, 'full', json_write)
            self.assertEqual((entry.read_bytes(), entry.stat().st_mtime_ns), before)
            self.assertTrue((root / 'components.local.json').is_file())
            self.assertTrue((root / 'components.full.json').is_file())
            spawn.assert_not_called()

    def test_custom_helper_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'optional/prompt_importer/importer.py'
            entry.parent.mkdir(parents=True)
            entry.write_text('# user helper', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '人工核对'):
                prepare_components(ROOT, root, 'full', json_write)
            self.assertEqual(entry.read_text(), '# user helper')

    def test_local_empty_library_initialized_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_local_data(root, json_write)
            presets = root / 'data/local/presets.json'
            self.assertEqual(json.loads(presets.read_text()), {'characters': {}, 'styles': {}})
            presets.write_text('{"characters":{"mine":{}},"styles":{}}', encoding='utf-8')
            initialize_local_data(root, json_write)
            self.assertIn('mine', json.loads(presets.read_text())['characters'])


if __name__ == '__main__':
    unittest.main()
