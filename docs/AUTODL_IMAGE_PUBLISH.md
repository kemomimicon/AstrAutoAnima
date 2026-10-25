# AutoDL 公开镜像发布步骤

发行软件版本：**0.5.2-1.44 / build44 / install.2**。

本次母版：`image-7476818e64`，`AstrAutoAnima-0.5.2-1.44-V042`，11.34GB。
2026-10-25 已在 RTX 5090 新实例完成恢复、首次改密重启、基础生图和 Hub 图片下载验收。
验收记录：`docs/acceptance/AUTODL_0.5.2-1.44_IMAGE1.json`。
镜像内源码提交为 `6bb7d6d81f8de1585885f5fc72ce6dd99ba4249e`；后续发行材料更新保留这一对应关系。

## 1. 准备镜像母版

使用新建的发布副本，放入对应版本仓库 `/root/AstrAutoAnima`、启动工具、许可证和初始化说明。
系统盘保存可恢复载荷；数据盘 `/root/autodl-tmp` 在新实例中由启动入口释放。
账号、应用令牌、QQ 会话、聊天与生成记录在首次启动时由接收者自行配置。
SeedVR2 大权重和 JoyCaption 通过勾选项下载。

既有原实例与私有镜像继续保留。本次 4090 D 的基础、HQ、精修、WD、SeedVR2 验收见
[发行记录](PUBLICATION_0.5.2-1.44.md)，QQ 投递已由维护者验证。

## 2. 保存新镜像

在 AutoDL 控制台保存新的母版镜像，记录镜像 UUID、名称、大小和软件提交。
用该镜像创建新实例，运行 `bash /root/AAA-Start.sh`，检查恢复、首次凭据、服务与首图。

## 3. AutoDL Art 导入

登录与算力云相同的账号，打开 AutoDL Art → 发布 → 镜像。

1. GitHub 项目填写 `kemomimicon/AstrAutoAnima`。
2. 镜像名填写 `AstrAutoAnima-0.5.2-1.44`。
3. 导入上一步新保存的镜像。
4. 镜像 README 使用 [平台介绍](AUTODL_ART_DESCRIPTION.md)。
5. 提交后根据平台审核结果补充材料。

导入参数：平台数字版本填 `44`，描述中写完整版本 `0.5.2-1.44`；PyTorch `2.11.0`，
CUDA `12.8`，建议数据盘 `50GB`。选择上述已验收的母版，验收实例中的个人设置保留在验收数据盘。

`/root/AstrAutoAnima` 提供对应源码；可运行 `python3 -B scripts/validate_release.py .` 验证仓库结构。
镜像内容按 [第三方清单](AUTODL_IMAGE_REDISTRIBUTION.md) 配套许可证和来源。

参考：[AutoDL Art 镜像](https://www.autodl.art/docs/image/)、
[AutoDL 保存与共享镜像](https://www.autodl.com/docs/image/)。
