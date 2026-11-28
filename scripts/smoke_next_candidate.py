"""Exercise an archived candidate against isolated build44 fixtures, then roll back."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '28b1f7f'


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def unpack_checked(archive, target):
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('ZIP CRC failed')
        manifest = json.loads(z.read('package-manifest.json'))
        expected = {row['path']: row for row in manifest['files']}
        if set(z.namelist()) != set(expected) | {'package-manifest.json'}:
            raise ValueError('Archive manifest differs')
        for name, row in expected.items():
            path = target / name
            if '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe ZIP member')
            data = z.read(name)
            if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Archive checksum differs')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return manifest


def run(patch_zip, work):
    work = work.resolve()
    if work.exists():
        raise ValueError('Choose a fresh fixture directory')
    work.mkdir(parents=True)
    patch = work / 'unpacked patch'
    identity = unpack_checked(patch_zip, patch)
    install = work / '旧版 安装 with spaces'
    hub = install / 'hub'
    plugin = install / 'astrbot/data/plugins/astrbot_plugin_comfy_bridge'
    comfy = install / 'ComfyUI'
    pd = install / 'astrbot/data/plugin_data/astrbot_plugin_comfy_bridge'
    pd.mkdir(parents=True)
    archive = subprocess.check_output(['git', 'archive', '--format=zip', BASELINE,
        'plugin/astrbot_plugin_comfy_bridge', 'hub/service'], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for name in z.namelist():
            if name.endswith('/') or '/tests/' in name or Path(name).name.startswith('.env'):
                continue
            if name.startswith('hub/service/'):
                target = hub / name.removeprefix('hub/service/')
            else:
                target = plugin / name.removeprefix('plugin/astrbot_plugin_comfy_bridge/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    (hub / 'web').mkdir(exist_ok=True)
    (hub / 'web/index.html').write_text('<html><body>build44 fixture web</body></html>', encoding='utf-8')
    old_files = {p: p.read_bytes() for folder in (hub, plugin) for p in folder.rglob('*') if p.is_file()}
    (comfy / 'models').mkdir(parents=True)
    (comfy / 'main.py').write_text('# fixture only\n', encoding='utf-8')
    model = comfy / 'models/retained.safetensors'; model.write_bytes(b'fixture model bytes')
    presets = pd / 'presets.json'
    dump(presets, {'characters': {'Alice': {'prompt': 'alice, red hair', 'lora': None}}, 'styles': {}})
    pool = pd / 'anima_random_prompt_pool.json'
    dump(pool, {'schema_version': 3, 'prompts': [{'id': 'kept', 'prompt': 'mountain lake',
        'enabled': True, 'source_code': 'G', 'safety_code': 'N'}]})
    # This environment only sees fixture Hub sources plus already installed test dependencies.
    venv.EnvBuilder(with_pip=False).create(hub / '.venv')
    python = hub / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    sites = json.loads(subprocess.check_output([str(python), '-c',
        'import site,json;print(json.dumps(site.getsitepackages()))'], text=True))
    destination = next(Path(p) for p in sites if Path(p).is_dir() and 'site-packages' in p)
    import fastapi
    dependency_site = Path(fastapi.__file__).resolve().parent.parent
    (destination / 'fixture.pth').write_text(str(hub / 'src') + '\n' + str(dependency_site) + '\n', encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    token = secrets.token_urlsafe(48)
    env = {'AAH_ADMIN_TOKEN': token, 'AAH_PORT': str(port), 'AAH_HOST': '127.0.0.1',
        'AAH_EXECUTION_MODE': 'remote', 'AAH_PLUGIN_DIR': str(plugin), 'AAH_PLUGIN_DATA_DIR': str(pd),
        'AAH_COMFYUI_ROOT': str(comfy), 'AAH_ASTRBOT_BOT_ID': 'fixture-bot', 'AAH_WEB_ROOT': str(hub / 'web')}
    dump(install / 'runtime-env.json', env)
    dump(install / 'services.json', [{'name': 'Hub', 'cwd': str(hub), 'command': [str(python)], 'port': port}])
    dump(install / 'plan.json', dict(install_root=str(install), plugin_dir=str(plugin), hub_home=str(hub),
        hub_python=str(python), comfyui_root=str(comfy), backup_root=str(install / 'aaa_update_backups'), ports=[port]))
    secret_file = plugin.parent.parent / 'config/astrbot_plugin_comfy_bridge_config.json'
    dump(secret_file, {'fixture_key': secrets.token_urlsafe(32)})
    protected = {p: p.read_bytes() for p in (model, pool, presets, install / 'runtime-env.json', secret_file)}
    cleanenv = {k: v for k, v in os.environ.items() if not k.startswith('AAH_') and k not in {'PYTHONPATH', 'PYTHONHOME'}}
    cleanenv.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    with (work / 'apply.log').open('wb') as log:
        for args in ([], ['--apply', '--confirm-stopped']):
            subprocess.run([sys.executable, '-B', str(patch / 'update.py'), '--plan', str(install / 'plan.json'), *args],
                cwd=work, env=cleanenv, stdout=log, stderr=log, check=True)
    backups = list((install / 'aaa_update_backups').glob('to_*'))
    assert len(backups) == 1
    backup = backups[0]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(route, value=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + route,
            data=json.dumps(value).encode() if value is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with opener.open(req, timeout=5) as response:
            return json.load(response)
    def start_and_check(expected, test_gallery=False):
        with (work / ('new-hub.log' if test_gallery else 'restored-hub.log')).open('wb') as log:
            process = subprocess.Popen([str(python), '-B', '-m', 'astr_auto_anima_hub'], cwd=hub,
                env=dict(cleanenv, **env), stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError('Fixture Hub exited; inspect fixture log')
                    try:
                        health = request('/api/v1/health')
                        assert health['status'] == 'ok' and health['version'] == expected, health
                        break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError('Fixture Hub did not become healthy')
                if test_gallery:
                    data = request('/api/v1/character-gallery')
                    saved = request('/api/v1/character-gallery', {'revision': data['revision'], 'character': 'Alice', 'published': True})
                    assert saved['items'][0]['character'] == 'Alice'
                    assert request('/api/v1/character-gallery')['revision'] == saved['revision']
                    with opener.open(f'http://127.0.0.1:{port}/', timeout=5) as response:
                        assert b'flutter_bootstrap.js' in response.read()
            finally:
                process.terminate(); process.wait(timeout=20)
    start_and_check(identity['version'].split('+')[0], True)
    for p, data in protected.items():
        assert p.read_bytes() == data, p.name
    card = pd / 'character_gallery/catalog.json'; card_bytes = card.read_bytes()
    # The original patch becomes unavailable. Recovery must use only the backup.
    patch.rename(work / 'patch moved away')
    with (work / 'rollback.log').open('wb') as log:
        subprocess.run([sys.executable, '-B', str(backup / 'update.py'), '--rollback', str(backup), '--confirm-stopped'],
            cwd=work, env=cleanenv, stdout=log, stderr=log, check=True)
    for p, data in {**old_files, **protected}.items():
        assert p.read_bytes() == data, p.name
    assert card.read_bytes() == card_bytes
    assert not (plugin / 'next_generation_runtime.py').exists()
    start_and_check('0.5.2-beta.1')
    report = dict(identity, baseline_commit=BASELINE, real_patch_apply=True, restored_old_Hub_health=True,
        new_Hub_health=True, web_served=True, character_gallery_save_read=True, private_bytes_preserved=True,
        backup_only_rollback=True, new_user_gallery_preserved_on_rollback=True, production_modified=False, gpu_job_started=False)
    report.pop('files', None)
    dump(work / 'smoke-result.json', report)
    print('PASS: archive -> build44 -> candidate Hub/Web/gallery -> independent backup -> build44 Hub', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    run(args.patch, args.work)
