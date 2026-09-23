# Linux 懒人包

使用文件名含 `lazy-bundle-linux` 的包。Linux 与 Windows 分开入口、预检和示例；不需要运行 `.cmd` 或 PowerShell。Linux 目前支持 CLI 接入，不支持 AstrBot Desktop 模式。

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

不自动安装系统驱动、配置 systemd、登录 QQ 或重启云实例。无卡环境可部署文件/CPU 验证，但不能据此判断 CUDA 推理正常。现有环境不自动替换 Torch。Windows 的便携 Python、盘符和 Desktop 数据目录规则不适用于 Linux。

后续联通见 [AM 与模型](ANIMA_MASTER.md)、[一键部署总览](EASY_INSTALL.md)。
