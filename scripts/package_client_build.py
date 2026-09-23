"""Package a just-built client; run outside personal home paths when compiling."""
import argparse
from pathlib import Path
import shutil
from build_release_archives import VERSION, write_zip


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--platform', choices=['web', 'windows', 'android'], required=True)
    p.add_argument('--edition', choices=['admin', 'service'], default='service')
    a = p.parse_args()
    if f'version: {VERSION}+' not in (a.client / 'pubspec.yaml').read_text('utf-8'):
        raise ValueError('Build source version differs from release version')
    a.output.mkdir(parents=True, exist_ok=True)
    edition = a.edition.capitalize()
    if a.platform == 'android':
        source = a.client / f'build/app/outputs/flutter-apk/app-{a.edition}-release.apk'
        if not source.is_file():
            raise FileNotFoundError(source)
        target = a.output / f'AstrAutoAnima-Android-{edition}-{VERSION}.apk'
        if target.exists():
            raise FileExistsError(target)
        shutil.copy2(source, target)
    else:
        base = a.client / ('build/web' if a.platform == 'web' else 'build/windows/x64/runner/Release')
        if not base.is_dir():
            raise FileNotFoundError(base)
        label = 'Web' if a.platform == 'web' else 'Windows-' + edition
        target = a.output / f'AstrAutoAnima-{label}-{VERSION}.zip'
        if target.exists():
            raise FileExistsError(target)
        files = [f for f in base.rglob('*') if f.is_file() and f.suffix not in {'.pdb', '.map'}]
        if not files:
            raise ValueError('Empty build')
        write_zip(target, [(f, f.relative_to(base).as_posix()) for f in files])
    print(target)


if __name__ == '__main__':
    main()
