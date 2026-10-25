# AstrAutoAnima 0.5.2-1.44 Windows 全量总包

版本：0.5.2-1.44 / build44 / install.2 / full.1。适用 Windows x64。
完整解压本包后，先打开同目录的 00_安装与使用说明.html，首次安装双击 Install-Windows.cmd。

## 1. 包里有什么

- installer：已经解压好的 Windows 安装器、插件、Hub、Web、工作流、自定义节点和首次配置工具。
- components：可独立安装的 AstrBot 插件、Hub 服务端和工作流/节点包。
- clients/windows：Admin 管理端和 Service 个人端，两个程序按用途选择，ZIP 必须整目录解压。
- clients/android：Android 管理端与个人端，可连接同一台 Hub。
- clients/web：独立 Web 成品；部署器已经为 Hub 配套提供 Web。
- tools：可视化词库编辑、批量导入导出、令牌管理、扩展说明、恢复和搬家工具。
- artwork：主题与开屏美术资源；source：本次对应公开源码；docs：完整专题说明和排错。
- connection-tools：连接 Linux/AutoDL 时使用的 SSH 隧道工具。

这是可独立部署的总包，无须再下载 Linux 总包。默认模型为 Anima Base 1.0，模型在安装器中选择下载或使用已有文件。
项目基础环境官方入口：AstrBot https://docs.astrbot.app/ ，ComfyUI https://docs.comfy.org/ ，NapCat https://napneko.github.io/ 。

## 2. 校验与解压

下载同名 sha256.txt。在 PowerShell 中计算压缩包哈希，与校验文件中的值比较：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '.\AstrAutoAnima-Windows-0.5.2-1.44-Full.zip'
```

完整解压到长期保留的位置，例如 D:\AAA-Package。进入解压目录，执行只读文件校验：

```powershell
py -3 .\verify_complete_suite.py
```

校验显示 PASS 后继续。首次系统没有 Python 时，可先双击 Install-Windows.cmd，按依赖引导安装 Python，再回到这里校验。
包的解压位置与“独立安装目录”是两个目录；独立安装目录可选 D:\AAA-install。不要选择磁盘根目录、下载临时目录或已有 ComfyUI 目录作为独立安装目录。

## 3. 首次部署

1. 双击 Install-Windows.cmd，进入中文安装与启动中心，打开①部署环境。
2. 全新安装选择 AstrBot CLI。按需要勾选安装 Python 依赖、全新 AstrBot、全新 ComfyUI、Anima Master 0.7.1，以及基础模型三件套；外部下载均由你选择。
3. 已有 AstrBot Desktop 时先运行一次让它初始化数据，再正常退出；选择 desktop 和真实数据目录（通常为用户目录下的 .astrbot），不另装第二套 AstrBot。
4. 已有 ComfyUI 时选择含 main.py 的真实目录；portable 选择外层目录，安装器会识别嵌入式 Python。填写的目录必须属于正在使用的同一套环境。
5. 默认基础模型为 anima-base-v1.0、qwen_3_06b_base、qwen_image_vae。阅读模型许可后选择下载与许可确认；安装器将其放入对应模型目录并绑定基础工作流。
6. 网络来源可选官方、已校验的 ModelScope 固定文件或本地模型文件。先预检，再执行部署；观察九阶段进度和实时日志。
7. 部署结束后使用所选独立安装目录中的 Start.cmd 日常启动，不需要每次重新部署。

Anima Master 0.7.1 是核心上游兼容基线，安装后还要配置 ComfyUI 地址和工作流；完整步骤见 docs/ANIMA_MASTER.md。0.9.1 的适配单独处理。
本次基础/HQ/精修/WD/SeedVR2 的 4090 D 实机结果，以及新镜像 5090 恢复与首图结果见 docs/PUBLICATION_0.5.2-1.44.md。

## 4. 登录、令牌与第一张图

打开 AstrBot：http://127.0.0.1:6185 ，ComfyUI：http://127.0.0.1:8188 ，AAA 管理端：http://127.0.0.1:6278 。
AstrBot 首次账号/密码信息查看它的启动终端或安装目录中的 AstrBot 日志，按首次登录页面完成自己的密码设置。

双击本包 First-Run-Windows.cmd，选择实际安装目录的 runtime-env.json，按向导完成授权、目标和首图。

凭据用途分别是：
- AstrBot 登录密码：用于 6185 管理网页。
- AstrBot OpenAPI Key：在 AstrBot 设置 → OpenAPI 创建完整 Key，授予实际使用的 chat/file/message 权限，填入 AAA 首图向导的 AstrBot API Key。
- Hub 管理员令牌：用于 AAA 管理端；由安装器在本机生成，保存在实际安装目录的 runtime-env.full.json / runtime-env.json 中的 AAH_ADMIN_TOKEN。
- 个人用户令牌：由管理端用户页创建，只填入 Service 个人端或对应用户的 App。
- NapCat WebUI Token：用于 NapCat 的 6099 管理页面；OneBot Token：两端对接时填写同一个值，两者用途不同。

保存好自己的密码和令牌，录屏前收起凭据。OpenAPI 复制创建成功时的完整 Key，列表显示的短前缀不能用于鉴权。
先用英文提示词生成一张图，确认任务完成、App 能预览并下载，再配置词库、角色、LoRA 和高级工作流。
中文提示词转换使用自己配置的 LLM Provider；普通英文生图按提示词直接运行。

## 5. QQ、词库、角色和扩展

在安装中心②准备 NapCat，完成官方安装流程后打开 NapCat 并扫码登录。AstrBot 新建 OneBot v11，端口 6199；NapCat 的 WebSocket 客户端连接 ws://127.0.0.1:6199/ws，两端 Token 相同。QQ 中发送 /sid 获取实际 Bot ID，再在 AAA 配置真实私聊或群聊目标。
QQ 扫码登录由实例使用者完成；具体界面和启动说明见 docs/NAPCAT_SETUP.md。

词库：在管理端导入自己的 JSON/CSV/TXT，或打开 installer/tools/prompt_pool_manager.py 编辑工作副本；可创建自定义分组、批量导入并导出。
角色：按 docs/FIRST_RUN.md 装配角色词典；LoRA 文件放到 ComfyUI 模型目录，在管理端建立角色/画风预设。
令牌：管理端用户页可创建与轮换个人令牌；离线批量工具为 installer/tools/hub_lite_user_manager.py。
HQ、Anima 精修、WD、SeedVR2、JoyCaption 和 Studio 扩展按 docs/EXTENSIONS_GUIDE.md 选择安装。SeedVR2 图像和 VAE 分块保持关闭。
美术资源和工具逐项操作见 docs/ARTWORK.md、docs/TOOLS.md；配置与量化方案见 docs/HARDWARE_AND_QUANTIZATION.md。

## 6. 更新、日常启动与恢复

- 日常使用：运行实际安装目录的 Start.cmd；仅连接服务器时，打开 clients/windows 中对应的 Admin 或 Service。
- 安装失败：保留原目录和日志，重新打开安装器，读取原 last-plan.json，修正对应阶段后预检并继续。
- 401：区分 AstrBot Key 与 Hub 令牌；核对服务地址、完整 Key 和权限后重新验证。
- 模型下载失败：改选已提供的来源或本地文件，保留断点文件，核对大小和 SHA256。
- 改名或搬迁：先停服务，使用安装中心的 Windows 搬家/路径修复工具；先备份，再复制和修复路径。
- 提示 LoRA not in list：按 ComfyUI 返回的模型相对名称选择，Windows 子目录分隔符也需匹配；使用 docs/QUICK_LORA_DOCTOR.txt 的检测指引。
- 提示找不到原任务：使用新任务生成的原图消息及其关联标记；QQ 官方适配说明见 docs/REMAKE_HOTFIX.md。

完整 Q&A：docs/SETUP_QA.md、docs/TROUBLESHOOTING.md。遇到问题欢迎在 bilibili 联系「ケモミミロリコン」，附组件版本、操作步骤和报错截图。
项目与更新：https://github.com/kemomimicon/AstrAutoAnima/releases/tag/v0.5.2-1.44
