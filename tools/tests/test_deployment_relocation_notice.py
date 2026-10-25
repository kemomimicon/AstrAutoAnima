from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment_support import default_install_directory, relocation_notice
import deploy_project


class DeploymentReminderTests(unittest.TestCase):
    def test_default_is_stable_and_not_relative_to_download(self):
        self.assertEqual(Path(default_install_directory()), Path.home() / 'AstrAutoAnima-install')
        root = Path(__file__).resolve().parents[2]
        text = (root / 'tools/deploy_project.py').read_text('utf-8')
        self.assertIn('default_install_directory()', text)
        self.assertNotIn("str(ROOT.parent / 'AstrAutoAnima-install')", text)

    def test_start_refuses_old_instance_and_incomplete_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'new'; root.mkdir()
            self.assertTrue(relocation_notice(root, [{'name': 'Hub', 'cwd': str(Path(tmp) / 'old/hub')}]))
            self.assertFalse(relocation_notice(root, [{'name': 'Hub', 'cwd': str(root / 'hub')}]))
            (root / '.aaa-migration-incomplete').write_bytes(b'incomplete')
            self.assertTrue(relocation_notice(root, [{'name': 'Hub', 'cwd': str(root / 'hub')}]))

    def test_wrong_root_stops_before_launching_any_service(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'new'; root.mkdir()
            (root / deploy_project.MARKER).write_bytes(b'')
            (root / 'runtime-env.json').write_text('{}', encoding='utf-8')
            (root / 'services.json').write_text(json.dumps([
                {'name': 'ComfyUI', 'cwd': str(root / 'comfy')},
                {'name': 'Hub', 'cwd': str(Path(tmp) / 'old/hub')}]), encoding='utf-8')
            with patch.object(deploy_project.subprocess, 'Popen') as launch:
                results = deploy_project.start_services(root, lambda _: None)
            launch.assert_not_called()
            self.assertIn('停止启动', results[0])


if __name__ == '__main__': unittest.main()
