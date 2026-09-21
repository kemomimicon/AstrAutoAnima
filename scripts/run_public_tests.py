"""Run tests with an isolated current directory so fallback runtime state is never packaged."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'plugin'), str(ROOT / 'hub/service/src'), str(ROOT / 'tools')]
SUITES = {'tools': ROOT / 'tools/tests', 'plugin': ROOT / 'plugin/astrbot_plugin_comfy_bridge/tests',
          'hub': ROOT / 'hub/service/tests'}
if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'tools'
    use_pytest = '--pytest' in sys.argv
    sys.path.insert(0, str(SUITES[name]))
    tests = None if use_pytest else unittest.defaultTestLoader.discover(str(SUITES[name]))
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='aaa-public-tests-') as directory:
        try:
            os.chdir(directory)
            if use_pytest:
                import pytest
                code = pytest.main([str(SUITES[name]), '--rootdir', str(ROOT), '--confcutdir', str(ROOT),
                                    '-q', '-p', 'no:cacheprovider',
                                    '--basetemp', str(Path(directory) / 'pytest')])
            else:
                result = unittest.TextTestRunner(verbosity=1).run(tests)
                code = int(not result.wasSuccessful())
        finally:
            os.chdir(previous)
    raise SystemExit(code)
