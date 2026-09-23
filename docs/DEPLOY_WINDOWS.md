# Windows 懒人包

使用文件名含 `lazy-bundle-windows` 的包，完整解压后双击 **Deploy-Windows.cmd**。不要在压缩软件内直接运行。首屏为英文依赖引导（兼容 Windows PowerShell 5.1），后续配置向导为中文。

## 三个目录不能混用

| 向导字段 | 该填什么 | 不该填什么 |
| --- | --- | --- |
| 独立安装目录 | 新的空目录，如 `D:\AAA-install`，不存在也会创建 | ZIP 解压目录、磁盘根、已有 ComfyUI 或 AstrBot 目录 |
| AstrBot 根目录 | 真正含 `data` 的运行目录，或者直接选择 `data` | 只有 `backend / webui / exe` 的桌面软件安装目录 |
| ComfyUI 根目录 | 含 `main.py` 的源码目录；或 portable 外层目录 | `models`、`output`、单独的 Python 文件夹 |

### 已有 AstrBot Desktop

1. 先正常运行一次桌面版，使它初始化数据；之后退出桌面版及其后台服务再部署。
2. AstrBot 类型选 **desktop**。通常数据根为 `%USERPROFILE%\.astrbot`；如果启动参数指定了其他数据位置，以实际位置为准。
3. 该字段留空时会查找默认数据位置。误选 EXE 安装目录时也会尝试默认位置；请在日志/最后计划中确认解析出的目录就是当前实例。不应通过新建空 `data` 来绕过检查。
4. 不填写 AstrBot Python，不勾选下载全新 AstrBot。向导不修改桌面版内置 Python，不运行第二套后端。
5. 部署后手动打开 Desktop，在插件页确认 AAA 与 **Anima Master 0.7.1** 加载成功。缺依赖时使用桌面版/插件管理器支持的安装方式；不要向内置 Python 随意升级依赖。
6. 桌面版 WebUI 端口若不是 6185，修改安装目录 `runtime-env.json` 的 `AAH_ASTRBOT_URL` 后重启 Hub。此文件含令牌，勿分享。

### 已有 CLI / ComfyUI portable

- AstrBot 选 **cli**，使用其真实 Python；该环境应有同目录的 `astrbot.exe`。源码直接运行但没有 CLI 的环境不能冒充 CLI，请手动管理或另建独立 CLI 实例。
- portable 支持 `python_embeded\python.exe` 和 `python_embedded\python.exe` 自动发现；自定义整合包请明确选择其实际 Python。
- 所有要写入的服务先正常退出，端口占用时不会自动强杀。

### 全新部署

选择 cli，勾选“允许安装依赖”“下载全新 AstrBot”“下载全新 ComfyUI”。默认使用 Python 3.12；缺失时询问后通过 winget 获取。Git 也需单独同意安装。没有 winget 可按提示通过官方安装器安装后重试，不能跳过后假装成功。

再按需勾选默认 Anima 三件套、许可确认、AM 0.7.1。下载均是独立选择；详情见 [模型和 AM 指引](ANIMA_MASTER.md)。驱动、QQ 登录、OpenAPI 授权仍需用户处理。

## 常见错误

- **`Invalid argument ... install"\\runtime-env.json`**：旧启动器把结尾反斜杠和引号错误传给 Python。本版已改为切换当前目录后 `--start "."`。不是用户多输入了引号，也不是中文目录本身有问题。
- **PowerShell 中文乱码并报缺括号/引号**：旧脚本编码问题。本版启动脚本只使用 ASCII，已在 Windows PowerShell 5.1 做语法检查；`chcp 65001` 不能修复已经被错误解码的源码。
- **目标目录不存在**：独立安装目录可自动创建；已有环境目录必须真的存在，不能自动创建空目录代替运行环境。
- **缺 `runtime-env.json` / Hub Python**：部署尚未完成。重新运行部署向导修复，不要手工创建空 JSON，也不要拿作者配置填入。
- **符号链接/目录联接被拒绝**：目前部署器为防止错写不支持写入重解析路径。选择真实目录，不要删除联接指向的数据。

以后用安装目录的 `Start.cmd`。升级前备份，失败保留日志，不卸载模型、不清空原始数据。
