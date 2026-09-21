"""Read-only verification of actual release ZIP/APK contents, including compiled path leaks."""
import argparse
import json
from pathlib import Path
import re
import zipfile

PRIVATE_PATH = re.compile(rb'(?:[A-Za-z]:[/\\]Users[/\\])(?!YOUR_USER|username)[^/\\\x00\s]{1,80}[/\\]')
SECRET_NAMES = {'.env', 'runtime-env.json', 'last-plan.json', 'extension_host.py',
                'studio_workbench.dart', 'lite_users.json', 'delivery_targets.json'}
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
            if name.startswith('/') or '..' in Path(name).parts or Path(name).name in SECRET_NAMES:
                failures.append('unsafe/private entry: ' + name)
            sdk_symbols = name in SDK_SYMBOLS or any(name.endswith('/web/' + item) for item in SDK_SYMBOLS)
            if name.endswith(('.pem', '.key', '.keystore', '.jks', '.sqlite3', '.db', '.pdb')) or (name.endswith('.symbols') and not sdk_symbols):
                failures.append('private/debug artifact: ' + name)
            content = archive.read(member)
            if name.endswith(('anima_random_prompt_pool.json', 'kp_prompt_pool.json')):
                if json.loads(content).get('prompts') != []:
                    failures.append('nonempty bundled corpus: ' + name)
            if name.endswith(('privacy_scan.py', 'verify_release_archives.py')):
                continue
            if PRIVATE_PATH.search(content) or PRIVATE_PATH.search(content.replace(b'\x00', b'')):
                failures.append('local user path embedded: ' + name)
            if b'/extensions/anima-lora-studio/' in content or b'oc_greeting_layered_atlas' in content:
                failures.append('excluded connector/artwork: ' + name)
        if 'lazy-bundle' in path.name:
            prefix = 'AstrAutoAnima-0.5.0-beta.1/'
            for required in ('.astr_auto_anima_public_root', '一键部署_AstrAutoAnima.bat',
                             'tools/deploy_project.py', 'hub/service/web/index.html'):
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
