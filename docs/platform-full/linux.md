# AstrAutoAnima 0.5.2-1.44 Linux 全量总包

版本：0.5.2-1.44 / build44 / install.2 / full.1。适用 Linux x86_64 服务器或本地 Linux 电脑。
本包提供服务部署与 Hub Web 管理界面；还附带连接这台服务器使用的 Windows、Android 管理端和个人端。

## 1. 包里有什么

- installer：已经解压好的 Linux 安装器、插件、Hub、Web、工作流、自定义节点和配置工具。
- components：可独立安装的 AstrBot 插件、Hub 服务和工作流/节点包。
- clients：Windows Admin/Service、Android 管理端/个人端、独立 Web 成品；Hub 安装器也已内置 Web。
- tools：词库编辑与导入导出、用户令牌管理、扩展说明和恢复工具。
- artwork：主题与开屏资源；source：本次公开源码；docs：完整专题说明和常见问题。
- connection-tools：在自己的 Windows 电脑上连接 Linux 服务器时使用的 SSH 隧道工具。

本总包可独立完成 Linux 服务部署，无须再下载 Windows 总包。模型由安装器按所选来源下载，或使用已有文件。
官方环境入口：AstrBot https://docs.astrbot.app/ ，ComfyUI https://docs.comfy.org/ ，NapCat https://napneko.github.io/ 。

## 2. 校验、解压与 Python

将本包与同名 sha256.txt 放到服务器长期保存的目录。以下命令在服务器终端执行：

```bash
sha256sum -c AstrAutoAnima-Linux-0.5.2-1.44-Full.sha256.txt
unzip AstrAutoAnima-Linux-0.5.2-1.44-Full.zip
cd AstrAutoAnima-Linux-0.5.2-1.44-Full
python3 -B verify_complete_suite.py
```

全新 AstrBot 环境使用 Python 3.12，并准备 Git、curl 和 Python venv。终端检查：

```bash
python3 --version
command -v git curl
python3 -m venv --help
```

服务器有多个 Python 时，用 AAA_PYTHON 指向所需的真实 Python 可执行文件。AutoDL 可使用独立的 Python 3.12 Conda 环境；数据与模型优先放在持久数据盘。
包的解压目录与独立安装目录分开；AutoDL 示例独立安装目录为 /root/autodl-tmp/aaa-install，普通用户可选择自己有写权限的长期目录。

## 3. 部署：有桌面与只有终端

有桌面的 Linux，已安装 Tkinter 后运行：

```bash
bash Install-Linux.sh
```

在安装中心①选择全新或已有环境、依赖、模型和 Anima Master 0.7.1；先预检，再执行。

无桌面服务器使用计划文件。在本总包根目录复制示例，然后用 Jupyter 编辑器或文本编辑器填写自己的路径和选择：

```bash
cp installer/examples/deployment-plan.linux.json my-plan.json
python3 -m json.tool my-plan.json
```

示例最初为接入已有环境。按用途修改这些字段：
- destination：独立安装目录，不能与包解压目录、ComfyUI 或 AstrBot 目录重合。
- 已有环境：astrbot 填含 data 的实际运行目录，comfyui 填含 main.py 的目录；相应 Python 填真实路径。
- 全新安装：清空 astrbot、comfyui、astrbot_python、comfy_python，选择 install_astrbot、install_comfyui、install_dependencies 为 true。
- 核心上游：选择 install_am 为 true，安装兼容基线 Anima Master 0.7.1；0.9.1 的适配单独处理。
- 基础模型：选择 download_models 为 true；阅读模型许可后将 accept_model_license 设为 true，默认下载 Anima Base 1.0、Qwen 编码器和 VAE。
- 网络来源：download_mode 可选 official 或 modelscope，也可按 docs/DOWNLOAD_NETWORK.md 填写本地模型文件及代理/镜像选项。
- 首次尚未创建的 AstrBot API Key 和 Bot ID 留空，完成服务安装后再配置。

填写好后，用计划文件的绝对路径预检和安装：

```bash
bash Install-Linux.sh --plan "$PWD/my-plan.json"
bash Install-Linux.sh --plan "$PWD/my-plan.json" --apply
```

需要指定 Python 时，两条命令都加上相同的 AAA_PYTHON：

```bash
AAA_PYTHON=/absolute/path/to/python3.12 bash Install-Linux.sh --plan "$PWD/my-plan.json"
AAA_PYTHON=/absolute/path/to/python3.12 bash Install-Linux.sh --plan "$PWD/my-plan.json" --apply
```

观察九阶段日志。失败保留安装目录、下载断点和 last-plan.json，修正对应项目后重新预检并继续。
成功后执行实际安装目录的 Start.sh 日常启动。

## 4. 打开 Web、查看凭据和配置首次授权

同机访问：AstrBot http://127.0.0.1:6185 ，ComfyUI http://127.0.0.1:8188 ，AAA 管理端 http://127.0.0.1:6278 。
远程服务器用户在自己的电脑运行 connection-tools/Open-AAA-Tunnel.cmd，填写该实例控制台提供的 SSH 主机、端口和自己的凭据。隧道窗口保持打开，再用电脑浏览器访问以上本地地址。
SSH 密码、AstrBot 登录密码、OpenAPI Key 和 Hub 令牌分别用于不同入口。

凭据位置与用途：
- AstrBot 首次登录：查看 AstrBot 启动终端或实际安装目录的 AstrBot 日志，按首次登录页面完成自己的密码设置。
- AstrBot OpenAPI：登录 6185 → 设置 → OpenAPI，创建完整 Key 并授予实际使用的 chat/file/message 权限，填入 AAA 管理端或首图配置。
- Hub 管理员令牌：安装器在本机生成，实际安装目录的 runtime-env.full.json / runtime-env.json 中 AAH_ADMIN_TOKEN 用于管理端登录。
- 个人令牌：管理端用户页创建，提供给对应用户的 Service 个人端或手机 App。
- NapCat WebUI Token：登录 6099 页面；OneBot Token 用于 NapCat/AstrBot 两端对接。

保存自己的凭据，录屏前收起凭据。复制 OpenAPI 创建成功时的完整 Key，列表中的短前缀不能鉴权。
无桌面服务器通过 Hub Web 管理用户、词库和生图；有桌面的 Linux 可运行 First-Run-Linux.sh 打开本机配置向导。

## 5. NapCat、投递与第一张图

按 docs/NAPCAT_SETUP.md 在服务器准备固定版本官方安装入口，然后在交互终端完成安装、启动和 QQ 扫码。
AstrBot 使用 OneBot v11，反向 WebSocket 端口 6199；NapCat 的 WebSocket 客户端连接 ws://127.0.0.1:6199/ws，两端填同一个 OneBot Token。
QQ 中发送 /sid 获取实际 Bot ID；在 AAA 管理端填写自己的私聊或群聊目标，再配置相应用户令牌。

先提交一张英文提示词基础图，确认任务完成、Web/App 预览和下载都正常，再配置词库和高级扩展。
中文转换使用自行配置的 LLM Provider。Anima Master 配置与基础模型绑定见 docs/ANIMA_MASTER.md。

## 6. 词库、角色、工具与扩展

管理端导入自己的 JSON/CSV/TXT 词库，可自定义分组。图形词库编辑器为 installer/tools/prompt_pool_manager.py；有桌面时可使用，命令行使用 --help 查看导入导出选项。
角色词典装配见 docs/FIRST_RUN.md，LoRA 和画风按实际模型名称建立预设。
用户令牌可在管理端用户页创建、禁用和轮换；离线批量管理工具为 installer/tools/hub_lite_user_manager.py。
HQ、Anima 精修、WD、SeedVR2、JoyCaption 和 Studio 连接器按 docs/EXTENSIONS_GUIDE.md 选择安装与装配。SeedVR2 图像与 VAE 分块保持关闭。
完整工具用法见 docs/TOOLS.md，配置与量化方案见 docs/HARDWARE_AND_QUANTIZATION.md，美术资源见 docs/ARTWORK.md。
4090 D 的基础/HQ/精修/WD/SeedVR2 验收与 5090 新镜像恢复首图结果见 docs/PUBLICATION_0.5.2-1.44.md。

## 7. 日常启动、恢复与 Q&A

- 日常启动：执行实际安装目录中的 Start.sh；不要重复全新部署。
- 下载慢或中断：保留断点，按大小和 SHA256 校验；可改用已提供的来源或本地文件。
- 401：核对报错来自 AstrBot 还是 Hub，检查对应的完整 Key/令牌、地址和权限。
- 节点或模型缺失：先看 ComfyUI 启动日志，再按 docs/WORKFLOWS.md 和扩展说明补齐对应模型/节点。
- GPU 显存：按基础、HQ/精修、反推、SeedVR2 分阶段验收；具体配置见硬件说明。
- Linux 安装目录中的配置与虚拟环境含绝对路径，搬迁前应停服务并备份，按新位置重新装配环境；Windows 搬家工具只用于 Windows。

常见问题见 docs/SETUP_QA.md、docs/TROUBLESHOOTING.md。遇到问题欢迎在 bilibili 联系「ケモミミロリコン」，附组件版本、操作步骤和报错截图。
项目与更新：https://github.com/kemomimicon/AstrAutoAnima/releases/tag/v0.5.2-1.44
