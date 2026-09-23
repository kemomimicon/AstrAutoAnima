# AstrAutoAnima 0.5.0 Beta 完整发行整合包

本整合包统一收录已发布并校验的 **0.5.0-beta.2** 组件。它是完整的 Beta 发行套件，**不是取消 Beta 标识的稳定版**，也不是包含显卡驱动和模型的全离线系统镜像。

## 从这里开始

先完整解压外层 `AstrAutoAnima-0.5.0-beta.2-complete.zip`，再按以下用途选择内部 ZIP。**不要全部安装，也不要直接在压缩包里启动程序。**

| 用途 | 目录与操作 |
| --- | --- |
| Windows 电脑部署服务 | 解压 `deployment/` 中的 windows 懒人包，进入解压目录双击 `Deploy-Windows.cmd`；详见 `docs/DEPLOY_WINDOWS.md` |
| Linux／云服务器部署服务 | 解压 `deployment/` 中的 linux 懒人包，有桌面运行 `sh Deploy-Linux.sh`；无桌面按 `docs/DEPLOY_LINUX.md` 使用计划文件预检与 `--apply` |
| 已有服务器，只安装 App | `clients/windows/` 或 `clients/android/` 中选择 Admin（管理端）或 Service（用户端），填写自己服务器的 Hub 地址和令牌 |
| 使用浏览器 | 两个懒人包已内置 Web；独立 Web 包在 `clients/web/`，需要配套 Hub，不是双击 HTML 就能独立生图 |
| 手动升级插件、Hub、工作流 | 使用 `components/`；先备份自己的配置、词库和数据并正常停止相关服务，参阅 `docs/INSTALL.md`、`docs/WORKFLOWS.md` |
| 本地编辑词库／管理用户令牌 | 解压 `tools/` 下的工具包，按其中 `docs/TOOLS.md` 启动工具；图形界面需 Python + Tkinter |
| 开发、修改和查看源码 | `source/` 包含对应发布源码；部署无需先编译客户端 |
| 使用授权美术资源 | `artwork/` 含主题和开屏资源；授权说明见 `docs/ARTWORK.md` |

Windows 客户端 ZIP 必须整目录解压。Android APK 使用社区测试签名；若与旧安装签名冲突，先导出配置再处理，避免丢失设置。Linux 本包提供服务部署和 Web 客户端，不含原生 Linux 桌面 App。

## 必须了解的配置

1. **Anima Master 0.7.1 是已联调的核心上游**；0.9.1 未测试，不要直接替代。安装后按 `docs/ANIMA_MASTER.md` 完成连接及配置。
2. 默认模型方案为 **Anima Base 1.0**。模型权重不随包分发，显式勾选下载并确认许可后才拉取和自动归档；也可选择已有模型。其他环境、节点、依赖下载同样由用户选择。
3. 公共提示词库和私人预设为空。用本地编辑器导入自己有权使用的提示词，可建立自定义分组。没有导入词库时，随机抽图无候选是正常现象。
4. QQ 登录、NapCat／OneBot 对接、AstrBot API Key、Bot ID 和 App 令牌需要按自己的环境配置。部署成功不代表这些授权已自动完成。
5. 手机连接本地电脑时，`127.0.0.1` 指向手机自身；请使用受保护且可达的 Hub 地址，推荐 HTTPS／VPN，勿裸露管理服务。不要分享本机生成的凭据文件。
6. 中文转换依赖自行配置的 LLM Provider。反推、HQ、放大等高级工作流需要各自的节点和模型，不是基础包解压后即全部可用。

## 校验和排错

- 外层 ZIP：可与 GitHub 附件 `AstrAutoAnima-0.5.0-beta.2-complete.sha256.txt` 比较 SHA256。
- 解压后：在整合包根目录运行 `python verify_complete_suite.py`（Linux 可用 `python3`），逐项验证内部分包和文档，不安装依赖、不联网、不改文件。
- `suite-manifest.json` 记录完整目录、文件大小、哈希和组件来源；`original-release/` 保存原始分包清单及发布说明。
- 哈希用于完整性核对，不代替可信下载来源。校验失败请重新下载，不要忽略错误继续安装。
- 路径、PowerShell 编码、目标目录、端口占用、授权和节点问题详见 `docs/TROUBLESHOOTING.md`、`docs/EASY_INSTALL.md`。

## 内容和验证边界

整合包保留原分包字节，不重新混入私人开发目录。**不包含密钥、API 凭据、服务器配置、QQ 登录数据、真实提示词库、模型权重或炼丹炉连接器**。工作流包版本独立于主项目，为 `0.8.0-beta.1-public`；这不是 Anima Master 的版本。

基线发布提交：`3709c1da57b4808f663c907795fd5fe107b2a173`。Windows、Python 3.11／3.12 CI 已通过；Hub 隔离启动与配置保留测试通过。详细结果见 `docs/VERIFY_RELEASE.md`。仍未完成全部全新系统及实际 GPU 生图组合验收，不承诺所有机器无人值守成功。

官方项目入口：[AstrAutoAnima](https://github.com/kemomimicon/AstrAutoAnima)、[AstrBot](https://docs.astrbot.app/)、[ComfyUI](https://docs.comfy.org/)、[NapCat](https://napneko.github.io/)。
