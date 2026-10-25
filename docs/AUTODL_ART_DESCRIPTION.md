# AstrAutoAnima 0.5.2-1.44

## 项目用途

AstrAutoAnima 将 AstrBot、QQ/NapCat 与 ComfyUI/Anima 连接起来，提供基础生图、
角色/画风预设、随机提示词、图片记录、Hub 管理端及个人客户端入口。
镜像用于减少首次部署的依赖安装和模型搬运；QQ 扫码、API 授权和个人配置仍由使用者完成。

GitHub 项目：https://github.com/kemomimicon/AstrAutoAnima

软件版本 0.5.2-1.44，内部 AAA 0.5.2-beta.1/build44，AM 0.7.1。

## 内容和限制

候选预装 AAA、ComfyUI、AstrBot、Anima 基础三件套、WD/CL、Studio 与连接扩展、
SeedVR2 节点及镜像专用公共资源。模型、第三方项目和语料各自遵守原许可证，不属于 AAA 的统一 MIT 授权。

不提供个人 QQ 登录态、共享密码/令牌、提供者生成或训练记录。JoyCaption 完整环境未安装，
SeedVR2 大权重按需另下。不会自动训练，不启用图像或 VAE 分块。

RTX 4090 D 已通过基础 1024×1536、HQ/精修 1280×1920、WD 反推及分类选择、
SeedVR2 3B FP16 整图 682×1024 验收。QQ 投递由维护者验证。
数据盘建议 50GiB 起，为输出和扩展模型预留空间。

## 首次启动

仅在独立、满足资源要求的新实例中执行：

```bash
bash /root/AAA-Start.sh
```

首次校验并释放环境，生成自己的应用凭据。遇到目录冲突立即停止，不删除旧目录绕过保护。
无卡轻量检查不要执行此命令。之后使用同一入口，不重新运行部署安装器。

在自己的电脑连接 SSH 隧道，访问 AstrBot 6185、ComfyUI 8188、Hub 6278 和 NapCat 6099。
SSH 凭据来自自己的云控制台；应用凭据从实例初始化记录私下领取。AstrBot 登录密码、OpenAPI Key、
Hub 管理员/普通用户令牌、NapCat Token、OneBot Token 用途不同，不能混用；初次登录后及时改密。

OneBot 连接地址为 `ws://127.0.0.1:6199/ws`，两端使用同一个连接 Token。
先验证普通英文单张生图，再配置词库、角色、群投递、HQ和可选扩展。

完整步骤见仓库 `docs/AUTODL_IMAGE.md`；维护者验收见 `docs/AUTODL_IMAGE_PUBLISH.md`。

## 隐私和维护

不要公开运行配置、初始凭据、SSH 私钥、QQ 会话或网盘授权。泄露后在对应服务撤销/更换，
删除文本不等于撤销权限。二次分发前重新脱敏，不能直接分享已登录个人账号的测试实例。
高级工作流和多组件对接仍为 Beta；求助请提供脱敏的错误、组件版本和复现步骤。
