"""Create a separate post-install wizard distribution from an explicit public allowlist."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['first_run_config.py', 'first_run_checks.py', 'first_run_wizard.py', 'prompt_pool_manager.py',
           'hub_lite_user_manager.py', 'start_first_run_wizard.cmd', 'start_first_run_wizard.sh']


def write_zip(destination, entries):
    if destination.exists():
        raise FileExistsError('Will not overwrite a previous distribution')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith('.sh') else 0o644) << 16
            content = path.read_bytes()
            if name.endswith('.cmd'):
                content = content.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            elif name.endswith(('.py', '.md', '.sh')):
                content = content.replace(b'\r\n', b'\n')
            archive.writestr(info, content)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP verification failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--python-license', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.exe.is_file() or not args.python_license.is_file():
        raise ValueError('Built EXE and Python license are required')
    args.output.mkdir(parents=True, exist_ok=True)
    entries = {'README.md': ROOT / 'docs/FIRST_RUN_WIZARD.md', 'LICENSE': ROOT / 'LICENSE'}
    for doc in sorted((ROOT / 'docs').glob('*.md')):
        entries['docs/' + doc.name] = doc
    source = dict(entries)
    for name in SOURCES:
        source['tools/' + name] = ROOT / 'tools' / name
    source['tools/tests/test_first_run_config.py'] = ROOT / 'tools/tests/test_first_run_config.py'
    source['tools/tests/test_first_run_checks.py'] = ROOT / 'tools/tests/test_first_run_checks.py'
    source['tools/build_character_dictionary.py'] = ROOT / 'plugin/astrbot_plugin_comfy_bridge/tools/build_character_dictionary.py'
    windows = dict(entries)
    windows['AstrAutoAnima-FirstRun-Wizard.exe'] = args.exe
    windows['licenses/Python-LICENSE.txt'] = args.python_license
    windows['licenses/RUNTIME_NOTICES.md'] = ROOT / 'docs/FIRST_RUN_RUNTIME_NOTICES.md'
    built = []
    for label, items in [('Windows', windows), ('Source', source)]:
        target = args.output / f'AstrAutoAnima-FirstRun-Wizard-1.1-{label}.zip'
        write_zip(target, items)
        built.append(target)
        print('BUILT', target.name, target.stat().st_size)
    checksum = args.output / 'SHA256SUMS.txt'
    if checksum.exists():
        raise FileExistsError('Existing checksum manifest')
    checksum.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
                               for path in built), encoding='utf-8')


if __name__ == '__main__':
    main()
