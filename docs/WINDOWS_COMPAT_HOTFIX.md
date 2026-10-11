# Windows 紧急兼容补丁：0.5.0-beta.2-windows.2

适用于公开 0.5.0-beta.2、network.1、lora.1、windows.1 部署。包含此前所有紧急修复。
其它版本或修改过源码的部署，请先比较文件，不要盲目覆盖。

## 已安装 windows.1：本次只需更新插件

正常退出 AstrBot，备份插件代码和个人配置，将最小补丁内 plugin_files 的文件按相同结构复制到实际插件目录，再启动 AstrBot。
必须带上新增的 lora_name_runtime.py；不要只更新 main.py，否则会缺模块。
Hub、自定义节点、客户端和模型无需再次安装。
不要删除真实 loras 子目录，不用批量修改已存预设中的正反斜杠。

## windows.2 新增：LoRA 列表中存在却 not in list

插件会向实际目标 ComfyUI 查询标准 LoRA 节点的可选名称，不使用 Hub 操作系统猜测分隔符。
例如预设 loras/example.safetensors 会匹配服务端返回的 loras\example.safetensors。
优先准确匹配，其次只转换分隔符；存在多义、无匹配、网络错误、超时或枚举异常时不提交任务，
并返回可读错误。不删除目录、不忽略大小写、不按 basename 猜模型、不静默跳过 LoRA。
仅修改本次提交的工作流副本，已存角色/画风预设及工作流文件保持不变。

适用于标准 LoraLoader 和 LoraLoaderModelOnly；第三方 LoRA 堆及由其它节点动态输出的字符串仍由对应节点负责，未宣称通用适配所有自定义加载器。
模型列表每次提交按节点类型读取一次，无跨实例/跨任务缓存；无 LoRA 任务不增加请求。

## 修复内容

- Windows 不再执行仅适用于 Linux 的自动休眠检查，修复提交生图时的 HTTP 503 假休眠提示。ComfyUI、AstrBot 插件、Hub 三层一致处理。
- Linux 仍保留 flock、当前启动标识和休眠闸门检查；锁冲突、状态损坏仍拒绝任务，不以“忽略所有异常”绕过保护。
- 反推记录支持 Windows 本机绝对目录，不再硬编码必须处于 /workspace。空目录配置使用 ComfyUI output/AstrAutoAnima/reverse_history；设置 AAH_PLUGIN_DATA_DIR 时优先使用其 reverse_history。已有 Linux 绝对目录仍可使用。
- 反推存储拒绝相对路径、磁盘根、用户主目录以及符号链接/目录联接，避免写入错误位置。
- 角色词典管理覆盖层默认跟随基础词典目录下的 hub_state/character_dictionary_edits.json，避免 Hub 改了角色但插件不读取。
- 图片清理在解析真实路径前检查 Windows reparse points，包括目录联接及其父目录；扫描时跳过链接目录。不会清理模型、配置或非图片文件。
- 单独使用角色词典安装脚本时，Windows 默认写入当前用户 .astrbot 的插件数据目录；自定义部署请显式指定 --data-root。

## 已部署用户：最小热修复包（推荐）

下载 AAA_Windows_Compatibility_Hotfix_0.5.0-beta.2-windows.2.zip。
它只含本轮所需源码和说明，不含用户词库、角色预设、令牌、模型或个人工作流配置。

1. 等正在运行的任务结束，正常退出 ComfyUI、AstrBot 和 Hub。不要只刷新网页。
2. 备份实际运行的 AAA 插件目录、ComfyUI 自定义节点目录、Hub 源码，以及现有配置和插件数据。
3. 将 plugin_files 内的文件复制进实际的 astrbot_plugin_comfy_bridge 插件目录，按相同相对路径覆盖。
   - AstrBot Desktop 常见位置：%USERPROFILE%\.astrbot\data\plugins\astrbot_plugin_comfy_bridge。
   - 以实际运行实例为准；不是 AstrBot EXE 安装目录。
   - 不覆盖 data、plugin_data、presets.json、词库或任何 config。
4. 将 comfyui_nodes 内的文件复制进实际 ComfyUI/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools。
   - 不要把它放进 workflows 文件夹。
   - 若此前手动注释了 install_idle_admission()，本包的 __init__.py 会恢复标准入口；修复已在内部做平台判断，不需要再手动注释。
5. 若部署了 Hub，将 hub_files 内的文件按相同结构合并到 Hub 项目目录。
   - 默认目录结构含 pyproject.toml、src/astr_auto_anima_hub。
   - 不覆盖 .env、runtime-env.json、services.json、hub_state 或 .venv。
   - 使用该 Hub 自己的虚拟环境重新注册源码：

   Windows PowerShell（在 Hub 项目目录内执行）：

   ```powershell
   & ".\.venv\Scripts\python.exe" -m pip install --no-deps --no-build-isolation -e .
   ```

   Linux（若一并更新，使用实际 Hub 环境）：

   ```bash
   ./.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
   ```

   若使用非源码安装，改用完整 Hub 组件包，并保留原配置；不要在不明确运行路径时随意覆盖 site-packages。
6. 正常重启三项服务。ComfyUI 必须完整重启；仅重载 AstrBot 插件不能卸载旧 HTTP 拦截器。
7. 客户端、模型、LoRA 不需要重新下载或安装。

若基础角色词典单独放在自定义目录，请在插件中把“角色词典管理覆盖层路径”显式设为 Hub 实际使用的覆盖层文件。补丁尊重已有显式配置，不会擅自重置。

## 新用户

使用带 windows.2 的 Windows 懒人包；Linux 用户选 Linux 包。
不要再从旧 complete 包中重新部署旧组件。此次不重编 App，继续使用现有公开客户端。
完整插件组件包包含空的公开示例库，老用户请优先使用最小补丁，避免覆盖自己的库。

## 验收顺序

1. /aimg_status 确认插件为 0.5.0-beta.2-windows.2；Hub 健康接口仍显示 windows.1（本次 Hub 没有版本变更）。
2. 普通生图一张，再选一个已安装画风、最后加角色；Quick 无槽位图保留 dynamic、槽位留空。
3. 使用已安装的反推模型测试“仅反推”；确认返回提示词，并在配置的 reverse_history/records 中生成记录。
4. 在管理端修改一个测试角色别名，确认插件可识别；测试后可还原。
5. 图片清理先确认 output_dir 是插件专用图片目录。联接目录会被拒绝，不要通过删除保护代码强行绕过。

自动化覆盖 Windows CMD/PowerShell、插件和 Hub 运行逻辑、离线反推记录写入、目录联接拒绝，并在 Linux 验证真实 flock。
离线测试不代表已经替用户完成 GPU 模型加载和实际出图验收。

## 回退

正常退出相关服务，恢复步骤 2 的对应源码备份，再启动；若回退 Hub 版本则重新执行虚拟环境内的安装命令。
不要删除模型、词库、密钥文件或休眠锁。Linux 云实例若出现真实休眠提示，仍须排查控制器状态。
