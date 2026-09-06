from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SOURCE_NAMES = {"B": "basic", "G": "generate", "D": "discord", "C": "codex", "R": "reverse"}
SAFETY_NAMES = {"N": "normal", "H": "nsfw", "S": "sexual"}
CUSTOM_GROUP_PATTERN = re.compile(r"^[^\s@/+,]{1,64}$", flags=re.UNICODE)


class PoolError(RuntimeError):
    pass


def empty_pool() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "catalog_revision": 1,
        "release_version": "custom",
        "description": "User-managed AstrAutoAnima prompt pool",
        "custom_group_definitions": [],
        "prompts": [],
    }


def load_pool(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_pool()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolError(f"无法读取提示词库：{exc}") from exc
    if isinstance(data, list):
        data = {**empty_pool(), "prompts": data}
    if not isinstance(data, dict) or not isinstance(data.get("prompts"), list):
        raise PoolError("JSON 必须是提示词数组，或包含 prompts 数组的对象")
    group_definitions(data)
    validate_records(data["prompts"])
    return data


def _split_values(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[|,，;；\n]+", raw) if item.strip()]


def normalize_group_id(value: str) -> str:
    group_id = str(value or "").strip().casefold()
    if not CUSTOM_GROUP_PATTERN.fullmatch(group_id):
        raise PoolError("分组 ID 长度须为 1-64，且不能包含空格或 @ / + ,")
    return group_id


def group_definitions(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.setdefault("custom_group_definitions", [])
    if not isinstance(raw, list):
        raise PoolError("custom_group_definitions 必须是数组")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            group_id = normalize_group_id(item)
            name = item.strip()
        elif isinstance(item, dict):
            group_id = normalize_group_id(str(item.get("id", "")))
            name = str(item.get("name", group_id)).strip() or group_id
        else:
            raise PoolError("自定义分组定义必须是字符串或对象")
        if group_id in seen:
            raise PoolError(f"重复的自定义分组 ID：{group_id}")
        seen.add(group_id)
        result.append({"id": group_id, "name": name})
    payload["custom_group_definitions"] = result
    return result


def normalize_record(raw: dict[str, Any], *, fallback_id: str = "") -> dict[str, Any]:
    prompt = str(raw.get("prompt", "")).strip()
    if not prompt:
        raise PoolError("提示词正文不能为空")
    record_id = str(raw.get("id", fallback_id)).strip()
    if not record_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", record_id):
        raise PoolError(f"无效 ID：{record_id!r}")
    source_code = str(raw.get("source_code", "B")).strip().upper()
    safety_code = str(raw.get("safety_code", "N")).strip().upper()
    if source_code not in SOURCE_NAMES:
        raise PoolError(f"不支持的来源组：{source_code}")
    if safety_code not in SAFETY_NAMES:
        raise PoolError(f"不支持的内容级别：{safety_code}")
    categories = raw.get("categories", [])
    if isinstance(categories, str):
        categories = _split_values(categories)
    if not isinstance(categories, list):
        raise PoolError(f"记录 {record_id} 的 categories 必须是数组")
    custom_groups = raw.get("custom_groups", [])
    if isinstance(custom_groups, str):
        custom_groups = _split_values(custom_groups)
    if not isinstance(custom_groups, list):
        raise PoolError(f"记录 {record_id} 的 custom_groups 必须是数组")
    normalized_groups = list(
        dict.fromkeys(normalize_group_id(str(value)) for value in custom_groups)
    )
    try:
        weight = float(raw.get("weight", 1))
    except (TypeError, ValueError) as exc:
        raise PoolError(f"记录 {record_id} 的 weight 不是数字") from exc
    if weight <= 0:
        raise PoolError(f"记录 {record_id} 的 weight 必须大于 0")
    result = dict(raw)
    result.update(
        {
            "id": record_id,
            "name": str(raw.get("name", record_id)).strip() or record_id,
            "enabled": bool(raw.get("enabled", True)),
            "weight": int(weight) if weight.is_integer() else weight,
            "prompt": prompt,
            "prompt_position": str(raw.get("prompt_position", "suffix")) or "suffix",
            "categories": [str(item).strip() for item in categories if str(item).strip()],
            "custom_groups": normalized_groups,
            "source_group": SOURCE_NAMES[source_code],
            "source_code": source_code,
            "safety_level": SAFETY_NAMES[safety_code],
            "safety_code": safety_code,
            "content_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
        }
    )
    result.setdefault("safety_matches", [])
    result.setdefault("duplicate_of", None)
    return result


def validate_records(records: list[Any]) -> None:
    ids: set[str] = set()
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict):
            raise PoolError(f"第 {index} 条不是 JSON 对象")
        record = normalize_record(raw)
        if record["id"].casefold() in ids:
            raise PoolError(f"重复 ID：{record['id']}")
        ids.add(record["id"].casefold())


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


def save_pool(path: Path, payload: dict[str, Any]) -> Path | None:
    records = payload.get("prompts", [])
    if not isinstance(records, list):
        raise PoolError("prompts 必须是数组")
    normalized = [normalize_record(item) for item in records]
    validate_records(normalized)
    output = dict(payload)
    output["schema_version"] = 3
    group_definitions(output)
    output["catalog_revision"] = int(payload.get("catalog_revision", 0)) + 1
    output["prompts"] = normalized
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup(path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            json.dump(output, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    payload.clear()
    payload.update(output)
    return backup


def merge_records(
    target: dict[str, Any], incoming: Iterable[dict[str, Any]], *, overwrite: bool
) -> tuple[int, int]:
    records = target["prompts"]
    assert isinstance(records, list)
    positions = {
        str(item.get("id", "")).casefold(): index
        for index, item in enumerate(records)
        if isinstance(item, dict)
    }
    added = updated = 0
    for raw in incoming:
        item = normalize_record(raw)
        key = item["id"].casefold()
        if key in positions:
            if not overwrite:
                continue
            records[positions[key]] = item
            updated += 1
        else:
            positions[key] = len(records)
            records.append(item)
            added += 1
    return added, updated


def remove_records(payload: dict[str, Any], ids: Iterable[str]) -> int:
    wanted = {item.strip().casefold() for item in ids if item.strip()}
    records = payload["prompts"]
    assert isinstance(records, list)
    before = len(records)
    payload["prompts"] = [
        item
        for item in records
        if str(item.get("id", "")).casefold() not in wanted
    ]
    return before - len(payload["prompts"])


def export_records(
    path: Path,
    records: list[dict[str, Any]],
    definitions: list[dict[str, str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.casefold() == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=("id", "name", "source_code", "safety_code", "enabled", "weight", "categories", "custom_groups", "prompt"),
            )
            writer.writeheader()
            for item in records:
                writer.writerow(
                    {
                        **{key: item.get(key, "") for key in writer.fieldnames or ()},
                        "categories": "|".join(item.get("categories", [])),
                        "custom_groups": "|".join(item.get("custom_groups", [])),
                    }
                )
    else:
        path.write_text(
            json.dumps(
                {
                    **empty_pool(),
                    "custom_group_definitions": definitions or [],
                    "prompts": records,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog, ttk
    except ImportError as exc:
        raise PoolError("当前 Python 缺少 Tkinter，请使用命令行模式") from exc

    root = tk.Tk()
    root.title("AstrAutoAnima 提示词库管理器")
    root.geometry("1120x760")
    current_path: Path | None = None
    payload = empty_pool()
    dirty = False
    filter_var = tk.StringVar()
    status_var = tk.StringVar(value="新建空提示词库；可打开现有 JSON。")

    outer = ttk.Frame(root, padding=10)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(2, weight=1)
    toolbar = ttk.Frame(outer)
    toolbar.grid(row=0, column=0, sticky="ew")
    ttk.Label(toolbar, text="搜索：").pack(side="left")
    search = ttk.Entry(toolbar, textvariable=filter_var, width=30)
    search.pack(side="left", padx=(0, 12))

    columns = ("id", "source", "safety", "groups", "enabled", "name")
    tree = ttk.Treeview(outer, columns=columns, show="headings", selectmode="browse")
    for name, title, width in (
        ("id", "ID", 180), ("source", "来源", 55), ("safety", "级别", 55),
        ("groups", "自定义分组", 180), ("enabled", "启用", 55), ("name", "名称", 260),
    ):
        tree.heading(name, text=title)
        tree.column(name, width=width, anchor="w")
    tree.grid(row=2, column=0, sticky="nsew", pady=8)

    editor = ttk.LabelFrame(outer, text="记录编辑", padding=10)
    editor.grid(row=3, column=0, sticky="ew")
    editor.columnconfigure(1, weight=1)
    fields = {name: tk.StringVar() for name in ("id", "name", "source", "safety", "weight", "categories", "groups")}
    enabled_var = tk.BooleanVar(value=True)
    for row, (name, label) in enumerate((
        ("id", "ID"), ("name", "名称"), ("source", "来源 B/G/D/C/R"),
        ("safety", "级别 N/H/S"), ("weight", "权重"), ("categories", "分类（| 分隔）"),
        ("groups", "自定义分组（| 分隔）"),
    )):
        ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(editor, textvariable=fields[name]).grid(row=row, column=1, sticky="ew", pady=2)
    ttk.Checkbutton(editor, text="启用", variable=enabled_var).grid(row=0, column=2, padx=12)
    ttk.Label(editor, text="提示词").grid(row=7, column=0, sticky="nw", pady=2)
    prompt_text = tk.Text(editor, height=7, wrap="word")
    prompt_text.grid(row=7, column=1, columnspan=2, sticky="ew", pady=2)

    def records() -> list[dict[str, Any]]:
        value = payload.get("prompts", [])
        assert isinstance(value, list)
        return value

    def refresh(*_args: object) -> None:
        tree.delete(*tree.get_children())
        query = filter_var.get().strip().casefold()
        for index, item in enumerate(records()):
            searchable = "\n".join(
                str(item.get(key, ""))
                for key in ("id", "name", "prompt", "categories", "custom_groups")
            ).casefold()
            if query and query not in searchable:
                continue
            tree.insert("", "end", iid=str(index), values=(
                item.get("id", ""), item.get("source_code", "B"), item.get("safety_code", "N"),
                "|".join(item.get("custom_groups", [])),
                "是" if item.get("enabled", True) else "否", item.get("name", ""),
            ))
        status_var.set(f"共 {len(records())} 条，当前显示 {len(tree.get_children())} 条" + ("（未保存）" if dirty else ""))

    def clear_editor() -> None:
        defaults = {"source": "B", "safety": "N", "weight": "1"}
        for name, variable in fields.items():
            variable.set(defaults.get(name, ""))
        enabled_var.set(True)
        prompt_text.delete("1.0", "end")
        tree.selection_remove(tree.selection())

    def selected_index() -> int | None:
        selected = tree.selection()
        return int(selected[0]) if selected else None

    def load_selection(_event: object = None) -> None:
        index = selected_index()
        if index is None or index >= len(records()):
            return
        item = records()[index]
        values = {
            "id": item.get("id", ""), "name": item.get("name", ""),
            "source": item.get("source_code", "B"), "safety": item.get("safety_code", "N"),
            "weight": item.get("weight", 1), "categories": "|".join(item.get("categories", [])),
            "groups": "|".join(item.get("custom_groups", [])),
        }
        for name, value in values.items():
            fields[name].set(str(value))
        enabled_var.set(bool(item.get("enabled", True)))
        prompt_text.delete("1.0", "end")
        prompt_text.insert("1.0", str(item.get("prompt", "")))

    def editor_record() -> dict[str, Any]:
        return normalize_record({
            "id": fields["id"].get(), "name": fields["name"].get(),
            "source_code": fields["source"].get(), "safety_code": fields["safety"].get(),
            "weight": fields["weight"].get(), "categories": fields["categories"].get(),
            "custom_groups": fields["groups"].get(),
            "enabled": enabled_var.get(), "prompt": prompt_text.get("1.0", "end"),
        })

    def add_or_update(update: bool) -> None:
        nonlocal dirty
        try:
            item = editor_record()
            index = selected_index() if update else None
            if update and index is None:
                raise PoolError("请先选择要修改的记录")
            duplicate = next((i for i, old in enumerate(records()) if str(old.get("id", "")).casefold() == item["id"].casefold() and i != index), None)
            if duplicate is not None:
                raise PoolError(f"ID 已存在：{item['id']}")
            if index is None:
                records().append(item)
            else:
                records()[index] = item
            dirty = True
            refresh()
            clear_editor()
        except Exception as exc:
            messagebox.showerror("操作失败", str(exc))

    def delete_selected() -> None:
        nonlocal dirty
        index = selected_index()
        if index is None:
            return
        item = records()[index]
        if not messagebox.askyesno("确认删除", f"删除 {item.get('id')}？保存时会自动备份原库。"):
            return
        records().pop(index)
        dirty = True
        clear_editor()
        refresh()

    def open_file() -> None:
        nonlocal current_path, payload, dirty
        chosen = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not chosen:
            return
        try:
            payload = load_pool(Path(chosen))
            current_path = Path(chosen)
            dirty = False
            clear_editor()
            refresh()
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def save_file(save_as: bool = False) -> None:
        nonlocal current_path, dirty
        if save_as or current_path is None:
            chosen = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
            if not chosen:
                return
            current_path = Path(chosen)
        try:
            backup = save_pool(current_path, payload)
            dirty = False
            refresh()
            messagebox.showinfo("保存完成", f"已保存：{current_path}" + (f"\n备份：{backup}" if backup else ""))
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def import_file() -> None:
        nonlocal dirty
        chosen = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not chosen:
            return
        try:
            incoming_payload = load_pool(Path(chosen))
            incoming = incoming_payload["prompts"]
            assert isinstance(incoming, list)
            overwrite = messagebox.askyesno("重复 ID", "重复 ID 是否覆盖？选择“否”将跳过重复项。")
            added, updated = merge_records(payload, incoming, overwrite=overwrite)
            definitions = group_definitions(payload)
            known = {item["id"] for item in definitions}
            for item in group_definitions(incoming_payload):
                if item["id"] not in known:
                    definitions.append(item)
                    known.add(item["id"])
            payload["custom_group_definitions"] = definitions
            dirty = dirty or added > 0 or updated > 0
            refresh()
            messagebox.showinfo("导入完成", f"新增 {added} 条，更新 {updated} 条")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))

    def export_file() -> None:
        chosen = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json"), ("CSV", "*.csv")])
        if not chosen:
            return
        try:
            visible = [records()[int(i)] for i in tree.get_children()]
            export_records(Path(chosen), visible, group_definitions(payload))
            messagebox.showinfo("导出完成", f"已导出 {len(visible)} 条")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def manage_groups() -> None:
        window = tk.Toplevel(root)
        window.title("管理自定义分组")
        window.geometry("560x420")
        window.transient(root)
        window.grab_set()

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        group_list = tk.Listbox(frame, exportselection=False)
        group_list.grid(row=0, column=0, columnspan=3, sticky="nsew")
        group_id_var = tk.StringVar()
        group_name_var = tk.StringVar()
        ttk.Label(frame, text="分组 ID").grid(row=1, column=0, sticky="w", pady=(10, 2))
        ttk.Entry(frame, textvariable=group_id_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(10, 2))
        ttk.Label(frame, text="显示名称").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=group_name_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)

        def definitions() -> list[dict[str, str]]:
            return group_definitions(payload)

        def refresh_groups() -> None:
            group_list.delete(0, "end")
            for item in definitions():
                group_list.insert("end", f"{item['id']}  —  {item['name']}")

        def select_group(_event: object = None) -> None:
            selected = group_list.curselection()
            if not selected:
                return
            item = definitions()[selected[0]]
            group_id_var.set(item["id"])
            group_name_var.set(item["name"])

        def save_group() -> None:
            nonlocal dirty
            try:
                group_id = normalize_group_id(group_id_var.get())
                name = group_name_var.get().strip() or group_id
                items = definitions()
                selected = group_list.curselection()
                old_id = items[selected[0]]["id"] if selected else ""
                duplicate = next(
                    (item for item in items if item["id"] == group_id and item["id"] != old_id),
                    None,
                )
                if duplicate:
                    raise PoolError(f"分组 ID 已存在：{group_id}")
                if selected:
                    items[selected[0]] = {"id": group_id, "name": name}
                    if old_id != group_id:
                        for record in records():
                            record["custom_groups"] = [
                                group_id if value == old_id else value
                                for value in record.get("custom_groups", [])
                            ]
                else:
                    items.append({"id": group_id, "name": name})
                payload["custom_group_definitions"] = items
                dirty = True
                group_id_var.set("")
                group_name_var.set("")
                refresh_groups()
                refresh()
            except Exception as exc:
                messagebox.showerror("保存分组失败", str(exc), parent=window)

        def delete_group() -> None:
            nonlocal dirty
            selected = group_list.curselection()
            if not selected:
                return
            items = definitions()
            item = items[selected[0]]
            if not messagebox.askyesno(
                "删除分组",
                f"删除分组 {item['id']}，并从全部提示词移除该分组？",
                parent=window,
            ):
                return
            items.pop(selected[0])
            payload["custom_group_definitions"] = items
            for record in records():
                record["custom_groups"] = [
                    value
                    for value in record.get("custom_groups", [])
                    if value != item["id"]
                ]
            dirty = True
            group_id_var.set("")
            group_name_var.set("")
            refresh_groups()
            refresh()

        group_list.bind("<<ListboxSelect>>", select_group)
        ttk.Button(frame, text="新增/保存", command=save_group).grid(row=3, column=0, pady=12)
        ttk.Button(frame, text="删除", command=delete_group).grid(row=3, column=1, pady=12)
        ttk.Button(frame, text="关闭", command=window.destroy).grid(row=3, column=2, pady=12)
        ttk.Label(
            frame,
            text="调用格式：@分组ID；多个分组使用 @组1+组2。",
        ).grid(row=4, column=0, columnspan=3, sticky="w")
        refresh_groups()

    for text, command in (("打开", open_file), ("保存", save_file), ("另存为", lambda: save_file(True)), ("导入", import_file), ("导出当前筛选", export_file), ("管理自定义分组", manage_groups)):
        ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=3)
    edit_buttons = ttk.Frame(editor)
    edit_buttons.grid(row=8, column=0, columnspan=3, pady=8)
    for text, command in (("新建", clear_editor), ("添加", lambda: add_or_update(False)), ("更新所选", lambda: add_or_update(True)), ("删除所选", delete_selected)):
        ttk.Button(edit_buttons, text=text, command=command).pack(side="left", padx=5)
    ttk.Label(outer, textvariable=status_var).grid(row=4, column=0, sticky="ew")
    tree.bind("<<TreeviewSelect>>", load_selection)
    filter_var.trace_add("write", refresh)
    clear_editor()
    refresh()
    root.mainloop()
    return 0


def parse_ids(raw: Iterable[str]) -> list[str]:
    return [item for value in raw for item in re.split(r"[,，;；\s]+", value) if item]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AstrAutoAnima 离线提示词库管理器")
    sub = parser.add_subparsers(dest="command")
    validate = sub.add_parser("validate")
    validate.add_argument("pool", type=Path)
    add = sub.add_parser("add")
    add.add_argument("pool", type=Path); add.add_argument("--id", required=True); add.add_argument("--prompt", required=True)
    add.add_argument("--name", default=""); add.add_argument("--source", default="B"); add.add_argument("--safety", default="N"); add.add_argument("--categories", default=""); add.add_argument("--groups", default="")
    imp = sub.add_parser("import")
    imp.add_argument("pool", type=Path); imp.add_argument("source", type=Path); imp.add_argument("--overwrite", action="store_true")
    delete = sub.add_parser("delete")
    delete.add_argument("pool", type=Path); delete.add_argument("--ids", action="append", required=True)
    export = sub.add_parser("export")
    export.add_argument("pool", type=Path); export.add_argument("output", type=Path); export.add_argument("--query", default="")
    group_list = sub.add_parser("group-list")
    group_list.add_argument("pool", type=Path)
    group_add = sub.add_parser("group-add")
    group_add.add_argument("pool", type=Path); group_add.add_argument("--id", required=True); group_add.add_argument("--name", default="")
    group_delete = sub.add_parser("group-delete")
    group_delete.add_argument("pool", type=Path); group_delete.add_argument("--id", required=True)
    sub.add_parser("gui")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {None, "gui"}:
        return launch_gui()
    payload = load_pool(args.pool)
    records = payload["prompts"]
    assert isinstance(records, list)
    if args.command == "validate":
        print(f"校验通过：{len(records)} 条")
        return 0
    if args.command == "add":
        added, _ = merge_records(payload, [{"id": args.id, "name": args.name or args.id, "prompt": args.prompt, "source_code": args.source, "safety_code": args.safety, "categories": args.categories, "custom_groups": args.groups}], overwrite=False)
        if not added:
            raise PoolError(f"ID 已存在：{args.id}")
        backup = save_pool(args.pool, payload)
        print(f"已添加 1 条；备份：{backup or '无'}")
    elif args.command == "import":
        incoming_payload = load_pool(args.source)
        incoming = incoming_payload["prompts"]
        assert isinstance(incoming, list)
        added, updated = merge_records(payload, incoming, overwrite=args.overwrite)
        definitions = group_definitions(payload)
        known = {item["id"] for item in definitions}
        for item in group_definitions(incoming_payload):
            if item["id"] not in known:
                definitions.append(item)
                known.add(item["id"])
        payload["custom_group_definitions"] = definitions
        backup = save_pool(args.pool, payload)
        print(f"新增 {added} 条，更新 {updated} 条；备份：{backup or '无'}")
    elif args.command == "delete":
        removed = remove_records(payload, parse_ids(args.ids))
        backup = save_pool(args.pool, payload)
        print(f"已删除 {removed} 条；备份：{backup or '无'}")
    elif args.command == "export":
        query = args.query.casefold().strip()
        selected = [item for item in records if not query or query in json.dumps(item, ensure_ascii=False).casefold()]
        export_records(args.output, selected, group_definitions(payload))
        print(f"已导出 {len(selected)} 条到 {args.output}")
    elif args.command == "group-list":
        for item in group_definitions(payload):
            print(f"{item['id']}\t{item['name']}")
    elif args.command == "group-add":
        group_id = normalize_group_id(args.id)
        definitions = group_definitions(payload)
        if any(item["id"] == group_id for item in definitions):
            raise PoolError(f"分组 ID 已存在：{group_id}")
        definitions.append({"id": group_id, "name": args.name.strip() or group_id})
        payload["custom_group_definitions"] = definitions
        backup = save_pool(args.pool, payload)
        print(f"已添加分组 {group_id}；备份：{backup or '无'}")
    elif args.command == "group-delete":
        group_id = normalize_group_id(args.id)
        definitions = group_definitions(payload)
        remaining = [item for item in definitions if item["id"] != group_id]
        if len(remaining) == len(definitions):
            raise PoolError(f"找不到分组：{group_id}")
        payload["custom_group_definitions"] = remaining
        for item in records:
            item["custom_groups"] = [
                value for value in item.get("custom_groups", []) if value != group_id
            ]
        backup = save_pool(args.pool, payload)
        print(f"已删除分组 {group_id}；备份：{backup or '无'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PoolError as exc:
        raise SystemExit(f"错误：{exc}") from exc
