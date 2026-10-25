# 0.5.2-1.44 发行说明

对外版本 **0.5.2-1.44**，客户端 build44，安装包修订 install.2。
插件内部版本 0.5.2-beta.1，Hub 0.5.2b1。完整包汇集服务器组件、各端客户端和首次部署指南。

## 实机验收

2026-10-25，独立 AutoDL RTX 4090 D 24GB 实例：

| 项目 | 结果 |
| --- | --- |
| 基础三件套大小与 SHA256 | 通过 |
| ComfyUI / AstrBot / Hub 启动 | 通过 |
| AstrBot OpenAPI 生图 | 1024×1536，通过 |
| Hub 任务、图片下载与哈希 | 通过 |
| HQ stable | 1280×1920，通过 |
| Anima light 精修 | 1280×1920，通过 |
| WD 单独反推 | 通过 |
| WD 环境/动作分类选择 | 通过 |
| SeedVR2 3B FP16 | 384×576 → 682×1024，通过 |
| 扩展安装后基础生图回归 | 1024×1536，通过 |
| QQ 投递 | 维护者验证通过 |

SeedVR2 使用整图推理、CPU offload 和 batch=1，图像及 VAE 分块关闭。
本轮采用 ComfyUI v0.21.1、Torch 2.11.0+cu128、AstrBot 4.27.2、Anima Master 0.7.1。
JoyCaption、CL Tagger 可按扩展说明选装。AM 0.9.1 仍采用单独适配流程。

## 安装修复

1. ComfyUI Git 下载中断后自动使用校验过的官方同版本归档，残留目录另存备份。
2. 固定 Torch/torchvision/torchaudio 组合；普通依赖沿用用户配置的 PyPI 来源。
3. HQ 和精修生成独立模型绑定副本，接通模板占位 LoRA；已有自定义副本与真实 LoRA 保留。
4. WD 单独反推有专用五节点模板；完整 WD/CL/JoyCaption 模板继续提供。
5. SeedVR2 节点固定到实测提交，3B FP16 与 VAE 可选 ModelScope 固定文件，大小及 SHA256 一并验证。

## 下载与配置

完整包内打开 `first-run-guide/部署完整指南_打开即用.html`。
已有环境更新前备份 `data/config`、插件数据和自定义工作流。
软件包使用空词库和通用模板，私人令牌、账号、模型与业务数据在本机配置。

Windows 管理端与个人服务端分开提供；Android 提供管理端和个人端；Web 随 Hub 部署。
客户端沿用本次 build44 对应成品，插件、Hub、安装器和工作流按本次提交打包。

AutoDL 公开镜像按 [镜像发布步骤](AUTODL_IMAGE_PUBLISH.md) 导入平台。
既有原实例和已保存镜像保留，新的软件包通过 GitHub 发行页提供。

## AutoDL image.1 / V 0.4.2

公开镜像母版 `AstrAutoAnima-0.5.2-1.44-V042` 含 G 组 4,000 条、V 国风完整卡 193,339 条、
角色词典 21,051 条，以及 Studio 0.25.0。2026-10-25 的 RTX 5090 全新实例通过一键恢复、
独立应用凭据、首次登录改密与重启、OpenAPI、1024×1536 基础生图及 Hub 图片下载验收。
首次恢复到完成基础首图约 3.5 分钟。

镜像源码提交 `6bb7d6d81f8de1585885f5fc72ce6dd99ba4249e`；
载荷 SHA256 `416ca962fc1c78c024dce0396775f1991184dc630d60e783e7a4b5cefa61dbf9`。
完整验收记录位于 `docs/acceptance/AUTODL_0.5.2-1.44_IMAGE1.json`。
