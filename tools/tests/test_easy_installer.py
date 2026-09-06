from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from easy_installer import InstallPlan, execute_plan, load_optional_components  # noqa: E402


class EasyInstallerTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Path:
        repo = root / "release"
        (repo / "tools").mkdir(parents=True)
        (repo / ".astr_auto_anima_public_root").touch()
        (repo / "tools/optional_components.json").write_text(
            json.dumps({"schema_version": 1, "components": []}),
            encoding="utf-8",
        )
        return repo

    def test_dry_run_does_not_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            astrbot_data = root / "astrbot/data"
            comfyui = root / "ComfyUI"
            astrbot_data.mkdir(parents=True)
            comfyui.mkdir()
            messages: list[str] = []
            backup = execute_plan(
                InstallPlan(
                    repo_root=repo,
                    astrbot_data=astrbot_data,
                    comfyui_root=comfyui,
                    hub_home=root / "hub",
                    components=set(),
                    apply=False,
                ),
                messages.append,
            )
            self.assertFalse(backup.exists())
            self.assertTrue(any("预检模式" in line for line in messages))

    def test_optional_manifest_is_local_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            self.assertEqual(load_optional_components(repo), [])


if __name__ == "__main__":
    unittest.main()
