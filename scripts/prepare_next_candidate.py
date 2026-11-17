"""Stage the current client sources for isolated, reproducible local compilation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def stage(destination):
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(ROOT):
        raise ValueError('Choose a fresh build directory outside the source tree')
    names = subprocess.check_output(['git', 'ls-files', '-z', 'clients/flutter'], cwd=ROOT).decode().split('\0')
    manifest = {}
    for name in filter(None, names):
        path = ROOT / name
        if path.is_symlink():
            raise ValueError('Linked build source')
        data = path.read_bytes()
        relative = Path(name).relative_to('clients/flutter')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    (destination.parent / 'client-source-sha256.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('STAGED', len(manifest), 'client files', destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-dir', type=Path, required=True)
    stage(parser.parse_args().client_dir)
