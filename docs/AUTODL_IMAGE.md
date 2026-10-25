# AutoDL 候选镜像使用说明

这份说明适用于拟与视频和镜像同步发布的 AAA `0.5.2-1.44`，内部标识
`0.5.2-beta.1/build44`、部署修订 `entryfix.1`。本地仓库已整合新版候选源码，
软件安装包已完成 4090 D 基础和扩展验收，见 [发行记录](PUBLICATION_0.5.2-1.44.md)。
本文的 18.06GB 数据对应已保存的私有镜像；公开镜像以平台发行页为准。
昨天已保存的私有镜像保持原样，不会自动获得本次源码整合与文档更正。

## 选择正确的部署方式

镜像恢复、源码部署和旧版升级是三条不同路线。镜像已经预装环境，不要在恢复目录再次运行
本仓库旧版 `Deploy-Linux.sh --apply`，也不要直接复制别人的虚拟环境。

候选镜像约 18.06GB，系统盘内的压缩软件载荷约 17GiB，释放后约 26.39GiB；新数据盘建议
50GiB 起步，训练数据、生成图片、缓存和额外模型另留空间。镜像大小不是推理显存需求。

候选包含 AAA Hub/插件/管理 Web、ComfyUI 环境、Anima 基础三件套、AM 0.7.1、
Studio 0.25.0 及连接扩展、WD/CL、SeedVR2 节点，以及镜像专用公共词库和角色词典。
源码仓库保持空提示词库，不包含这些模型和语料。第三方内容须满足
[再分发清单](AUTODL_IMAGE_REDISTRIBUTION.md)；本项目许可证不替它们授权。

未包含 JoyCaption 的完整环境及权重、SeedVR2 大权重、个人 QQ 登录态、提供者密码/API Key、
用户记录、生成图和训练项目。SeedVR2 要另行明确选择下载；未安装 JoyCaption 时不能宣称专用反推可用。
AM 兼容基线固定 0.7.1，0.9.1 未联调；Studio 固定 0.25.0，不自动升级。

## 没有显卡时只做结构检查

此阶段不运行 `AAA-Start.sh`、`image_first_boot.py --apply` 或 `--start`。
这些是恢复/启动入口，会解压、生成凭据和启动服务，不是只读检查。
不要初始化已封存母版，也不要为了检查自行创建计费实例。

在已经取得本次仓库补丁的独立测试实例中，可以运行：

```bash
python3 -B /root/AstrAutoAnima/tools/autodl_public_image_20261025/public_probe.py
```

脚本只用标准库，默认不读取大载荷正文，不启动服务、不解压、不联网、不创建凭据、不导入 Torch。
它不读取运行中的应用配置，也不会显示任何密码。退出码 0 仅表示未发现结构错误；
输出里的 `pending` 不代表验收成功，`public_release_approved` 始终为 `false`。

需要完整核对载荷 SHA256 时可显式加参数，顺序读取约 17GiB，不进行解压：

```bash
python3 -B /root/AstrAutoAnima/tools/autodl_public_image_20261025/public_probe.py --verify-payload
```

此检查只识别当前固定封存载荷，不会自动接受陌生 manifest 或更新期望哈希。
`.git` 目录存在只算结构信息，不能代替仓库来源、固定提交和源码对应关系的核对。

## 有显卡后首次恢复

以下步骤仅用于独立新实例；先确认新数据盘没有他人或已有项目的同名目录，且 CPU/内存/GPU
满足实际模型需求。测试实例不要覆盖原实例或已保存镜像。

```bash
bash /root/AAA-Start.sh
```

启动器校验载荷、按原绝对路径恢复环境、生成独立凭据并启动 ComfyUI/AstrBot/Hub。
等待完成，不同时启动多份。目录冲突时停止排查，不删模型或旧配置绕过保护。
以后使用同一入口，不重新部署。NapCat 和 Studio 按镜像随附说明按需单独启动。

## SSH 连接与打开后台

SSH 主机、端口和密码从自己的 AutoDL 控制台领取，不是应用密码，不要使用提供者的连接资料。
在 Windows 电脑的 PowerShell、从本仓库根目录运行：

```powershell
.\tools\autodl_public_image_20261025\Open-AAA-Tunnel.ps1 -CheckOnly
```

上面只检查 OpenSSH 客户端。建立连接时运行：

```powershell
.\tools\autodl_public_image_20261025\Open-AAA-Tunnel.ps1
```

按提示实际填写 `root@` 后的主机和 `-p` 后的端口，不能把提示文字当默认值；空值和端口 0
会被拒绝。首次连接核对主机指纹。输入密码无字符、隧道建立后窗口安静均可能正常，保持窗口打开。
脚本只绑定本地回环，不开放服务器公网端口，不更改主机校验或防火墙。

没有 `ssh.exe` 或脚本策略拦截时，使用 [AutoDL 官方图形隧道工具](https://www.autodl.com/docs/ssh_proxy/)，
不要求关闭安全策略，不安装 SSH 服务端。转发 6185、8188、6278、6099；6199 是实例内 OneBot 连接，不必转发。

| 本机地址 | 用途 | 凭据 |
| --- | --- | --- |
| `http://127.0.0.1:6185` | AstrBot 后台 | AstrBot 登录密码 |
| `http://127.0.0.1:8188` | ComfyUI | 仅通过本机隧道，不直接公开 |
| `http://127.0.0.1:6278` | AAA Hub 管理端 | full 管理员令牌 |
| `http://127.0.0.1:6099/webui` | NapCat 后台 | NapCat WebUI Token |

本机端口冲突时，可更换转发的本地端口，服务器服务端口不变。脚本 `-Help` 不是参数；
用 PowerShell `Get-Help` 或脚本参数说明查看可选本地端口。

## 密码与令牌分别放在哪里

先停止录屏/直播，确认终端没有共享日志，再查询。默认只查看配置状态：

```bash
bash /opt/aaa-image-20261024/Show-Credentials.sh
```

按需查询 Hub 管理员令牌和 NapCat WebUI Token，交互输入 `SHOW` 后才显示：

```bash
bash /opt/aaa-image-20261024/Show-Credentials.sh --show hub --profile full
bash /opt/aaa-image-20261024/Show-Credentials.sh --show napcat
```

首次登录资料在实例自己的 `aaa-install/INITIAL_CREDENTIALS.json`，权限应为 600。
镜像原工具的 `--show initial` 显示的是初次生成的记录，不是改密后当前密码的反查：

```bash
bash /opt/aaa-image-20261024/Show-Credentials.sh --show initial
```

不要把该文件整体发群或加入仓库。修改 AstrBot 密码后初始密码失效；优先使用 guide.1 的新版
逐项查询工具核对初始记录与当前密码摘要。删除文本不等于撤销泄露凭据，泄露须在对应服务更换。

| 名称 | 从哪里取得 | 填到哪里 |
| --- | --- | --- |
| SSH 密码 | 自己的 AutoDL 控制台 | 本机 SSH/文件传输/隧道 |
| AstrBot 登录密码 | 新实例初始记录，随后自己改密 | AstrBot 后台登录 |
| AstrBot OpenAPI 完整 Key | 登录 AstrBot，在设置中创建所需权限的 Key | Hub 的 `AAH_ASTRBOT_API_KEY` |
| Hub 管理员令牌 | 当前 full 配置的查询入口 | AAA 管理端，不能给普通用户 |
| Hub 普通用户令牌 | 管理员为用户单独创建 | 用户自己的客户端 |
| NapCat WebUI Token | NapCat 查询入口 | 6099 后台登录 |
| OneBot Token | 用户私下生成/设置 | AstrBot OneBot 和 NapCat 客户端两端相同 |

OpenAPI Key 不能只复制列表短前缀，也不能用后台密码代替。实际平台 Bot ID 不是群号或个人 QQ 号。
修改 Hub 配置前先确认没有活动任务、正常停止 Hub，并私密备份；保留管理员令牌和其他字段，
不要混填 full/local 两个档位。具体操作沿用 20261024 guide.1 第 9 节，不覆盖运行中的个人配置。

## QQ 对接与第一张图

启动自己的 NapCat 并自行扫码。AstrBot 创建 OneBot v11 适配器，监听 `127.0.0.1:6199`；
NapCat 创建 WebSocket **客户端**，地址必须带 `/ws`：

```text
ws://127.0.0.1:6199/ws
```

两端填写相同 OneBot Token，消息使用数组格式，保存并确认握手。先私聊 `/sid` 核对真实身份，再测试：

```text
/aimg_status
/aimg 1girl, solo, standing, fully clothed, park, daylight
```

先不叠加 LoRA、随机词库、HQ、反推、放大或五连。QQ 真正收到图片才算这条链路通过，
不能以“排队成功”或健康接口正常代替。Hub 鉴权、客户端预览下载和投递群各自再验收。
词库、角色词典、Studio 及可选模型在首图后逐项检查，不自动启动训练，不启用图像/VAE 分块。

## 恢复和排错

- 目录已存在：停止，不删除重装；核对是否误用了母版或已有数据盘。
- 6185 API 返回 401：检查完整 OpenAPI Key、权限和 Hub 实际读取的配置，不先重置后台密码。
- 管理端 401：检查 full/local 档位及其管理员令牌。
- 找不到 `ssh`、端口 0：修复本机连接工具或输入，和服务端 API Key 无关。
- QQ 无回复：检查实际登录、OneBot 客户端方向、`/ws`、共享 Token、Bot ID 与权限。
- 模型/节点缺失：先核对工作流和实际枚举，不改名伪装、不关哈希校验。
- 改密后无法登录：旧初始记录不能反查当前密码；按匹配 AstrBot 版本的恢复流程处理，不删 data。

求助只提供脱敏报错，不发送完整配置、初始记录、QQ 会话、SSH 私钥或网盘授权。
原候选短说明缺少 `/ws` 的地方需在下一份母版中修正；本地修改本文不会自动改变已保存云镜像。

相关入口：[AutoDL 镜像](https://www.autodl.com/docs/image/)、
[AstrBot OneBot 接入](https://docs.astrbot.app/en/platform/aiocqhttp.html)、
[NapCat 官方说明](https://napneko.github.io/guide/boot/Shell)。
