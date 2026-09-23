"""Offline installed-package preflight, not a replacement for clean-machine/GPU tests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from build_release_archives import VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    for platform in ('windows', 'linux'):
        archive = args.directory / f'AstrAutoAnima-lazy-bundle-{platform}-{VERSION}.zip'
        with tempfile.TemporaryDirectory(prefix='AAA bundle (test) ') as t:
            base = Path(t)
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                forbidden = ('.sh',) if platform == 'windows' else ('.cmd', '.bat', '.ps1')
                assert not any(n.endswith(forbidden) for n in names), 'Mixed platform launchers'
                for name in names:
                    if name.startswith('/') or ':' in name or '..' in Path(name).parts:
                        raise ValueError('Unsafe archive path')
                z.extractall(base / 'release')
            root = base / 'release' / f'AstrAutoAnima-{VERSION}'
            assert (root / 'hub/service/web/index.html').is_file()
            assert (root / 'tools/model_catalog.json').is_file()
            if platform != ('windows' if os.name == 'nt' else 'linux'):
                print(platform + ': archive structure OK; native preflight requires that OS')
                continue
            astro, comfy = base / 'astro', base / 'comfy'
            (astro / 'data').mkdir(parents=True)
            comfy.mkdir()
            (comfy / 'main.py').write_text('# fixture', encoding='utf-8')
            for service in (astro, comfy):
                binary = service / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
                binary.parent.mkdir(parents=True)
                binary.touch()
            astr_bin = astro / ('.venv/Scripts/astrbot.exe' if os.name == 'nt' else '.venv/bin/astrbot')
            astr_bin.touch()
            plan = base / 'plan.json'
            plan.write_text(json.dumps({'destination': str(base / 'new-install'),
                'platform': platform, 'astrbot': str(astro), 'comfyui': str(comfy)}), encoding='utf-8')
            result = subprocess.run([sys.executable, str(root / 'tools/deploy_project.py'), '--plan', str(plan)],
                cwd=root, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'ascii'}, capture_output=True)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
            assert not (base / 'new-install').exists(), 'Preflight unexpectedly wrote installation'
            print(platform + ': extracted package offline preflight OK')


if __name__ == '__main__':
    main()
