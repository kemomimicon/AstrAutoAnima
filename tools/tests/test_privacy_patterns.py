import importlib.util
from pathlib import Path
import unittest


class PrivacyPatternTests(unittest.TestCase):
    def pattern(self):
        source = Path(__file__).resolve().parents[2]/'scripts/privacy_scan.py'
        spec = importlib.util.spec_from_file_location('aaa_public_privacy', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.TEXT_PATTERNS['generic API secret']

    def test_blank_env_value_does_not_capture_next_setting(self):
        self.assertIsNone(self.pattern().search('AAH_LOCAL_LLM_API_KEY=\nAAH_LOCAL_LLM_GUIDE_PATH=\n'))

    def test_nonempty_secret_still_detected(self):
        for spacing in ('=', ' = ', '\t=\t'):
            with self.subTest(spacing=spacing):
                self.assertIsNotNone(self.pattern().search('API_KEY'+spacing+'"'+('z'*32)+'"'))
