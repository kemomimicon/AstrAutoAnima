"""Bundle the immutable beta.2 public artifacts; never read private project directories."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from verify_release_archives import check

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.5.0-beta.2'
BASE_COMMIT = '3709c1da57b4808f663c907795fd5fe107b2a173'
BASE_MANIFEST_HASH = '06f809adb1730be90b17a1a6dd4f2db13c8ddd2c1c0f495ca3cc20868bed3751'
PREFIX = f'AstrAutoAnima-{VERSION}-complete'
ASSETS = {
    f'AstrAutoAnima-lazy-bundle-windows-{VERSION}.zip': 'deployment',
    f'AstrAutoAnima-lazy-bundle-linux-{VERSION}.zip': 'deployment',
    f'astrbot_plugin_comfy_bridge-{VERSION}.zip': 'components',
    f'astr_auto_anima_hub_service-{VERSION}.zip': 'components',
    'Anima_Workflow_Pack-0.8.0-beta.1-public.zip': 'components',
    f'AstrAutoAnima-Windows-Admin-{VERSION}.zip': 'clients/windows',
    f'AstrAutoAnima-Windows-Service-{VERSION}.zip': 'clients/windows',
    f'AstrAutoAnima-Android-Admin-{VERSION}.apk': 'clients/android',
    f'AstrAutoAnima-Android-Service-{VERSION}.apk': 'clients/android',
    f'AstrAutoAnima-Web-{VERSION}.zip': 'clients/web',
    f'AstrAutoAnima-tools-{VERSION}.zip': 'tools',
    f'AstrAutoAnima-artwork-{VERSION}.zip': 'artwork',
    f'AstrAutoAnima-{VERSION}-source.zip': 'source',
    'README.md': 'original-release',
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest(payload: bytes) -> dict[str, str]:
    result = {}
    for line in payload.decode('utf-8').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  ([^/\\:]+)', line)
        if not match or match[2] in result or match[2] in {'.', '..'}:
            raise ValueError('Invalid or duplicate original checksum entry')
        result[match[2]] = match[1]
    if set(result) != set(ASSETS):
        raise ValueError('Original release asset set differs from approved set')
    return result


def build(artifacts: Path, output: Path) -> Path:
    artifacts = artifacts.resolve(strict=True)
    output = output.resolve()
    if output == artifacts or output.is_relative_to(ROOT):
        raise ValueError('Use a separate output directory outside the source repository')
    manifest_bytes = (artifacts / 'SHA256SUMS.txt').read_bytes()
    if sha(manifest_bytes) != BASE_MANIFEST_HASH:
        raise ValueError('Original beta.2 manifest does not match the published baseline')
    expected = read_manifest(manifest_bytes)
    entries: dict[str, bytes] = {}
    for name, folder in ASSETS.items():
        path = artifacts / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked release asset: ' + name)
        payload = path.read_bytes()
        if sha(payload) != expected[name]:
            raise ValueError('Original checksum mismatch: ' + name)
        if path.suffix in {'.zip', '.apk'}:
            failures = check(path)
            if failures:
                raise ValueError('Privacy/structure failure: ' + repr(failures))
        entries[f'{folder}/{name}'] = payload
        print('VERIFIED', name)

    # Documentation is taken from the verified public source ZIP, not local/private files.
    with zipfile.ZipFile(io.BytesIO(entries[f'source/AstrAutoAnima-{VERSION}-source.zip'])) as source:
        source_prefix = f'AstrAutoAnima-{VERSION}/'
        for name in source.namelist():
            relative = name.removeprefix(source_prefix)
            if relative.startswith('docs/') and relative.endswith('.md'):
                entries[relative] = source.read(name)
            elif relative in {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'release-manifest.json'}:
                entries[relative] = source.read(name)
    entries['original-release/SHA256SUMS.txt'] = manifest_bytes
    entries['README.md'] = (ROOT / 'docs/COMPLETE_SUITE.md').read_bytes()
    entries['verify_complete_suite.py'] = (ROOT / 'tools/verify_complete_suite.py').read_bytes()
    suite = {
        'release': VERSION, 'distribution': 'complete-suite', 'status': 'prerelease',
        'component_commit': BASE_COMMIT, 'original_manifest_sha256': BASE_MANIFEST_HASH,
        'private_data_included': False, 'models_included': False,
        'files': [{'path': name, 'size': len(data), 'sha256': sha(data)}
                  for name, data in sorted(entries.items())],
    }
    entries['suite-manifest.json'] = (json.dumps(suite, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    destination = output / f'{PREFIX}.zip'
    checksum = output / f'{PREFIX}.sha256.txt'
    guide = output / f'{PREFIX}-README.md'
    if any(path.exists() for path in (destination, checksum, guide)):
        raise FileExistsError('Refusing to overwrite an existing complete distribution')
    output.mkdir(parents=True, exist_ok=True)
    # Already-compressed original artifacts remain byte-identical, without recompression.
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(f'{PREFIX}/{name}', (2026, 9, 23, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('Complete ZIP failed CRC verification')
        for name, data in entries.items():
            if sha(archive.read(f'{PREFIX}/{name}')) != sha(data):
                raise ValueError('Complete ZIP payload changed: ' + name)
    checksum.write_text(f'{sha(destination.read_bytes())}  {destination.name}\n', encoding='utf-8')
    guide.write_bytes(entries['README.md'])
    print(f'BUILT {destination.name}: {len(entries)} verified files, {destination.stat().st_size:,} bytes')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.artifacts, args.output)
