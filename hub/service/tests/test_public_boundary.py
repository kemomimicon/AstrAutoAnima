import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub import service_recovery


class PublicBoundaryTests(unittest.TestCase):
    def test_construct_app_does_not_write_to_configured_data_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'not-created'
            with patch.object(Path, 'mkdir', side_effect=AssertionError('eager write')):
                create_app(Settings(plugin_data_dir=root))
            self.assertFalse(root.exists())

    def test_defaults_do_not_require_server_root_permissions(self):
        import os
        with patch.dict(os.environ, {}, clear=True):
            for settings in (Settings(), Settings.from_env()):
                self.assertFalse(settings.plugin_dir.is_absolute())
                self.assertFalse(settings.plugin_data_dir.is_absolute())
                self.assertFalse(settings.comfyui_root.is_absolute())

    def test_no_training_extension_routes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        app = create_app(Settings(admin_token='test-' + 'x' * 40, plugin_dir=root / 'plugin',
                                  plugin_data_dir=root / 'data', comfyui_root=root / 'comfy'))
        routes = [getattr(route, 'path', '') for route in app.routes]
        self.assertFalse(any('/extensions/' in route or 'auto-sleep' in route for route in routes))
        self.assertFalse(hasattr(app.state, 'extension_host'))

    def test_no_private_recovery_commands(self):
        with patch('subprocess.Popen') as spawn:
            with self.assertRaises(ValueError):
                service_recovery.submit('.', 'test')
            spawn.assert_not_called()
