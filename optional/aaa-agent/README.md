# AstrAutoAnima Agent 插件 0.1.0

让 Codex、DeepSeek Harness 或其他 MCP 宿主调用自己的 AstrAutoAnima Hub。适合需要生成头像、场景或配图，并把图片文件交给下一步工具的 Agent 工作流。

插件包含生图、取图、角色与画风预设查询，以及检查 Hub、已授权目标和任务状态的工具。生成任务进入 Hub 跑图记录。发布到社交账号由已接入该账号的工具负责。

## 1. 准备

先在现有 AAA 客户端确认 Hub 能生成并保存一张图。以 0.5.2-1.44 的 Hub 后台为兼容基线。在线 Hub 使用有生成权限的个人用户令牌和已授权目标。本机工作站使用本机 Hub 令牌，目标为 `local`。

在解压目录打开终端，使用 Python 3.11 或 3.12。Windows PowerShell：

```powershell
$aaaRuntime = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.aaa-agent\venv'
python -m venv $aaaRuntime
$aaaPython = Join-Path $aaaRuntime 'Scripts\python.exe'
& $aaaPython -m pip install -r requirements.txt
& $aaaPython agent.py --configure
```

Linux/macOS：

```sh
python3 -m venv ~/.aaa-agent/venv
aaa_python="$HOME/.aaa-agent/venv/bin/python"
"$aaa_python" -m pip install -r requirements.txt
"$aaa_python" agent.py --configure
```

本机 Hub 或 SSH 隧道填写 `http://127.0.0.1:6278`，远程直连填写 HTTPS 地址。目标 ID 可以先留空，接入后用 `aaa_status` 查询。配置保存在用户目录 `~/.aaa-agent/config.json`，其中包含令牌。调整地址或更换令牌后重启 MCP 连接。多实例可使用 `--config` 指定不同配置文件。

## 2. Codex

用 CLI 添加本地 MCP 连接。Windows PowerShell：

```powershell
codex mcp add astr_auto_anima -- $aaaPython (Resolve-Path agent.py).Path
```

Linux/macOS：

```sh
codex mcp add astr_auto_anima -- "$aaa_python" "$(pwd)/agent.py"
```

打开新会话，先让 Codex 调用 `aaa_status`。需要 Skill 时，将 `skills/astr-auto-anima` 安装到 Codex 的技能目录。支持本地插件目录的 Codex 也可使用本包的 `plugin.json` 与 `mcp.json` 一起加载工具和 Skill。通过插件目录启动时，`python` 须在宿主 PATH 中。选择一种 MCP 接入方式即可。

发行 ZIP 的外层目录带有本地插件目录索引。可从内层 `aaa-agent` 目录执行 `codex plugin marketplace add ..`，然后在 Codex 桌面的插件目录安装 AstrAutoAnima。命令行也可执行 `codex plugin add astr-auto-anima@astr-auto-anima-local`。

[Codex 插件打包说明](https://developers.openai.com/plugins/build/plugins)

## 3. DeepSeek Harness

用同一 Python 环境生成 DSH 配置层。补丁只记录本地程序路径和配置文件路径。

```powershell
& $aaaPython agent.py --dsh-patch aaa-dsh.patch.json
dsh web --patch (Resolve-Path aaa-dsh.patch.json).Path
```

Linux/macOS 使用 `"$aaa_python" agent.py --dsh-patch aaa-dsh.patch.json`，然后运行 `dsh web --patch "$PWD/aaa-dsh.patch.json"`。已有 DSH 启动命令时，可将 `--patch` 和文件路径加到原命令。安装了桌面版且已启用命令行入口时，可用对应的 `desktop` profile。补丁也可作为配置项合并到用户现有 profile。

在会话中查找 `mcp__astr_auto_anima__aaa_status`。支持图片输入的 DSH 会话可以显示 MCP 图片预览，文件路径也会随结果返回。

可让 DSH 读取包内的 `skills/astr-auto-anima/SKILL.md`，作为生图与排障的操作手册。

[DSH 官方 MCP 客户端配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)

## 4. 第一次生图

可以对 Agent 说：

> 用我的 AstrAutoAnima Hub 画一张雨后的街道，暖色路灯，3:2。只生成一张，完成后把图片文件路径给我。

| 工具 | 用途 |
| --- | --- |
| `aaa_status` | 查看 Hub 版本、运行模式、可用目标和仅保存记录能力 |
| `aaa_presets` | 查看可用角色和画风名称 |
| `aaa_generate` | 提交一张图。支持普通英文、中文和 HQ |
| `aaa_job` | 按任务 ID 查询状态和图片 ID |
| `aaa_recent_jobs` | 核对最近任务，适用于提交后连接中断 |
| `aaa_image` | 校验并下载图片到配置文件同级的 `outputs`，可返回预览 |

远程生成时填写配置中的目标 ID，或在每次调用时传入 `aaa_status` 返回的授权目标。该 ID 用于 Hub 的权限和工作流选择。普通英文生图不依赖文本 Provider。中文和 HQ 需要 Hub 配好对应的翻译或工作流能力。

如果插件提示缺少仅保存记录接口，核对管理端连到的 Hub 服务版本及代理。任务失败时记录任务 ID，并结合 Hub 和 ComfyUI 日志排查。提交超时先查最近任务，再决定是否重新发起。维护步骤见 [Agent 操作手册](skills/astr-auto-anima/SKILL.md)。
