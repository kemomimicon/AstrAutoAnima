"""The public single-image recipe must never silently re-enable spatial tiling."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SeedVR2ReleaseDefaultsTests(unittest.TestCase):
    def test_native_template_disables_both_vae_tiling_stages(self):
        graph = json.loads((ROOT / 'comfyui/workflows/Anima_SeedVR2_Refine_Beta_api.json').read_text('utf-8'))
        self.assertFalse(any('tiling' in node['class_type'].lower() for node in graph.values()))
        vaes = [node['inputs'] for node in graph.values() if node['class_type'] == 'SeedVR2LoadVAEModel']
        self.assertEqual(len(vaes), 1)
        self.assertIs(vaes[0]['encode_tiled'], False)
        self.assertIs(vaes[0]['decode_tiled'], False)
        native = [node['inputs'] for node in graph.values() if node['class_type'] == 'SeedVR2VideoUpscaler']
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0]['batch_size'], 1)

    def test_registry_uses_only_native_seedvr2_settings(self):
        data = json.loads((ROOT / 'plugin/astrbot_plugin_comfy_bridge/data/workflow_registry.json').read_text('utf-8'))
        entry = next(item for item in data['workflows'] if item['id'] == 'seedvr2_refine_v1')
        self.assertIs(entry['capability']['tile_default'], False)
        enhance = entry['profiles']['seedvr2']['enhance']
        self.assertEqual(set(enhance), {'target_resolution', 'color_correction', 'resolution_target'})
        self.assertEqual(enhance['resolution_target'], 'longest')


if __name__ == '__main__':
    unittest.main()
