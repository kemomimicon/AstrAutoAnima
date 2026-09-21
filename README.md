# AstrAutoAnima

面向 AstrBot + QQ/NapCat + ComfyUI/Anima 的完整跑图桥接套件。它把 QQ 指令、动态角色/画风
LoRA、分级随机提示词、图片反推、HQ/放大精修、远程 Hub 和 Windows/Android 客户端组合为
一套可在云服务器或本地计算机部署的方案。

> 当前为 `0.5.0-beta.1` 公开测试版（不是正式稳定版）。不含炼丹炉 / LoRA Studio 扩展接口、代理、会话或客户端入口。
> HQ、Refine、Reverse 等高级工作流仍为实验性组件，
> 请先在测试群和备份配置上验证，再迁移生产环境。

## 组件版本

| 组件 | 公开包版本 | 作用 |
| --- | --- | --- |
| AstrBot 插件 | `0.5.0-beta.1` | QQ 指令、工作流调度、预设、提示词池、任务记录 |
| Hub 服务 | `0.5.0b1` | 令牌鉴权、远程任务、预设/提示词/图片记录 API |
| Flutter 客户端 | `0.5.0-beta.1+35` | Web/Windows/Android 管理和远程生图 |
| 工作流包 | `0.8.0-beta.1-public` | 最新模板脱敏导出，不含独立训练服务 |
| 自定义节点 | Workflow Tools | 训练数据质检、反推编译与记录保存 |
| 工作流 | HQ / Refine / Reverse / Training Beta | 多工作流模板；安装前必须填写模型占位符 |

## 兼容性特别说明

- 本项目实际联调的是 **AstrBot 绘画大师（Anima Master）0.7.2**。
- 已知上游有 **0.8.0**，但本项目尚未对 0.8.0 做回归测试；不要把“能加载”视为兼容保证。
- 建议首次部署固定 0.7.2。升级 0.8.0 前备份 AstrBot 的 `data/config`、插件数据及工作流，
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
作者的默认生产工作流、私人启动图、模型、LoRA、生成图片、反推历史、日志、备份或服务器
目录快照。工作流模板中的 `YOUR_*` 均为必须由部署者填写的占位符。

## 优点与限制（摘要）

优点是模块完整、可审计、可按指令动态改写工作流，并同时覆盖 QQ 与客户端入口。限制是
部署组件较多、节点 ID 与工作流拓扑强耦合；HQ/Refine/反推/训练仍属 Beta，模型和外部节点
需要用户自行下载且受各自许可证约束。详见[完整说明](docs/FEATURES_AND_LIMITATIONS.md)。

## 许可证

本仓库自有代码使用 [MIT License](LICENSE)。第三方软件、模型、LoRA、提示词和生成内容不因
本仓库许可证而改变其原有授权；请逐项检查 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
