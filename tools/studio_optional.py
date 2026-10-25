"""Opt-in AnimaLoraStudio installer. No existing Studio upgrade or process control."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

REPOSITORY = 'https://github.com/WalkingMeatAxolotl/AnimaLoraStudio'
COMMIT = 'd049ccfafbd3ce19cb65570e7172f84ae2195e61'
VERSION = '0.25.0'
CONNECTOR = '0.1.1'
COMPONENT_ID = 'anima-lora-studio'
RESOURCE = Path(__file__).resolve().parents[1] / 'optional/studio'


def no_links(path: Path) -> Path:
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('必须使用不含 .. 的绝对路径')
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and part.lstat().st_file_attributes & 0x400
                                if os.name == 'nt' else False):
            raise ValueError('路径不能包含链接或 junction：' + str(part))
    if path.resolve() != path:
        raise ValueError('路径不规范：' + str(path))
    return path


def studio_version(root: Path) -> str:
    no_links(root)
    path = no_links(root / 'studio/__init__.py')
    for node in ast.parse(path.read_text('utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets):
            return str(ast.literal_eval(node.value))
    raise ValueError('未能识别 Studio 版本')


def read_connector(resource: Path = RESOURCE) -> tuple[dict[str, bytes], str]:
    package = no_links(resource.resolve() / f'AAA_Studio025_Connector-{CONNECTOR}.zip')
    expected = json.loads((resource / 'package.json').read_text('utf-8'))['connector_sha256']
    raw = package.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('连接器校验失败')
    result = {}
    with zipfile.ZipFile(package) as archive:
        total = 0
        for item in archive.infolist():
            name = item.filename
            posix = PurePosixPath(name)
            if (not name or name.startswith('/') or '\\' in name or ':' in name
                    or any(p in {'.', '..'} for p in name.split('/'))
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('不安全的连接器路径：' + name)
            if item.is_dir():
                continue
            total += item.file_size
            if total > 64 * 1024**2 or item.file_size > 20 * 1024**2:
                raise ValueError('连接器体积异常')
            key = str(posix).casefold()
            if key in {n.casefold() for n in result}:
                raise ValueError('连接器路径重复')
            result[name] = archive.read(item)
    required = {'manifest.json', 'web/index.html', 'LICENSE', 'SOURCE.json',
                'source/studio-web-corresponding-source.zip'}
    if not required <= result.keys():
        raise ValueError('连接器缺少前端、许可或对应源码')
    manifest = json.loads(result['manifest.json'])
    if manifest['id'] != COMPONENT_ID or manifest['version'] != CONNECTOR:
        raise ValueError('连接器身份不符')
    source = json.loads(result['SOURCE.json'])
    if hashlib.sha256(result[source['corresponding_source']]).hexdigest() != source['sha256']:
        raise ValueError('连接器对应源码校验失败')
    return result, expected


def registry_state(root: Path) -> tuple[bytes | None, dict]:
    no_links(root)
    path = no_links(root / 'active.json')
    raw = path.read_bytes() if path.exists() else None
    data = json.loads(raw) if raw is not None else {'schema_version': 1, 'extensions': {}}
    if set(data) != {'schema_version', 'extensions'} or data['schema_version'] != 1 or not isinstance(data['extensions'], dict):
        raise ValueError('现有扩展注册表异常，停止')
    if COMPONENT_ID in data['extensions']:
        raise ValueError('已有炼丹炉注册项；本安装器不覆盖、不升级现有连接器')
    target = no_links(root / 'packages' / COMPONENT_ID / CONNECTOR)
    if target.exists():
        raise ValueError('连接器目录已存在；停止重复安装')
    return raw, data


def install_connector(root: Path, payload: dict[str, bytes]) -> None:
    before, data = registry_state(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.aaa-studio-install.lock'
    # Exclusive lock is intentionally retained: do not silently rerun a partial install.
    with lock.open('x', encoding='utf-8') as stream:
        stream.write('Do not rerun. Read installation result before manual recovery.\n')
    target = root / 'packages' / COMPONENT_ID / CONNECTOR
    no_links(target)
    target.mkdir(parents=True, exist_ok=False)
    for name, content in payload.items():
        path = no_links(target / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(content)
    current = root / 'active.json'
    no_links(current)
    if (current.read_bytes() if current.exists() else None) != before:
        raise ValueError('安装期间扩展注册表发生变化；未启用新连接器')
    if before is not None:
        fd, backup = tempfile.mkstemp(prefix='active.before-studio-', suffix='.json', dir=root)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(before)
        print('仅注册表备份：', backup)
    data['extensions'][COMPONENT_ID] = {'version': CONNECTOR, 'enabled': True}
    fd, temporary = tempfile.mkstemp(prefix='active.studio-', suffix='.json', dir=root)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    if (current.read_bytes() if current.exists() else None) != before:
        raise ValueError('注册表已变化；保留临时文件，不覆盖')
    os.replace(temporary, current)
    print('连接器已启用；旧数据、图片、模型未修改。请在管理端刷新扩展入口。')


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout.strip()


def fetch(destination: Path) -> None:
    no_links(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('新装目录必须不存在，且父目录必须已存在')
    git = shutil.which('git')
    if not git:
        raise ValueError('请先安装 Git')
    destination.mkdir()
    print('下载失败会保留当前新建目录，不删除任何文件：', destination)
    run([git, 'init', '.'], destination)
    run([git, 'remote', 'add', 'origin', REPOSITORY + '.git'], destination)
    run([git, 'fetch', '--depth', '1', 'origin', COMMIT], destination)
    run([git, '-c', 'core.hooksPath=.git/aaa-disabled-hooks', 'checkout', '--detach', 'FETCH_HEAD'], destination)
    if run([git, 'rev-parse', 'HEAD'], destination) != COMMIT or studio_version(destination) != VERSION:
        raise ValueError('上游提交或版本与锁定值不符；停止')
    print('官方提交及 Studio 版本已核对：', COMMIT, VERSION)


def bootstrap(destination: Path) -> None:
    # Only a fresh directory fetched during this invocation may reach this method.
    # Official bootstrap creates its own venv; never uses Hub/ComfyUI's environment.
    no_links(destination)
    if sys.platform == 'win32':
        command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'studio.bat', 'build']
    elif sys.platform.startswith('linux'):
        command = ['bash', 'studio.sh', 'build']
    else:
        raise ValueError('本安装器仅验证 Windows/Linux；不承诺 macOS GPU 训练')
    print('运行上游安装器并构建前端；可能下载多 GB 的依赖，不启动训练或服务。', flush=True)
    subprocess.run(command, cwd=destination, check=True, stdin=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--destination', type=Path, help='全新 Studio 绝对目录（不得已存在）')
    group.add_argument('--existing', type=Path, help='已安装的 Studio 0.25.x，只检查版本/接入')
    parser.add_argument('--plugin-data', type=Path, help='AAA 实际插件数据目录；不填则只安装独立 Studio')
    parser.add_argument('--extensions-root', type=Path, help='配置了 AAH_EXTENSIONS_ROOT 时用该绝对路径')
    parser.add_argument('--install-dependencies', action='store_true', help='新装时调用官方脚本建立环境和前端')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--accept-license', action='store_true')
    args = parser.parse_args(argv)
    if args.plugin_data and args.extensions_root:
        parser.error('--plugin-data 与 --extensions-root 二选一')
    if args.existing and args.install_dependencies:
        parser.error('已有 Studio 不执行依赖安装/更新，请使用原项目管理方式')
    source = no_links(args.existing or args.destination)
    if args.existing:
        if not studio_version(source).startswith('0.25.'):
            raise ValueError('当前连接器仅兼容 Studio 0.25.x；新版请独立使用，勿降级')
    elif source.exists() or not source.parent.is_dir():
        raise ValueError('新装目录必须不存在且父目录已存在，不覆盖已有安装')
    if args.install_dependencies and (not shutil.which('node') or not shutil.which('npm')):
        raise ValueError('安装依赖前请先配置 Node.js 18+ / npm')
    root = args.extensions_root
    if args.plugin_data:
        no_links(args.plugin_data)
        if not args.plugin_data.is_dir():
            raise ValueError('插件数据目录必须已存在；请勿选择代码目录')
        root = args.plugin_data / 'hub_state/extensions'
    payload = None
    if root:
        no_links(root)
        if root == source or root in source.parents or source in root.parents:
            raise ValueError('Studio 与 Hub 扩展目录不能包含彼此')
        payload, _ = read_connector()
        registry_state(root)
    print('第三方项目：AnimaLoraStudio / WalkingMeatAxolotl 与贡献者')
    print('原项目：', REPOSITORY)
    print('许可：GPL-3.0；部分组件 Apache-2.0，模型另计；AAA 仅提供可选接入。')
    print('兼容基线：Studio 0.25.x；不声称这是上游最新版。')
    print('Studio：', source)
    print('扩展目录：', root or '不接入，只准备独立 Studio')
    print('不重启任何服务、不改现有训练、不开公网端口、不下载模型。')
    if not args.apply:
        print('预检完成：未下载、安装或修改。确认后加 --apply --accept-license。')
        return 0
    if not args.accept_license:
        raise ValueError('请阅读上游许可后显式添加 --accept-license')
    if args.destination:
        fetch(source)
        if args.install_dependencies:
            bootstrap(source)
    if root and payload:
        install_connector(root, payload)
    print('服务未启动。进入 Studio 目录后运行：')
    print('  studio.bat run --host 127.0.0.1 --port 8765 --no-browser' if sys.platform == 'win32'
          else '  bash studio.sh run --host 127.0.0.1 --port 8765 --no-browser')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print('安装停止，已有服务/训练/数据未清理：', exc, file=sys.stderr)
        raise SystemExit(1)
