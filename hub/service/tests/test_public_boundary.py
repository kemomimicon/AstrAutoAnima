import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub import service_recovery


class PublicBoundaryTests(unittest.TestCase):
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
