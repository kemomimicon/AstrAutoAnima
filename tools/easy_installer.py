#!/usr/bin/env python3
"""AstrAutoAnima novice-friendly local installer (network is opt-in only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class InstallError(RuntimeError):
    pass


Logger = Callable[[str], None]


@dataclass
class InstallPlan:
    repo_root: Path
    astrbot_data: Path
    comfyui_root: Path
    hub_home: Path
    components: set[str] = field(default_factory=lambda: {"plugin", "comfyui"})
    external: set[str] = field(default_factory=set)
    comfy_python: Path | None = None
    install_external_requirements: bool = False
    apply: bool = False


def _first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        expanded = candidate.expanduser()
        if expanded.exists():
            return expanded.resolve()
    return None


def guess_install_paths(repo_root: Path) -> dict[str, Path]:
    """Find common local/server layouts without modifying anything."""
    workspace = repo_root.parent
    astrbot_candidates = [
        Path(value)
        for value in (os.getenv("AAA_ASTRBOT_DATA"), os.getenv("AAH_ASTRBOT_DATA"))
        if value
    ] + [
        workspace / "astrbot-runtime/data",
        repo_root / "AstrBot/data",
        workspace / "AstrBot/data",
        Path("/workspace/astrbot-runtime/data"),
        Path("C:/AstrBot/data"),
    ]
    comfy_candidates = [
        Path(value)
        for value in (os.getenv("AAA_COMFYUI_ROOT"), os.getenv("AAH_COMFYUI_ROOT"))
        if value
    ] + [
        workspace / "ComfyUI",
        repo_root / "ComfyUI",
        Path("/workspace/ComfyUI"),
        Path("C:/ComfyUI"),
    ]
    comfy_root = _first_existing(comfy_candidates)
    python_candidates: list[Path] = []
    if comfy_root:
        python_candidates.extend(
            [
                comfy_root / ".venv/Scripts/python.exe",
                comfy_root / ".venv/bin/python",
                comfy_root / "python_embeded/python.exe",
            ]
        )
    python_candidates.extend(
        [
            Path("/workspace/KSKvENv/bin/python"),
            Path("/usr/local/miniconda3/envs/py310/bin/python"),
        ]
    )
    return {
        "astrbot_data": _first_existing(astrbot_candidates) or Path(),
        "comfyui_root": comfy_root or Path(),
        "hub_home": (workspace / "astr-auto-anima-hub").resolve(),
        "comfy_python": _first_existing(python_candidates) or Path(),
    }


def load_optional_components(repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / "tools/optional_components.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"无法读取外部组件清单：{exc}") from exc
    components = payload.get("components")
    if not isinstance(components, list):
        raise InstallError("外部组件清单缺少 components 数组")
    return [item for item in components if isinstance(item, dict)]


def validate_plan(plan: InstallPlan) -> None:
    if not (plan.repo_root / ".astr_auto_anima_public_root").is_file():
        raise InstallError(f"不是有效的发布包目录：{plan.repo_root}")
    unknown_components = plan.components - {"plugin", "comfyui", "hub"}
    if unknown_components:
        raise InstallError(f"未知本项目组件：{', '.join(sorted(unknown_components))}")
    if ("plugin" in plan.components or "hub" in plan.components) and not plan.astrbot_data.is_dir():
        raise InstallError(f"AstrBot data 目录不存在：{plan.astrbot_data}")
    if ("comfyui" in plan.components or plan.external) and not plan.comfyui_root.is_dir():
        raise InstallError(f"ComfyUI 根目录不存在：{plan.comfyui_root}")
    if "hub" in plan.components and not plan.hub_home.parent.is_dir():
        raise InstallError(f"Hub 目标的父目录不存在：{plan.hub_home.parent}")
    known = {item.get("id") for item in load_optional_components(plan.repo_root)}
    unknown = plan.external - known
    if unknown:
        raise InstallError(f"未知外部组件：{', '.join(sorted(unknown))}")
    if plan.install_external_requirements:
        if not plan.comfy_python or not plan.comfy_python.is_file():
            raise InstallError("勾选安装外部依赖后，必须选择有效的 ComfyUI Python")


def backup_and_copy(source: Path, target: Path, backup_root: Path, log: Logger) -> None:
    if not source.is_dir():
        raise InstallError(f"发布包缺少目录：{source}")
    if target.exists():
        backup = backup_root / target.name
        if backup.exists():
            raise InstallError(f"备份目标已存在：{backup}")
        shutil.copytree(target, backup)
        log(f"已备份：{target} -> {backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    log(f"已安装：{source} -> {target}")


def copy_workflows(source: Path, target: Path, backup_root: Path, log: Logger) -> None:
    target.mkdir(parents=True, exist_ok=True)
    backup = backup_root / "workflows"
    backup.mkdir(parents=True, exist_ok=True)
    for source_file in sorted(source.glob("*.json")):
        destination = target / source_file.name
        if destination.exists():
            shutil.copy2(destination, backup / destination.name)
        shutil.copy2(source_file, destination)
        log(f"工作流：{destination}")


def run_checked(command: list[str], log: Logger, *, cwd: Path | None = None) -> None:
    log("执行：" + " ".join(command))
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line.rstrip())
    code = process.wait()
    if code:
        raise InstallError(f"命令执行失败，退出码 {code}")


def install_git_component(
    item: dict[str, Any], plan: InstallPlan, log: Logger
) -> Path:
    target = plan.comfyui_root / str(item["target"])
    if target.exists():
        log(f"已存在，安全跳过（不会覆盖）：{target}")
        return target
    git = shutil.which("git")
    if not git:
        raise InstallError("未找到 Git；请安装 Git 后重试该外部组件")
    run_checked([git, "clone", "--filter=blob:none", str(item["url"]), str(target)], log)
    commit = str(item.get("commit", "")).strip()
    if commit:
        run_checked([git, "-C", str(target), "checkout", "--detach", commit], log)
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(
    url: str,
    target: Path,
    log: Logger,
    *,
    expected_sha256: str = "",
) -> None:
    # Both final and resume paths must stay in real directories.
    from deployment_support import no_links
    no_links(target)
    no_links(target.with_name(target.name + '.part'))
    if target.is_file() and target.stat().st_size > 0:
        if not expected_sha256 or sha256_file(target) == expected_sha256.casefold():
            log(f"已存在且校验通过，安全跳过：{target}")
            return
        raise InstallError(f"目标文件已存在但 SHA256 不匹配，请人工检查：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    curl = shutil.which("curl")
    if not curl:
        raise InstallError("未找到 curl；大模型下载需要 curl 以支持断点续传")
    run_checked(
        [
            curl,
            "-L",
            "--fail",
            "--retry",
            "20",
            "--retry-delay",
            "5",
            "--connect-timeout",
            "30",
            "-C",
            "-",
            "-o",
            str(partial),
            url,
        ],
        log,
    )
    if expected_sha256:
        actual = sha256_file(partial)
        if actual != expected_sha256.casefold():
            raise InstallError(
                f"下载文件 SHA256 不匹配：{partial}\n实际：{actual}"
            )
    os.replace(partial, target)
    log(f"下载完成：{target}")


def install_external(plan: InstallPlan, backup_root: Path, log: Logger) -> None:
    del backup_root  # External targets are never overwritten by this installer.
    catalog = {item["id"]: item for item in load_optional_components(plan.repo_root)}
    for component_id in sorted(plan.external):
        item = catalog[component_id]
        log(f"\n外部组件：{item['name']}")
        installed_root: Path | None = None
        if item["kind"] == "git":
            installed_root = install_git_component(item, plan, log)
        elif item["kind"] == "download_set":
            for file in item.get("files", []):
                download_file(
                    str(file["url"]),
                    plan.comfyui_root / str(file["target"]),
                    log,
                    expected_sha256=str(file.get("sha256", "")),
                )
        else:
            raise InstallError(f"不支持的外部组件类型：{item['kind']}")
        if (
            installed_root
            and plan.install_external_requirements
            and plan.comfy_python
            and (installed_root / "requirements.txt").is_file()
        ):
            run_checked(
                [
                    str(plan.comfy_python),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(installed_root / "requirements.txt"),
                ],
                log,
            )


def write_initial_hub_env(plan: InstallPlan, log: Logger) -> None:
    env_path = plan.hub_home / ".env"
    if env_path.exists():
        log(f"保留现有 Hub 配置：{env_path}")
        return
    config_root = plan.hub_home.parent / "astr-auto-anima-hub-config"
    config_root.mkdir(parents=True, exist_ok=True)
    plugin_dir = plan.astrbot_data / "plugins/astrbot_plugin_comfy_bridge"
    plugin_data = plan.astrbot_data / "plugin_data/astrbot_plugin_comfy_bridge"
    admin_token = "aah_admin_" + secrets.token_urlsafe(48)
    lite_token = "aah_lite_" + secrets.token_urlsafe(48)
    values = {
        "AAH_HOST": "127.0.0.1",
        "AAH_PORT": "6278",
        "AAH_ADMIN_TOKEN": admin_token,
        "AAH_LITE_TOKEN": lite_token,
        "AAH_LITE_TOKEN_QQ": "",
        "AAH_ASTRBOT_URL": "http://127.0.0.1:6185",
        "AAH_ASTRBOT_API_KEY": "",
        "AAH_ASTRBOT_BOT_ID": "your-bot-id",
        "AAH_COMFYUI_URL": "http://127.0.0.1:8188",
        "AAH_PLUGIN_DIR": str(plugin_dir),
        "AAH_PLUGIN_DATA_DIR": str(plugin_data),
        "AAH_COMFYUI_ROOT": str(plan.comfyui_root),
        "AAH_DELIVERY_TARGETS_PATH": str(config_root / "delivery_targets.json"),
        "AAH_LITE_USERS_PATH": str(config_root / "lite_users.json"),
    }
    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    token_file = plan.hub_home / "首次安装令牌_请妥善保存.txt"
    token_file.write_text(
        f"管理员令牌：{admin_token}\n初始普通用户令牌：{lite_token}\n",
        encoding="utf-8",
    )
    log(f"已生成 Hub 配置：{env_path}")
    log(f"一次性令牌文件：{token_file}")


def install_hub(plan: InstallPlan, backup_root: Path, log: Logger) -> None:
    source = plan.repo_root / "hub/service"
    if plan.hub_home.exists():
        source_backup = backup_root / "hub_source"
        shutil.copytree(
            plan.hub_home,
            source_backup,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
        )
        log(f"已备份 Hub 源码（不含虚拟环境）：{source_backup}")
    plan.hub_home.mkdir(parents=True, exist_ok=True)
    existing_env = plan.hub_home / ".env"
    env_backup = existing_env.read_bytes() if existing_env.is_file() else None
    shutil.copytree(source, plan.hub_home, dirs_exist_ok=True)
    if env_backup is not None:
        existing_env.write_bytes(env_backup)
    write_initial_hub_env(plan, log)
    venv_python = plan.hub_home / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if not venv_python.is_file():
        run_checked([sys.executable, "-m", "venv", str(plan.hub_home / ".venv")], log)
    run_checked([str(venv_python), "-m", "pip", "install", "-e", str(plan.hub_home)], log)


def execute_plan(plan: InstallPlan, log: Logger) -> Path:
    validate_plan(plan)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = plan.repo_root.parent / f"AstrAutoAnima_backup_{stamp}"
    log("=== 部署摘要 ===")
    log(f"发布包：{plan.repo_root}")
    log(f"安装模块：{', '.join(sorted(plan.components)) or '无'}")
    log(f"联网拉取：{', '.join(sorted(plan.external)) or '无（默认）'}")
    log(f"备份目录：{backup_root}")
    if not plan.apply:
        log("当前为预检模式，没有修改任何文件。")
        return backup_root
    backup_root.mkdir(parents=True, exist_ok=False)
    if "plugin" in plan.components:
        backup_and_copy(
            plan.repo_root / "plugin/astrbot_plugin_comfy_bridge",
            plan.astrbot_data / "plugins/astrbot_plugin_comfy_bridge",
            backup_root,
            log,
        )
    if "comfyui" in plan.components:
        backup_and_copy(
            plan.repo_root / "comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools",
            plan.comfyui_root / "custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools",
            backup_root,
            log,
        )
        copy_workflows(
            plan.repo_root / "comfyui/workflows",
            plan.comfyui_root / "user/default/workflows",
            backup_root,
            log,
        )
    if "hub" in plan.components:
        install_hub(plan, backup_root, log)
    if plan.external:
        install_external(plan, backup_root, log)
    log("\n部署完成。请重载 AstrBot 插件，并完整重启 ComfyUI。")
    return backup_root


def launch_gui(repo_root: Path) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise InstallError("当前 Python 缺少 Tkinter，请改用命令行模式") from exc

    root = tk.Tk()
    root.title("AstrAutoAnima 一键部署助手")
    root.geometry("940x760")
    messages: queue.Queue[tuple[str, str]] = queue.Queue()

    guessed = guess_install_paths(repo_root)
    astrbot_var = tk.StringVar(value=str(guessed["astrbot_data"]) if guessed["astrbot_data"] != Path() else "")
    comfy_var = tk.StringVar(value=str(guessed["comfyui_root"]) if guessed["comfyui_root"] != Path() else "")
    hub_var = tk.StringVar(value=str(guessed["hub_home"]))
    comfy_python_var = tk.StringVar(value=str(guessed["comfy_python"]) if guessed["comfy_python"] != Path() else "")
    component_vars = {key: tk.BooleanVar(value=key != "hub") for key in ("plugin", "comfyui", "hub")}
    external_catalog = load_optional_components(repo_root)
    external_vars = {item["id"]: tk.BooleanVar(value=False) for item in external_catalog}
    deps_var = tk.BooleanVar(value=False)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    def choose_dir(variable: Any) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            variable.set(chosen)

    for row, (label, variable) in enumerate((
        ("AstrBot data 目录", astrbot_var),
        ("ComfyUI 根目录", comfy_var),
        ("Hub 安装目录", hub_var),
        ("ComfyUI Python（可选）", comfy_python_var),
    )):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        command = (lambda value=variable: choose_dir(value))
        ttk.Button(frame, text="选择", command=command).grid(row=row, column=2, padx=4)

    local_box = ttk.LabelFrame(frame, text="安装本项目组件（离线）", padding=8)
    local_box.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
    for key, text in (("plugin", "AstrBot 插件"), ("comfyui", "自定义节点与工作流"), ("hub", "Hub 服务")):
        ttk.Checkbutton(local_box, text=text, variable=component_vars[key]).pack(side="left", padx=12)

    external_box = ttk.LabelFrame(frame, text="可选外部拉取（默认全部关闭）", padding=8)
    external_box.grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)
    for index, item in enumerate(external_catalog):
        ttk.Checkbutton(
            external_box,
            text=item["name"],
            variable=external_vars[item["id"]],
        ).grid(row=index // 2, column=index % 2, sticky="w", padx=8, pady=3)
    ttk.Checkbutton(
        external_box,
        text="同时安装所选外部节点 requirements.txt（会修改 ComfyUI Python 环境）",
        variable=deps_var,
    ).grid(row=(len(external_catalog) + 1) // 2, column=0, columnspan=2, sticky="w", padx=8, pady=6)

    log_text = tk.Text(frame, height=20, wrap="word", state="disabled")
    log_text.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=8)
    frame.rowconfigure(7, weight=1)

    def append_log(message: str) -> None:
        log_text.configure(state="normal")
        log_text.insert("end", message + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")

    def build_plan(apply: bool) -> InstallPlan:
        comfy_python = Path(comfy_python_var.get()).expanduser() if comfy_python_var.get().strip() else None
        return InstallPlan(
            repo_root=repo_root,
            astrbot_data=Path(astrbot_var.get().strip() or ".").expanduser(),
            comfyui_root=Path(comfy_var.get().strip() or ".").expanduser(),
            hub_home=Path(hub_var.get().strip() or ".").expanduser(),
            components={key for key, value in component_vars.items() if value.get()},
            external={key for key, value in external_vars.items() if value.get()},
            comfy_python=comfy_python,
            install_external_requirements=deps_var.get(),
            apply=apply,
        )

    def worker(apply: bool) -> None:
        try:
            execute_plan(build_plan(apply), lambda value: messages.put(("log", value)))
            messages.put(("done", "部署完成" if apply else "预检通过"))
        except Exception as exc:
            messages.put(("error", str(exc)))

    def start(apply: bool) -> None:
        if apply and not messagebox.askyesno("确认部署", "确认按当前勾选项开始部署？外部拉取可能耗时很久。"):
            return
        threading.Thread(target=worker, args=(apply,), daemon=True).start()

    def poll_messages() -> None:
        try:
            while True:
                kind, message = messages.get_nowait()
                if kind == "log":
                    append_log(message)
                elif kind == "done":
                    messagebox.showinfo("完成", message)
                else:
                    append_log("错误：" + message)
                    messagebox.showerror("部署失败", message)
        except queue.Empty:
            pass
        root.after(150, poll_messages)

    buttons = ttk.Frame(frame)
    buttons.grid(row=6, column=0, columnspan=3, pady=4)
    ttk.Button(buttons, text="仅预检", command=lambda: start(False)).pack(side="left", padx=8)
    ttk.Button(buttons, text="开始部署", command=lambda: start(True)).pack(side="left", padx=8)
    ttk.Button(buttons, text="退出", command=root.destroy).pack(side="left", padx=8)
    ttk.Label(frame, text="提示：外部组件全部为自愿选项；已有外部目录不会被覆盖。", foreground="#875f00").grid(row=8, column=0, columnspan=3, sticky="w")
    poll_messages()
    root.mainloop()
    return 0


def parse_csv(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--astrbot-data", type=Path)
    parser.add_argument("--comfyui-root", type=Path)
    parser.add_argument("--hub-home", type=Path)
    parser.add_argument("--components", default="plugin,comfyui")
    parser.add_argument("--external", default="")
    parser.add_argument("--comfy-python", type=Path)
    parser.add_argument("--install-external-requirements", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    if not args.astrbot_data and not args.comfyui_root and not args.hub_home:
        return launch_gui(repo_root)
    guessed = guess_install_paths(repo_root)
    astrbot_data = args.astrbot_data or guessed["astrbot_data"]
    comfyui_root = args.comfyui_root or guessed["comfyui_root"]
    hub_home = args.hub_home or guessed["hub_home"]
    comfy_python = args.comfy_python or guessed["comfy_python"]
    plan = InstallPlan(
        repo_root=repo_root,
        astrbot_data=astrbot_data.expanduser().resolve(),
        comfyui_root=comfyui_root.expanduser().resolve(),
        hub_home=hub_home.expanduser().resolve(),
        components=parse_csv(args.components),
        external=parse_csv(args.external),
        comfy_python=comfy_python.expanduser().resolve() if comfy_python != Path() else None,
        install_external_requirements=args.install_external_requirements,
        apply=args.apply,
    )
    execute_plan(plan, print)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        raise SystemExit(f"错误：{exc}") from exc
