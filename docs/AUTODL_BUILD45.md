# AutoDL build45 母版准备与交接

目标镜像名：`AstrAutoAnima-0.5.3-beta.1-build45`。目标载荷标识：`0.5.3-beta.1-build45-image.1`。

本准备包提供同提交的主项目源码、Linux 更新包、镜像构建与首次启动工具。`image-preparation.json` 记录提交、更新包和源码校验值；平台镜像 UUID 和实际 runtime.tar.gz 校验值在母版构建完成后登记。

## 准备母版

从现有公开 build44 镜像创建独立发布副本，保留原实例和旧镜像。首次恢复后，正常停止 Hub、AstrBot、ComfyUI、Studio，再按 Linux 更新包执行预检和更新。工作目录沿用 `/root/autodl-tmp/aaa-install`，先核对本次实例上的真实路径。

将本包完整源码解压后的 `AstrAutoAnima-0.5.3-beta.1` 目录放到 `/root/AstrAutoAnima`。已有同名目录先改名留存。完整源码和服务更新必须来自同一个准备包。

基础运行环境复用原公开母版；新模型与节点见 `docs/NEXT_ANIMA_FEATURES.md`。Turbo 与 SnapRef 的权重按功能选择安装。模型、G/V 资源、角色词典及第三方环境继续按实际授权和原有目录核对。

## 构建新载荷

本包 `runtime-tools` 已使用新的 `/opt/aaa-image-build45` 运行目录，由下方构建入口在载荷完成后复制，不覆盖旧的 `/opt/aaa-image-052144`。

构建器位于另一个源代码目录；输出目录必须尚不存在。先将运行工具留在本准备包目录，执行本包的 `Build-Payload.sh`，它会创建 `/opt/aaa-image-build45` 并放入配套工具。命令仅在准备好的发布副本中执行：

```bash
bash Build-Payload.sh
```

构建器从升级后的应用环境取程序和已选公共资源，并生成空账号、空令牌的初始化模板。新载荷保存为 `/opt/aaa-image-build45/runtime.tar.gz`，真实 SHA256 记录在同目录 `payload-manifest.json`。

构建完成后用同目录 `verify_payload.py` 校验载荷。随后将新入口复制到 `/root/AAA-Start.sh`、`/root/AAA-Credentials.sh`，对应文件分别为 `Start-Image.sh`、`Show-Credentials.sh`；辅助控制入口按同目录说明部署。

## 保存和首次恢复

镜像只保存系统盘。完成载荷校验后，清理发布副本中的 QQ 会话、浏览器/网盘授权、SSH 私钥与授权、初始密码文件、登录日志及业务运行数据；先留存必要的个人备份，再按实际检查结果处理。`image_release_audit.py` 可以对指定目录生成只读检查记录。

系统级 SSH 密钥初始化沿用公开 build44 的 sshd 包装入口，确认新建实例各自生成主机密钥。不要直接保存日常使用中的实例作为公开母版。

用新镜像创建独立验收实例，运行：

```bash
bash /root/AAA-Start.sh
bash /root/AAA-Credentials.sh --show initial
bash /root/AAA-Credentials.sh --show hub --profile full
```

确认首次凭据各自生成、改密重启、普通生图及 QQ 投递；再核对收藏内容与回执、NapCat 入口、余额入口和已装的新工作流。记录新镜像 UUID、载荷 SHA256 和实际源码提交，之后在 AutoDL Art 选择这个新镜像。

## 平台介绍摘要

AstrBot × ComfyUI/Anima 跑图工作站，提供 QQ 指令交互、Windows/Android/Web 管理端、角色与画风预设、词库与收藏、HQ/精修/反推。build45 加入 Anima Turbo、SnapRef 参考生图、角色画廊与预设多人图；保留首次凭据查询、模型选装及更新回退工具。

使用问题可到项目 GitHub 或 bilibili——ケモミミロリコン反馈。发布时按母版实际选装内容列出模型和第三方版本。
