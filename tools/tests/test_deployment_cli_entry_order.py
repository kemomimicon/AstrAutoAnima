"""Guard real script evaluation order, not only import-time function availability."""
import ast
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import json
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / 'tools/deploy_project.py'


def probe_entry_order(text):
    tree = ast.parse(text)
    entry = [n for n in tree.body if isinstance(n, ast.If)
             and ast.unparse(n.test) == "__name__ == '__main__'"]
    if len(entry) != 1:
        raise AssertionError('Expected one main entry')
    # Preserve the actual top-level order and definitions. Only main's body is
    # replaced so this test cannot install, download, start services or use GPU.
    probe = ast.parse('''def main():
    assert callable(local_hq_workflow)
    assert callable(configure_local)
''').body[0]
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                nodes.append(probe)
            elif isinstance(node, ast.FunctionDef) and node.name in ('local_hq_workflow', 'configure_local'):
                nodes.append(node)
        elif node is entry[0]:
            nodes.append(node)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    with contextlib.redirect_stderr(io.StringIO()):
        exec(compile(module, str(DEPLOY), 'exec'), {'__name__': '__main__', 'sys': sys})


class DeploymentCLIEntryTests(unittest.TestCase):
    def test_all_definitions_precede_real_cli_entry(self):
        text = DEPLOY.read_text('utf-8-sig')
        tree = ast.parse(text)
        self.assertIsInstance(tree.body[-1], ast.If)
        self.assertEqual(ast.unparse(tree.body[-1].test), "__name__ == '__main__'")
        probe_entry_order(text)

    def test_probe_rejects_original_build44_order(self):
        text = DEPLOY.read_text('utf-8-sig')
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)
        helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('local_hq_workflow', 'configure_local')]
        chunks = [''.join(lines[n.lineno-1:n.end_lineno]) for n in helpers]
        for chunk in chunks:
            text = text.replace(chunk, '')
        broken = text.rstrip() + '\n\n' + '\n\n'.join(chunks) + '\n'
        with self.assertRaises(SystemExit) as result:
            probe_entry_order(broken)
        self.assertEqual(result.exception.code, 1)

    def test_direct_script_help_is_successful(self):
        result = subprocess.run([sys.executable, '-B', str(DEPLOY), '--help'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--plan', result.stdout)

    def test_direct_script_preflight_has_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / 'plan.json'
            destination = root / 'install'
            plan.write_text(json.dumps({'destination': str(destination), 'platform': 'auto',
                'deployment_profile': 'full', 'astrbot_mode': 'cli',
                'install_astrbot': True, 'install_comfyui': True,
                'install_dependencies': True}), encoding='utf-8')
            before = plan.read_bytes()
            result = subprocess.run([sys.executable, '-B', str(DEPLOY), '--plan', str(plan)],
                                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('追加 --apply', result.stdout)
            self.assertFalse(destination.exists())
            self.assertEqual(plan.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
