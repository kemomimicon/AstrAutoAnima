# AstrAutoAnima

**0.5.2-1.44 · build44 · install.2**

面向 AstrBot + QQ/NapCat + ComfyUI/Anima 的跑图桥接套件，支持 Windows 本地电脑和 Linux 云服务器。
包含 QQ 生图、动态角色/画风 LoRA、随机提示词、图片反推、HQ、放大精修、Hub 和 Windows/Android/Web 客户端。

[下载最新完整包](https://github.com/kemomimicon/AstrAutoAnima/releases/tag/v0.5.2-1.44) ·
[安装说明](docs/EASY_INSTALL.md) · [初次配置](docs/FIRST_RUN_WIZARD.md) ·
[本次验收](docs/PUBLICATION_0.5.2-1.44.md) · [AutoDL 镜像使用](docs/AUTODL_IMAGE.md)

## 下载安装

首次安装选择 `AstrAutoAnima-0.5.2-1.44-install.2-complete.zip`，解压后打开
`first-run-guide/部署完整指南_打开即用.html`。Windows 和 Linux 部署包二选一。
管理端用于配置服务，个人端用于提交任务；服务端安装在运行模型的电脑或云实例。
AutoDL 终端部署只需上传指南内 `UPLOAD_TO_AUTODL` 的 Prepare ZIP 和 SHA256 文件。

软件包包含插件、Hub、工作流、自定义节点、批量词库工具、令牌管理、安装及首图向导和客户端。
模型按勾选项下载，词库可自行导入，账号及令牌由首次配置生成。

## 本次更新

- 整合 build44：角色造型、提示词分类、预设保存、断线重连、QQ 官方消息关联和重跑修复。
- ComfyUI Git 克隆失败时转用同版本官方 ZIP；固定 CUDA 12.8 PyTorch 组合。
- HQ/精修副本自动绑定所选基础模型，自动接通空画风链。
- 新增 WD 单独反推模板和 SeedVR2 3B FP16 固定下载清单，提供同 SHA256 的 ModelScope 来源。
- Windows/Linux 独立入口、阶段进度、恢复填写、搬家修复、密码/令牌查询与 SSH 指引。

RTX 4090 D 验收通过：基础 1024×1536、HQ/精修 1280×1920、WD 反推和分类选择、
SeedVR2 3B FP16 整图 682×1024。QQ 投递由维护者验证通过。

## 组件版本

| 组件 | 版本 |
| --- | --- |
| AstrBot 插件 | 0.5.2-beta.1 |
| Hub | 0.5.2b1 |
| Windows / Android / Web | 0.5.2-beta.1+44 |
| 工作流包 | 0.8.0-beta.1-public |
| 安装修订 | install.2 |
| Anima Master 兼容基线 | 0.7.1 |

## 兼容性特别说明

- 本项目实际联调的是 **AstrBot 绘画大师（Anima Master）0.7.1**。
- 已知上游有 **0.9.1**，但本项目尚未对 0.9.1 做回归测试；不要把“能加载”视为兼容保证。
- 建议首次部署固定 0.7.1。升级 0.9.1 前备份 AstrBot 的 `data/config`、插件数据及工作流，
  并在独立实例测试命令冲突、Provider、图片返回和工作流覆盖行为。
- AstrAutoAnima 的 `/aimg` 等指令可能与其他绘图插件重名；同一命令只保留一个处理插件。

基础环境只列官方入口，本仓库不重复提供其安装教程：

- AstrBot：<https://github.com/AstrBotDevs/AstrBot> / <https://docs.astrbot.app/>
- ComfyUI：<https://github.com/Comfy-Org/ComfyUI> / <https://docs.comfy.org/>
- NapCatQQ：<https://github.com/NapNeko/NapCatQQ> / <https://napneko.github.io/>
- Anima Master：<https://github.com/YayiMiko/anima-master>
- Anima 模型：<https://huggingface.co/circlestone-labs/Anima>

## 主要特色

- 私聊/群聊来源识别，AstrBot 管理员与白名单体系可继续作为入口权限层。
- Quick、HQ、已有图 Refine、WD/CL/JoyCaption 反推统一登记和任务追踪。
- 动态角色 / 画风 LoRA 链（默认最多 16 项，兼容旧固定槽）、底模直出角色、触发词与画风组合预设。
- `er_sde`、DPM++ 2M、DPM++ 2M SDE、GPU SDE 选项，以及步数、CFG、画布比例覆盖。
- B/G/D/C/R 来源组与 N/H/S 安全标签；S 组显式调用和受保护角色回退。
- 单抽、五连抽（默认限制同一普通用户一个活动任务）、混沌时刻和有序角色 / 画风任务套组。
- `/aicn` 中文提示词转换、`/aip` 可复选反推和仅返回提示词模式。
- Hub 管理端、普通用户令牌、Windows/Android 客户端、历史任务与图片查看/保存。
- 无第三方依赖的本地提示词管理器和 Hub 用户令牌管理器。
- 镜头、光照、材质选项；图片记录、自动保存、收藏 / 举报、可选安全审核；角色词典及个人画风。
- 提示词库可建立任意自定义分组，不要求沿用作者的来源组命名；固定 B/G/D/C/R 与 N/H/S
  只作为兼容和安全路由层保留。
- 一键部署向导：可接入已有环境，也可勾选下载独立 AstrBot / ComfyUI，安装依赖、生成本地配置和令牌、启动并检查服务。
  下载默认关闭；QQ 登录、API 授权、模型选择仍由用户确认。首次完成配置后，用生成的 Start 入口启动即可。

## 仓库结构

```text
plugin/                 AstrBot 插件（公开空提示词池）
comfyui/custom_nodes/   本项目自定义节点
comfyui/workflows/      脱敏工作流模板
hub/service/            FastAPI Hub 服务
clients/flutter/        Windows/Android 客户端源码
tools/                  提示词库、Hub 令牌本地管理工具
examples/               空数据结构与安全示例
docs/                   安装、使用、部署、排错和隐私说明
scripts/                发布前检查与辅助脚本
```

## 快速开始

Windows 与 Linux 用户可直接下载各自的 [0.5.2-1.44 独立全量总包](docs/PLATFORM_FULL_PACKAGES.md)。
每个包均包含平台安装器、全套组件与客户端、工具、源码和中文 HTML 指引；解压后从 `00_安装与使用说明.html` 开始。

1. 新手先看 [新版懒人包说明](docs/EASY_INSTALL.md)，双击一键部署入口；已有环境也可按 [手动安装教程](docs/INSTALL.md) 更新。
2. 安装 AstrBot 插件、自定义节点和所需的工作流 JSON。
3. 在工作流中把 `YOUR_ANIMA_*`、`YOUR_STYLE_LORA_*` 替换成自己实际存在的模型。
4. 在 AstrBot 插件配置页填写各 API 工作流绝对路径和正确节点 ID。
5. 用 [提示词管理工具](docs/TOOLS.md) 导入自己的审核库；公开包故意不带作者私有库。
6. 如需客户端，配置并启动 Hub，再生成用户令牌。
7. 先执行 `/aimg_status`，然后用一条普通 `/aimg` 在私聊中完成最小验证。

完整说明：

- [详细安装](docs/INSTALL.md)
- [一键部署懒人包](docs/EASY_INSTALL.md)
- [Windows 部署](docs/DEPLOY_WINDOWS.md) / [Linux 部署](docs/DEPLOY_LINUX.md)
- [Anima Master 0.7.1 配置与模型下载](docs/ANIMA_MASTER.md)
- [授权主题与开屏](docs/ARTWORK.md)
- [使用手册](docs/USAGE.md)
- [本地/服务器部署](docs/DEPLOYMENT.md)
- [常见错误排查](docs/TROUBLESHOOTING.md)
- [本地管理工具](docs/TOOLS.md)
- [特色、优点与限制](docs/FEATURES_AND_LIMITATIONS.md)
- [隐私与公开包边界](docs/PRIVACY.md)
- [发布包及校验说明](docs/RELEASE_ARTIFACTS.md)
- [第三方组件与许可证](THIRD_PARTY_NOTICES.md)

## 公开包不包含什么

本仓库不包含服务器令牌、QQ 登录数据、真实 QQ 号、私有/第三方提示词语料、角色/画风预设、
作者的默认生产工作流、未授权私人图片、模型、LoRA、生成图片、反推历史、日志、备份或服务器
目录快照。工作流模板中的 `YOUR_*` 均为必须由部署者填写的占位符。

## 优点与限制（摘要）

优点是模块完整、可审计、可按指令动态改写工作流，并同时覆盖 QQ 与客户端入口。限制是
部署组件较多、节点 ID 与工作流拓扑强耦合；HQ/Refine/反推/训练仍属 Beta，模型和外部节点
需要用户自行下载且受各自许可证约束。详见[完整说明](docs/FEATURES_AND_LIMITATIONS.md)。

## 许可证

本仓库自有代码使用 [MIT License](LICENSE)。第三方软件、模型、LoRA、提示词和生成内容不因
本仓库许可证而改变其原有授权；请逐项检查 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 反馈与交流

使用中遇到问题，欢迎在 bilibili 联系 **ケモミミロリコン**，附上组件版本、操作步骤和报错截图。
