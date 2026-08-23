# AstrAutoAnima Hub

当前阶段：`Hub 0.3.8-dev.2 / Client 0.3.8-dev.3 / M3.9 本地自动保存与跑图记录 Beta Hotfix`

本目录配套 `astrbot_plugin_comfy_bridge 0.3.1-beta.1`。目前提供：

- Hub 自身健康检查。
- Bearer Token 管理员鉴权。
- AstrBot、ComfyUI、插件版本、提示词库、预设文件、磁盘和 NVIDIA GPU 探测。
- 提示词库的筛选、新增、修改、删除、批量导入与筛选导出。
- 角色/画风预设的新增、修改、重命名与删除。
- 写入前修订冲突检查、原文件备份、临时文件原子替换、删除回收站与 JSONL 审计。
- Windows/Android Flutter 客户端的工作站概览和管理界面源码。
- 管理端与用户端分离登录；用户端可同步预设、浏览启用提示词并生成 QQ 跑图指令。
- Lite 用户端可把结构化任务提交给 Hub，由 AstrBot 处理并主动返图到管理员允许的 QQ 群或私聊。
- 快捷跑图可选择原有工作流采样设置、DPM++ 2M、DPM++ 2M SDE 或 DPM++ 2M SDE GPU。
- 应用可按任务开启自定义 Steps/CFG，Hub 会将它们转换为 `步数=` 与 `CFG=` 前置参数。
- 快捷跑图支持 `/aicn` 中文生图，并继续复用角色、画风、比例与采样器预设。
- 快捷跑图支持 `/aip` 专用图片反推：客户端选择 JPEG/PNG/WebP 后上传到 Hub，Hub 再通过 AstrBot 文件与 Chat API 以图文消息调用插件。
- `/aip` 保留完整、场景、动作、角色、安全或原始单选模式，并新增场景/动作/角色/外观/服装/构图/其他/安全过滤复选。
- 客户端可启用“只返回反推提示词，不跑图”，返回分区结果、合并提示词、安全级别和记录 ID。
- 快捷跑图新增 HQ Stable/Beauty：Hub 会生成 `/ahq` 指令并转发放大、重绘、
  采样器、Steps、CFG、角色、画风和画布参数。
- 快捷跑图新增已有图 Light/Medium 重修：可上传图片，或填写插件返回的父任务
  `job_id`，由 `/arefine` 恢复已记录的最终提示词和实际 LoRA 组合。
- 反推结果由模型判级，因此 Hub 强制只允许投递到 QQ 私聊目标，避免敏感结果越界返回群聊。
- 支持一人一令牌并绑定唯一 QQ 私聊目标；用户之间无法查看或投递到彼此的私聊目标。
- 远程任务与状态按令牌所有者隔离，AstrBot 会话身份也按用户区分。
- Hub 持久化 App 提交的跑图记录与结果图；普通用户只能查看自己的记录，管理员可查看全部记录。
- 客户端跑图页可开启“完成后自动保存到本地”；Android 可通过系统目录选择器自选保存位置并持久保留授权，也可恢复默认目录。保存失败不会影响 QQ 返图。
- 管理端和用户端均新增“记录”页，可按任务类型/状态筛选、预览结果图并再次下载。

现有插件目录不会被修改。

整套安装、权限与公开数据边界见仓库根目录的 `docs/`。

## 服务端开发启动

推荐在独立虚拟环境安装：

```bash
cd /workspace/astr_auto_anima_hub
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

设置环境变量：

```bash
export AAH_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export AAH_LITE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export AAH_LITE_TOKEN_QQ=123456789
export AAH_ASTRBOT_API_KEY="abk_只保存在服务端的Key"
export AAH_ASTRBOT_BOT_ID=your-bot-id
export AAH_DELIVERY_TARGETS_PATH=/workspace/astr-auto-anima-hub-config/delivery_targets.json
export AAH_LITE_USERS_PATH=/workspace/astr-auto-anima-hub-config/lite_users.json
export AAH_PLUGIN_DIR=/workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge
export AAH_PLUGIN_DATA_DIR=/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge
export AAH_COMFYUI_ROOT=/workspace/ComfyUI
```

启动：

```bash
astr-auto-anima-hub
```

也可以使用模块入口：

```bash
python -m astr_auto_anima_hub
```

默认监听：

```text
http://127.0.0.1:6278
```

## API

无需鉴权：

```text
GET /api/v1/health
```

普通用户客户端使用独立的 `AAH_LITE_TOKEN`，只能访问只读接口（管理员令牌也可访问）：

```text
GET /api/v1/lite/prompts?source=D&safety=N&query=rain&page=1&page_size=20
GET /api/v1/lite/presets
GET /api/v1/lite/delivery-targets
POST /api/v1/lite/jobs
GET /api/v1/lite/jobs?kind=hq&status=succeeded&page=1&page_size=20
GET /api/v1/lite/jobs/{job_id}
GET /api/v1/lite/jobs/{job_id}/images/{image_id}
```

`POST /api/v1/lite/jobs` 的 `kind` 可为 `direct`、`chinese`、`reverse`、`random`、`chaos`、`hq` 或 `refine`。`sampler` 字段可为 `""`、`"2m"`、`"2m_sde"` 或 `"2m_sde_gpu"`；空字符串表示保留工作流当前采样设置。可选的 `steps` 范围为 1–200，`cfg` 范围为 0–30；不传时跟随所选预设或原工作流。

`hq` 使用 `profile=stable|beauty`；`refine` 使用 `profile=light|medium`。二者都可传
`scale`（1.0–2.0）与 `denoise`（0–1）。`refine` 需要上传 `source_image_data`，
或者提供 `parent_job_id` 复用插件保存的任务元数据。

`reverse` 任务还需要 `source_image_name` 和 `source_image_data`，可使用兼容字段 `reverse_preset`，或通过 `reverse_categories` 复选分类；`reverse_only=true` 表示只返回反推结果、不跑图。图片以 JPEG/PNG/WebP Base64 data URI 传入，解码后最大 20 MiB，且返图目标必须是私聊。

需要请求头 `Authorization: Bearer <AAH_ADMIN_TOKEN>`：

```text
GET /api/v1/workstation/status
GET /api/v1/sync/revisions
GET /api/v1/prompts?source=D&safety=N&query=rain&page=1&page_size=20
GET /api/v1/presets
```

写入接口还必须提供读取列表时获得的修订号：

```text
If-Match: <revision>
X-Device-Name: <设备名称，可选>
```

管理接口：

```text
POST   /api/v1/prompts
PATCH  /api/v1/prompts/{id}
DELETE /api/v1/prompts/{id}
POST   /api/v1/prompts/import
GET    /api/v1/prompts/export?source=D&safety=N&query=rain

POST   /api/v1/presets/{style|character}
PUT    /api/v1/presets/{style|character}/{name}
DELETE /api/v1/presets/{style|character}/{name}
```

如果 QQ 端或另一台管理设备已经修改文件，旧修订写入会返回 HTTP 409，客户端刷新后才允许重新编辑。备份、回收站和审计记录位于：

```text
<AAH_PLUGIN_DATA_DIR>/hub_state/backups
<AAH_PLUGIN_DATA_DIR>/hub_state/trash
<AAH_PLUGIN_DATA_DIR>/hub_state/audit.jsonl
```

## Flutter 客户端

开发机当前环境：

```text
Flutter 3.47.0 stable
Dart 3.13.0
SDK：D:\dev\flutter
安卓 SDK：D:\Android\Sdk（API 36 / Build Tools 36.0.0）
微软构建工具：Visual Studio Build Tools 2022 + C++ ATL
目标平台：Android、Windows
```

SDK 已加入实际 Windows 用户 PATH，Android/Windows 平台壳已经生成。重启终端或 Codex 后可直接使用 `flutter`；当前会话也可以使用完整路径 `D:\dev\flutter\bin\flutter.bat`。

常用命令：

```powershell
cd apps/flutter_client
flutter pub get
flutter analyze
flutter test
flutter run -d windows
flutter build windows --release
flutter build apk --release
```

开发机已完成 Android 与 Windows 全部工具链，Windows 开发者模式已开启，Google Android SDK 许可已接受。发布产物位于项目根目录的 `releases` 目录。

客户端 0.3.8-dev.3 在管理端和用户端均提供“服务器开启提醒”，并在快捷跑图页
加入 HQ Stable/Beauty 与 Refine Light/Medium。勾选提醒后每 30 秒检查 Hub，
只在“离线→在线”时发送一次系统通知。设置会在本机持久化保存。

客户端的自动保存开关与保存目录仅存储在本机。Hub 的任务记录和结果图位于：

```text
<AAH_PLUGIN_DATA_DIR>/hub_state/remote_jobs/records
<AAH_PLUGIN_DATA_DIR>/hub_state/remote_jobs/media
```

记录功能从安装 0.3.8 后的新任务开始生效，不会自动补录旧版本只存在于内存中的任务。
本版本暂不自动清理历史记录；本地 ComfyUI 文件会优先使用硬链接保存，避免在同一文件系统
上重复占用一份图片空间，不支持硬链接时才退回普通复制。

0.3.8-dev.2 兼容 AstrBot 仅返回 `attachment_saved` 的实际 SSE 格式：Hub 会通过
`GET /api/v1/file?attachment_id=...` 把附件保存进历史。Android 客户端使用 MediaStore
写入公开的 `Downloads/AstrAutoAnima`，并支持点击历史缩略图进行缩放预览。

Android 客户端 0.3.8-dev.3 可通过 Storage Access Framework 选择其他保存文件夹。
用户授权会跨启动保留；若目录被删除或系统收回授权，需在 App 内重新选择。
点击“恢复默认”后，再次使用 `Downloads/AstrAutoAnima`。

直投目标由服务端控制，Lite API 只返回目标 ID、显示名和群聊/私聊类型，不返回真实 UMO。群聊默认允许 N/H，S 只能发送到绑定令牌的“我的 QQ 私聊”。配置格式见 `examples/delivery_targets.example.json`。

## 为成员生成 QQ 绑定令牌

先准备一个 UTF-8 文本文件，每行一个 QQ 号。生成器会创建两个不同用途的文件：

```bash
python scripts/generate_lite_user_tokens.py \
  --qq-file /workspace/astr-auto-anima-hub-config/member_qq.txt \
  --registry /workspace/astr-auto-anima-hub-config/lite_users.json \
  --delivery /workspace/astr-auto-anima-hub-config/lite_user_tokens_private.csv
```

- `lite_users.json` 只含令牌 SHA-256 哈希，供 Hub 读取。
- `lite_user_tokens_private.csv` 含令牌明文，由管理员逐人私发；不得上传群聊、Git 或公开网盘。
- 两个目标文件均拒绝覆盖，避免误操作导致已经分发的令牌失效。
- 在注册表中把某人的 `enabled` 改为 `false` 并重启 Hub，即可单独撤销其令牌。
- 既有 `AAH_LITE_TOKEN` 可通过 `AAH_LITE_TOKEN_QQ` 绑定给令牌所有者，不需要重新生成。

客户端把 Hub 地址与模式保存在普通首选项，把连接令牌保存在系统安全存储。用户端使用独立的只读 Lite Token，不会获得管理员写权限。设备绑定、刷新令牌和设备撤销仍是后续阶段。

## 当前可验证范围

- 服务端 Python 单元与 API 测试均可运行。
- 服务端已完成真实进程启动、HTTP 健康检查和鉴权冒烟测试。
- 已用当前 `astrbot_plugin_comfy_bridge 0.2.10` 的 7471 条提示词库验证读取适配器。
- Flutter `analyze` 已通过，零问题。
- 服务端单元与 API 测试包含模拟的“生成图片→上传附件→主动投递”及 HQ/Refine 指令链路。
- Flutter 测试覆盖现有指令和 HQ/Refine 指令构建。
- Android/Windows 平台壳已经生成。
- Windows x64 Release 和 Android Release APK 均已构建并生成 SHA256。
- 提示词与预设的写入会先备份，并拒绝覆盖过期修订。

## 安全说明

- `AAH_ADMIN_TOKEN` 不得使用示例值，也不得发给普通用户。
- `AAH_LITE_TOKEN` 与管理员令牌必须不同；普通用户只能获得 Lite Token。
- AstrBot API Key 只能保存在 Hub 服务端，并且只授予 `chat`、`im`、`file` scopes。
- 每位用户只获得自己的 QQ 绑定令牌；不要多人共用，也不要把私密交付 CSV 上传到服务器以外的公开位置。
- Hub 默认只监听 `127.0.0.1`。
- 不要直接把 6278 端口裸露到公网。
- AstrBot API Key、Civitai Token 和百度 Token 只能保存在服务端。
