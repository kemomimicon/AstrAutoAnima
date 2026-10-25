# Linux 懒人包

默认安装在用户目录下 `AstrAutoAnima-install`，不要部署到下载/临时目录。安装后不能直接改名或移动：配置与虚拟环境含绝对路径。搬迁需停止服务、备份并核对配置及环境；本轮独立搬家工具仅支持 Windows，不要在 Linux 使用。

使用文件名含 `lazy-bundle-linux` 的包。Linux 与 Windows 分开入口、预检和示例；不需要运行 `.cmd` 或 PowerShell。Linux 目前支持 CLI 接入，不支持 AstrBot Desktop 模式。

失败后不要新建第二套目录或清空模型，按 [失败续接说明](EASY_INSTALL.md) 处理。源码候选版会在开始执行时提前保存原独立目录的 `last-plan.json` 和 `deployment-status.json`，不含 API Key；CLI 可用同一 `last-plan.json` 再次 `--plan` 预检，核对后加 `--apply`。不能把 `runtime-env.json` 当计划文件。已经部署完成仅需开机使用时执行原 `Start.sh`，不重复 `--apply`。

## 无桌面服务器（推荐）

已有 Python、Git、curl 和 venv 功能。全新 AstrBot 用 Python 3.12；具体 GPU 环境由驱动和所选 PyTorch 共同决定。

```bash
cp examples/deployment-plan.linux.json my-plan.json
# 用文本编辑器修改 my-plan.json 后，先只读预检：
sh Deploy-Linux.sh --plan my-plan.json
# 预检成功并确认所有选项后执行：
sh Deploy-Linux.sh --plan my-plan.json --apply
```

默认示例是“接入已有环境”，路径仅为示例，必须改成自己的实际路径。若服务器 `python3` 不是所需版本：

```bash
AAA_PYTHON=/path/to/python3.12 sh Deploy-Linux.sh --plan my-plan.json
```

`destination` 为独立空目录；`astrbot` 是含真实 `data` 的运行目录；`comfyui` 是含 `main.py` 的目录。Python 不在各自 `.venv/bin/python` 或 `venv/bin/python` 时，显式填写 `astrbot_python` / `comfy_python`，例如已有 Conda 环境。AstrBot Python 同目录须有 `astrbot` CLI。

全新环境把 `install_astrbot`、`install_comfyui`、`install_dependencies` 设为 true，并清空对应已有路径。没有模型可勾选 `download_models: true`，阅读模型许可后设 `accept_model_license: true`；上游插件用 `install_am: true`。外部组件全都默认不拉取。

预检不联网、不修改环境。执行阶段会安装所选内容并启动服务；已有服务须先正常停止。路径存在错误、权限不足或依赖安装失败会停止并保留文件，不会用更强删除命令“修复”。

部署后执行安装目录的 `Start.sh`。`runtime-env.json` 含令牌，权限设为 600；Hub 默认监听 127.0.0.1，远程访问应另配 HTTPS/VPN，不直接暴露 ComfyUI 和管理端口。

## 有桌面的 Linux

系统已有 Tkinter 时运行 `sh Deploy-Linux.sh`；没有桌面时入口会给出计划文件用法，不再直接报 Tk DISPLAY 异常。可用 CLI 完成相同工作。

## 边界

模型或 AM ZIP 下载受限时，计划文件可配置 `download_mode`、`hf_mirror`、`github_mirror`、`download_proxy`、`am_archive`；见 [下载排错与字段说明](DOWNLOAD_NETWORK.md)。Windows 证书兼容开关不可用于 Linux。

不自动安装系统驱动、配置 systemd、登录 QQ 或重启云实例。无卡环境可部署文件/CPU 验证，但不能据此判断 CUDA 推理正常。现有环境不自动替换 Torch。Windows 的便携 Python、盘符和 Desktop 数据目录规则不适用于 Linux。

后续联通见 [AM 与模型](ANIMA_MASTER.md)、[一键部署总览](EASY_INSTALL.md)。
# NapCat 与统一入口（2026-10-20 本地候选）

有桌面的 Linux 运行 `sh Deploy-Linux.sh` 进入安装与启动中心。原 `--plan`、`--apply`、`--start` 命令保持兼容；无桌面仍使用计划文件。

NapCat 引导只在确认后准备固定提交、SHA256 校验的官方脚本，显示命令由你在服务器的交互终端执行；不自动 sudo、改开机服务或覆盖旧安装。QQ 扫码与设备验证仍由本人完成。桌面 / 无桌面、已有容器和 OneBot 对接的区别见 [NapCat 指引](NAPCAT_SETUP.md)。
