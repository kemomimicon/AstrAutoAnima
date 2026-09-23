# AstrAutoAnima Hub

当前公开测试版：`Hub 0.5.0-beta.2 / Client 0.5.0-beta.2 / Web App`

本目录是独立部署、并与 `astrbot_plugin_comfy_bridge 0.5.0-beta.2` 配套的项目。目前提供：

- Hub 自身健康检查。
- 管理端实时资源仪表每 2 秒更新 CPU、系统内存、GPU 核心、显存与 GPU 温度；接口仅允许管理员令牌访问。
- Bearer Token 管理员鉴权。
- AstrBot、ComfyUI、插件版本、提示词库、预设文件、磁盘和 NVIDIA GPU 探测。
- 提示词库的筛选、新增、修改、删除、批量导入与筛选导出。
- 角色/画风预设的新增、修改、重命名与删除。
- 写入前修订冲突检查、原文件备份、临时文件原子替换、删除回收站与 JSONL 审计。
- Web/Windows/Android Flutter 客户端的工作站概览和管理界面源码。
- 管理端与用户端分离登录；用户端可同步预设、浏览启用提示词并生成 QQ 跑图指令。
- Lite 用户端可把结构化任务提交给 Hub，由 AstrBot 处理并主动返图到管理员允许的 QQ 群或私聊。
- 快捷跑图可选择原有工作流采样设置、DPM++ 2M、DPM++ 2M SDE 或 DPM++ 2M SDE GPU。
- 应用可按任务开启自定义 Steps/CFG，Hub 会将它们转换为 `步数=` 与 `CFG=` 前置参数。
- 应用可按任务选择九种 ComfyUI 调度器，Hub 会将其转换为 `调度器=` 前置参数。
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
- 管理端新增“用户”页，可创建 QQ 绑定用户、启停账号、控制群聊目标权限、换发令牌和安全删除。
- 用户令牌明文只在创建或换发时返回一次；服务端注册表始终只保存 SHA-256 哈希。
- K 组使用独立 KP 模板库；App 生成完成后可点赞 K 条目并幂等保存到主库 P 组。
- 管理端“LoRA”页扫描全部 `.safetensors`，可设置画风/角色/其他分类、客户端显示名、推荐触发词和启用状态。
- 用户端“预设”页提供 3 个个人画风槽位，每槽最多 16 个画风 LoRA，支持独立强度与推荐触发词一键添加。
- 个人画风 LoRA 强度滑条扩展为 0–2.5，仍可手填 -5–5；已加入的 LoRA 可再次编辑强度。
- 管理员重新扫描 LoRA 后，缺失或禁用的画风 LoRA 会从个人方案中移除；空方案释放槽位。
- 快捷跑图允许直接输入中文角色名，并选择弱/强/关闭三档角色 tag 词典模式。
- 管理端和用户端新增“角色词典”页，可用中文名、英文名或 Danbooru tag 搜索，
  查看作品 tag、弱/强提示词并一键复制；查询直接读取服务器本地词典，不调用 LLM。
- 管理端角色词表页支持分页编辑与停用低有效性条目，所有修改写入独立覆盖层并保留备份、
  回收站与审计记录，不改写第三方基础词典。
- 普通用户可为词表角色点星收藏、自定义显示名和保存默认弱/强模式；收藏按账号隔离。
- 生图页将原有角色预设下拉与 Danbooru 词表输入彻底分离，词表模式下可从个人收藏下拉选取。
- 反推复选新增“特殊特征”，兽耳、尾巴、角、翅膀等与固定外貌分开返回。
- 精修新增 SeedVR2 方案；只上传图片即可提交，不要求额外提示词。
- 五连抽任务卡和历史页显示全部五个提示词编号，而不是只显示第一项。

Hub 只会按明确操作更新插件数据目录中的提示词库、预设、LoRA 目录索引和审计数据；不会覆盖 ComfyUI 工作流或模型文件。

## iPhone Web App

0.3.13-dev.1 起，Hub 可以在自己的根地址同时提供 Flutter Web App。客户端与
API 使用同一个 HTTPS 域名，因此无需开放跨域访问，也不会把用户令牌发送给第三方站点。

先构建客户端：

```powershell
cd apps/flutter_client
flutter build web --release
```

把 `build/web` 的全部文件部署到服务器目录，例如：

```text
/workspace/astr-auto-anima-hub-web
```

在 Hub 的 `.env` 增加：

```text
AAH_WEB_ROOT=/workspace/astr-auto-anima-hub-web
```

重启 Hub 后，访问原 Hub 根地址即可打开客户端，API 仍位于 `/api/v1/...`。
对 iPhone 提供服务时必须在 Hub 前配置可信 HTTPS，不能把裸露的 6278 HTTP 端口直接
发布到公网。用户在 Safari 中打开 HTTPS 地址，点击“分享”→“添加到主屏幕”即可安装。

Web App 与原生客户端的差异：

- 图片选择使用 iOS 系统照片/文件选择器。
- 图片保存由 Safari 下载管理，网页不能自行选择任意本地文件夹。
- 当前上线提醒只在 Web App 正在运行时轮询；它不是服务端离线推送。
- 连接地址首次自动填写为当前 Web App 的 HTTPS 地址。

完整的产品边界、权限模型和阶段路线见：
[AstrAutoAnima Hub 产品与架构设计](../docs/AstrAutoAnima_Hub_产品与架构设计_v0.1.md)。

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
# 以下三项通常无需设置；留空时写入 AAH_PLUGIN_DATA_DIR/hub_state 或插件数据目录
# export AAH_KP_PROMPT_POOL_PATH=/custom/kp_prompt_pool.json
# export AAH_LORA_CATALOG_PATH=/custom/lora_catalog.json
# export AAH_PERSONAL_STYLES_PATH=/custom/personal_styles.json
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
GET /api/v1/lite/characters?query=初音未来&limit=20
GET /api/v1/lite/character-favorites
PUT /api/v1/lite/character-favorites/{tag}
DELETE /api/v1/lite/character-favorites/{tag}
GET /api/v1/lite/delivery-targets
POST /api/v1/lite/jobs
GET /api/v1/lite/jobs?kind=hq&status=succeeded&page=1&page_size=20
GET /api/v1/lite/jobs/{job_id}
GET /api/v1/lite/jobs/{job_id}/images/{image_id}
POST /api/v1/lite/jobs/{job_id}/likes/{kp_prompt_id}
GET /api/v1/lite/style-loras
GET /api/v1/lite/personal-styles
PUT /api/v1/lite/personal-styles/{1|2|3}
DELETE /api/v1/lite/personal-styles/{1|2|3}
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
GET /api/v1/admin/lite-users
GET /api/v1/admin/loras
GET /api/v1/admin/characters?query=初音&page=1&page_size=50
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

POST   /api/v1/admin/lite-users
PATCH  /api/v1/admin/lite-users/{qq}
POST   /api/v1/admin/lite-users/{qq}/rotate
DELETE /api/v1/admin/lite-users/{qq}

PATCH  /api/v1/admin/loras/{relative_safetensors_path}
PATCH  /api/v1/admin/characters/{tag}
DELETE /api/v1/admin/characters/{tag}
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
flutter build apk --release --android-skip-build-dependency-validation
flutter build web --release
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

0.3.9-dev.1 修复了错误链路与重复提交：AstrBot 返回的五连抽冷却、精修参数错误等
纯文本失败原因会原样显示，不再统一误报为 SSE 格式问题。客户端在当前任务结束前禁用再次提交；
上传外部精修图片时，必须填写补充提示词或历史任务 ID。快捷跑图页同时新增九种任务级调度器选择。

0.3.10-dev.1 恢复客户端连续入队：只在单次 HTTP 提交期间防止重复点击，服务端返回
`queued` 后立即允许提交下一个任务。每个未完成任务独立轮询，因此多任务仍能分别更新状态、
通知结果并执行自动下载。Hub 保持单工作器依次消费队列，不会同时挤占 ComfyUI。

Hub 0.3.10-dev.1 / Client 0.3.11-dev.1 把用户令牌管理整合进管理端。管理员可在“用户”页
添加 QQ 绑定用户、编辑备注、启停账号、控制群聊权限、换发令牌或删除用户。创建和换发时
仅显示一次明文令牌，可复制令牌或交付 CSV；列表和 API 均不会返回令牌哈希。

直投目标由服务端控制，Lite API 只返回目标 ID、显示名和群聊/私聊类型，不返回真实 UMO。群聊默认允许 N/H，S 只能发送到绑定令牌的“我的 QQ 私聊”。配置格式见 `examples/delivery_targets.example.json`。

## 为成员生成 QQ 绑定令牌

推荐使用 Client 0.3.11-dev.1 管理端的“用户”页直接添加。Hub 会即时读取注册表，完成增删、
启停或换发后不需要重启服务。已有令牌无法找回，只能通过“换发令牌”生成新令牌。

以下脚本保留为首次部署或离线批量生成的备用方式。

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
- 在管理端关闭某人的“账号启用”，即可立即撤销其令牌。
- 既有 `AAH_LITE_TOKEN` 可通过 `AAH_LITE_TOKEN_QQ` 绑定给令牌所有者，不需要重新生成。

客户端把 Hub 地址与模式保存在普通首选项，把连接令牌保存在系统安全存储。用户端使用独立的只读 Lite Token，不会获得管理员写权限。设备绑定、刷新令牌和设备撤销仍是后续阶段。

## 当前可验证范围

- 服务端 Python 单元与 API 测试均可运行。
- 服务端已完成真实进程启动、HTTP 健康检查和鉴权冒烟测试。
- 已用当前 `astrbot_plugin_comfy_bridge 0.3.5 Beta` 的主提示词库与独立 KP 库验证读取适配器。
- Flutter `analyze` 已通过，零问题。
- 服务端单元与 API 测试包含模拟的“生成图片→上传附件→主动投递”及 HQ/Refine 指令链路。
- Flutter 测试覆盖现有指令、HQ/Refine 指令构建和用户令牌响应解析。
- Hub API 测试覆盖用户创建、查重、启停、换发、旧令牌失效、删除和敏感字段不泄露。
- Web/Android/Windows 平台壳已经生成。
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
