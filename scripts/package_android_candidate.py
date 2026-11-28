"""Verify Android candidates against previous signed APKs and add delivery assets."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    p = subprocess.run([str(a) for a in args], capture_output=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise ValueError('Android verification failed: ' + p.stdout[-3000:] + p.stderr[-3000:])
    return p.stdout


def inspect(apk, sdk):
    cert = command([sdk / 'apksigner.bat', 'verify', '--verbose', '--print-certs', apk])
    fingerprint = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([a-f0-9]+)', cert)
    if len(fingerprint) != 1:
        raise ValueError('Expected one verified APK signer')
    badging = command([sdk / 'aapt.exe', 'dump', 'badging', apk])
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    if not package or 'application-debuggable' in badging:
        raise ValueError('Invalid package identity or debuggable release')
    with zipfile.ZipFile(apk) as z:
        if z.testzip():
            raise ValueError('APK CRC failure')
        names = set(z.namelist())
        arches = sorted({n.split('/')[1] for n in names if n.startswith('lib/') and n.endswith('/libapp.so')})
        if arches != ['arm64-v8a', 'armeabi-v7a', 'x86_64']:
            raise ValueError('Missing universal APK architecture')
        for arch in arches:
            if 'lib/' + arch + '/libflutter.so' not in names:
                raise ValueError('Missing Flutter engine')
    command([sdk / 'zipalign.exe', '-c', '-P', '16', '4', apk])
    return {'package_id': package[1], 'version_code': int(package[2]), 'version_name': package[3],
        'signer_sha256': fingerprint[0], 'min_sdk': int(re.search(r"sdkVersion:'(\d+)'", badging)[1]),
        'target_sdk': int(re.search(r"targetSdkVersion:'(\d+)'", badging)[1]),
        'architectures': arches, 'signature_verified': True, 'alignment_16k_verified': True,
        'debuggable': False, 'sha256': digest(apk), 'size': apk.stat().st_size}


def package(build, baseline, output, sdk):
    release = json.loads((ROOT / 'release-manifest.json').read_text('utf-8'))
    identity = json.loads((output / 'candidate-assets.json').read_text('utf-8'))
    for name, expected in json.loads((build / 'client-source-sha256.json').read_text('utf-8')).items():
        # Flutter can regenerate Windows registrants during Android preparation.
        # Android consumes shared Dart/assets and its own platform sources.
        if digest(ROOT / 'clients/flutter' / name) != expected or (not name.startswith('windows/') and digest(build / 'client' / name) != expected):
            raise ValueError('Compiled client source changed: ' + name)
    reports = []
    for edition, previous in [('admin', 'astr_auto_anima_hub_admin-0.5.2-beta.1+44-android.apk'),
                              ('service', 'astr_auto_anima_hub_client-0.5.2-beta.1+44-android.apk')]:
        source = build / f'client/build/app/outputs/flutter-apk/app-{edition}-release.apk'
        old = inspect(baseline / previous, sdk)
        new = inspect(source, sdk)
        assert new['package_id'] == old['package_id'] == 'com.reln.astrautoanima.hubclient.' + edition
        assert new['signer_sha256'] == old['signer_sha256'], 'Signing identity changed'
        assert new['version_code'] == release['public_build'] > old['version_code']
        assert new['version_name'] == release['release']
        name = f'AstrAutoAnima-Android-{edition.title()}-{release["release"]}-build{release["public_build"]}.apk'
        target = output / name
        if target.exists():
            raise FileExistsError(target)
        reports.append(dict(new, name=name, edition=edition, baseline_sha256=old['sha256'],
                            baseline_version_code=old['version_code'], update_identity_matches=True))
    # Both editions must pass all checks before either is delivered.
    for row in reports:
        source = build / f'client/build/app/outputs/flutter-apk/app-{row["edition"]}-release.apk'
        target = output / row['name']
        shutil.copy2(source, target)
        assert digest(target) == row['sha256']
        identity['assets'].append({k: row[k] for k in ('name', 'size', 'sha256')})
    report = {'version': identity['version'], 'client_source_commit': identity['source_commit'],
        'apks': reports, 'physical_device_tested': False, 'published': False}
    (output / 'verification/android-apk-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    (output / 'candidate-assets.json').write_text(json.dumps(identity, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in identity['assets']), encoding='ascii')
    (output / 'ANDROID_SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in reports), encoding='ascii')
    shutil.copy2(ROOT / 'docs/NEXT_ANDROID_UPDATE.md', output / '02_安卓安装与更新说明.txt')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('build-dir', 'baseline', 'output', 'build-tools'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    package(a.build_dir, a.baseline, a.output, a.build_tools)
