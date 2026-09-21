import copy
import hashlib
import json
import unittest
import zipfile
from pathlib import Path
from astrbot_plugin_comfy_bridge.prompt_pool_runtime import _merge_prompt_pools

ROOT = Path(__file__).resolve().parents[2]


class GenerateMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'deliverables/catalog_260910_integration/prompt_pool.before_260910.json').is_file():
            raise unittest.SkipTest('Private migration fixtures are not distributed')
        # Freeze the G-only release baseline; newer catalogs also update D.
        cls.new = json.loads((ROOT/'deliverables/catalog_260910_integration/prompt_pool.before_260910.json').read_text(encoding='utf-8'))
        with zipfile.ZipFile(ROOT/'releases/astrbot_plugin_comfy_bridge-0.3.7-beta.1.zip') as archive:
            name = next(n for n in archive.namelist() if n.replace('\\', '/').endswith('data/anima_random_prompt_pool.json'))
            cls.old = json.loads(archive.read(name))

    def test_release_baseline_migration(self):
        merged = _merge_prompt_pools(self.old, self.new)
        self.assertEqual(sum(p.get('source_code') == 'G' for p in merged['prompts']), 4000)
        self.assertEqual([p for p in merged['prompts'] if p.get('source_code') != 'G'], [p for p in self.old['prompts'] if p.get('source_code') != 'G'])

    def test_edits_custom_and_deletions_survive(self):
        old = copy.deepcopy(self.old)
        entry = next(p for p in old['prompts'] if p.get('source_code') == 'G')
        entry['prompt'] = 'administrator edited this record'
        old['prompts'].append({'id': 'custom-G', 'source_code': 'G', 'prompt': 'custom'})
        old['deleted_prompt_ids'] = ['G-001A']
        merged = _merge_prompt_pools(old, self.new)
        by_id = {p['id']: p for p in merged['prompts']}
        self.assertEqual(by_id[entry['id']]['prompt'], entry['prompt'])
        self.assertIn('custom-G', by_id)
        self.assertNotIn('G-001A', by_id)
        self.assertEqual(_merge_prompt_pools(merged, self.new)['prompts'], merged['prompts'])

    def test_input_not_modified_and_g_unique(self):
        source = ROOT/'outputs/complete_prompt_library_json_20260909/anima_random_prompt_pool260909.json'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), 'fd43f401c1833fefe0ec3df09f7e9b8d6c03890fbddc51803d48bc3cea703d38')
        rows = [p for p in self.new['prompts'] if p.get('source_code') == 'G']
        self.assertEqual(len(rows), 4000)
        self.assertEqual(len({p['id'] for p in rows}), 4000)
