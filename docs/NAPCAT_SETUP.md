# NapCat 部署、QQ 登录与 OneBot 对接

2026-10-20 本地候选版说明。加入统一安装中心和独立 NapCat 四页引导；尚未据此更新 GitHub 发布附件。QQ 登录、上游安装器的确认与设备验证必须由本人完成。

## 打开入口

- 完整懒人包：Windows 双击 `Deploy-Windows.cmd`；有桌面的 Linux 运行 `sh Deploy-Linux.sh`，进入“安装与启动中心”→②。
- 首图向导新版：⑨“工具与帮助”→“NapCat 安装 / QQ 登录 / OneBot 连通引导”。
- 源码：`python tools/napcat_setup.py`，只需 Python 标准库、Tk；实际下载另需 curl。
- **已有 NapCat 且能登录：直接跳过①**。不重装 QQ，不移动或清理登录缓存。容器用户沿用自己的容器安装和启动方式。

四页不是强制逐页安装；可直接切换到出错那一页。准备文件、打开安装器、QQ 登录、OneBot 连接和第一张图是五个不同结果，不能互相替代。

## ① 准备与安装

选择一个独立的准备目录，默认是个人主目录下的 `AAA-NapCat-setup`。不要选现有 NapCat / QQ 安装目录。勾选准备授权后，才会下载；也可选择本地已下载的**同版本官方入口文件**。

支持官方直连、自选 HTTPS GitHub 镜像前缀、文件下载代理和本地文件。镜像按“前缀/完整官方URL”拼接，须选择支持此格式的可信服务；本工具不默认信任任何镜像。SHA256 和大小必须匹配，无法通过时不执行文件。网络设置仅作用于本工具准备入口，不代表之后的上游安装器会使用同一代理。

### Windows

本候选版固定入口为 [NapCat v4.18.38 的官方 OneKey ZIP](https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.38)，面向 Windows x64，约 1 MB，**不是完整 QQ / NapCat 离线包**。其他架构按上游说明自行安装，不承诺兼容。

1. “准备 / 断网后重试”：下载校验后解压到新的子目录，不覆盖原安装。
2. “下一步：运行入口”：再次校验入口及随附 DLL；阅读联网、系统权限提示并确认，才打开官方 `NapCatInstaller.exe`。
3. 在官方安装器中完成 QQ / NapCat 安装。它会继续下载依赖，实际版本及所需容量以上游为准；本工具不声称已校验其全部后续下载。
4. 按官方提示打开实际生成的 `NapCat.XXXX.Shell/napcat.bat`，保持它运行。**不要运行准备目录 `bootmain` 内的启动模板，更不要运行 kill-qq 脚本。**
5. 到②，打开 WebUI、手机 QQ 扫码。

入口 ZIP SHA256：`46c3ec155aa61f12e89bbf97013a21243d00b0019b5565992a88852d7627f39c`。不要给另一版本文件改名骗过校验。以 [NapCat 官方 Shell 安装说明](https://napneko.github.io/guide/boot/Shell) 为准；未签名程序被拦截时核对来源或联系管理员，不建议关闭系统安全防护。

### Linux（桌面或无桌面）

引导固定下载官方 NapCat-Installer 提交 `bc668fdc29bf3a7a53a3cff34572734322df8d17` 的安装脚本，准备后**不自动执行、不静默 sudo**。桌面引导显示完整命令，复制到这台 Linux 机器的终端运行。原脚本可安装系统依赖，可能询问 sudo 密码；推荐普通用户，已有安装不要使用 `--force`。

无桌面时，在完整解压的懒人包根目录执行：

```bash
python3 tools/napcat_setup.py --platform linux --prepare "$HOME/AAA-NapCat-setup" --allow-prepare
```

它只准备文件并打印一条已校验脚本的 `bash ... --docker n --cli y --github-proxy 0` 命令。阅读提示后自行运行该命令；完成后按官方提示使用 `napcat` 管理启动。不是在 Windows 电脑执行 Linux 命令。

网络不通可先下载固定脚本，再本地导入：

```bash
python3 tools/napcat_setup.py --platform linux --prepare "$HOME/AAA-NapCat-setup" --allow-prepare --local-file /absolute/path/napcat-install.sh --download-mode local
```

脚本 SHA256：`eafcc4594198f60d9f6649665bce57acbc9432a0cf534bbdead2f0c561837b33`。也支持 `--download-mode mirror --github-mirror https://YOUR_MIRROR_PREFIX` 或 `--download-mode proxy --proxy http://127.0.0.1:YOUR_PROXY_PORT`，其中示例占位值必须替换。代理不自动应用到上游安装脚本。

## ② QQ 登录

默认本机 WebUI 为 `http://127.0.0.1:6099/webui`；真实端口以 NapCat 启动输出为准。使用**自己的启动输出所给 WebUI Token**登录，不依赖固定默认密码。按 WebUI 展示扫码，手机 QQ 自己确认；不能让向导代替扫码或绕过设备校验。

可选在向导填写 WebUI Token / 双重验证动态码，再明确确认“检查 QQ 登录状态”。仅访问本机回环地址，不经过系统代理、不跟随重定向、不把 Token 放进 URL 或日志；只执行 WebUI 认证与读取状态，不切换 QQ、不请求账号列表。Token 只在窗口内存，关闭即不再保留。

远程服务器应在服务器上检查；通过你已有的安全访问方式查看远程 WebUI。**不要把电脑的 127.0.0.1 当成云服务器，也不要为方便检查把 WebUI 无保护地开放到公网。**

## ③ 让 AstrBot 收到 QQ 消息

同机、非容器的参考配置：

| 谁 | 需要填写什么 |
| --- | --- |
| AstrBot | 新增并启用 OneBot v11 / aiocqhttp 消息平台，作为反向 WebSocket 服务端；监听 127.0.0.1，端口 6199，设置平台 Bot ID |
| NapCat | 新建 **WebSocket 客户端**；URL `ws://127.0.0.1:6199/ws`；消息格式 Array（数组）；启用并保存 |
| 两边 | 同一个 OneBot `access_token`，大小写一致；先在向导显式生成，再分别填写，不自动改 JSON |

**不是 HTTP POST，也不是 NapCat 的 WebSocket 服务端。**6099 是 NapCat WebUI，6185 是 AstrBot 管理后台，6199 是此示例的 OneBot 端口，6278 是 AAA Hub；不能混用。

“只检查本机端口”只测 TCP，不能证明另一端是 AstrBot、Token 正确或 OneBot 握手成功。真正验收：

1. 保存两端设置，AstrBot 日志出现 OneBot / aiocqhttp adapter connected。
2. 用自己的另一 QQ 私聊机器人发 `/sid`，收到会话标识；记下实际平台 Bot ID / UMO，别把 Bot ID 当 QQ 号码。
3. 回 AAA 首图向导：配置完整 AstrBot OpenAPI Key、Hub 授权、自己的私聊目标，保存后按说明重启相关服务。
4. 先验收基础单图和取图，再试 QQ 投递、群和高级功能。

容器 / 跨机器不能照抄 localhost：NapCat 的 `127.0.0.1` 是它自己所在环境。共同容器网络使用 AstrBot 服务名；跨主机使用明确的私网 / 安全隧道和正确监听接口。不要为试连直接向公网开放未加密、未鉴权的 OneBot。详见 [AstrBot 官方 OneBot 配置](https://docs.astrbot.app/en/platform/aiocqhttp.html)。

## 五种凭据别混填

| 凭据 | 用途 |
| --- | --- |
| AstrBot 后台登录密码 | 登录 AstrBot 管理界面，不是 API Key |
| AstrBot OpenAPI Key | AAA Hub 调用 AstrBot API；须复制完整值和授予相应权限 |
| AAA Hub 管理 / 用户令牌 | AAA 客户端连接 Hub；普通用户不使用管理令牌 |
| NapCat WebUI Token | 进入 NapCat WebUI / 本机状态检查 |
| OneBot access_token | 仅 NapCat 与 AstrBot 的消息连接，两端一致 |

向导生成 OneBot Token 不会自动安装或保存到任何配置。复制密钥会经过系统剪贴板，可能被历史记录或同步保存，因此须确认并自行清除；不要截图或发给群友。

## 二次恢复，不从头删除

- **下载断了**：同一个准备目录重试，复用完整文件或断点；换网络不关闭校验。已解压的入口会保留，不清除原安装。
- **官方安装器报错**：查看安装器日志；入口已准备不等于完整安装完成。下游下载链接以官方工具为准。
- **6099 拒绝连接**：查实际 NapCat 启动窗口，是否启动了安装后生成的入口；不要仅凭 screen 名或目录存在判活。
- **WebUI 401 / 认证失败**：核对本实例 WebUI Token 和 2FA，别改 Hub / AstrBot 密钥。
- **QQ 掉线**：自行扫码，不清 QQ 缓存；保留原配置。
- **端口开着但 /sid 没回复**：核对客户端方向、`/ws`、两端 OneBot Token、平台启用状态和连接日志；再看 AstrBot 指令权限 / 会话过滤。
- **/sid 正常但 AAA 401**：返回 AAA 授权页，不重装 NapCat。
- **日常开机**：AAA 使用安装目录 `Start`；NapCat 使用原 `napcat.bat` / `napcat` 管理方式。本候选版不改系统开机启动，也不替换已有自启动脚本。

测试边界：本地覆盖了路径 / ZIP 安全、固定文件校验、授权边界、模拟登录状态与界面创建；不等同于每种 Windows / Linux 上实际登录 QQ 或成功投递验收。请先在测试部署中按以上步骤完成真实 `/sid` 和首图验收。
