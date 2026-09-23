"""Start the real Hub on loopback, preserving simulated existing deployment settings."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from deploy_project import Plan, configure


def main():
    with tempfile.TemporaryDirectory(prefix='aaa-hub-upgrade-') as temporary:
        root = Path(temporary)
        astro, comfy = root / 'astro', root / 'comfy'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = secrets.token_urlsafe(48)
        env_path = root / 'runtime-env.json'
        env_path.write_text(json.dumps({'AAH_ADMIN_TOKEN': token, 'AAH_PORT': str(port)}), encoding='utf-8')
        settings = configure(Plan(str(root)), root, astro, comfy)
        self_saved = configure(Plan(str(root)), root, astro, comfy)
        assert self_saved == settings and settings['AAH_ADMIN_TOKEN'] == token
        # Isolated current directory and explicit paths; never inherit production AAH settings.
        env = {k: v for k, v in os.environ.items() if not k.startswith('AAH_')}
        env.update(settings, PYTHONPATH=str(ROOT / 'hub/service/src'), PYTHONDONTWRITEBYTECODE='1')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        with (root / 'hub-test.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'astr_auto_anima_hub'], cwd=root,
                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError('Hub exited during isolated smoke test')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/v1/health', timeout=1) as response:
                            payload = json.load(response)
                        assert payload['service'] == 'astr-auto-anima-hub'
                        assert payload['status'] == 'ok'
                        print('Real Hub startup/health OK:', payload['version'])
                        break
                    except OSError:
                        time.sleep(.5)
                else:
                    raise RuntimeError('Hub readiness timed out')
                assert json.loads(env_path.read_text('utf-8'))['AAH_ADMIN_TOKEN'] == token
                print('Existing token and custom port preserved; no production service touched')
            finally:
                # This exact subprocess was created by this test, never a searched system PID.
                process.terminate()
                process.wait(timeout=15)


if __name__ == '__main__':
    main()
