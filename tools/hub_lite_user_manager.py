from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


QQ_PATTERN = re.compile(r"^[1-9][0-9]{4,14}$")


class ManagerError(RuntimeError):
    pass


def parse_qq_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(
            item for item in re.split(r"[,，;；\s]+", str(value)) if item
        )
    invalid = [item for item in result if not QQ_PATTERN.fullmatch(item)]
    if invalid:
        raise ManagerError(f"无效 QQ 号：{', '.join(invalid[:5])}")
    if len(result) != len(set(result)):
        raise ManagerError("输入中存在重复 QQ 号")
    if not result:
        raise ManagerError("请至少输入一个 QQ 号")
    return result


def load_registry(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "users": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagerError(f"无法读取注册表：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        raise ManagerError("注册表必须是包含 users 数组的 JSON 对象")
    return data


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.backup_{stamp}")
    index = 2
    while backup.exists():
        backup = path.with_name(f"{path.name}.backup_{stamp}_{index}")
        index += 1
    shutil.copy2(path, backup)
    return backup


def save_registry(path: Path, payload: dict[str, object]) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup(path)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return backup


def add_users(
    path: Path,
    qq_values: list[str],
    *,
    allow_group: bool = True,
    rotate_existing: bool = False,
) -> tuple[list[tuple[str, str]], Path | None]:
    payload = load_registry(path)
    users = payload["users"]
    assert isinstance(users, list)
    existing = {
        str(item.get("qq", "")): item
        for item in users
        if isinstance(item, dict) and str(item.get("qq", ""))
    }
    duplicates = [qq for qq in qq_values if qq in existing]
    if duplicates and not rotate_existing:
        raise ManagerError(
            "QQ 已存在；如需换发令牌请启用 rotate-existing："
            + ", ".join(duplicates[:5])
        )

    issued: list[tuple[str, str]] = []
    for qq in qq_values:
        token = f"aah_u_{secrets.token_urlsafe(32)}"
        record = {
            "id": f"qq-{qq}",
            "label": f"QQ {qq}",
            "qq": qq,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "allow_group": allow_group,
            "enabled": True,
        }
        if qq in existing:
            current = existing[qq]
            assert isinstance(current, dict)
            current.clear()
            current.update(record)
        else:
            users.append(record)
            existing[qq] = record
        issued.append((qq, token))
    payload["version"] = 1
    return issued, save_registry(path, payload)


def set_enabled(path: Path, qq_values: list[str], enabled: bool) -> Path | None:
    payload = load_registry(path)
    users = payload["users"]
    assert isinstance(users, list)
    wanted = set(qq_values)
    found: set[str] = set()
    for item in users:
        if isinstance(item, dict) and str(item.get("qq", "")) in wanted:
            item["enabled"] = enabled
            found.add(str(item["qq"]))
    missing = sorted(wanted - found)
    if missing:
        raise ManagerError(f"注册表中没有这些 QQ：{', '.join(missing)}")
    return save_registry(path, payload)


def write_delivery(path: Path, issued: list[tuple[str, str]]) -> None:
    if path.exists():
        raise ManagerError("明文令牌交付表已存在，请换一个文件名")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["qq", "token"])
        writer.writerows(issued)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def list_users(path: Path) -> list[dict[str, object]]:
    payload = load_registry(path)
    users = payload["users"]
    assert isinstance(users, list)
    return [item for item in users if isinstance(item, dict)]


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise ManagerError("当前 Python 缺少 Tkinter，请使用命令行模式") from exc

    root = tk.Tk()
    root.title("AstrAutoAnima Hub 用户与令牌管理器")
    root.geometry("760x600")
    registry_var = tk.StringVar(value=str(Path.cwd() / "lite_users.json"))
    delivery_var = tk.StringVar(
        value=str(Path.cwd() / f"lite_tokens_{datetime.now():%Y%m%d_%H%M%S}.csv")
    )
    rotate_var = tk.BooleanVar(value=False)
    group_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="令牌明文只写入交付 CSV，请勿提交到 Git。")

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    def choose_file(variable: tk.StringVar, save: bool, title: str) -> None:
        value = (
            filedialog.asksaveasfilename(title=title, defaultextension=".json")
            if save
            else filedialog.askopenfilename(title=title)
        )
        if value:
            variable.set(value)

    ttk.Label(frame, text="注册表 JSON：").grid(row=0, column=0, sticky="w")
    ttk.Entry(frame, textvariable=registry_var).grid(row=0, column=1, sticky="ew")
    ttk.Button(
        frame,
        text="选择",
        command=lambda: choose_file(registry_var, True, "选择或创建 lite_users.json"),
    ).grid(row=0, column=2, padx=6)

    ttk.Label(frame, text="明文交付 CSV：").grid(row=1, column=0, sticky="w", pady=8)
    ttk.Entry(frame, textvariable=delivery_var).grid(row=1, column=1, sticky="ew")
    ttk.Button(
        frame,
        text="选择",
        command=lambda: delivery_var.set(
            filedialog.asksaveasfilename(
                title="选择新的令牌交付 CSV",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
            )
            or delivery_var.get()
        ),
    ).grid(row=1, column=2, padx=6)

    ttk.Label(frame, text="QQ 号（每行一个）：").grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(12, 4)
    )
    qq_text = tk.Text(frame, height=12)
    qq_text.grid(row=3, column=0, columnspan=3, sticky="nsew")
    frame.rowconfigure(3, weight=1)
    ttk.Checkbutton(frame, text="允许群聊目标", variable=group_var).grid(
        row=4, column=0, sticky="w", pady=8
    )
    ttk.Checkbutton(
        frame, text="已存在用户换发新令牌", variable=rotate_var
    ).grid(row=4, column=1, sticky="w", pady=8)
    ttk.Label(frame, textvariable=status_var, wraplength=700).grid(
        row=5, column=0, columnspan=3, sticky="ew", pady=8
    )

    def issue() -> None:
        try:
            values = parse_qq_values([qq_text.get("1.0", "end")])
            issued, backup = add_users(
                Path(registry_var.get().strip()),
                values,
                allow_group=group_var.get(),
                rotate_existing=rotate_var.get(),
            )
            delivery = Path(delivery_var.get().strip())
            write_delivery(delivery, issued)
            status_var.set(
                f"已添加/换发 {len(issued)} 位用户；交付表：{delivery}"
                + (f"；备份：{backup}" if backup else "")
            )
            messagebox.showinfo("完成", status_var.get())
        except Exception as exc:
            messagebox.showerror("操作失败", str(exc))

    def show_users() -> None:
        try:
            users = list_users(Path(registry_var.get().strip()))
            lines = [
                f"{item.get('qq')} | {'启用' if item.get('enabled', True) else '停用'} | "
                f"群聊={'是' if item.get('allow_group', True) else '否'}"
                for item in users
            ]
            messagebox.showinfo("当前用户", "\n".join(lines) or "注册表为空")
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    buttons = ttk.Frame(frame)
    buttons.grid(row=6, column=0, columnspan=3, pady=10)
    ttk.Button(buttons, text="添加并生成令牌", command=issue).pack(
        side="left", padx=8
    )
    ttk.Button(buttons, text="查看已有用户", command=show_users).pack(
        side="left", padx=8
    )
    ttk.Button(buttons, text="退出", command=root.destroy).pack(side="left", padx=8)
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hub Lite 用户与令牌离线管理器")
    sub = parser.add_subparsers(dest="command")
    add = sub.add_parser("add", help="追加用户并生成一次性明文令牌")
    add.add_argument("--registry", type=Path, required=True)
    add.add_argument("--delivery", type=Path, required=True)
    add.add_argument("--qq", action="append", default=[])
    add.add_argument("--qq-file", type=Path)
    add.add_argument("--no-group", action="store_true")
    add.add_argument("--rotate-existing", action="store_true")
    for name in ("enable", "disable"):
        command = sub.add_parser(name, help=f"{name} 用户")
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--qq", action="append", required=True)
    listing = sub.add_parser("list", help="列出用户，不显示令牌哈希")
    listing.add_argument("--registry", type=Path, required=True)
    sub.add_parser("gui", help="启动图形界面")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {None, "gui"}:
        return launch_gui()
    if args.command == "list":
        for item in list_users(args.registry):
            print(
                item.get("qq"),
                "enabled=" + str(bool(item.get("enabled", True))).lower(),
                "allow_group=" + str(bool(item.get("allow_group", True))).lower(),
            )
        return 0
    if args.command in {"enable", "disable"}:
        values = parse_qq_values(args.qq)
        backup = set_enabled(args.registry, values, args.command == "enable")
        print(f"已更新 {len(values)} 位用户；备份：{backup or '无'}")
        return 0
    raw_values = list(args.qq)
    if args.qq_file:
        raw_values.append(args.qq_file.read_text(encoding="utf-8-sig"))
    values = parse_qq_values(raw_values)
    issued, backup = add_users(
        args.registry,
        values,
        allow_group=not args.no_group,
        rotate_existing=args.rotate_existing,
    )
    write_delivery(args.delivery, issued)
    print(f"已添加/换发 {len(issued)} 位用户")
    print(f"注册表：{args.registry}")
    print(f"交付表：{args.delivery}")
    print(f"备份：{backup or '无'}")
    print("警告：交付表含明文令牌，不要上传到 Git、群聊或公开网盘。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
