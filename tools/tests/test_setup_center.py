import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_center


class SetupCenterTests(unittest.TestCase):
    def test_argv_and_missing_tools(self):
        for name in ('deploy_project', 'first_run_wizard', 'napcat_setup'):
            command = setup_center.tool_command(name, 'windows')
            self.assertEqual(command[0], sys.executable)
            self.assertTrue(Path(command[1]).is_file())
        with self.assertRaises(ValueError): setup_center.tool_command('../unknown')

    def test_headless_plan_and_exit_code_preserved(self):
        with patch.object(setup_center.subprocess, 'call', return_value=7) as call, patch.object(setup_center, 'launch_gui') as gui:
            result = setup_center.main(['--platform', 'linux', '--plan', '/tmp/a b/plan.json', '--apply'])
            self.assertEqual(result, 7)
            self.assertEqual(call.call_args.args[0][-5:], ['--platform', 'linux', '--plan', '/tmp/a b/plan.json', '--apply'])
            gui.assert_not_called()

    def test_entrypoints_use_center(self):
        root = Path(__file__).resolve().parents[2]
        for file in ('Deploy-Linux.sh', 'tools/bootstrap_windows.ps1'):
            self.assertIn('setup_center.py', (root / file).read_text('utf-8-sig'))


if __name__ == '__main__': unittest.main()
