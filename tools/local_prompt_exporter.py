from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SOURCE_CODES = ("B", "G", "D", "C", "R")
SAFETY_CODES = ("N", "H", "S")
SOURCE_NAME_TO_CODE = {
    "basic": "B",
    "generate": "G",
    "discord": "D",
    "codex": "C",
    "reverse": "R",
}
SAFETY_NAME_TO_CODE = {"normal": "N", "nsfw": "H", "sexual": "S"}


class ExporterError(ValueError):
    pass


def load_prompt_records(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.is_file():
        raise ExporterError(f"找不到提示词库：{path}")
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExporterError(f"无法读取 JSON：{exc}") from exc

    metadata: dict[str, Any] = {}
    if isinstance(data, dict):
        records = data.get("prompts")
        metadata = {key: value for key, value in data.items() if key != "prompts"}
    elif isinstance(data, list):
        records = data
    else:
        records = None
    if not isinstance(records, list):
        raise ExporterError("JSON 必须是提示词数组，或包含 prompts 数组的对象。")

    valid: list[dict[str, Any]] = []
    for index, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            raise ExporterError(f"第 {index} 条记录不是 JSON 对象。")
        if not str(item.get("prompt", "")).strip():
            raise ExporterError(f"第 {index} 条记录缺少 prompt。")
        valid.append(item)
    return valid, metadata


def entry_source_code(item: dict[str, Any]) -> str:
    code = str(item.get("source_code", "")).strip().upper()
    if code in SOURCE_CODES:
        return code
    return SOURCE_NAME_TO_CODE.get(
        str(item.get("source_group", "basic")).strip().casefold(), "B"
    )


def entry_safety_code(item: dict[str, Any]) -> str:
    code = str(item.get("safety_code", "")).strip().upper()
    if code in SAFETY_CODES:
        return code
    return SAFETY_NAME_TO_CODE.get(
        str(item.get("safety_level", "normal")).strip().casefold(), "N"
    )


def parse_code_list(raw: str, valid_codes: Iterable[str]) -> set[str]:
    valid = set(valid_codes)
    text = str(raw or "").strip().upper()
    if not text or text in {"ALL", "*", "全部"}:
        return valid
    parts = {part for part in re.split(r"[,/;+\s]+", text) if part}
    invalid = sorted(parts - valid)
    if invalid:
        raise ExporterError(f"不支持的分组代码：{', '.join(invalid)}")
    return parts


def parse_id_list(raw: str) -> set[str]:
    return {
        item.strip().casefold()
        for item in re.split(r"[,，;；\s]+", str(raw or ""))
        if item.strip()
    }


def filter_prompt_records(
    records: list[dict[str, Any]],
    *,
    source_codes: set[str] | None = None,
    safety_codes: set[str] | None = None,
    keyword: str = "",
    ids: set[str] | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    sources = source_codes or set(SOURCE_CODES)
    safety = safety_codes or set(SAFETY_CODES)
    wanted_ids = {value.casefold() for value in (ids or set())}
    folded_keyword = str(keyword or "").strip().casefold()
    result: list[dict[str, Any]] = []

    for item in records:
        if not include_disabled and not bool(item.get("enabled", True)):
            continue
        if entry_source_code(item) not in sources:
            continue
        if entry_safety_code(item) not in safety:
            continue
        if wanted_ids and str(item.get("id", "")).casefold() not in wanted_ids:
            continue
        if folded_keyword:
            searchable = "\n".join(
                (
                    str(item.get("id", "")),
                    str(item.get("name", "")),
                    str(item.get("prompt", "")),
                    " ".join(str(value) for value in item.get("categories", [])),
                )
            ).casefold()
            if folded_keyword not in searchable:
                continue
        result.append(item)
    return result


def _normalized_export_record(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["source_code"] = entry_source_code(item)
    result["safety_code"] = entry_safety_code(item)
    return result


def export_json(
    path: Path,
    records: list[dict[str, Any]],
    *,
    source_path: Path,
    filters: dict[str, Any],
) -> None:
    payload = {
        "schema_version": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source_path.resolve()),
        "count": len(records),
        "filters": filters,
        "prompts": [_normalized_export_record(item) for item in records],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def export_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = (
        "id",
        "name",
        "source_code",
        "safety_code",
        "enabled",
        "weight",
        "categories",
        "prompt",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in records:
            writer.writerow(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "source_code": entry_source_code(item),
                    "safety_code": entry_safety_code(item),
                    "enabled": bool(item.get("enabled", True)),
                    "weight": item.get("weight", 1),
                    "categories": "|".join(
                        str(value) for value in item.get("categories", [])
                    ),
                    "prompt": item.get("prompt", ""),
                }
            )


def export_txt(
    path: Path, records: list[dict[str, Any]], *, prompt_only: bool = False
) -> None:
    blocks: list[str] = []
    for item in records:
        prompt = str(item.get("prompt", "")).strip()
        if prompt_only:
            blocks.append(prompt)
        else:
            blocks.append(
                f"# {item.get('id', '无ID')} | "
                f"{entry_source_code(item)}/{entry_safety_code(item)} | "
                f"{item.get('name', '未命名')}\n{prompt}"
            )
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def export_records(
    input_path: Path,
    output_path: Path,
    *,
    output_format: str,
    source_codes: set[str],
    safety_codes: set[str],
    keyword: str = "",
    ids: set[str] | None = None,
    include_disabled: bool = False,
    prompt_only: bool = False,
) -> tuple[int, Path]:
    records, _ = load_prompt_records(input_path)
    selected = filter_prompt_records(
        records,
        source_codes=source_codes,
        safety_codes=safety_codes,
        keyword=keyword,
        ids=ids,
        include_disabled=include_disabled,
    )
    fmt = output_format.strip().casefold()
    if fmt not in {"json", "csv", "txt"}:
        raise ExporterError("导出格式只能是 JSON、CSV 或 TXT。")
    output_path = output_path.with_suffix(f".{fmt}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filters = {
        "source_codes": sorted(source_codes),
        "safety_codes": sorted(safety_codes),
        "keyword": keyword,
        "ids": sorted(ids or set()),
        "include_disabled": include_disabled,
    }
    if fmt == "json":
        export_json(output_path, selected, source_path=input_path, filters=filters)
    elif fmt == "csv":
        export_csv(output_path, selected)
    else:
        export_txt(output_path, selected, prompt_only=prompt_only)
    return len(selected), output_path


def default_pool_path() -> Path:
    adjacent = Path(__file__).resolve().parent / "anima_random_prompt_pool.json"
    return adjacent if adjacent.is_file() else Path.cwd() / "anima_random_prompt_pool.json"


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise ExporterError(
            "当前 Python 没有 Tkinter，无法启动图形界面；请使用命令行模式。"
        ) from exc

    root = tk.Tk()
    root.title("AstrAutoAnima 本地提示词批量导出工具")
    root.geometry("820x700")
    root.minsize(720, 620)

    input_var = tk.StringVar(value=str(default_pool_path()))
    output_var = tk.StringVar(value=str(Path(__file__).resolve().parent / "outputs"))
    keyword_var = tk.StringVar()
    format_var = tk.StringVar(value="JSON")
    enabled_only_var = tk.BooleanVar(value=True)
    prompt_only_var = tk.BooleanVar(value=False)
    source_vars = {code: tk.BooleanVar(value=True) for code in SOURCE_CODES}
    safety_vars = {code: tk.BooleanVar(value=True) for code in SAFETY_CODES}
    status_var = tk.StringVar(value="请选择筛选条件，然后预览或导出。")

    main = ttk.Frame(root, padding=16)
    main.pack(fill="both", expand=True)
    main.columnconfigure(1, weight=1)

    ttk.Label(main, text="提示词库 JSON：").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Entry(main, textvariable=input_var).grid(row=0, column=1, sticky="ew", pady=5)

    def choose_input() -> None:
        chosen = filedialog.askopenfilename(
            title="选择提示词库 JSON",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if chosen:
            input_var.set(chosen)

    ttk.Button(main, text="浏览…", command=choose_input).grid(row=0, column=2, padx=(8, 0))

    ttk.Label(main, text="导出目录：").grid(row=1, column=0, sticky="w", pady=5)
    ttk.Entry(main, textvariable=output_var).grid(row=1, column=1, sticky="ew", pady=5)

    def choose_output() -> None:
        chosen = filedialog.askdirectory(title="选择导出目录")
        if chosen:
            output_var.set(chosen)

    ttk.Button(main, text="浏览…", command=choose_output).grid(row=1, column=2, padx=(8, 0))

    group_box = ttk.LabelFrame(main, text="来源组", padding=10)
    group_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 5))
    for index, code in enumerate(SOURCE_CODES):
        ttk.Checkbutton(group_box, text=code, variable=source_vars[code]).grid(
            row=0, column=index, padx=16
        )

    safety_box = ttk.LabelFrame(main, text="内容级别", padding=10)
    safety_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
    for index, code in enumerate(SAFETY_CODES):
        ttk.Checkbutton(safety_box, text=code, variable=safety_vars[code]).grid(
            row=0, column=index, padx=24
        )

    ttk.Label(main, text="关键词：").grid(row=4, column=0, sticky="w", pady=8)
    ttk.Entry(main, textvariable=keyword_var).grid(
        row=4, column=1, columnspan=2, sticky="ew", pady=8
    )

    ttk.Label(main, text="指定 ID：").grid(row=5, column=0, sticky="nw", pady=5)
    id_text = tk.Text(main, height=7, wrap="word")
    id_text.grid(row=5, column=1, columnspan=2, sticky="nsew", pady=5)
    main.rowconfigure(5, weight=1)
    ttk.Label(
        main,
        text="可用空格、逗号或换行分隔；留空表示不限制，例如 discord-0014。",
    ).grid(row=6, column=1, columnspan=2, sticky="w")

    option_frame = ttk.Frame(main)
    option_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 5))
    ttk.Checkbutton(
        option_frame, text="只导出启用记录", variable=enabled_only_var
    ).pack(side="left", padx=(0, 20))
    ttk.Checkbutton(
        option_frame, text="TXT 仅保留提示词", variable=prompt_only_var
    ).pack(side="left")
    ttk.Label(option_frame, text="导出格式：").pack(side="left", padx=(30, 5))
    ttk.Combobox(
        option_frame,
        textvariable=format_var,
        values=("JSON", "CSV", "TXT"),
        state="readonly",
        width=8,
    ).pack(side="left")

    status = ttk.Label(main, textvariable=status_var, foreground="#245b8a", wraplength=760)
    status.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 5))

    def current_filters() -> tuple[Path, set[str], set[str], set[str]]:
        input_path = Path(input_var.get().strip().strip('"')).expanduser()
        sources = {code for code, var in source_vars.items() if var.get()}
        safety = {code for code, var in safety_vars.items() if var.get()}
        if not sources:
            raise ExporterError("请至少选择一个来源组。")
        if not safety:
            raise ExporterError("请至少选择一个内容级别。")
        ids = parse_id_list(id_text.get("1.0", "end"))
        return input_path, sources, safety, ids

    def preview() -> None:
        try:
            input_path, sources, safety, ids = current_filters()
            records, _ = load_prompt_records(input_path)
            selected = filter_prompt_records(
                records,
                source_codes=sources,
                safety_codes=safety,
                keyword=keyword_var.get(),
                ids=ids,
                include_disabled=not enabled_only_var.get(),
            )
            preview_ids = ", ".join(str(item.get("id", "?")) for item in selected[:8])
            status_var.set(
                f"匹配 {len(selected)} 条。"
                + (f" 前几条：{preview_ids}" if preview_ids else "")
            )
        except Exception as exc:
            messagebox.showerror("预览失败", str(exc))

    def run_export() -> None:
        try:
            input_path, sources, safety, ids = current_filters()
            output_dir = Path(output_var.get().strip().strip('"')).expanduser()
            selector = "".join(code for code in SOURCE_CODES if code in sources)
            selector += "-" + "".join(code for code in SAFETY_CODES if code in safety)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = output_dir / f"prompt_export_{selector}_{stamp}"
            count, path = export_records(
                input_path,
                output_base,
                output_format=format_var.get(),
                source_codes=sources,
                safety_codes=safety,
                keyword=keyword_var.get(),
                ids=ids,
                include_disabled=not enabled_only_var.get(),
                prompt_only=prompt_only_var.get(),
            )
            status_var.set(f"导出完成：{count} 条｜{path}")
            messagebox.showinfo("导出完成", f"共导出 {count} 条：\n{path}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    button_frame = ttk.Frame(main)
    button_frame.grid(row=9, column=0, columnspan=3, pady=(12, 0))
    ttk.Button(button_frame, text="预览数量", command=preview).pack(side="left", padx=8)
    ttk.Button(button_frame, text="批量导出", command=run_export).pack(side="left", padx=8)
    ttk.Button(button_frame, text="退出", command=root.destroy).pack(side="left", padx=8)

    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AstrAutoAnima 本地提示词批量导出工具（不依赖 AstrBot/ComfyUI）"
    )
    parser.add_argument("input", nargs="?", help="提示词库 JSON；省略时启动 GUI")
    parser.add_argument("-o", "--output", help="导出文件路径（扩展名会按格式修正）")
    parser.add_argument("--format", choices=("json", "csv", "txt"), default="json")
    parser.add_argument("--source", default="ALL", help="来源组，如 D、B,G,D 或 ALL")
    parser.add_argument("--safety", default="ALL", help="级别组，如 N,H 或 S")
    parser.add_argument("--keyword", default="", help="按 ID、名称、提示词、分类搜索")
    parser.add_argument("--ids", default="", help="指定 ID，逗号或空格分隔")
    parser.add_argument("--include-disabled", action="store_true", help="包含停用记录")
    parser.add_argument("--prompt-only", action="store_true", help="TXT 仅输出提示词正文")
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gui or not args.input:
        try:
            return launch_gui()
        except ExporterError as exc:
            parser.error(str(exc))

    input_path = Path(args.input).expanduser()
    output = (
        Path(args.output).expanduser()
        if args.output
        else Path.cwd() / f"prompt_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        count, path = export_records(
            input_path,
            output,
            output_format=args.format,
            source_codes=parse_code_list(args.source, SOURCE_CODES),
            safety_codes=parse_code_list(args.safety, SAFETY_CODES),
            keyword=args.keyword,
            ids=parse_id_list(args.ids),
            include_disabled=args.include_disabled,
            prompt_only=args.prompt_only,
        )
    except ExporterError as exc:
        parser.error(str(exc))
    print(f"导出完成：{count} 条 -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
