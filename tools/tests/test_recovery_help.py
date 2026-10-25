"""Recovery help stays offline and available before loading an installation."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RecoveryHelpTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse((ROOT / 'tools/first_run_wizard.py').read_text(encoding='utf-8'))
        self.faq = (ROOT / 'docs/TROUBLESHOOTING.md').read_text(encoding='utf-8')

    def test_all_topics_resolve_exactly_once(self):
        assignment = next(n for n in ast.walk(self.tree) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'recovery_topics' for t in n.targets))
        topics = ast.literal_eval(assignment.value)
        self.assertEqual(len(topics), len(set(topics)))
        self.assertGreaterEqual(len(topics), 10)
        for topic in topics:
            with self.subTest(topic=topic):
                self.assertEqual(self.faq.splitlines().count('## ' + topic), 1)

    def test_recovery_does_not_require_session_or_execute_changes(self):
        fn = next(n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == 'recovery')
        calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
        for forbidden in ('session', 'load', 'save', 'work', 'subprocess.Popen', 'webbrowser.open'):
            self.assertNotIn(forbidden, calls)
        self.assertFalse(any(isinstance(n, (ast.Assign, ast.AugAssign)) and
                             'state[' in ast.unparse(n) for n in ast.walk(fn)))

    def test_critical_boundaries_in_faq(self):
        for marker in ('pbkdf2_password', 'jwt_secret', '不要创建空目录', '不公开上传',
                       '普通用户令牌'):
            self.assertIn(marker, self.faq)
        self.assertIn('不需要重新完成首次配置', self.faq)

    def test_distribution_includes_offline_faq(self):
        packager = (ROOT / 'scripts/package_first_run_wizard.py').read_text(encoding='utf-8')
        self.assertIn("(ROOT / 'docs').glob('*.md')", packager)
        self.assertIn("'first_run_wizard.py'", packager)


if __name__ == '__main__':
    unittest.main()
