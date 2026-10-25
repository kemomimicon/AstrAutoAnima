"""Read-only verification of actual release ZIP/APK contents, including compiled path leaks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_resource_policy import unreviewed_gufeng_payload

PRIVATE_PATH = re.compile(rb'(?:[A-Za-z]:[/\\]Users[/\\])(?!YOUR_USER|username)[^/\\\x00\s]{1,80}[/\\]')
SECRET_NAMES = {'.env', 'runtime-env.json', 'last-plan.json',
                'lite_users.json', 'delivery_targets.json'}
# Flutter's public CanvasKit JS symbol tables are SDK runtime assets, not the
# application's split-debug-info. Keep them for the generated service-worker cache.
SDK_SYMBOLS = {'canvaskit/canvaskit.js.symbols', 'canvaskit/skwasm_heavy.js.symbols',
               'canvaskit/skwasm.js.symbols', 'canvaskit/wimp.js.symbols',
               'canvaskit/chromium/canvaskit.js.symbols',
               'canvaskit/webparagraph/canvaskit.js.symbols'}


def check(path):
    failures = []
    with zipfile.ZipFile(path) as archive:
        names = [n.filename.replace('\\', '/') for n in archive.infolist()]
        if len(names) != len(set(names)):
            failures.append('duplicate entries')
        for member, name in zip(archive.infolist(), names):
            if member.is_dir():
                continue
            if unreviewed_gufeng_payload(name):
                failures.append('unreviewed GuFeng resource payload: ' + name)
                continue
            if name.startswith('/') or '..' in Path(name).parts or Path(name).name in SECRET_NAMES:
                failures.append('unsafe/private entry: ' + name)
            sdk_symbols = (name in SDK_SYMBOLS or name.removeprefix('web/') in SDK_SYMBOLS
                           or any(name.endswith('/web/' + item) for item in SDK_SYMBOLS))
            if name.endswith(('.pem', '.key', '.keystore', '.jks', '.sqlite3', '.db', '.pdb')) or (name.endswith('.symbols') and not sdk_symbols):
                failures.append('private/debug artifact: ' + name)
            content = archive.read(member)
            if name.endswith('/candidate-source-manifest.json') or name == 'candidate-source-manifest.json':
                prefix = name.removesuffix('candidate-source-manifest.json')
                rows = json.loads(content)
                for relative, row in rows.items():
                    if (Path(relative).is_absolute() or '..' in Path(relative).parts
                            or ':' in relative or '\\' in relative):
                        failures.append('unsafe source manifest entry: ' + relative)
                        continue
                    target = prefix + relative
                    if target not in names:
                        failures.append('source manifest missing file: ' + relative)
                    elif hashlib.sha256(archive.read(target)).hexdigest() != row.get('sha256'):
                        failures.append('source manifest hash mismatch: ' + relative)
            if name.endswith(('anima_random_prompt_pool.json', 'kp_prompt_pool.json')):
                if json.loads(content).get('prompts') != []:
                    failures.append('nonempty bundled corpus: ' + name)
            if name.endswith(('privacy_scan.py', 'verify_release_archives.py')):
                continue
            if PRIVATE_PATH.search(content) or PRIVATE_PATH.search(content.replace(b'\x00', b'')):
                failures.append('local user path embedded: ' + name)
        if 'lazy-bundle' in path.name:
            markers = [n for n in names if n.endswith('/.astr_auto_anima_public_root')]
            if len(markers) != 1:
                failures.append('lazy bundle needs one release-root marker')
                return failures
            prefix = markers[0].removesuffix('.astr_auto_anima_public_root')
            entry = 'Deploy-Linux.sh' if '-linux-' in path.name else 'Deploy-Windows.cmd'
            for required in ('.astr_auto_anima_public_root', entry,
                             'tools/deploy_project.py', 'tools/deployment_support.py',
                             'tools/model_catalog.json', 'tools/install_progress.py', 'tools/setup_center.py', 'hub/service/web/index.html'):
                if prefix + required not in names:
                    failures.append('incomplete lazy bundle: ' + required)
    return failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    files = sorted(p for p in args.directory.iterdir() if p.suffix in {'.zip', '.apk'})
    errors = []
    for file in files:
        results = check(file)
        print(('FAIL ' if results else 'PASS ') + file.name)
        errors.extend(file.name + ': ' + result for result in results)
    for error in errors:
        print(error)
    raise SystemExit(1 if errors or not files else 0)
