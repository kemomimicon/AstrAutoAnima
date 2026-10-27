"""Install the single-file 0.5.2-1.44 QQ Official admission repair."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid

NAME = 'platform_switchboard.py'


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def checked(path):
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() or bool(getattr(part.lstat(), 'st_file_attributes', 0) & 0x400)
           for part in (path, *path.parents) if part.exists()):
        raise ValueError('目录含链接，请选择真实插件目录。')
    return path


def locate(selected):
    selected = checked(selected)
    matches = [p for p in (selected, selected / 'data/plugins/astrbot_plugin_comfy_bridge',
                          selected / 'astrbot/data/plugins/astrbot_plugin_comfy_bridge',
                          selected / 'plugins/astrbot_plugin_comfy_bridge')
               if (p / NAME).is_file() and (p / 'main.py').is_file() and (p / 'metadata.yaml').is_file()]
    if len(matches) != 1:
        raise ValueError('请选择实际 astrbot_plugin_comfy_bridge 插件目录；找到的目录数量不是 1。')
    plugin = checked(matches[0])
    target = checked(plugin / NAME)
    if not target.is_file() or target.stat().st_nlink != 1:
        raise ValueError('目标必须是普通独立文件。')
    return plugin


def install(selected, bundle, *, apply=False, confirmed=False):
    plugin = locate(selected)
    target = plugin / NAME
    manifest = json.loads((bundle / 'patch-manifest.json').read_text('utf-8'))
    replacement = (bundle / 'plugin_files' / NAME).read_bytes()
    if digest(replacement) != manifest['replacement_sha256']:
        raise ValueError('补丁校验失败，请重新解压。')
    compile(replacement.decode('utf-8-sig'), NAME, 'exec')
    original = target.read_bytes()
    if digest(original) == manifest['replacement_sha256']:
        return '已安装本修复，无需重复更新。'
    if digest(original) != manifest['original_sha256']:
        raise ValueError('当前文件与本次发布基线不同；未覆盖，请把版本和报错反馈维护者。')
    if not apply:
        return '预检通过：仅替换 ' + str(target)
    if not confirmed:
        raise ValueError('请先正常退出 AstrBot，并确认服务已停止。')
    backup_root = checked(plugin.parent.parent / 'aaa_patch_backups')
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / ('qqofficial_admission_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex)
    backup.mkdir()
    old_file = backup / NAME
    with old_file.open('xb') as stream:
        stream.write(original)
    if old_file.read_bytes() != original or target.read_bytes() != original:
        raise ValueError('备份校验或原文件复核失败；未覆盖。')
    (backup / 'backup-info.json').write_text(json.dumps({
        'target': str(target), 'sha256': hashlib.sha256(original).hexdigest(),
        'replacement_sha256': hashlib.sha256(replacement).hexdigest()}, indent=2), encoding='utf-8')
    descriptor, temporary = tempfile.mkstemp(prefix='.qqofficial-', suffix='.tmp', dir=plugin)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
        if Path(temporary).read_bytes() != replacement or target.read_bytes() != original:
            raise ValueError('写入前校验失败；原文件保留。')
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return '更新完成，仅替换 ' + NAME + '\n备份：' + str(backup) + '\n请重启 AstrBot 后测试 /aimg。'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-stopped', action='store_true')
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    if args.gui:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askdirectory(title='选择已有安装目录或实际 AAA 插件目录', parent=root)
            if not selected:
                return
            result = install(Path(selected), bundle)
            if not result.startswith('预检通过'):
                messagebox.showinfo('QQ 官方机器人接单修复', result, parent=root)
                return
            if messagebox.askyesno('确认已退出 AstrBot', result + '\n\n请正常退出 AstrBot（含后台）。\n是否已停止，并开始自动备份和修复？', parent=root):
                messagebox.showinfo('修复完成', install(Path(selected), bundle, apply=True, confirmed=True), parent=root)
        except Exception as exc:
            messagebox.showerror('修复未完成', str(exc), parent=root)
            raise
        finally:
            root.destroy()
    else:
        if args.plugin_dir is None:
            parser.error('请填写 --plugin-dir，或 Windows 使用 --gui。')
        print(install(args.plugin_dir, bundle, apply=args.apply, confirmed=args.confirm_stopped))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('修复失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
