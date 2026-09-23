"""Read-only integrity check for an extracted official complete suite (Python 3.10+)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify(root: Path) -> int:
    root = root.resolve(strict=True)
    manifest = json.loads((root / 'suite-manifest.json').read_text('utf-8'))
    entries = manifest['files']
    if not isinstance(entries, list) or not entries:
        raise ValueError('Empty or invalid file manifest')
    seen: set[str] = set()
    for entry in entries:
        name = entry['path']
        parts = PurePosixPath(name)
        if not name or '\\' in name or ':' in name or parts.is_absolute() or '..' in parts.parts:
            raise ValueError('Unsafe manifest path')
        if name.casefold() in seen:
            raise ValueError('Duplicate manifest path')
        seen.add(name.casefold())
        path = root.joinpath(*parts.parts)
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root):
            raise ValueError('Symbolic links are not accepted')
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('File escapes suite directory')
        if not path.is_file() or path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
            raise ValueError('Integrity check failed: ' + name)
    return len(entries)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        print(f'PASS: {verify(args.directory)} files verified. No files changed.')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        raise SystemExit(1)
