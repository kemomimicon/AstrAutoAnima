import copy
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_comfy_bridge.prompt_pool_runtime import _merge_prompt_pools, ensure_prompt_pool, load_prompt_pool
from astrbot_plugin_comfy_bridge.visual_preset_runtime import VisualPresetCatalog, VisualPresetError, load_visual_catalog

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'astrbot_plugin_comfy_bridge/data'


class CatalogMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'deliverables/catalog_260910_integration/prompt_pool.before_260910.json').is_file():
            raise unittest.SkipTest('Private migration snapshot is not distributed')
        cls.old = json.loads((ROOT / 'deliverables/catalog_260910_integration/prompt_pool.before_260910.json').read_text(encoding='utf-8'))
        cls.new = load_prompt_pool(DATA / 'anima_random_prompt_pool.json')

    def test_exact_old_defaults_upgrade(self):
        result = _merge_prompt_pools(self.old, self.new)
        self.assertEqual({r['id']:r for r in result['prompts']}, {r['id']:r for r in self.new['prompts']})
        self.assertEqual(len(result['prompts']), 23063)
        self.assertEqual(sum(r.get('enabled', True) for r in result['prompts']), 22495)

    def test_edits_disabled_deleted_and_favorites_survive(self):
        old = copy.deepcopy(self.old)
        rows = [r for r in old['prompts'] if r['source_code'] == 'D']
        rows[0]['prompt'] = 'administrator changed prompt'
        rows[1]['enabled'] = False
        favorite = {'id':'liked-test', 'source_code':'P', 'prompt':'personal', 'liked_by':'user1'}
        old['prompts'].append(favorite)
        old['deleted_prompt_ids'] = [rows[2]['id']]
        result = _merge_prompt_pools(old, self.new)
        idx = {r['id']:r for r in result['prompts']}
        self.assertEqual(idx[rows[0]['id']], rows[0])
        self.assertFalse(idx[rows[1]['id']]['enabled'])
        self.assertNotIn(rows[2]['id'], idx)
        self.assertEqual(idx['liked-test'], favorite)
        self.assertEqual(_merge_prompt_pools(result, self.new)['prompts'], result['prompts'])

    def test_persistent_upgrade_backed_up_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pool.json'
            path.write_text(json.dumps(self.old), encoding='utf-8')
            ensure_prompt_pool(path, DATA / 'anima_random_prompt_pool.json')
            ensure_prompt_pool(path, DATA / 'anima_random_prompt_pool.json')
            self.assertEqual(len(list(path.parent.glob('*.pre-catalog-*'))), 1)
            self.assertEqual(load_prompt_pool(path)['catalog_revision'], 2026091006)


class VisualCatalogTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((DATA / 'aaa_anima_lighting_material_presets_v1.json').read_text(encoding='utf-8-sig'))
        self.catalog = VisualPresetCatalog(self.data)

    def test_original_asset_unchanged(self):
        self.assertIsNotNone(load_visual_catalog(DATA / 'aaa_anima_lighting_material_presets_v1.json')[0])

    def test_compile_and_off(self):
        original = copy.deepcopy(self.data)
        light = self.catalog.compile_lighting('lighting_golden_hour', 'lighting_volumetric')
        self.assertTrue(light.startswith('golden hour,'))
        self.assertIn('volumetric lighting', light)
        material = self.catalog.compile_material('material_silk', ['material_lace'], 'material_wet_surface')
        self.assertTrue(material.startswith('silk fabric,'))
        self.assertIn('wet surface', material)
        self.assertEqual(self.catalog.compile_lighting(), '')
        self.assertEqual(self.catalog.compile_material(), '')
        self.assertEqual(self.data, original)
        self.assertNotIn('masterpiece', light + material)

    def test_conflicts_roles_and_limits(self):
        with self.assertRaises(VisualPresetError):
            self.catalog.compile_lighting('lighting_high_key', 'lighting_rim_strong')
        with self.assertRaises(VisualPresetError):
            self.catalog.compile_lighting('lighting_volumetric')
        with self.assertRaises(VisualPresetError):
            self.catalog.compile_material('material_silk', ['material_lace'] * 3)
        with self.assertRaises(VisualPresetError):
            self.catalog.compile_material('not_a_preset')

    def test_bad_catalog_degrades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            self.assertIsNone(load_visual_catalog(path)[0])
            path.write_text('{broken', encoding='utf-8')
            self.assertIsNone(load_visual_catalog(path)[0])
            path.write_text('{}', encoding='utf-8')
            self.assertTrue(load_visual_catalog(path)[1])


if __name__ == '__main__':
    unittest.main()
