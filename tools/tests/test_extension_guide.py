import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extension_guide as guide
ROOT = Path(__file__).resolve().parents[2]


class ExtensionGuideTests(unittest.TestCase):
    def test_all_sections_exactly_match_catalog_and_faq_search(self):
        items = guide.load_catalog()
        sections = guide.read_sections(ROOT / 'docs/EXTENSIONS_GUIDE.md')
        self.assertEqual({i['id'] for i in items}, {s['id'] for s in sections})
        self.assertEqual(len(items), 24)
        for section in sections: self.assertGreater(len(section['body']), 180)
        questions = guide.read_sections(ROOT / 'docs/SETUP_QA.md')
        self.assertGreaterEqual(len(questions), 40)
        self.assertTrue(guide.filter_records(questions, '401'))
        self.assertTrue(guide.filter_records(questions, 'model.onnx.data'))
        self.assertEqual(guide.filter_records(questions, 'impossible_fixture_word'), [])

    def test_component_ids_and_manifest_preview_readonly(self):
        for item in guide.load_catalog():
            if item['action'] == 'deploy':
                selected = guide.component_selection(item['id'], ROOT)
                self.assertTrue(selected)
                if not (ROOT / 'tools/deploy_project.py').is_file():
                    self.assertIn('不包含完整部署器', guide.preview_plan(item, ROOT))
                    with self.assertRaises(ValueError): guide.action_command(item, ROOT)
                    continue
                self.assertIn('仅预览', guide.preview_plan(item, ROOT))
                command = guide.action_command(item, ROOT)
                self.assertEqual(command[-2:], ['--extension', item['id']])
                self.assertNotIn('--apply', command)

    def test_seedvr2_downloads_never_select_tiling(self):
        known = json.loads((ROOT / 'tools/optional_components.json').read_text('utf-8'))['components']
        self.assertNotIn('seedvr2_tiling_node', {i['id'] for i in known})
        for identifier in ('refine', 'refine_low', 'refine_balanced'):
            selected = guide.component_selection(identifier, ROOT)
            self.assertIn('seedvr2_node', {i['id'] for i in selected})
            self.assertFalse(any('tiling' in i['id'].lower() for i in selected))

    def test_missing_deployer_never_uses_frozen_exe_as_python(self):
        item = next(i for i in guide.load_catalog() if i['id'] == 'reverse_wd')
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn('不包含完整部署器', guide.preview_plan(item, Path(tmp)))
            with patch.object(sys, 'frozen', True, create=True), self.assertRaisesRegex(ValueError, '完整懒人包'):
                guide.action_command(item, Path(tmp))
        with patch.object(sys, 'frozen', True, create=True):
            with self.assertRaises(ValueError): guide.action_command(item, ROOT)

    def test_unknown_actions_and_components_rejected(self):
        data = {'schema_version': 1, 'items': guide.load_catalog()}
        data['items'][0]['action'] = 'shell'
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'catalog.json'; file.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError): guide.load_catalog(file)
        with self.assertRaises(ValueError): guide.component_selection('../bad', ROOT)

    def test_frozen_actions_use_flags_and_no_arbitrary_command(self):
        with patch.object(sys, 'frozen', True, create=True):
            for item in guide.load_catalog(ROOT / 'tools/extension_catalog.json'):
                if item['action'] in guide.TOOL_ACTIONS:
                    command = guide.action_command(item, ROOT)
                    self.assertEqual(command[0], sys.executable)
                    self.assertNotIn('shell', command)
            item = next(i for i in guide.load_catalog(ROOT / 'tools/extension_catalog.json') if i['id'] == 'studio')
            with self.assertRaises(ValueError): guide.action_command(item, ROOT)

    def test_probe_requires_consent_no_auth_and_only_health_schema(self):
        with patch.object(guide, 'request_json') as request:
            with self.assertRaises(ValueError): guide.inspect_hub('http://127.0.0.1:6278')
            request.assert_not_called()
        fixture = [{'service':'astr-auto-anima-hub', 'version':'0.5.2-beta.1', 'execution_mode':'local'},
                   {'paths': {'/api/v1/prompts/groups': {'get': {}, 'put': {}}, '/api/v1/prompts/import': {'post': {}}}}]
        with patch.object(guide, 'request_json', side_effect=fixture) as request:
            state = guide.inspect_hub('http://127.0.0.1:6278', consent=True)
            self.assertEqual(state['mode'], 'local')
            self.assertEqual([c.args[1] for c in request.call_args_list], ['/api/v1/health', '/openapi.json'])
            self.assertTrue(all(len(c.args) == 2 for c in request.call_args_list))
            item = next(i for i in guide.load_catalog() if i['id'] == 'online_pool')
            self.assertIn('尚未验证', guide.capability_text(item, state))

    def test_openapi_unavailable_is_unknown_not_supported(self):
        with patch.object(guide, 'request_json', side_effect=[{'service':'astr-auto-anima-hub', 'version':'0.5.0b2'}, ValueError('fixture')]):
            state = guide.inspect_hub('http://127.0.0.1:6278', consent=True)
            self.assertFalse(state['schema_known']); self.assertEqual(state['mode'], '未提供')
            item = next(i for i in guide.load_catalog() if i['id'] == 'online_pool')
            self.assertIn('未知', guide.capability_text(item, state))
        with patch.object(guide, 'request_json', return_value={'service':'other'}), self.assertRaises(ValueError):
            guide.inspect_hub('http://127.0.0.1:6278', consent=True)

    def test_remote_http_is_rejected_before_request(self):
        with patch.object(guide, 'request_json') as request:
            with self.assertRaises(ValueError): guide.inspect_hub('http://192.168.0.2:6278', consent=True)
            request.assert_not_called()


if __name__ == '__main__': unittest.main()
