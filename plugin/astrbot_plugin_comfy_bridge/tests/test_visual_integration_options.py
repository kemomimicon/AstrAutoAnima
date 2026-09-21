import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preset_runtime import parse_generation_directives
from visual_preset_runtime import compile_visual_options, VisualPresetError


class VisualOptionsTests(unittest.TestCase):
    def test_quoted_character_and_visual_directives(self):
        body, options = parse_generation_directives('角色="角色 A" 主光=lighting_golden_hour 主材质=material_silk garden')
        self.assertEqual(body, 'garden')
        self.assertEqual(options['character'], '角色 A')
        compiled = compile_visual_options(options, ROOT / 'data/aaa_anima_lighting_material_presets_v1.json')
        self.assertIn('silk', compiled)
        self.assertNotIn('masterpiece', compiled)

    def test_disabled_catalog_is_not_required(self):
        self.assertEqual(compile_visual_options({}, Path('missing')), '')
        with self.assertRaises(VisualPresetError):
            compile_visual_options({'lighting_key': 'unknown'}, Path('missing'))
