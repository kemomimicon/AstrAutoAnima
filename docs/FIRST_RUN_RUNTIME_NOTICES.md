# 首次配置向导双击版：运行库说明

Windows 1.1 构建使用 Python 3.12.14、Tcl/Tk 8.6 和 PyInstaller 6.22.3；应用源代码随 Source ZIP 提供。

- 项目自身按随包 LICENSE 授权。
- Python 及其捆绑组件的许可见 `licenses/Python-LICENSE.txt`。
- Tcl/Tk 运行资源随可执行程序打包，Tk 资源中包含 `license.terms`。本工具没有调用或分发模型权重。
- PyInstaller 引导程序采用其许可及应用分发例外；参考 https://pyinstaller.org/en/stable/license.html 。打包应用不意味着其源码必须改用 PyInstaller 的许可。
- Python 原生运行库含第三方构建系统的通用 Administrator 编译路径；它们不是维护者的运行配置，也不包含维护者账号、令牌或服务数据。项目模块的嵌入代码另行检查，不将第三方路径豁免应用于项目模块。

可执行程序目前没有商业代码签名证书。请从可信来源取得，并核对 SHA256，不要关闭系统安全检查。
