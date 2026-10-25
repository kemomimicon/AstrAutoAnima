"""Build a private offline resource candidate from exactly four allowed files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import zipfile

from deployment_support import clean_path, no_links
from gufeng_resource import (CATALOG_SHA256, CATALOG_VERSION, FILES, MANIFEST,
                             MAX_TOTAL_BYTES, inspect_module, sha256_file)

RELEASE_ROOT = Path(__file__).resolve().parents[1]


def build_candidate(source, output, *, apply=False, log=print):
    source, output = Path(source).absolute(), Path(output).absolute()
    no_links(source)
    no_links(output)
    if not source.is_dir():
        raise ValueError('请选择原资源目录')
    if output.resolve().is_relative_to(RELEASE_ROOT.resolve()):
        raise ValueError('逐来源授权待核对，私有资源候选禁止写入正式公开源码/包目录')
    if output.exists():
        raise ValueError('候选输出已存在，不覆盖；请选择新 ZIP 文件名')
    if output.suffix.lower() != '.zip':
        raise ValueError('私有候选输出必须为 ZIP')
    records = {}
    # Never enumerate/copy the surrounding E: tree, node code, or credentials.
    for name in FILES:
        path = source / name
        no_links(path)
        if not path.is_file():
            raise ValueError('资源白名单文件缺失：' + name)
        records[name] = {'size': path.stat().st_size, 'sha256': sha256_file(path)}
    if records['data/cards.sqlite3']['sha256'] != CATALOG_SHA256:
        raise ValueError('源数据库 SHA256 与固定 0.4.0 版本不符')
    if sum(item['size'] for item in records.values()) > MAX_TOTAL_BYTES:
        raise ValueError('源资源大小异常')
    catalog = json.loads((source / 'data/catalog_manifest.json').read_text('utf-8-sig'))
    if catalog.get('version') != CATALOG_VERSION or catalog.get('catalog_sha256') != CATALOG_SHA256:
        raise ValueError('源 catalog_manifest 版本/散列不匹配')
    manifest = {
        'schema_version': 1, 'id': 'gufeng', 'version': CATALOG_VERSION,
        'private_candidate': True, 'redistribution_status': 'pending-source-review',
        'notice': 'Source attribution preserved; public redistribution requires a separate source-by-source review.',
        'files': records,
    }
    available_at = output.parent
    while not available_at.exists():
        available_at = available_at.parent
    if shutil.disk_usage(available_at).free < sum(item['size'] for item in records.values()) + 32 * 1024 * 1024:
        raise ValueError('私有候选输出磁盘空间不足')
    if not apply:
        log('白名单与固定 SHA256 预检通过；未写入。追加 --apply 生成私有候选 ZIP，禁止直接公开分发。')
        return manifest
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in FILES:
            item = zipfile.ZipInfo(name)
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            with (source / name).open('rb') as incoming, archive.open(item, 'w', force_zip64=True) as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    # Stream every payload back through the same installer checks; no DB staging copy.
    inspect_module(output)
    log('私有候选 ZIP 已回读校验：' + str(output))
    log('SHA256 ' + sha256_file(output))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='包含 data/cards.sqlite3、data/catalog_manifest.json、README.md、SOURCES.md 的原资源目录')
    parser.add_argument('--output', required=True, help='公开源码目录之外的私有候选 ZIP')
    parser.add_argument('--apply', action='store_true', help='预检通过后写入单份压缩资源模块')
    args = parser.parse_args()
    build_candidate(clean_path(args.source), clean_path(args.output), apply=args.apply)


if __name__ == '__main__':
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except Exception as exc:
        print('国风资源候选打包失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
