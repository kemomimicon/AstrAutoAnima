"""Package the tested current source and freshly compiled clients; never publish."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAMP = (2026, 11, 18, 0, 0, 0)
RUNTIME = ('deploy_project.py', 'deployment_support.py', 'download_network.py',
           'install_progress.py', 'project_components.py', 'gufeng_resource.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def zip_checked(path, entries, identity):
    if path.exists():
        raise FileExistsError(path)
    entries = dict(entries)
    manifest = dict(identity, files=[{'path': n, 'size': len(d), 'sha256': sha(d)}
                                  for n, d in sorted(entries.items())])
    entries['package-manifest.json'] = encoded(manifest)
    if len({n.casefold() for n in entries}) != len(entries):
        raise ValueError('Duplicate archive path')
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in sorted(entries.items()):
            if '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe archive path')
            info = zipfile.ZipInfo(name, STAMP)
            info.create_system = 3
            info.external_attr = (0o755 if name.endswith('.sh') else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    with zipfile.ZipFile(path) as z:
        if z.testzip() or set(z.namelist()) != set(entries):
            raise ValueError('Archive CRC or path verification failed')
        for name, data in entries.items():
            if sha(z.read(name)) != sha(data):
                raise ValueError('Archive readback differs: ' + name)
    checksum = sha(path.read_bytes())
    print('VERIFIED', path.name, path.stat().st_size, flush=True)
    return {'name': path.name, 'size': path.stat().st_size, 'sha256': checksum}


def built_files(root):
    if not root.is_dir():
        raise ValueError('Missing compiled directory: ' + str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked build output')
        if path.is_file() and path.suffix.lower() not in {'.pdb', '.map'}:
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    if not result:
        raise ValueError('Empty build output')
    return result


def build(build_dir, output):
    if output.resolve().is_relative_to(ROOT):
        raise ValueError('Output must be outside the source tree')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Commit and freeze source before packaging')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    release = json.loads((ROOT / 'release-manifest.json').read_text('utf-8'))
    label = release['release'] + '-build' + str(release['public_build'])
    identity = {'version': release['public_display_version'], 'source_commit': commit,
                'candidate_only': True, 'published': False}
    output.mkdir(parents=True, exist_ok=True)
    names = filter(None, subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0'))
    tracked = {}
    for name in names:
        p = ROOT / name
        if p.is_symlink():
            raise ValueError('Linked source file')
        if p.is_file():
            tracked[name] = p.read_bytes()
    staged = json.loads((build_dir / 'client-source-sha256.json').read_text('utf-8'))
    for name, expected in staged.items():
        if sha(tracked['clients/flutter/' + name]) != expected:
            raise ValueError('Client source changed after compilation: ' + name)
    docs = {'00_更新与回退说明.txt': b'\xef\xbb\xbf' + tracked['docs/NEXT_CANDIDATE_UPDATE.md'],
            'docs/NEXT_ANIMA_FEATURES.md': tracked['docs/NEXT_ANIMA_FEATURES.md'],
            'LICENSE': tracked['LICENSE'], 'THIRD_PARTY_NOTICES.md': tracked['THIRD_PARTY_NOTICES.md']}
    assets = []
    for edition in ('unified', 'admin', 'service'):
        files = built_files(build_dir / ('final-windows-' + edition))
        required = {'astr_auto_anima_hub_client.exe', 'flutter_windows.dll', 'data/app.so'}
        if not required.issubset(files):
            raise ValueError('Incomplete Windows client: ' + edition)
        files.update(docs)
        files['client-build.json'] = encoded(dict(identity, edition=edition, target='windows-x64'))
        files['client-source-sha256.json'] = encoded(staged)
        assets.append(zip_checked(output / f'AstrAutoAnima-Windows-{edition.title()}-{label}.zip', files, identity))
    web = built_files(build_dir / 'client/build/web')
    if not {'index.html', 'main.dart.js', 'flutter_bootstrap.js'}.issubset(web):
        raise ValueError('Incomplete Web client')
    web['client-build.json'] = encoded(dict(identity, edition='unified', target='web'))
    assets.append(zip_checked(output / f'AstrAutoAnima-Web-{label}.zip', dict(web, **docs), identity))
    payload = {}
    for prefix, section in [('plugin/astrbot_plugin_comfy_bridge/', 'plugin/'), ('hub/service/', 'hub/'),
                            ('comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/', 'node/')]:
        for name, data in tracked.items():
            if name.startswith(prefix) and not {'tests', '__pycache__'} & set(Path(name).parts):
                relative = name.removeprefix(prefix)
                if Path(relative).name.startswith('.env') or relative.startswith('web/'):
                    continue
                payload[section + relative] = data
    payload.update({'web/' + name: data for name, data in web.items()})
    payload.update({'workflows/' + Path(n).name: d for n, d in tracked.items()
                    if n.startswith('comfyui/workflows/') and n.endswith('.json')})
    payload.update({'runtime/' + n: tracked['tools/' + n] for n in RUNTIME})
    requirements = tomllib.loads(tracked['hub/service/pyproject.toml'].decode())['project']['dependencies']
    payload['hub-requirements.txt'] = ('\n'.join(requirements) + '\n').encode()
    updater = tracked['tools/update_existing_install.py'].decode('utf-8')
    updater = updater.replace("VERSION='0.5.2-1.44'", 'VERSION=' + repr(identity['version']))
    core = tuple(int(v) for v in release['release'].split('-')[0].split('.'))
    updater = updater.replace('TARGET_CORE=(0,5,2)', 'TARGET_CORE=' + repr(core))
    for platform in ('Windows', 'Linux'):
        manifest = dict(identity, platform=platform.lower(), files=[{'path': n, 'size': len(d), 'sha256': sha(d)}
                                                                   for n, d in sorted(payload.items())])
        entries = {'payload/' + n: d for n, d in payload.items()}
        entries.update(docs)
        entries.update({'payload-manifest.json': encoded(manifest), 'update.py': updater.encode()})
        if platform == 'Windows':
            entries['Update-Windows.cmd'] = (b'@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\nset "PYTHONUTF8=1"\r\n'
                b'where py >nul 2>nul\r\nif errorlevel 1 (python "%~dp0update.py" --gui) else (py -3 "%~dp0update.py" --gui)\r\n'
                b'set "AAA_EXIT=%errorlevel%"\r\nif not "%AAA_EXIT%"=="0" pause\r\nexit /b %AAA_EXIT%\r\n')
        else:
            entries['Update-Linux.sh'] = (b'#!/bin/sh\nset -eu\nD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                b'exec "${AAA_PYTHON:-python3}" -B "$D/update.py" "$@"\n')
        entries['update-plan.example.json'] = encoded(dict(install_root='', plugin_dir='', hub_home='', hub_python='',
            web_dir='', comfyui_root='', astrbot_python='', comfy_python='', backup_root='', ports=[6185,6278,8188]))
        assets.append(zip_checked(output / f'AstrAutoAnima-{platform}-Update-{label}.zip', entries, identity))
    for name, data in docs.items():
        p = output / name
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_bytes(data)
    (output / 'candidate-assets.json').write_bytes(encoded(dict(identity, assets=assets)))
    (output / 'SHA256SUMS.txt').write_text(''.join(a['sha256'] + '  ' + a['name'] + '\n' for a in assets), encoding='ascii')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.build_dir, args.output)
