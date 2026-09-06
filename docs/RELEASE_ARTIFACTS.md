# 发布包说明

正式版使用统一版本号 `0.4.0`，工作流包版本为 `0.5.0`。

| 文件 | 用途 |
|---|---|
| `astrbot_plugin_comfy_bridge-0.4.0.zip` | 在 AstrBot 插件目录安装或升级桥接插件 |
| `astr_auto_anima_hub_service-0.4.0.zip` | 部署 Hub 后台服务 |
| `Anima_Workflow_Pack-0.5.0.zip` | 安装自定义节点和 ComfyUI 工作流模板 |
| `AstrAutoAnima-tools-0.4.0.zip` | 独立使用提示词库编辑、导入导出和令牌管理工具 |
| `AstrAutoAnima-lazy-bundle-0.4.0.zip` | 面向新手的一键部署包；外部下载默认全部关闭 |
| `AstrAutoAnima-0.4.0-source.zip` | 与发布标签对应的完整公开源码 |
| `AstrAutoAnima-admin-0.4.0-windows-x64.zip` | Windows 管理客户端 |
| `AstrAutoAnima-web-0.4.0.zip` | 可由 Hub 或静态 Web 服务托管的用户客户端 |
| `AstrAutoAnima-admin-0.4.0-android.apk` | Android 管理端 |
| `AstrAutoAnima-service-0.4.0-android.apk` | Android 用户端 |

下载后应使用同目录的 `SHA256SUMS.txt` 核对文件完整性。Android APK 使用社区测试签名，适合
侧载验证；应用商店分发者必须使用自己的 release keystore 重建。所有公开包均不包含真实令牌、
服务器地址、私人提示词库、模型、LoRA、图片、QQ/NapCat 数据或本地日志。

维护者可在仓库根目录执行以下命令，重新生成经过隐私检查的源码包：

```bash
python scripts/build_release_archives.py
```
