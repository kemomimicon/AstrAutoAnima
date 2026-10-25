"""Build independent Windows/Linux suites from the pinned public build44 release."""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.5.2-1.44'
BASE_SHA = '205120fb9059ccd7198def401ccb763dc50e51891b31c358c30260f401f0c023'
BASE_COMMIT = '29882ba009719f1707ac0bb2690b04df1763dff7'
TIME = (2026, 10, 25, 0, 0, 0)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_zip(payload: bytes, strip_root=False) -> dict[str, bytes]:
    result = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        seen = set()
        for item in archive.infolist():
            name = item.orig_filename
            p = PurePosixPath(name)
            if (name != item.filename or not name or '\\' in name or ':' in name or p.is_absolute()
                    or '..' in p.parts or name.casefold() in seen
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe, linked or duplicate ZIP entry')
            seen.add(name.casefold())
            if not item.is_dir():
                result[name] = archive.read(item)
    if strip_root:
        roots = {name.split('/')[0] for name in result}
        if len(roots) != 1 or any('/' not in n for n in result):
            raise ValueError('Expected one enclosing directory')
        result = {n.split('/', 1)[1]: d for n, d in result.items()}
    return result


def load_baseline(path: Path) -> dict[str, bytes]:
    payload = path.read_bytes()
    if sha(payload) != BASE_SHA:
        raise ValueError('Published install.2 complete SHA256 mismatch')
    entries = read_zip(payload, True)
    manifest = json.loads(entries['suite-manifest.json'])
    rows = manifest['files']
    if {r['path'] for r in rows} != set(entries) - {'suite-manifest.json'}:
        raise ValueError('Baseline manifest coverage differs')
    for row in rows:
        data = entries[row['path']]
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('Baseline member integrity mismatch')
    return entries


def render_guide(text: str, platform: str) -> bytes:
    """Offline manual with selectable/copyable code blocks and no remote assets."""
    blocks = []; code = None
    for line in text.splitlines():
        if line.startswith('```'):
            if code is None: code = []
            else:
                blocks.append('<div class="code"><button type="button">复制代码</button><pre><code>'
                              + html.escape('\n'.join(code)) + '</code></pre></div>')
                code = None
        elif code is not None: code.append(line)
        elif line.startswith('# '): blocks.append('<h1>' + html.escape(line[2:]) + '</h1>')
        elif line.startswith('## '): blocks.append('<h2>' + html.escape(line[3:]) + '</h2>')
        elif line.strip(): blocks.append('<p>' + html.escape(line) + '</p>')
    if code is not None: raise ValueError('Unclosed manual code fence')
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AstrAutoAnima PLATFORM 完整安装与使用说明</title>
<style>body{margin:0;background:#eef2f7;color:#243146;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1000px;margin:24px auto;background:white;border-radius:14px;padding:28px 36px}h1{color:#19469a;font-size:28px}
h2{margin-top:36px;border-bottom:2px solid #e8edf5;padding-bottom:8px}p{white-space:pre-wrap;overflow-wrap:anywhere}
.code{border:1px solid #d3deed;border-radius:8px;overflow:hidden;margin:18px 0}button{margin:8px 12px;background:#2858c3;color:white;border:0;border-radius:5px;padding:8px 16px;cursor:pointer}
pre{margin:0;padding:18px;background:#18253b;color:#e9f0fa;overflow:auto;line-height:1.6}code{font-family:Consolas,monospace}
@media(max-width:700px){main{margin:0;padding:18px}h1{font-size:24px}}</style><main>CONTENT</main>
<script>document.querySelectorAll('.code button').forEach(b=>b.onclick=async()=>{const t=b.parentElement.querySelector('code').textContent;try{await navigator.clipboard.writeText(t);b.textContent='已复制'}catch(e){const s=getSelection(),r=document.createRange();r.selectNodeContents(b.parentElement.querySelector('code'));s.removeAllRanges();s.addRange(r);b.textContent='已选中，请按 Ctrl+C'}});</script></html>'''
    return document.replace('PLATFORM', platform).replace('CONTENT', '\n'.join(blocks)).encode('utf-8')


def assemble(base: dict[str, bytes], platform: str, source_zip: bytes,
             source_commit: str) -> dict[str, bytes]:
    if platform not in {'windows', 'linux'}:
        raise ValueError('Unsupported platform')
    lazy_name = f'deployment/AstrAutoAnima-lazy-bundle-{platform}-0.5.2-beta.1.zip'
    installer = read_zip(base[lazy_name], True)
    entry = 'Deploy-Windows.cmd' if platform == 'windows' else 'Deploy-Linux.sh'
    for required in ('.astr_auto_anima_public_root', entry, 'tools/setup_center.py',
                     'tools/deploy_project.py', 'tools/deployment_support.py',
                     'tools/model_catalog.json', 'hub/service/web/index.html'):
        if required not in installer: raise ValueError('Incomplete platform installer: ' + required)
    other = 'Deploy-Linux.sh' if platform == 'windows' else 'Deploy-Windows.cmd'
    if other in installer: raise ValueError('Wrong-platform primary launcher in installer')
    public = read_zip(source_zip, True)
    entries = {}
    for name, data in base.items():
        if name.startswith(('deployment/', 'first-run-guide/', 'source/', 'docs/')):
            continue
        if name in {'suite-manifest.json', 'README.txt', 'BUILD_REPORT.json', 'offline-acceptance.json'}:
            continue
        entries[name] = data
    entries['provenance/validated-install2-build-report.json'] = base['BUILD_REPORT.json']
    entries['provenance/validated-install2-acceptance.json'] = base['offline-acceptance.json']
    entries.update({'installer/' + name: data for name, data in installer.items()})
    entries.update({name: data for name, data in public.items()
                    if name.startswith('docs/') or name in {'LICENSE', 'THIRD_PARTY_NOTICES.md'}})
    for name, data in public.items():
        if name.startswith('tools/autodl_public_image_20261025/Open-AAA-Tunnel.'):
            entries['connection-tools/' + name.rsplit('/', 1)[1]] = data
    entries[f'source/AstrAutoAnima-{VERSION}-public-source.zip'] = source_zip
    guide = public[f'docs/platform-full/{platform}.md']
    entries['00_先读我.txt'] = b'\xef\xbb\xbf' + guide
    entries['00_安装与使用说明.html'] = render_guide(guide.decode('utf-8-sig'), platform.title())
    if platform == 'windows':
        entries['Install-Windows.cmd'] = (b'@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\npushd "%~dp0installer"\r\n'
                                          b'if errorlevel 1 exit /b 1\r\ncall Deploy-Windows.cmd\r\n'
                                          b'set "AAA_EXIT=%ERRORLEVEL%"\r\npopd\r\nexit /b %AAA_EXIT%\r\n')
        entries['First-Run-Windows.cmd'] = (b'@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n'
                                            b'call "%~dp0installer\\tools\\start_first_run_wizard.cmd"\r\n')
    else:
        entries['Install-Linux.sh'] = (b'#!/bin/sh\nset -eu\n[ "$(uname -s)" = Linux ] || exit 1\n'
                                       b'DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                                       b'exec sh "$DIR/installer/Deploy-Linux.sh" "$@"\n')
        entries['First-Run-Linux.sh'] = (b'#!/bin/sh\nset -eu\nDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                                         b'if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then\n'
                                         b' echo "Use the Hub Web UI for headless Linux; see 00_ installation guide."\n exit 0\nfi\n'
                                         b'exec sh "$DIR/installer/tools/start_first_run_wizard.sh"\n')
    for name, data in entries.items():
        if name.endswith('.sh') and b'\r\n' in data:
            raise ValueError('Linux shell entry contains CRLF')
    manifest = {
        'public_display_version': VERSION, 'public_build': 44, 'platform': platform,
        'distribution': 'platform-full', 'packaging_revision': 'full.1',
        'component_source_commit': BASE_COMMIT, 'package_source_commit': source_commit,
        'published_complete_sha256': BASE_SHA, 'installer_archive_sha256': sha(base[lazy_name]),
        'models_included': False, 'private_data_included': False,
        'desktop_clients': ['windows-x64', 'android'], 'linux_interface': 'Hub Web',
        'files': [{'path': n, 'size': len(d), 'sha256': sha(d)} for n, d in sorted(entries.items())],
    }
    entries['suite-manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    return entries


def build(baseline: Path, output: Path) -> list[Path]:
    if output.resolve().is_relative_to(ROOT):
        raise ValueError('Place platform builds outside the source checkout')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Commit the package source before building')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(['git', 'archive', '--format=zip',
                                     f'--prefix=AstrAutoAnima-{VERSION}-source/', head], cwd=ROOT)
    base = load_baseline(baseline)
    output.mkdir(parents=True, exist_ok=True)
    built = []
    for platform in ('windows', 'linux'):
        prefix = f'AstrAutoAnima-{platform.title()}-{VERSION}-Full'
        destination = output / (prefix + '.zip')
        if destination.exists(): raise FileExistsError('Refusing to replace a released bundle')
        entries = assemble(base, platform, source, head)
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in sorted(entries.items()):
                item = zipfile.ZipInfo(prefix + '/' + name, TIME)
                item.external_attr = (0o755 if name.endswith('.sh') else 0o644) << 16
                item.compress_type = zipfile.ZIP_STORED if name.endswith(('.zip', '.apk')) else zipfile.ZIP_DEFLATED
                archive.writestr(item, data)
        verified = read_zip(destination.read_bytes(), True)
        if verified != entries: raise ValueError('Built ZIP readback differs')
        digest = sha(destination.read_bytes())
        output.joinpath(prefix + '.sha256.txt').write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
        output.joinpath(prefix + '-README.txt').write_bytes(entries['00_先读我.txt'])
        print('BUILT', destination.name, destination.stat().st_size, 'bytes', digest, flush=True)
        built.append(destination)
    output.joinpath('PLATFORM_FULL_SHA256SUMS.txt').write_text(''.join(
        sha(p.read_bytes()) + '  ' + p.name + '\n' for p in built), encoding='ascii')
    return built


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.baseline, args.output)
