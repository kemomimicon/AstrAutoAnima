"""Offline, opt-in GuFeng resource installation; no ComfyUI node or network use."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from deployment_support import no_links

CATALOG_VERSION = '0.4.0'
CATALOG_SHA256 = '2ce071962a67e97b0d60874dc6be033dfaf849f39c455bcd58ed3caf8aacea07'
ENV_KEY = 'AAH_LOCAL_GUFENG_CATALOG_PATH'
MODULE_NAME = 'gufeng-private-candidate-0.4.0.zip'
FILES = {
    'data/cards.sqlite3': 'cards.sqlite3',
    'data/catalog_manifest.json': 'catalog_manifest.json',
    'README.md': 'UPSTREAM_README.md',
    'SOURCES.md': 'SOURCES.md',
}
MANIFEST = 'resource-module.json'
MAX_TOTAL_BYTES = 1_200_000_000


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return sha256_stream(stream)


def sha256_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


@contextmanager
def module_files(module):
    """Expose only the fixed payload allowlist, without extracting archive paths."""
    module = Path(module).absolute()
    no_links(module)
    allowed = set(FILES) | {MANIFEST}
    if module.is_dir():
        for name in allowed:
            path = module / name
            no_links(path)
            if not path.is_file():
                raise ValueError('国风模块缺少文件：' + name)
        yield lambda name: (module / name).open('rb'), {
            name: (module / name).stat().st_size for name in allowed
        }
    elif module.is_file() and zipfile.is_zipfile(module):
        with zipfile.ZipFile(module) as archive:
            entries = archive.infolist()
            if len(entries) != len(allowed) or {item.filename for item in entries} != allowed:
                raise ValueError('国风 ZIP 文件清单异常；仅接受私有候选资源模块')
            for item in entries:
                kind = (item.external_attr >> 16) & 0o170000
                if item.is_dir() or kind not in (0, 0o100000) or item.flag_bits & 1:
                    raise ValueError('国风 ZIP 含链接或非普通文件')
            yield archive.open, {item.filename: item.file_size for item in entries}
    else:
        raise ValueError('未找到国风离线资源模块；请先按 optional/gufeng/README.md 组装私有候选模块')


def inspect_module(module):
    with module_files(module) as (open_file, sizes):
        if sum(sizes.values()) > MAX_TOTAL_BYTES or sizes[MANIFEST] > 64_000:
            raise ValueError('国风资源模块大小异常')
        with open_file(MANIFEST) as stream:
            manifest = json.load(stream)
        if (manifest.get('schema_version') != 1 or manifest.get('id') != 'gufeng'
                or manifest.get('version') != CATALOG_VERSION
                or manifest.get('redistribution_status') != 'pending-source-review'
                or manifest.get('private_candidate') is not True):
            raise ValueError('国风模块声明不匹配，或缺少逐来源再分发待核对标识')
        records = manifest.get('files', {})
        if set(records) != set(FILES):
            raise ValueError('国风模块必须完整保留数据库、清单、README 与 SOURCES 署名')
        if not isinstance(records['data/cards.sqlite3'], dict) or records['data/cards.sqlite3'].get('sha256') != CATALOG_SHA256:
            raise ValueError('国风数据库 SHA256 不符合固定版本')
        for name, record in records.items():
            if not isinstance(record, dict) or record.get('size') != sizes[name]:
                raise ValueError('国风资源文件大小不匹配：' + name)
            with open_file(name) as stream:
                if sha256_stream(stream) != record.get('sha256'):
                    raise ValueError('国风资源 SHA256 校验失败：' + name)
        with open_file('data/catalog_manifest.json') as stream:
            catalog = json.load(stream)
        if catalog.get('version') != CATALOG_VERSION or catalog.get('catalog_sha256') != CATALOG_SHA256:
            raise ValueError('国风 catalog_manifest 与数据库版本/散列不匹配')
        with open_file('data/cards.sqlite3') as stream:
            if stream.read(16) != b'SQLite format 3\x00':
                raise ValueError('国风数据库不是 SQLite 文件')
        return manifest


def validate_destination(root, manifest):
    target = Path(root) / 'hub/resources/gufeng'
    no_links(target)
    if target.exists() and not target.is_dir():
        raise ValueError('国风资源目标不是目录')
    missing_bytes = 0
    for source, name in FILES.items():
        path = target / name
        no_links(path)
        record = manifest['files'][source]
        if path.exists():
            if not path.is_file() or path.stat().st_size != record['size'] or sha256_file(path) != record['sha256']:
                raise ValueError('国风资源目标冲突，保留原文件，请人工核对：' + str(path))
        else:
            missing_bytes += record['size']
    module_record = target / MANIFEST
    no_links(module_record)
    if module_record.exists() and (not module_record.is_file() or json.loads(module_record.read_text('utf-8')) != manifest):
        raise ValueError('国风模块记录冲突，保留原文件')
    environment = Path(root) / 'runtime-env.local.json'
    no_links(environment)
    if not environment.exists():
        legacy = Path(root) / 'runtime-env.json'
        no_links(legacy)
        if legacy.is_file() and json.loads(legacy.read_text('utf-8')).get('AAH_EXECUTION_MODE') == 'local':
            environment = legacy
    if environment.is_file():
        existing = json.loads(environment.read_text('utf-8')).get(ENV_KEY)
        if existing and Path(existing).absolute() != (target / 'cards.sqlite3').absolute():
            raise ValueError('已有本机国风路径不同，不覆盖用户配置')
    available_at = target
    while not available_at.exists():
        available_at = available_at.parent
    if shutil.disk_usage(available_at).free < missing_bytes + 16 * 1024 * 1024:
        raise ValueError('国风资源目标磁盘空间不足')
    return target


def install_module(module, root, log=print):
    manifest = inspect_module(module)
    target = validate_destination(root, manifest)
    target.mkdir(parents=True, exist_ok=True)
    with module_files(module) as (open_file, _):
        for source, name in FILES.items():
            path = target / name
            if path.exists():
                log('国风资源相同 SHA256，复用：' + name)
                continue
            no_links(path)
            # Exclusive creation prevents replacing a file created since preflight.
            # A failed partial file is retained for inspection; never delete user data.
            with open_file(source) as incoming, path.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            if sha256_file(path) != manifest['files'][source]['sha256']:
                raise ValueError('国风资源复制后 SHA256 校验失败；保留文件，请人工核对：' + name)
    record = target / MANIFEST
    if not record.exists():
        with record.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    log('V · 国风古韵离线资源已校验；保留来源署名，公开再分发仍待逐来源核对')
    return target / 'cards.sqlite3'


def selected_module(plan, release):
    if not isinstance(plan.install_gufeng, bool):
        raise ValueError('install_gufeng 必须为布尔值 true / false')
    if plan.gufeng_module and not plan.install_gufeng:
        raise ValueError('选择国风模块后还需显式勾选安装，或追加 --install-gufeng')
    return Path(plan.gufeng_module) if plan.gufeng_module else Path(release) / 'optional/gufeng' / MODULE_NAME
