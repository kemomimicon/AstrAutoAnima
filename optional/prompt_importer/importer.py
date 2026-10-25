"""Optional, one-shot prompt importer. Python 3.10+; standard library only."""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def parse_file(path: Path) -> list[str]:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("文件编码无法识别")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("prompts", data.get("items", []))
        if not isinstance(data, list):
            raise ValueError("JSON 顶层应为列表或含 prompts/items 列表")
        values = [str(row.get("prompt", row.get("tags", row.get("text", ""))) if isinstance(row, dict) else row).strip()
                  for row in data]
    elif path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV 缺少表头")
        field = next((name for name in reader.fieldnames if name.casefold() in {"prompt", "tags", "text", "提示词"}), None)
        if field is None:
            raise ValueError("CSV 需要 prompt、tags、text 或 提示词 列")
        values = [str(row.get(field, "")).strip() for row in reader]
    elif path.suffix.lower() == ".txt":
        values = [line.strip() for line in text.splitlines()]
    else:
        raise ValueError("仅支持 .json、.csv、.txt")
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value.startswith("#"):
            continue
        marker = " ".join(value.casefold().split())
        if marker not in seen:
            result.append(value)
            seen.add(marker)
    return result


def validate_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("远程 Hub 必须使用 HTTPS；HTTP 仅允许本机 127.0.0.1")
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError("请输入 Hub 根地址，不要包含路径或密钥")
    return value


def request_json(base: str, token: str, method: str, path: str, payload: dict | None = None,
                 revision: str | None = None) -> dict:
    headers = {"Authorization": "Bearer " + token, "X-Device-Name": "Optional Prompt Importer"}
    if revision is not None:
        headers["If-Match"] = revision
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base + path, data=body, method=method, headers=headers)
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def sync(base: str, token: str, group_id: str, name: str, allow_private: bool,
         source: str, safety: str, prompts: list[str]) -> tuple[int, int]:
    if not token.strip():
        raise ValueError("请填写管理员令牌；令牌仅驻留内存")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", group_id):
        raise ValueError("组 ID 仅允许英文小写、数字、下划线、短横线，最长 64 位")
    if not name.strip() or len(name) > 100:
        raise ValueError("请输入 1–100 字的分组显示名")
    if len(prompts) > 10000:
        raise ValueError("单次最多导入 10000 条，请拆分文件")
    for _ in range(3):
        registry = request_json(base, token, "GET", "/api/v1/prompts/groups")
        groups = [row for row in registry["groups"] if row.get("id") != group_id]
        groups.append({"id": group_id, "name": name.strip(), "allow_private": allow_private})
        try:
            request_json(base, token, "PUT", "/api/v1/prompts/groups",
                         {"groups": groups}, registry["revision"])
            break
        except HTTPError as exc:
            if exc.code != 409:
                raise
    else:
        raise RuntimeError("分组登记时发生持续并发修改，请稍后再试")

    imported = 0
    for start in range(0, len(prompts), 500):
        batch = prompts[start:start + 500]
        payload = {"prompts": [{"prompt": value, "name": value[:80],
                                "source_code": source, "safety_code": safety,
                                "custom_groups": [group_id]} for value in batch]}
        for _ in range(3):
            page = request_json(base, token, "GET", "/api/v1/prompts?page=1&page_size=1")
            try:
                result = request_json(base, token, "POST", "/api/v1/prompts/import",
                                      payload, page["revision"])
                imported += int(result["count"])
                break
            except HTTPError as exc:
                if exc.code != 409:
                    raise
        else:
            raise RuntimeError(f"导入在第 {start + 1} 条遇到持续冲突；已导入 {imported} 条，重试会查重")
    return imported, len(prompts) - imported


def main() -> None:
    window = tk.Tk()
    window.title("AstrAutoAnima · 可选词库导入器")
    window.geometry("760x690")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    variables = {key: tk.StringVar(value=default) for key, default in {
        "file": "", "url": "http://127.0.0.1:6278", "token": "", "id": "",
        "name": "", "source": "B", "safety": "N"}.items()}
    private = tk.BooleanVar(value=False)
    prompts: list[str] = []

    def row(label: str, key: str, secret: bool = False) -> None:
        ttk.Label(frame, text=label).pack(anchor="w", pady=(8, 2))
        ttk.Entry(frame, textvariable=variables[key], show="•" if secret else "").pack(fill="x")

    row("Hub 地址（远程必须 HTTPS）", "url")
    row("管理员令牌（不保存、不写日志）", "token", True)
    row("自定义组 ID（例如 my_fantasy）", "id")
    row("组显示名（可中文）", "name")
    ttk.Checkbutton(frame, text="允许私聊抽取此组", variable=private).pack(anchor="w", pady=6)
    options = ttk.Frame(frame)
    options.pack(fill="x")
    ttk.Label(options, text="来源组：").pack(side="left")
    ttk.Combobox(options, textvariable=variables["source"], values=["B", "G", "D", "C", "R"],
                 state="readonly", width=6).pack(side="left")
    ttk.Label(options, text="安全分级：").pack(side="left", padx=(15, 0))
    ttk.Combobox(options, textvariable=variables["safety"], values=["N", "H", "S"],
                 state="readonly", width=6).pack(side="left")
    ttk.Label(frame, text="来源组/安全分级是原有体系；自定义组额外用于 @组ID 抽取。请人工确认分级。").pack(anchor="w", pady=8)
    preview = tk.Text(frame, height=11, wrap="word")
    preview.pack(fill="both", expand=True, pady=8)

    def choose() -> None:
        path = filedialog.askopenfilename(filetypes=[("词库文件", "*.json *.csv *.txt")])
        if not path:
            return
        try:
            parsed = parse_file(Path(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        prompts[:] = parsed
        variables["file"].set(path)
        preview.delete("1.0", "end")
        preview.insert("end", f"本地预览：去重后 {len(prompts)} 条；此时未同步服务器。\n\n")
        preview.insert("end", "\n".join(prompts[:20]))
        if len(prompts) > 20:
            preview.insert("end", "\n…仅显示前 20 条")

    ttk.Button(frame, text="选择 JSON / CSV / TXT 并预览", command=choose).pack(anchor="w")

    def do_sync() -> None:
        if not prompts:
            messagebox.showwarning("尚未选择", "请先选择词库并预览")
            return
        if not messagebox.askyesno("确认手动同步", f"即将登记分组并同步 {len(prompts)} 条提示词。已存在的同内容、同组、同分级条目会跳过。是否继续？"):
            return
        try:
            arguments = (
                validate_url(variables["url"].get()), variables["token"].get(),
                variables["id"].get().strip().casefold(), variables["name"].get(),
                private.get(), variables["source"].get(), variables["safety"].get(),
                list(prompts),
            )
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        button.configure(state="disabled")
        def worker() -> None:
            try:
                imported, skipped = sync(*arguments)
                window.after(0, lambda: messagebox.showinfo("完成", f"新导入 {imported} 条，跳过重复 {skipped} 条。"))
            except (ValueError, RuntimeError, HTTPError, URLError, OSError, KeyError) as exc:
                detail = f"{type(exc).__name__}: {getattr(exc, 'code', str(exc))}"
                window.after(0, lambda: messagebox.showerror("同步未完成", detail))
            finally:
                window.after(0, lambda: button.configure(state="normal"))
        threading.Thread(target=worker, daemon=True).start()

    button = ttk.Button(frame, text="确认并同步到 Hub（仅此时联网）", command=do_sync)
    button.pack(anchor="e", pady=10)
    window.mainloop()


if __name__ == "__main__":
    main()
