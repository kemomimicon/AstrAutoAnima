# 0.5.2-1.44 Windows / Linux 独立全量总包

两个包均为 build44 / install.2 / full.1，各自包含平台安装器、插件、Hub、工作流、自定义节点、
词库与令牌工具、美术资源、公开源码、Windows/Android/Web 客户端及完整说明。
Linux 使用服务端和 Hub Web 界面，附带的 Windows/Android 客户端可连接该服务器。

| 部署平台 | 下载 | 解压后入口 |
| --- | --- | --- |
| Windows x64 | [Windows 全量总包](https://github.com/kemomimicon/AstrAutoAnima/releases/download/v0.5.2-1.44/AstrAutoAnima-Windows-0.5.2-1.44-Full.zip) | `Install-Windows.cmd` |
| Linux x86_64 | [Linux 全量总包](https://github.com/kemomimicon/AstrAutoAnima/releases/download/v0.5.2-1.44/AstrAutoAnima-Linux-0.5.2-1.44-Full.zip) | `bash Install-Linux.sh`，无桌面使用计划文件 |

两个包根目录都有 `00_安装与使用说明.html`、`00_先读我.txt` 和 `verify_complete_suite.py`。
模型按向导选项下载，个人词库、角色/画风预设、账号和令牌在使用者自己的环境中配置。
组件沿用通过实机验收的 install.2 成品，桌面与手机客户端为同一组 build44 文件。
总包内 `suite-manifest.json` 记录各文件 SHA256、原组件基线及本次打包源码提交。

安装与首次配置：[Windows](platform-full/windows.md)、[Linux](platform-full/linux.md)。

维护者打包：使用已发布且 SHA256 固定的 `AstrAutoAnima-0.5.2-1.44-install.2-complete.zip`，
在干净的公开源码提交中执行：

```bash
python3 -B scripts/build_platform_full_suites.py --baseline /path/to/AstrAutoAnima-0.5.2-1.44-install.2-complete.zip --output /path/to/new-output
```

构建器核对原总包及其逐文件清单，提取各自平台安装器，保留已发布组件字节并写入本次公开源码与说明。
既有文件名不覆盖；新增总包、独立校验文件和 `PLATFORM_FULL_SHA256SUMS.txt` 上传同一发行页。
