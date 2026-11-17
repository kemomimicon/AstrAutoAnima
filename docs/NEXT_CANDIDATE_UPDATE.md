# AstrAutoAnima 0.5.3-beta.1 · build45 更新与回退

本地候选版，包含 Anima Turbo、角色画廊、预设多人图和 SnapRef `/aref`。先更新服务端，再使用本目录中的新版客户端。功能与模型放置说明见 `docs/NEXT_ANIMA_FEATURES.md`。

## 选哪个包

- Windows-Unified：完整客户端，管理与个人使用入口都包含。
- Windows-Admin：管理端；Windows-Service：个人使用端，这个文件名不代表 Python Hub 服务。
- Web：完整浏览器客户端；更新包已包含同版 Web，无需再覆盖一次。
- Windows-Update / Linux-Update：已有安装的程序更新包，包含插件、Hub、Web、AAA 自定义节点和工作流模板。

客户端 ZIP 都需完整解压，保留 EXE 旁的 DLL、data 等文件。请解压到新目录，并保留旧客户端整个文件夹。不要只复制 EXE。

## 更新前

1. 保存正在编辑的内容，等生成任务结束，正常退出 Hub、AstrBot、ComfyUI 和客户端。
2. 将对应系统更新包完整解压到原安装目录之外。更新工具需要 Python 3.10 以上，可复用原安装的 Python。
3. 保留原安装目录。更新器会检查版本、正在使用的端口、文件哈希、可用空间，并在首次覆盖前备份。
4. 模型、词库、角色预设、个人配置和密钥保留；新增的角色画廊数据另存。新工作流模板添加到 `ComfyUI/user/default/workflows/AAA_Update_0.5.3-beta.1+45`。旧工作流与现有默认模型、采样设置保留。

## Windows 懒人包

双击 `Update-Windows.cmd`，选择原安装目录（含 `runtime-env.json`、`services.json` 和 `Start.cmd`），点击“只做预检”。预检通过后勾选已退出服务，再点击“备份并升级”。

如果系统找不到 Python，在更新包目录打开 PowerShell，用原 Hub 的 Python 运行（将示例安装目录换成实际位置）：

```powershell
& 'D:\AAA-install\hub\.venv\Scripts\python.exe' .\update.py --gui
```

## Linux 懒人包

进入解压后的更新包目录，按实际安装路径修改第一行。预检不写程序文件：

```bash
AAA_INSTALL=/root/autodl-tmp/aaa-install
"$AAA_INSTALL/hub/.venv/bin/python" -B ./update.py --install-root "$AAA_INSTALL"
```

预检通过并已退出服务后执行：

```bash
"$AAA_INSTALL/hub/.venv/bin/python" -B ./update.py --install-root "$AAA_INSTALL" --apply --confirm-stopped
```

如预检明确提示缺少项目 Python 依赖，可追加 `--install-dependencies`。此选项联网补齐所列依赖，不下载 Torch 或模型。依赖环境的回退需使用更新前的环境备份；本工具的自动回退范围是项目程序文件。

## 非懒人包 / 只安装 AstrBot 插件

复制 `update-plan.example.json` 为 `update-plan.json`，填写要更新的实际路径。只更新插件时填写 `plugin_dir` 和 `backup_root`，其余路径留空；`plugin_dir` 必须指向 `astrbot_plugin_comfy_bridge` 文件夹。更新 Hub 时还需填写 `hub_home`、`hub_python`；Hub 必须使用该源码目录的可编辑安装。`comfyui_root` 用于同步 AAA 节点与新模板。

```bash
python update.py --plan update-plan.json
python update.py --plan update-plan.json --apply --confirm-stopped
```

端口不同时，将计划中的 `ports` 改为实际端口。确认相关服务均已退出后再更新。

## 更新完成

按原来的 Start 入口启动服务，打开新客户端并连接原 Hub 地址。登录令牌沿用原值。浏览器需重新加载页面。

先确认普通生图与原词库、角色预设正常，再按新功能说明配置 Turbo / SnapRef 模型和节点。新模型不在更新包内；`/aref` 使用 SnapRef 节点，不能把其权重当成普通 LoRA 使用。现有基础生图无需更换模型。

## 回退

备份位置会在更新日志中显示。懒人包默认放在原安装目录的 `aaa_update_backups/to_0.5.3-beta.1+45_日期_随机值`。手动计划使用指定的 `backup_root`。

每份备份自带旧程序、校验清单、恢复程序和恢复所需载荷。移走原更新包后，备份仍可独立恢复。

1. 正常退出全部相关服务。
2. Windows：进入这次备份，双击 `Rollback-Windows.cmd`，输入 `STOPPED`。
3. Linux：进入这次备份，执行下方命令：

```bash
python3 -B ./update.py --rollback "$PWD" --confirm-stopped
```

4. 回退成功后按原方式启动服务，使用保留的旧客户端目录。

更新过程中发生可捕获的异常会自动回退已改动程序；强制结束进程、断电后请使用备份入口恢复。回退前逐一核验旧备份与当前文件，更新后被人工改过的程序不会被强行覆盖。遇到冲突，保留备份和提示的文件名再处理。

回退保留更新后产生的词库修改、图片、任务记录、角色画廊数据和密钥。备份内的个人配置快照只用于人工恢复，不自动替换现用配置。备份含个人配置，请自行保管，不要直接公开上传。

## 校验与反馈

外层 `SHA256SUMS.txt` 校验 ZIP；每个 ZIP 的 `package-manifest.json` 校验包内文件；更新器还会在使用前校验 `payload-manifest.json`。

```powershell
Get-FileHash -Algorithm SHA256 .\AstrAutoAnima-Windows-Update-0.5.3-beta.1-build45.zip
```

```bash
sha256sum -c SHA256SUMS.txt
```

问题反馈可到项目 GitHub，或 bilibili：ケモミミロリコン。请附版本、操作步骤与错误文字，隐藏令牌和密码。
