# 密码和令牌对照

每台新实例首次启动生成独立凭据，私密记录在 `/root/autodl-tmp/aaa-install/INITIAL_CREDENTIALS.json`。

| 凭据 | 填在哪里 | 如何领取 |
| --- | --- | --- |
| AutoDL SSH 密码 | 电脑 SSH 隧道窗口 | 自己的 AutoDL 控制台 |
| AstrBot 登录密码 | 6185 网页登录 | `bash /root/AAA-Credentials.sh --show initial` |
| AstrBot OpenAPI Key | AAA 管理端的 AstrBot API Key | AstrBot 设置 → OpenAPI 创建完整 Key |
| Hub 管理员令牌 | AAA 管理端登录 | `bash /root/AAA-Credentials.sh --show hub --profile full` |
| 个人用户令牌 | Android/Windows 个人端 | 管理端 → 用户与令牌 → 新建用户 |
| NapCat WebUI Token | 6099 的登录页面 | NapCat 首次安装时显示的 WebUI Token；按安装指南查询实际配置 |
| OneBot Token | AstrBot 与 NapCat 的连接设置 | 初始记录中领取，两端保持一致 |

首次登录后修改 AstrBot 密码，将自己的凭据保存到密码管理器。分享截图和反馈日志前收起密钥。
需要换发时，在对应服务更新凭据，并同步更新使用该凭据的客户端。

完整服务与本机工作站分别使用 `runtime-env.full.json` 和 `runtime-env.local.json`。
查询本机工作站令牌时使用 `--profile local`。

遇到问题可在 bilibili 联系 **ケモミミロリコン**，提供版本、步骤和报错即可。

`napcat-config/webui.json` 是可供选装时导入的初始配置；安装后按 NapCat 实际配置目录查询当前 Token。
