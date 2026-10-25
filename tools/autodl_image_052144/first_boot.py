"""Explicit first boot for the AAA AutoDL image; never overwrites an installation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import secrets
import shutil
import subprocess
import tarfile
import time
import urllib.request

BASE = Path('/root/autodl-tmp')
INSTALL = BASE / 'aaa-install'
IMAGE = Path('/opt/aaa-image-052144')
NAPCAT = Path('/root/autodl-tmp/aaa-install/napcat-config/webui.json')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink path refused')


def private_json(path, value):
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('x', encoding='utf-8') as f:
        os.chmod(path, 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return 'pbkdf2_sha256$600000$' + salt.hex() + '$' + value.hex()


def initialize(root, image, napcat):
    """Generate separate credentials only on an extracted, untouched image payload."""
    no_links(root)
    if (root / 'runtime-env.json').exists() or (root / 'astrbot/data/cmd_config.json').exists():
        raise ValueError('Existing credentials/config found; refusing to initialize or reset')
    defaults = json.loads((root / '.image-defaults/templates.json').read_text('utf-8'))
    protected = [root / 'INITIAL_CREDENTIALS.json', root / 'runtime-env.full.json',
                 root / 'runtime-env.local.json', root / '.image-initialized.json', napcat]
    for path in protected:
        no_links(path)
        if path.exists():
            raise ValueError('Existing private state found; no overwrite')
    pw = 'Aa9-' + secrets.token_urlsafe(21)
    credentials = {
        'schema': 1, 'astrbot_username': 'astrbot', 'astrbot_initial_password': pw,
        'hub_admin_token': 'aah_admin_' + secrets.token_urlsafe(48),
        'hub_local_admin_token': 'aah_admin_' + secrets.token_urlsafe(48),
        'napcat_webui_token': secrets.token_urlsafe(36),
        'onebot_token_pending_manual_setup': secrets.token_urlsafe(36),
        'notice': 'Private. Change AstrBot initial password after login. OneBot is NOT automatically connected.',
    }
    private_json(root / 'INITIAL_CREDENTIALS.json', credentials)
    for name, token_key in [('full', 'hub_admin_token'), ('local', 'hub_local_admin_token')]:
        env = copy.deepcopy(defaults['env_' + name])
        env['AAH_ADMIN_TOKEN'] = credentials[token_key]
        private_json(root / ('runtime-env.' + name + '.json'), env)
        if name == 'full':
            private_json(root / 'runtime-env.json', env)
    astro = copy.deepcopy(defaults['astrbot'])
    dashboard = astro['dashboard']
    dashboard.update(username='astrbot', password=hashlib.md5(pw.encode()).hexdigest(),
                     pbkdf2_password=password_hash(pw), password_storage_upgraded=True,
                     password_change_required=True, jwt_secret=secrets.token_urlsafe(48), host='127.0.0.1')
    private_json(root / 'astrbot/data/cmd_config.json', astro)
    webui = {'host': '127.0.0.1', 'port': 6099, 'token': credentials['napcat_webui_token'],
             'autoLoginAccount': '', 'disableWebUI': False, 'enable2FA': False,
             'totpSecret': '', 'ipWhitelist': [], 'ipBlacklist': [], 'enableXForwardedFor': False}
    private_json(napcat, webui)
    private_json(root / '.image-initialized.json', {'schema': 1, 'image': '0.5.2-1.44-image.1', 'credentials_independent': True})
    print('首次配置已生成，凭据文件：', root / 'INITIAL_CREDENTIALS.json')
    print('查看账号密码：bash /root/AAA-Credentials.sh --show initial')
    print('查看管理令牌：bash /root/AAA-Credentials.sh --show hub --profile full')
    print('下一步：登录 AstrBot 创建 OpenAPI Key，再在 AAA 管理端完成连接。')


def allowed_member(member):
    p = PurePosixPath(member.name)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != 'autodl-tmp':
        return False
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
        return False
    if member.issym():
        # Data filter further checks resolved destination containment.
        if PurePosixPath(member.linkname).is_absolute():
            return False
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
        if not resolved.startswith('autodl-tmp/'):
            return False
    if member.islnk():
        q = PurePosixPath(member.linkname)
        if q.is_absolute() or '..' in q.parts or q.parts[0] != 'autodl-tmp':
            return False
    return True


def extract(image, base):
    manifest = json.loads((image / 'payload-manifest.json').read_text('utf-8'))
    archive = image / 'runtime.tar.gz'
    no_links(base)
    for relative in manifest['top_roots']:
        path = base / relative
        no_links(path)
        if path.exists():
            raise ValueError('Existing destination found; no merge or overwrite: ' + str(path))
    if shutil.disk_usage(base).free < manifest['unique_bytes'] + 2 * 1024**3:
        raise ValueError('Insufficient data disk; free payload size plus 2 GiB first')
    archives = [(archive, manifest['sha256'])]
    for extra in manifest.get('extra_archives', []):
        name = extra['file']
        if Path(name).name != name or not name.endswith('.tar.gz'):
            raise ValueError('Invalid supplemental archive name')
        archives.append((image / name, extra['sha256']))
    print('正在校验运行环境，请稍候。', flush=True)
    for path, expected in archives:
        if sha256(path) != expected:
            raise ValueError('运行环境校验失败：' + path.name)
    print('Extracting payload to original absolute paths; do not interrupt.', flush=True)
    # Stream in archive order; hardlinks refer to preceding archive members.
    count = 0
    for path, _ in archives:
        with tarfile.open(path, 'r|gz') as tar:
            for member in tar:
                if not allowed_member(member):
                    raise ValueError('Unsafe archive entry; extraction stopped')
                tar.extract(member, path=base.parent, filter='data')
                count += 1
                if count % 10000 == 0:
                    print('已释放文件：', count, flush=True)
    print('Extraction finished:', count, flush=True)


def launch(root, image):
    marker = root / '.image-initialized.json'
    if not marker.is_file():
        raise ValueError('Image is not initialized; use --apply first')
    astro = json.loads((root / 'astrbot/data/cmd_config.json').read_text('utf-8-sig'))
    env = dict(os.environ)
    if astro.get('dashboard', {}).get('password_change_required'):
        record = json.loads((root / 'INITIAL_CREDENTIALS.json').read_text('utf-8'))
        env['ASTRBOT_DASHBOARD_INITIAL_PASSWORD'] = record['astrbot_initial_password']
        print('Initial login password is in the private credential record; change it after login.', flush=True)
    else:
        env.pop('ASTRBOT_DASHBOARD_INITIAL_PASSWORD', None)
        print('AstrBot password already changed; initial password record is no longer a login credential.', flush=True)
    runner = root / 'deploy_project.py'
    command = [str(BASE / 'aaa-bootstrap-py312/bin/python'), '-B', str(runner), '--start', str(root), '--profile', 'full']
    # Match the existing CLI contract, verified during image preparation.
    result = subprocess.run(command, env=env, check=False)
    if result.returncode:
        raise ValueError('Core startup did not complete; inspect private runtime logs')
    for attempt in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:6185/api/auth/setup-status', timeout=2) as response:
                status = json.load(response)
            if response.status == 200 and status.get('status') == 'ok':
                break
        except (OSError, ValueError):
            pass
        time.sleep(1)
    else:
        raise ValueError('AstrBot 启动信息见运行目录 AstrBot.log')
    studio = BASE / 'apps/Start-Studio.sh'
    if studio.is_file():
        def ready():
            try:
                with urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2) as response:
                    value = json.load(response)
                return value.get('status') == 'ok' and value.get('version') == '0.25.0'
            except (OSError, ValueError):
                return False
        if not ready():
            with (root / 'Studio.log').open('ab') as log:
                subprocess.Popen(['bash', str(studio)], stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(30):
                if ready():
                    break
                time.sleep(1)
            else:
                raise ValueError('Studio 启动信息见运行目录 Studio.log')
        print('Studio 0.25.0 已就绪，可在 AAA 管理端扩展页打开。')
    print('首次配置：cat /root/AAA-README.md')
    print('密码和令牌：bash /root/AAA-Credentials.sh --show initial')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--start', action='store_true')
    args = parser.parse_args()
    if args.start:
        launch(INSTALL, IMAGE)
    elif args.apply:
        if INSTALL.exists():
            raise ValueError('aaa-install already exists; refusing overwrite, merge or reinitialization')
        extract(IMAGE, BASE)
        initialize(INSTALL, IMAGE, NAPCAT)
    else:
        print('PREVIEW. Use --apply on a NEW image instance only; existing installation is never overwritten.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError, KeyError, tarfile.TarError) as exc:
        raise SystemExit('启动失败：' + str(exc) + '\n启动日志：/root/autodl-tmp/AAA-image-start.log\n反馈：bilibili「ケモミミロリコン」')
