# 一键部署懒人包

一键部署助手面向已经装好 AstrBot、ComfyUI 和（如需 QQ）NapCatQQ 的用户。它不会替你安装
这些基础项目，也不会修改 QQ 登录数据；它负责把 AstrAutoAnima 自身的插件、工作流、自定义
节点和可选 Hub 放到正确位置，并在覆盖前备份。

## Windows 图形安装

1. 完整解压 `AstrAutoAnima-0.4.0-lazy-bundle.zip`，不要直接在压缩软件内运行。
2. 双击根目录 `一键部署_AstrAutoAnima.bat`。
3. 确认自动探测的 AstrBot `data`、ComfyUI 根目录与 Hub 安装目录；没有探测到时点“选择”。
4. 默认勾选“AstrBot 插件”和“自定义节点与工作流”，Hub 默认不选。
5. 先点“仅预检”。预检不会写入任何文件。
6. 确认摘要后点“开始部署”。已有组件会被复制到懒人包同级的时间戳备份目录。
7. 在 AstrBot WebUI 重载插件，并完整重启 ComfyUI。

工具只依赖 Python 3.10+ 标准库和 Tkinter。若窗口一闪而过，在终端运行：

```powershell
py -3 tools\easy_installer.py
```

即可看到具体错误。

## Linux/服务器

有图形环境时：

```bash
sh 一键部署_AstrAutoAnima.sh
```

无图形服务器使用命令行。以下第一条只预检，第二条才执行：

```bash
python3 tools/easy_installer.py \
  --astrbot-data /workspace/astrbot-runtime/data \
  --comfyui-root /workspace/ComfyUI \
  --hub-home /workspace/astr-auto-anima-hub

python3 tools/easy_installer.py \
  --astrbot-data /workspace/astrbot-runtime/data \
  --comfyui-root /workspace/ComfyUI \
  --hub-home /workspace/astr-auto-anima-hub \
  --apply
```

不安装 Hub 时保持默认 `--components plugin,comfyui`。安装 Hub：

```bash
python3 tools/easy_installer.py ... --components plugin,comfyui,hub --apply
```

首次安装 Hub 会在目标目录生成 `.env` 和一次性令牌文件。令牌只生成在用户机器上，不存在于
发布包中；阅读并转移到安全密码管理器后删除明文文件。

## 外部拉取开关

以下项目默认全部关闭：

- ComfyUI-Booru-Tagger 节点；
- JoyCaption GGUF 节点；
- SeedVR2 节点与分块放大节点；
- WD-EVA02 模型；
- JoyCaption Q6_K 与 mmproj 模型。

只有勾选具体项目时才会访问 GitHub/Hugging Face。已有外部目录不会被覆盖；大模型使用 `.part`
临时文件和断点续传，已知哈希会在完成后校验。勾选“安装外部 requirements.txt”会修改
ComfyUI Python 环境，所以它也是独立且默认关闭的选项。

CL Tagger v2 需要先在模型页面接受许可，因此不提供自动拉取开关。请按工作流说明手动安装。

例如只拉取两个反推节点（先预检）：

```bash
python3 tools/easy_installer.py ... \
  --external booru_tagger_node,joycaption_node
```

确认后追加 `--apply`。若还要安装节点依赖，必须同时给出真实 ComfyUI Python：

```bash
--comfy-python /workspace/KSKvENv/bin/python --install-external-requirements
```

## 安全边界

- 不删除 `plugin_data`、模型、用户工作流、QQ 数据或 Hub 数据库。
- 只备份和覆盖明确选择的同名本项目组件。
- 不自动启动、停止或杀死服务；部署后由用户按原有方式重载/重启。
- 不自动开放公网端口，不写防火墙规则。
- 不把真实令牌、QQ 号、提示词库或模型写回发布目录。
- 外部下载失败时保留 `.part` 供下次断点续传，不把半截文件伪装成最终模型。

如果已有自定义修改，先单独做人工备份并检查自动备份，再部署正式版。
