# 旧版本升级到 0.5.2-1.44

这是程序更新补丁，适用于已有的 0.4.x、0.5.0、0.5.1 和较早 build 的 0.5.2 安装。
历史 0.3.x 源码安装可通过手动路径计划预检。Hub 使用源码可编辑安装（pip -e），包括本项目历史懒人包和服务器更新脚本创建的环境。
运行环境为 Python 3.10+，AstrBot 4.17 至 4.x；Desktop 用户请在程序内核对版本。

下载：
- Windows：https://github.com/kemomimicon/AstrAutoAnima/releases/download/v0.5.2-1.44/AstrAutoAnima-Windows-Update-to-0.5.2-1.44.zip
- Linux：https://github.com/kemomimicon/AstrAutoAnima/releases/download/v0.5.2-1.44/AstrAutoAnima-Linux-Update-to-0.5.2-1.44.zip

目标程序内部版本为插件 0.5.2-beta.1、Hub 0.5.2-beta.1，客户端 build44；对外统一称 0.5.2-1.44。

## 更新哪些内容

更新 AAA 插件、Hub 源码与 Web、自定义节点；懒人包更新相应启动辅助代码和已有启动入口。
Windows 补丁附带 build44 Admin/Service 客户端。Linux 使用更新后的 Hub Web，其他设备客户端从同一发行页选择。

已有的个人配置、API Key、令牌、用户表、词库、角色/画风预设、模型、图片记录及原工作流保持原值。
新版工作流放在 ComfyUI 的 user/default/workflows/AAA_Update_0.5.2-1.44 中，已有同名模板也保留；新功能需要时再复制、选择自己的模型并绑定。
旧插件 data 中已存在的资源不覆盖；对应的新公开默认文件放在插件的 .aaa-update-defaults 中供核对。

本补丁不更换 AstrBot、ComfyUI、NapCat、Anima Master、Torch 或模型。核心上游继续使用 Anima Master 0.7.1。

## 更新前

1. 下载对应系统补丁及同名 sha256.txt，核对 SHA256 后完整解压到独立目录。
2. 先让现有任务完成，正常退出 Hub、AstrBot（Desktop 要退出后台）和 ComfyUI；暂停会立即重新拉起它们的守护程序。
3. 记住现有安装目录和启动方式。更新器不会强杀进程或自动重启服务。
4. 备份会写在原安装目录的 aaa_update_backups，代码和配置快照在修改前创建并校验。备份含私人配置，请本人保管。

## Windows 懒人包：图形操作

1. 双击 Update-Windows.cmd；需要 Python 3.10+ 与 Tkinter（原部署使用的 Python 可继续用）。
2. 选择已有安装目录：就是包含 Start.cmd、runtime-env.json、services.json 的目录，不是刚解压的补丁。
3. 点“只做预检”，核对旧版本、文件数量和缺失依赖提示。
4. 确认服务退出后勾选“我已正常退出…”。只有提示需要补齐依赖时，才按需要勾选“允许补齐依赖”。
5. 点“备份并升级”，等待日志显示更新完成，保存日志中的备份路径。
6. 按原来的 Start.cmd 或桌面入口启动服务，按下文检查。

## Linux 懒人包：终端操作

先进入解压后的补丁目录。下面的安装路径替换成自己的实际路径：

```bash
python3 -B update.py --install-root /your/AAA-install
python3 -B update.py --install-root /your/AAA-install --apply --confirm-stopped
```

也可以使用本包入口：

```bash
bash Update-Linux.sh --install-root /your/AAA-install
bash Update-Linux.sh --install-root /your/AAA-install --apply --confirm-stopped
```

如果预检提示确实缺少本补丁的 Python 依赖，并同意从当前配置的 PyPI 来源补齐，执行：

```bash
python3 -B update.py --install-root /your/AAA-install --apply --confirm-stopped --install-dependencies
```

只处理所选服务对应的依赖；不会安装 Torch、CUDA 或下载模型。失败时保留原目录和备份，按报错修正后重新预检。
Linux 有桌面和 Tkinter 时也可运行 python3 update.py --gui。

## 手动安装／分开的服务目录

复制 update-plan.example.json 为 my-update-plan.json，用编辑器填写实际路径：
- plugin_dir：现有 astrbot_plugin_comfy_bridge 目录；只更新 Hub 的用户可留空。
- hub_home：含 pyproject.toml 和 src/astr_auto_anima_hub 的 Hub 目录。
- hub_python：启动这套 Hub 的 Python，例如 Hub/.venv/bin/python 或 Hub/.venv/Scripts/python.exe。
- web_dir：实际 Web 成品目录；通常为 Hub/web，原配置另有 AAH_WEB_ROOT 时填该实际目录。
- comfyui_root：含 main.py 的 ComfyUI 目录；不在此机器更新节点时留空。
- astrbot_python、comfy_python：对应服务实际 Python；AstrBot Desktop 留空并在其插件管理器处理依赖。
- install_root：仅懒人包布局填写，手动安装留空，不会替换自定义自启动脚本。
- backup_root：本人有写权限的备份目录；ports：所有相关服务在本机使用的端口。

```bash
python3 -B update.py --plan my-update-plan.json
python3 -B update.py --plan my-update-plan.json --apply --confirm-stopped
```

Windows 终端将 python3 换为 py -3。只更新插件可仅填 plugin_dir、backup_root 和相关 ports；只更新 Hub 可留空插件与 ComfyUI 路径。
若提示 Hub 不是所选源码的可编辑安装，先核对自己实际的 Hub 目录及 Python，不要对不明环境强行覆盖；可使用对应总包的手动安装说明完成该布局的升级。

## 更新后怎么检查

1. 按原方式启动服务。Hub /api/v1/health 应返回 status=ok，版本为 0.5.2-beta.1。
2. AstrBot 插件页确认 0.5.2-beta.1 加载成功；运行 /aimg_status 核对原工作流、模型与预设仍正确。
3. 原账号、Hub 令牌、OpenAPI Key 和用户令牌继续使用。401 时核对完整 Key 与接口权限，不需要重新生成全部令牌。
4. 新生成一张普通图，确认预览和下载；QQ 回复关联／重跑使用更新后新生成的消息验证，旧的无关联消息不补造记录。
5. Web 浏览器硬刷新。Windows 关闭旧客户端，把 clients/windows 中两个 ZIP 按用途解压到新文件夹，运行新版 Admin 或 Service，保留原 AppData 设置。
6. Android 用户在同一发行页安装对应 build44 APK；如提示签名不一致，先导出个人配置再处理安装。

此补丁采用代码级更新，Hub 原可编辑安装与 Python 环境保持。健康接口显示的是新版应用代码；pip show 的历史安装元数据可在有需要时另行重新安装登记。

## 需要回退时

先退出相关服务，找到日志中记录的那份备份目录，使用同一补丁的 update.py：

```bash
python3 -B update.py --rollback /your/AAA-install/aaa_update_backups/to_0.5.2-1.44_时间戳_编号 --confirm-stopped
```

回退恢复被替换的旧程序文件，并移除本次新加且没有被修改的文件；用户配置和词库保持当前值。
升级后自行改过的代码会触发冲突提示，工具保留它，先人工合并。可选 pip 依赖安装的变化不属于代码回退范围。
保留补丁目录和备份，回退需要用它们核对目标与 SHA256。

## 常见问题

- 提示端口占用：对应服务仍运行，正常退出后重试。
- 路径包含符号链接或联接：选择服务实际目录，不删除链接指向的数据。
- 提示版本比补丁新：不要降级，用匹配的新版本更新包。
- 缺 Pillow/aiohttp：使用实际 AstrBot Python 补齐；Desktop 通过其插件管理器处理。
- 缺 Hub 依赖：按提示选择补齐依赖，或由管理员在该 Hub Python 环境安装。
- 旧令牌长度不足：新版要求 Hub 管理员令牌至少 32 字符，旧全局 AAH_LITE_TOKEN（如配置）也需满足长度且与管理员令牌不同；工具停止更新，由本人先处理，不会自动轮换用户表中的个人令牌。
- 新 HQ/反推/放大选项未绑定：在独立模板目录中配置自己的模型并选择，原工作流保持可用。

完整操作见 docs/TOOLS.md、docs/TROUBLESHOOTING.md。反馈可在 bilibili 联系「ケモミミロリコン」，附旧版本、更新日志和报错截图，收起凭据。
