import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_comfy_bridge.prompt_group_policy import private_group_denial


class PromptGroupPolicyTests(unittest.TestCase):
    def test_private_permission_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prompt_groups.json"
            self.assertIsNotNone(private_group_denial(path, ["unknown"]))
            self.assertIsNone(private_group_denial(path, []))
            path.write_text(json.dumps({"groups": [
                {"id": "public", "allow_private": True},
                {"id": "closed", "allow_private": False},
            ]}), encoding="utf-8")
            self.assertIsNone(private_group_denial(path, ["public"]))
            self.assertIsNotNone(private_group_denial(path, ["closed"]))
            self.assertIsNotNone(private_group_denial(path, ["unregistered"]))


if __name__ == "__main__":
    unittest.main()
