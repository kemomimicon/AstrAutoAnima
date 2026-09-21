# 0.5.0-beta.1 发布附件

本次使用新的 Git 标签，不覆盖 v0.4.0 或已有提示词独立发布。所有附件以同页 SHA256SUMS.txt 校验。

| 文件 | 用途 |
| --- | --- |
| `AstrAutoAnima-lazy-bundle-0.5.0-beta.1.zip` | 新手优先：部署向导、插件、Hub、节点、模板、编辑工具和文档 |
| `astrbot_plugin_comfy_bridge-0.5.0-beta.1.zip` | 单独更新 AstrBot 插件 |
| `astr_auto_anima_hub_service-0.5.0-beta.1.zip` | 单独部署 Hub 服务 |
| `Anima_Workflow_Pack-0.8.0-beta.1-public.zip` | 脱敏工作流与节点包 |
| `AstrAutoAnima-tools-0.5.0-beta.1.zip` | 离线词库编辑 / 批量导入导出 / 令牌管理；完整部署请使用懒人包 |
| `AstrAutoAnima-0.5.0-beta.1-source.zip` | 完整公开源码和测试 |
| `AstrAutoAnima-Windows-Admin-0.5.0-beta.1.zip` | Windows 管理端，需完整解压后运行 |
| `AstrAutoAnima-Windows-Service-0.5.0-beta.1.zip` | Windows 普通用户端 |
| `AstrAutoAnima-Android-Admin-0.5.0-beta.1.apk` | Android 管理端 |
| `AstrAutoAnima-Android-Service-0.5.0-beta.1.apk` | Android 普通用户端 |
| `AstrAutoAnima-Web-0.5.0-beta.1.zip` | 普通用户 Web App；解压后设置 AAH_WEB_ROOT |

Android 使用社区测试签名，不含签名私钥。不保证可覆盖安装不同签名的旧包；先备份客户端设置。
Python / GPU / 第三方模型不随包内置：按向导显式勾选，或使用已有环境。所有客户端首次连接都由使用者填写地址和令牌。

维护者使用 `python scripts/build_release_archives.py --output <仓库外输出目录>` 打包。源包和懒人包不含本地构建缓存、凭据、真实词库或用户运行记录。
