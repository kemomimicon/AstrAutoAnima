# 安装教程

本文只说明 AstrAutoAnima 自身的安装。AstrBot、ComfyUI、NapCatQQ 的安装请使用各自官方文档：

- AstrBot：<https://astrbot.org/zh/docs>
- ComfyUI：<https://docs.comfy.org/>
- NapCatQQ：<https://napneko.github.io/>
- Anima Master：<https://github.com/YayiMiko/anima-master>

## 1. 前置条件

- Python 3.10 或 3.11。
- AstrBot 4.x，已通过 NapCat/aiocqhttp 收发 QQ 消息。
- ComfyUI API 能从 AstrBot 所在机器访问。
- 已按 Anima 模型卡安装模型及基础工作流依赖。
- **Anima Master 固定使用已联调的 0.7.2。0.8.0 尚未测试。**
- Windows 客户端需要 Windows 10/11 x64；Android 客户端按 Release 中 APK 的最低系统要求。

建议目录结构：

```text
AAA_STACK/
├─ AstrBot/
├─ ComfyUI/
├─ AstrAutoAnima/
└─ config/                 # .env、令牌注册表等私密文件
```

服务器可把 `AAA_STACK` 换成 `/workspace`，Windows 可用 `D:\AAA_STACK`。本文用以下变量表示：

- `ASTRBOT_DATA`：AstrBot 的 `data` 目录。
- `COMFYUI_ROOT`：ComfyUI 根目录。
- `AAA_REPO`：本仓库根目录。

## 2. 安装 AstrBot 插件

关闭或重载前先备份现有插件目录及插件数据目录。把：

```text
AAA_REPO/plugin/astrbot_plugin_comfy_bridge
```

完整复制到：

```text
ASTRBOT_DATA/plugins/astrbot_plugin_comfy_bridge
```

不要覆盖或删除已有的：

```text
ASTRBOT_DATA/plugin_data/astrbot_plugin_comfy_bridge
```

其中保存用户预设、提示词池、反推历史和任务记录。随后在 AstrBot WebUI 重载插件；若重载失败，
完整重启 AstrBot。日志中应出现：

```text
Plugin astrbot_plugin_comfy_bridge (0.3.1-beta.1)
```

公开包的内置提示词池是空的，不会覆盖私人库。新安装需要按第 7 节导入自己的提示词。

也可以先用跨平台安装器做只读预演，再明确执行：

```bash
python scripts/install_project.py --astrbot-data "ASTRBOT_DATA" --comfyui-root "COMFYUI_ROOT"
python scripts/install_project.py --astrbot-data "ASTRBOT_DATA" --comfyui-root "COMFYUI_ROOT" --apply
```

安装器会备份已存在的插件、自定义节点和同名工作流，但绝不触碰 `plugin_data`；服务重启仍需
手动完成。

## 3. 安装自定义节点

复制：

```text
AAA_REPO/comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools
```

到：

```text
COMFYUI_ROOT/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools
```

使用启动 ComfyUI 的同一个 Python 安装其 `requirements.txt`，然后重启 ComfyUI。不要只在系统
Python 中安装依赖。访问 `http://COMFYUI_HOST:8188/object_info`，确认至少存在：

```text
AnimaCaptionBatchGuard
AnimaReverseCompiler
AnimaReverseResultSaver
```

反推还需要下列外部节点，按其仓库说明安装：

- <https://github.com/nestflow/ComfyUI-Booru-Tagger>
- <https://github.com/judian17/ComfyUI-joycaption-beta-one-GGUF>

训练与反推模型不随包分发。模型来源和许可证见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

## 4. 安装并修改工作流

把 `comfyui/workflows` 中需要的 JSON 复制到 ComfyUI 用户工作流目录，或直接从 ComfyUI 打开：

| 文件 | 用途 | 状态 |
| --- | --- | --- |
| `Anima_HQ_Txt2Img_Beta_api.json` | HQ Stable/Beauty | Beta |
| `Anima_Refine_Existing_Beta_api.json` | 已有图放大低重绘 | Beta |
| `Anima_WD_CT_JoyCaption_Reverse_Beta.json` | 可视化反推工作流 | Beta |
| `Anima_WD_CT_JoyCaption_Reverse_Beta_api.json` | 插件调用反推 API | Beta |
| `Anima_WD_EVA02_Safe_Caption_Train_v2.json` | 独立炼丹打标/质检 | Beta |

HQ 和 Refine 模板经过脱敏，包含以下故意不可运行的占位符：

```text
YOUR_ANIMA_UNET.safetensors
YOUR_ANIMA_CLIP.safetensors
YOUR_ANIMA_VAE.safetensors
YOUR_STYLE_LORA_1.safetensors ... YOUR_STYLE_LORA_4.safetensors
```

必须在 ComfyUI 中选择自己真实存在的模型。四个 LoRA 槽可换为通用占位 LoRA，也可保持与
插件动态槽位节点 `46,47,48,49` 对应；仅把权重设为 0 并不能解决文件不存在的问题。

训练模板中的 `YOUR_TRAINING_DATASET_DIR`、`YOUR_TRAIN_WRAPPER.py`、`YOUR_TRAIN_PYTHON`、
`YOUR_ANIMA_MODEL_PATH`、`YOUR_ANIMA_CLIP_PATH`、`YOUR_ANIMA_VAE_PATH` 和
`YOUR_LORA_OUTPUT_DIR` 也必须逐项配置。训练功能独立于 Hub，默认先质检 caption，不要在未
抽查数据时直接开始训练。

修改后用 ComfyUI 的 **Save (API Format)** 重新导出 API JSON。普通 Quick 工作流不随公开包
提供，因为原生产工作流含私人配置；请把自己的可运行 Anima 工作流导出为 API 格式。

## 5. 配置插件

在 AstrBot WebUI 的插件配置页至少填写：

| 配置 | 示例含义 |
| --- | --- |
| `comfyui_base_url` | AstrBot 能访问的 ComfyUI API，例如 `http://127.0.0.1:8188` |
| `workflow_path` | 自己的 Quick API 工作流绝对路径 |
| `hq_workflow_path` | 修改后的 HQ API JSON |
| `refine_workflow_path` | 修改后的 Refine API JSON |
| `reverse_workflow_path` | 反推 API JSON |
| `positive_prompt_node_id` | 默认 `11`，必须与工作流一致 |
| `negative_prompt_node_id` | 默认 `12` |
| `sampler_node_id` | 默认 `19` |
| `style_lora_node_ids` | 默认 `46,47,48,49` |
| `dynamic_role_node_id` | 必须是不与现有节点冲突的新 ID |

如果工作流节点有变化，不能只修改文件名；同时更新插件配置或 `data/workflow_registry.json`。
执行 `/aimg_status` 确认连接、工作流、节点数和 LoRA 槽位。

## 6. 本地反推保存目录

服务器默认允许反推结果写入 `/workspace`。本地部署时默认允许写入 ComfyUI 当前目录。若
AstrBot 和 ComfyUI 分属不同根目录，启动 ComfyUI 前设置允许根目录：

Linux/macOS：

```bash
export AAA_REVERSE_ALLOWED_ROOTS="/srv/aaa:/data/aaa"
```

Windows PowerShell：

```powershell
$env:AAA_REVERSE_ALLOWED_ROOTS = 'D:\AAA_STACK;E:\AAA_DATA'
```

然后重启 ComfyUI。不要把系统盘根目录作为允许根目录。

## 7. 初始化提示词池

公开包只有空库。运行：

```text
Windows: tools\start_prompt_pool_manager.bat
通用:   python tools/prompt_pool_manager.py
```

打开：

```text
ASTRBOT_DATA/plugin_data/astrbot_plugin_comfy_bridge/anima_random_prompt_pool.json
```

可从空模板 `examples/prompt_pool.empty.json` 新建，导入你有权使用且已审核的 JSON/数组，保存后
重载插件。详细操作见 [工具说明](TOOLS.md)。未导入任何条目时 `/aimg` 仍可用，但随机好图会
提示所选范围无可用提示词。

## 8. 安装 Hub（可选）

Hub 只在需要 Windows/Android 客户端或远程管理时安装：

```bash
cd AAA_REPO/hub/service
python -m venv .venv
# Linux/macOS
.venv/bin/python -m pip install -e .
# Windows
.venv\Scripts\python.exe -m pip install -e .
```

复制 `.env.example` 为仓库外的私密 `.env`，填写实际路径、Bot ID 和令牌。令牌最简生成方式：

```text
Windows: tools\start_hub_user_manager.bat
通用:   python tools/hub_lite_user_manager.py
```

管理员令牌也可用 Python 生成：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

不要把真实 `.env` 放进 Git。加载环境变量后启动：

```bash
astr-auto-anima-hub
```

检查：

```text
GET http://127.0.0.1:6278/api/v1/health
```

应返回 `service=astr-auto-anima-hub` 和 `status=ok`。公网使用必须经过 HTTPS 或可信 VPN。

## 9. 安装客户端（可选）

优先从 GitHub Release 下载已构建的 Windows x64 ZIP 或 Android APK。首次连接填写：

- Hub HTTPS 地址（局域网测试可用 HTTP）。
- 管理员或用户令牌。
- 需要回图的个人/群目标。
- Android 图片保存目录；系统权限不足时选择应用可写目录。

自行构建源码：

```bash
cd clients/flutter
flutter pub get
flutter test
flutter build windows --release
flutter build apk --release
```

## 10. 最小验收

按顺序完成：

1. ComfyUI `/system_stats` 返回 200。
2. AstrBot 日志出现插件 `0.3.1-beta.1`，QQ `/aimg_status` 有响应。
3. `/aimg 1girl, solo` 成功回图。
4. 配置预设后验证角色/画风 LoRA。
5. `/aip 仅反推 分类=场景,动作` 成功返回文本。
6. `/ahq stable ...` 和 `/arefine light` 分别验证。
7. Hub 健康接口、令牌鉴权、客户端历史图片显示和本地保存分别验证。

任一步失败先停止，不要继续覆盖配置；转到[排错手册](TROUBLESHOOTING.md)。
