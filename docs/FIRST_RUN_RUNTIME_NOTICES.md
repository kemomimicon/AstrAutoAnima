# 首次配置向导双击版：运行库说明

Windows 1.1 构建使用 Python 3.12.14、Tcl/Tk 8.6 和 PyInstaller 6.22.3；应用源代码随 Source ZIP 提供。

1.2-candidate.7 使用此前相同的 Python 3.12、Tcl/Tk 8.6 与 PyInstaller 6.22.2 构建EXE，仅更新随包公开说明和扩展清单。包含 NapCat 引导、离线扩展/量化配置中心与可选在线词库导入器，但不随包分发 QQ / NapCat 或其登录数据；经用户确认后才准备官方入口或发送导入请求，第三方组件许可及运行要求以上游说明为准。Studio等外部组件只提供说明，不含训练接口或数据。独立首图EXE不替代完整部署器；本轮不启用图像/VAE分块。

- 项目自身按随包 LICENSE 授权。
- Python 及其捆绑组件的许可见 `licenses/Python-LICENSE.txt`。
- Tcl/Tk 运行资源随可执行程序打包，Tk 资源中包含 `license.terms`。本工具没有调用或分发模型权重。
- PyInstaller 引导程序采用其许可及应用分发例外；参考 https://pyinstaller.org/en/stable/license.html 。打包应用不意味着其源码必须改用 PyInstaller 的许可。
- Python 原生运行库含第三方构建系统的通用 Administrator 编译路径；它们不是维护者的运行配置，也不包含维护者账号、令牌或服务数据。项目模块的嵌入代码另行检查，不将第三方路径豁免应用于项目模块。

可执行程序目前没有商业代码签名证书。请从可信来源取得，并核对 SHA256，不要关闭系统安全检查。
