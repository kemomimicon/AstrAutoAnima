# 0.5.0 Beta 一键部署与首次使用

## 能自动完成什么

本包不是只复制文件：选择目录和选项后，一次点击完成预检、独立 Python 环境、所选依赖安装、插件 / 节点安装、配置和随机管理员令牌生成、服务启动与健康检查。以后用安装目录的 `Start.cmd`（Windows）或 `Start.sh`（Linux）启动。

不偷偷替用户做的事情：安装显卡驱动、接受模型许可证、下载未勾选模型、登录 QQ、绕过 AstrBot API 授权、修改系统防火墙或公开端口。没有模型或授权时，程序会明确报告“待配置”，不是宣称生图已可用。本 Beta 尚不承诺所有全新 Windows/Linux、显卡和第三方节点组合均可无人值守安装。

首次外部下载可能数 GB；建议先完成 Quick，再逐项启用反推与放大。已有环境只接入，不更换其 PyTorch。NapCat / QQ 使用自己的官方安装方式，向导不会操作登录缓存。

## Windows：首次部署

先选择对应系统的包：[Windows 分步指引](DEPLOY_WINDOWS.md) / [Linux 分步指引](DEPLOY_LINUX.md)。AstrBot Desktop 与 CLI 必须选择正确模式；桌面版无需填写内置 Python。

1. 下载并完整解压 `AstrAutoAnima-lazy-bundle-windows-0.5.0-beta.2.zip`。不要在 ZIP 内运行。
2. 双击 `Deploy-Windows.cmd`。缺 Python 3.12 时会询问是否用 winget 安装官方 Python；缺 Git 时也单独询问。拒绝则不下载。
3. 选择一个**空的独立安装目录**，例如 `D:\AAA-install`，不要选择磁盘根目录、用户目录或 ZIP 解压目录内部。
4. 二选一：
   - 已有环境：填写 AstrBot 根目录（包含 `data`）、ComfyUI 根目录及其 Python 可执行文件。venv 的 Python 通常在 `.venv\Scripts\python.exe`。
   - 全新环境：勾选下载 AstrBot 4.27.2、ComfyUI v0.21.1。会安装到独立目录，不覆盖其他实例。
5. 首次安装勾选“允许安装依赖”。NVIDIA 环境保留 GPU 选项，须已安装兼容驱动；CPU 选项仅适合安装验证，实际生图可能非常慢。不支持自动选择 AMD/Intel 计算后端，请接入已配置好的 ComfyUI。
6. 选择本地 UNET、CLIP、VAE，或勾选下载默认 **Anima Base 1.0** 三件套并确认许可。会按哈希校验并自动放置，生成不含私人 LoRA 的 Quick API 工作流。勾选核心上游 **Anima Master 0.7.1**，按 [AM 配置说明](ANIMA_MASTER.md) 完成联通。
7. 如果已有 AstrBot OpenAPI Key / 平台 Bot ID，一并填写；否则可稍后填写。**Bot ID 不是用户 QQ 或群号。**
8. 按需勾选反推 / 放大节点与模型下载，默认全部关闭。
9. 点击“预检并一键部署 / 启动”。部署时请勿关闭窗口；失败时不会自动删除旧数据、不会强杀服务，也不会重复执行另一套安装命令。

不要同时运行旧实例：6185 / 8188 / 6278 被占用时，部署会停止，防止边运行边覆盖。

## 第一次联通

- AstrBot：打开 `http://127.0.0.1:6185`。首次密码查看安装目录 `AstrBot.log`，按上游提示修改。
- ComfyUI：打开 `http://127.0.0.1:8188`；健康接口 `/system_stats` 应返回 JSON。
- Hub：访问 `http://127.0.0.1:6278/api/v1/health` 应显示 `0.5.0-beta.2` 和 `ok`。附带 Web App 的懒人包会自动配置首页；纯源码 / 服务包没有 Web App 时根页面 404 不代表服务未启动。
- App：填写 Hub 地址和安装目录 `runtime-env.json` 中的 `AAH_ADMIN_TOKEN`。不要把这个文件发到群里或提交 Git。
- AstrBot API：在 WebUI `设置 → OpenAPI` 创建所需 API Key，授予实际使用接口的 chat / message 等权限，再用向导填写 Key 和 Bot ID。向导不会自行改写 AstrBot 的内部密钥数据库。
- QQ：按 NapCat 和 AstrBot 官方文档完成登录、OneBot 连接；已有用户配置会保留。
- 中文生图 `/aicn` 仍需可用 LLM Provider，不会凭空提供免费翻译 API。反推模型、普通生图与 LLM API 是不同依赖。

重新配置前正常关闭各服务，再重开向导，指向同一个受管理安装目录；既有令牌、配置、用户提示词不会自动重置。仅新增缺失配置键；显式填写的新 API Key / Bot ID 会更新 Hub 的对应值。若需要改已有工作流路径，请在 AstrBot 插件设置中修改。

用 `/aimg_status` 检查插件后先跑一张普通图。HQ / Refine / SeedVR2 的模板仍有 `YOUR_*` 占位符；请按 `docs/WORKFLOWS.md` 选择所需节点、模型和参数，不能把仅部署文件当作全部高级工作流已经验收。

## Linux / 无图形服务器

准备 Python 3.12+（全新 AstrBot）、venv 和 Git。有桌面时可执行 `sh 一键部署_AstrAutoAnima.sh` 打开同一个向导。无桌面不要调用 Tk 窗口：

1. 复制 `examples/deployment-plan.linux.json` 为自己的计划，修改安装目录和已有环境路径。
2. 首次安装将 `install_dependencies` 设为 `true`；全新环境再按需设 `install_astrbot` / `install_comfyui` 为 `true`。
3. 计划可填写模型本地路径；API Key 可以先留空。包含密钥的计划文件必须妥善保护，勿发布。

```bash
python3 tools/deploy_project.py --plan /path/to/my-plan.json
python3 tools/deploy_project.py --plan /path/to/my-plan.json --apply
```

第一条仅预检，不写文件、不联网。第二条安装并启动。之后运行安装目录的 `Start.sh`，不是反复运行完整安装。

全新环境下载固定 AstrBot 4.27.2 / ComfyUI v0.21.1；Python 第三方依赖会由 pip 解析，不是全离线镜像。网络代理请用系统正常配置，不要在 URL 中嵌入账号密钥。

## 安全、备份和升级

- 默认 Hub 和 ComfyUI 只监听回环地址；手机或远程客户端应通过自己配置的 HTTPS / VPN。不要裸露 QQ、ComfyUI 或 AstrBot 管理端口。
- 文件升级前在安装目录 `backup_时间_随机值` 保存项目源码及插件配置；用户运行数据不会被发布包替换。首次旧版升级仍建议独立备份 AstrBot data。
- `.deploy.lock` 防止重复安装。异常断电后若遗留该文件，先确认没有安装进程，再手工删除该**单个文件**重试。
- `runtime-env.json` 是本地凭据；Linux 权限为 600，Windows 使用账户目录 ACL。`last-plan.json` 不保存 API Key。
- 日志和备份可能含用户后续配置，应留在本机，不要当发布资产上传。
- 不自动配置系统级开机自启；可把 `Start` 入口交给自己的服务管理器。不要给陌生用户系统关机或重启权限。
- 原有 `tools/easy_installer.py` 仍可用于专业用户只部署文件；新版默认入口是 `tools/deploy_project.py`。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 无 Python / Tkinter | Windows 按提示安装官方 Python 3.12（含 Tcl/Tk）；Linux 用计划文件 CLI 或安装系统 python3-tk |
| 目标目录非空 | 使用新空目录；接入已有服务时填写已有环境字段，不要把它们当向导安装目录 |
| pip / Git 下载失败 | 查网络、代理和日志，保留现有目录重试，不要删除配置或模型 |
| CUDA 不可用 | 先核对显卡驱动；CPU 仅验证服务，不能保证跑图速度；不自动卸载旧 Torch |
| 有进程但服务未就绪 | 以健康接口和日志为准，不以 screen 名或进程存在作为成功标志 |
| 反推缺节点 / llama_cpp 失败 | 查节点 requirements、GGUF/mmproj 配对与 GPU 后端；本向导不保证可自动编译所有平台的 llama-cpp CUDA |
| Hub 401 / 403 | 核对本机新生成令牌、普通用户权限及 AstrBot API scope，不使用作者服务器的令牌 |
| 随机抽不到提示词 | 公共包是空库，先导入自己的内容。可用本地提示词编辑器创建任意自定义组 |
| 第一次就能打开页面但不能跑图 | 阅读安装目录“下一步.txt”：模型、Bot ID、API Key、QQ 登录必须完成；健康检查不等于生图测试 |

官方参考：[AstrBot CLI](https://docs.astrbot.app/en/use/cli.html)、[AstrBot OpenAPI](https://docs.astrbot.app/dev/openapi.html)、[ComfyUI](https://docs.comfy.org/)、[NapCatQQ](https://napneko.github.io/)、[Python](https://www.python.org/downloads/)。
