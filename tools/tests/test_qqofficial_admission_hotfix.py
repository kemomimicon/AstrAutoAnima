import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apply_qqofficial_admission_hotfix import digest, install


class QQOfficialAdmissionHotfixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / '补丁 解压目录'
        self.plugin = self.root / '安装 目录/astrbot/data/plugins/astrbot_plugin_comfy_bridge'
        self.plugin.mkdir(parents=True)
        (self.bundle / 'plugin_files').mkdir(parents=True)
        self.old = b'VALUE = "before"\r\n'
        self.new = b'VALUE = "after"\n'
        (self.plugin / 'platform_switchboard.py').write_bytes(self.old)
        (self.plugin / 'main.py').write_bytes(b'# existing plugin')
        (self.plugin / 'metadata.yaml').write_bytes(b'version: 0.5.2-beta.1')
        (self.bundle / 'plugin_files/platform_switchboard.py').write_bytes(self.new)
        (self.bundle / 'patch-manifest.json').write_text(json.dumps({
            'original_sha256': digest(self.old), 'replacement_sha256': digest(self.new)}), encoding='utf-8')
        self.private = self.plugin.parent.parent / 'plugin_data/astrbot_plugin_comfy_bridge'
        self.private.mkdir(parents=True)
        self.data = {'pool.json': b'{"prompts":[]}', 'keys.json': b'{"key":"fixture-only"}'}
        for name, content in self.data.items():
            (self.private / name).write_bytes(content)

    def test_actual_apply_backups_data_preservation_and_idempotence(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertIn('预检通过', install(self.plugin.parents[3], self.bundle))
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        result = install(self.plugin, self.bundle, apply=True, confirmed=True)
        self.assertIn('更新完成', result)
        backups = list((self.plugin.parent.parent / 'aaa_patch_backups').glob('*/platform_switchboard.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertEqual((self.plugin / 'platform_switchboard.py').read_bytes(), self.new)
        for name, content in self.data.items():
            self.assertEqual((self.private / name).read_bytes(), content)
        self.assertIn('已安装', install(self.plugin, self.bundle, apply=True, confirmed=True))
        self.assertEqual(len(list(backups[0].parent.parent.iterdir())), 1)

    def test_modified_user_code_is_not_overwritten(self):
        content = self.old + b'# user edit\r\n'
        (self.plugin / 'platform_switchboard.py').write_bytes(content)
        with self.assertRaisesRegex(ValueError, '基线不同'):
            install(self.plugin, self.bundle, apply=True, confirmed=True)
        self.assertEqual((self.plugin / 'platform_switchboard.py').read_bytes(), content)
        self.assertFalse((self.plugin.parent.parent / 'aaa_patch_backups').exists())

    def test_tampered_payload_and_no_stop_confirmation_do_not_write(self):
        with self.assertRaisesRegex(ValueError, '服务已停止'):
            install(self.plugin, self.bundle, apply=True)
        (self.bundle / 'plugin_files/platform_switchboard.py').write_bytes(b'# tampered')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            install(self.plugin, self.bundle, apply=True, confirmed=True)
        self.assertEqual((self.plugin / 'platform_switchboard.py').read_bytes(), self.old)
        self.assertFalse((self.plugin.parent.parent / 'aaa_patch_backups').exists())

    def test_atomic_replace_failure_leaves_original_and_verified_backup(self):
        with patch('apply_qqofficial_admission_hotfix.os.replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                install(self.plugin, self.bundle, apply=True, confirmed=True)
        self.assertEqual((self.plugin / 'platform_switchboard.py').read_bytes(), self.old)
        backups = list((self.plugin.parent.parent / 'aaa_patch_backups').glob('*/platform_switchboard.py'))
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertEqual(list(self.plugin.glob('.qqofficial-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
