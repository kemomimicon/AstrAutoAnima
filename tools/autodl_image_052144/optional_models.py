"""Opt-in optional weights only. Reuses AAA's verified, resumable downloader."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

DEFAULT_TOOLS = Path('/root/AstrAutoAnima/tools')
DEFAULT_COMFY = Path('/root/autodl-tmp/aaa-install/ComfyUI')
SEED_REV = '09ced71023636e9bc8cdf9cdecfb2625d1e691e8'
SEED_FP16 = [
    {'target': 'models/SEEDVR2/seedvr2_ema_3b_fp16.safetensors', 'size': 6783018808,
     'sha256': '2fd0e03a3dad24e07086750360727ca437de4ecd456f769856e960ae93e2b304',
     'url': f'https://huggingface.co/numz/SeedVR2_comfyUI/resolve/{SEED_REV}/seedvr2_ema_3b_fp16.safetensors?download=true'},
    {'target': 'models/SEEDVR2/ema_vae_fp16.safetensors', 'size': 501324814,
     'sha256': '20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1',
     'url': f'https://huggingface.co/numz/SeedVR2_comfyUI/resolve/{SEED_REV}/ema_vae_fp16.safetensors?download=true'},
]
PROFILES = {
    'seedvr2-fp16': ('seedvr2_models_fp16', 'SeedVR2 3B FP16 + VAE'),
    'seedvr2-q4': ('seedvr2_models_q4', 'SeedVR2 3B Q4 + VAE'),
    'seedvr2-q8': ('seedvr2_models_q8', 'SeedVR2 3B Q8 + VAE'),
    'joycaption-q4': ('joycaption_models_q4', 'JoyCaption Q4 + mmproj'),
    'joycaption-q6': ('joycaption_models', 'JoyCaption Q6 + mmproj'),
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            value.update(block)
    return value.hexdigest()


def records(profile, tools):
    identifier = PROFILES[profile][0]
    if identifier is None:
        return [dict(row) for row in SEED_FP16]
    catalog = json.loads((tools / 'optional_components.json').read_text('utf-8-sig'))
    item = next(x for x in catalog['components'] if x['id'] == identifier)
    if item['kind'] != 'download_set':
        raise ValueError('Expected weights-only component')
    return item['files']


def validate_record(row):
    path = Path(row['target'])
    if (path.is_absolute() or '..' in path.parts or '\\' in row['target'] or ':' in row['target']
            or not row['target'].startswith('models/')):
        raise ValueError('Unsafe model target')
    sha = row.get('sha256', '')
    if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or row.get('size', 0) <= 0:
        raise ValueError('Missing fixed model size/SHA256')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--tools-root', type=Path, default=DEFAULT_TOOLS)
    parser.add_argument('--comfy-root', type=Path, default=DEFAULT_COMFY)
    parser.add_argument('--mode', choices=('official', 'mirror', 'modelscope', 'proxy'), default='official')
    parser.add_argument('--hf-mirror', default='')
    parser.add_argument('--proxy', default='')
    parser.add_argument('--local-dir', type=Path, help='Import already downloaded files by basename, without network')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--accept-model-license', action='store_true')
    args = parser.parse_args(argv)
    if args.list:
        for key, (_, label) in PROFILES.items():
            print(key, label)
        return 0
    if not args.profile:
        if not sys.stdin.isatty():
            parser.print_help()
            return 0
        keys = list(PROFILES)
        for index, key in enumerate(keys, 1):
            print(index, PROFILES[key][1])
        answer = input('Choose 1-5 (0 cancels): ').strip()
        if answer == '0':
            return 0
        if answer not in {str(x) for x in range(1, len(keys) + 1)}:
            raise ValueError('Invalid selection')
        args.profile = keys[int(answer) - 1]
        mirror = input('Optional HTTPS Hugging Face mirror (blank = official): ').strip()
        if mirror:
            args.mode, args.hf_mirror = 'mirror', mirror
        interactive_consent = True
    else:
        interactive_consent = False
    tools = args.tools_root.expanduser().absolute()
    if not (tools / 'easy_installer.py').is_file():
        raise ValueError('AAA tools missing; use the complete image/tools package, or --tools-root')
    sys.path.insert(0, str(tools))
    from deployment_support import no_links
    from download_network import DownloadNetwork
    from easy_installer import download_file
    root = args.comfy_root.expanduser().absolute()
    no_links(root)
    if not (root / 'main.py').is_file():
        raise ValueError('Select an existing ComfyUI root')
    network = DownloadNetwork(mode=args.mode, hf_mirror=args.hf_mirror, proxy=args.proxy)
    network.validate()
    selected = records(args.profile, tools)
    for row in selected:
        validate_record(row)
        no_links(root / row['target'])
        print(row['target'], f"{row['size']:,} bytes", '\n  source:', row['url'])
    print('Weights only: no node/dependency installation, service restart, workflow rewrite or GPU job.')
    print('Quantized variants can lose detail; model file size is not the VRAM requirement. Tiling is not enabled.')
    if args.profile.startswith('joycaption'):
        print('JoyCaption also needs its compatible node and a CUDA-enabled llama-cpp-python build; these are NOT installed by this weights script.')
    if locals().get('interactive_consent', False):
        if input('Review the source/model licenses above. Download this profile? Type YES: ').strip() != 'YES':
            return 0
        args.apply = args.accept_model_license = True
    if not args.apply:
        print('PREVIEW ONLY. Add --apply --accept-model-license to download/import.')
        return 0
    if not args.accept_model_license:
        raise ValueError('Read upstream model license and pass --accept-model-license')
    if args.local_dir:
        imports = []
        for row in selected:
            target = root / row['target']
            source = args.local_dir / target.name
            no_links(source)
            if not source.is_file() or source.stat().st_size != row['size'] or digest(source) != row['sha256']:
                raise ValueError('Local file size/SHA256 mismatch: ' + source.name)
            if target.exists():
                if not target.is_file() or target.stat().st_size != row['size'] or digest(target) != row['sha256']:
                    raise ValueError('Existing target conflict; no overwrite: ' + target.name)
                continue
            imports.append((source, target, row))
        for source, target, row in imports:
            target.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(target.parent).free < row['size'] + 32 * 1024**2:
                raise ValueError('Insufficient disk space')
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024**2)
            if digest(target) != row['sha256']:
                raise ValueError('Imported file readback failed; retained for inspection')
            print('VERIFIED_LOCAL_IMPORT', target)
    else:
        for row in selected:
            download_file(row['url'], root / row['target'], print,
                          expected_sha256=row['sha256'], expected_size=row['size'],
                          network=network, modelscope_url=row.get('modelscope_url', ''))
    print('Selected weights verified. Restart ComfyUI when idle and select the downloaded variant manually.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('STOPPED:', exc, file=sys.stderr)
        raise SystemExit(1)
