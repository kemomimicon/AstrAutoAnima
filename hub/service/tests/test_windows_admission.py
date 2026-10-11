import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings


class WindowsAdmissionTests(unittest.TestCase):
    def test_windows_post_is_not_blocked_by_copied_linux_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            data = root / "data"
            data.mkdir()
            (data / "idle_shutdown.lock").touch()
            (data / "idle_shutdown_gate.json").write_text('{"blocked":true}', "utf-8")
            settings = Settings(plugin_data_dir=data, plugin_dir=root / "plugin", comfyui_root=root / "comfy")
            with patch.object(sys, "platform", "win32"):
                client = TestClient(create_app(settings))
                try:
                    # A nonexistent route must reach routing (404), not idle middleware (503).
                    self.assertEqual(client.post("/compat-nonexistent").status_code, 404)
                    # Authentication is still required; the fix is not an auth bypass.
                    self.assertEqual(client.post("/api/v1/admin/services/restart?confirmed=true").status_code, 401)
                finally:
                    client.close()
