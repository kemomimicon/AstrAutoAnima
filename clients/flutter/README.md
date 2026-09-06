# AstrAutoAnima Hub Client 0.4.0

`0.4.0` 正式版整合了此前 0.3.17 开发线的 Web/Windows/Android 功能，并移除公开构建中的
私人启动图素材。历史版本记录保留在下文。

Web/Windows/Android 管理与用户子客户端。

当前功能：

- Android 采用同一套 Flutter 源码、两个 product flavor：`admin` 管理端与
  `service` 用户服务端；两个安装包拥有独立包名和本地安全存储。
- 管理端可在 Hub 离线时直连优云智算 OpenAPI，查询、GPU/无卡启动和关闭指定
  实例；公钥和私钥只保存在管理设备的系统安全存储中。
- 用户服务端加入 OC 蓝底白线条动态开屏。
- 角色词典增加“添加到使用角色”按钮，并自动带入弱/强标签模式。
- 角色检索利用官方父子关系识别衍生形态；共享短别名优先本体，完整形态名仍可
  精确触发。

Android 双端构建（两个 flavor 使用独立应用 ID，可同时安装）：

```powershell
flutter build apk --release --flavor admin -t lib/main_admin.dart
flutter build apk --release --flavor service -t lib/main_service.dart
```

仓库默认仅为本地侧载测试配置 debug 签名。公开发布或上架前必须在
`android/app/build.gradle.kts` 中接入自己的 release keystore，且不要把密钥或口令提交到仓库。

0.3.17-dev.1 新增：

- 角色预设与 Danbooru 词表角色分离，只有开启词表开关才显示输入框与弱/强模式。
- 词表角色支持按账号点星收藏、自定义显示名，并在生图页从收藏下拉选择。
- 管理版角色词表页支持修改别名、作品、强模式外貌、帖子数，以及停用/恢复条目。
- 反推分类增加“特殊特征”，用于兽耳、尾巴、角、翅膀等非普通体貌细节。
- 已有图片精修默认 Profile 改为 SeedVR2，Light/Medium 仍可显式选择。

- 管理端和普通用户端新增“角色词典”页。
- 支持中文角色名、英文名与 Danbooru tag 模糊搜索。
- 显示中文别名、标准角色 tag、作品 tag 和强模式外貌词。
- 弱/强模式提示词可以直接切换和复制；查询只读服务器本地词典，不调用 LLM。

0.3.15-dev.1 新增：

- 管理端“工作站概览”新增实时资源仪表。
- 每 2 秒刷新 CPU、系统内存、GPU 核心与显存使用率，并显示 GPU 温度。
- 支持多张 NVIDIA GPU；没有 NVIDIA GPU 或 `nvidia-smi` 不可用时显示兼容提示。
- 实时资源 API 仅管理员可访问，普通用户端不会读取工作站硬件信息。

0.3.14-dev.1 新增：

- 角色框支持直接输入中文名，并提供弱/强/关闭三档 Danbooru tag 模式。
- 个人画风 LoRA 滑条改为 0–2.5，允许手填 -5–5，并可再次编辑已加入 LoRA 的强度。
- 精修新增 SeedVR2 方案，可只上传图片直接执行。
- 五连抽任务卡与历史记录展示全部五个提示词编号。

0.3.13-dev.1 新增：

- 可安装到 iPhone 主屏幕的 Flutter Web App。
- Web App 默认连接当前 HTTPS 域名下的 Hub，无需手工填写服务器地址。
- Safari 中支持照片上传、图片下载和运行期间的工作站上线通知。
- Web 下载遵循浏览器权限与下载目录，不显示原生文件夹选择控件。
- Hub 0.3.13-dev.1 可通过 `AAH_WEB_ROOT` 在同一域名提供 Web App。

0.3.11-dev.1 新增：

- 管理端新增“用户”页，直接管理 QQ 绑定用户和连接令牌。
- 支持添加用户、编辑备注、启停账号、切换群聊目标权限、换发令牌与安全删除。
- 新令牌只显示一次，可复制纯令牌或两列交付 CSV；客户端不会持久保存其他用户令牌。
- 需要配套 Hub 0.3.10-dev.1，旧 Hub 不提供用户管理 API。

0.3.10-dev.1 新增与修复：

- 快捷跑图恢复连续提交：任务进入 Hub 队列后立即可继续加入新任务。
- 每个排队/生成任务独立轮询，不会因提交新任务而丢失旧任务的状态和自动下载。
- 页面显示当前待处理数量；提交按钮在队列未清空时保持可用。

0.3.9-dev.1 新增与修复：

- 快捷跑图新增九种 ComfyUI 调度器，选择只作用于当前任务。
- 当前任务排队或生成期间禁用再次提交，避免五连抽被重复创建并触发冷却。
- 上传外部图片精修时，客户端会要求补充提示词或历史任务 ID。
- 配套 Hub 0.3.9-dev.1 会原样显示 AstrBot 返回的冷却和参数错误。

0.3.8-dev.3 新增：

- Android 可调用系统文件夹选择器，自行设定跑图保存目录。
- 所选目录采用 SAF 持久授权，App 重启后继续使用。
- 快捷跑图页和记录页均可更改目录，并可一键恢复 `Downloads/AstrAutoAnima`。

0.3.8-dev.2 修复：

- Android 改用 MediaStore 保存到公开的 `Downloads/AstrAutoAnima`。
- 历史记录中的缩略图可点击并在 App 内缩放查看。
- 配套 Hub 0.3.8-dev.2 可从 AstrBot `attachment_saved` 事件恢复真实图片。

0.3.8-dev.1 新增：

- 快捷跑图页新增“生成完成后自动保存到本地”开关，并可选择本地保存目录。
- 管理端和用户端新增“记录”页，可按跑图类型、状态筛选历史任务。
- 历史页可预览结果图并手动下载；普通用户只能读取自己的任务，管理员可读取全部任务。
- 自动保存失败只显示本地错误，不影响 AstrBot 已完成的 QQ 返图。

0.3.7-dev.1 新增：

- HQ Stable/Beauty 两套 Profile，可调整放大倍率和二次重绘强度。
- Refine Light/Medium 两套 Profile，可上传已有图片或填写父任务 `job_id`。
- 继续复用现有角色、画风、画面比例、采样器、Steps 与 CFG 控件。
- 客户端只提交语义参数，不保存或暴露 ComfyUI 节点 ID。

“快捷跑图”页支持四档采样选择：原有工作流、DPM++ 2M、DPM++ 2M SDE 和 DPM++ 2M SDE GPU。DPM 预设默认为 30 步 / CFG 6；开启“自定义 Steps 与 CFG”后可对当前任务独立调整。

0.3.5-dev.1 新增：

- 中文生图 `/aicn`，可选择现有角色、画风、比例与采样设置。
- 图片反推 `/aip`，可从 Windows/Android 选择 JPEG、PNG 或 WebP。
- 反推支持完整、场景、动作、角色、安全、原始六种模式。
- 反推完成后仍可套用现有角色/画风 LoRA 预设，并把额外提示词追加到反推结果。
- 反推任务只允许返图到私聊目标；单张输入图片上限为 20 MiB。

## 服务器开启提醒

在“工作站概览”勾选“服务器开启提醒”后：

- 开关会保存到本机，下次启动继续生效。
- 客户端每 30 秒检测一次 Hub Service。
- 只在检测到“离线 → 在线”时发送一次系统通知，不会在持续在线时反复打扰。
- Windows 最小化时可继续检测。Android 在应用存活时检测，转入后台后的实际频率受系统省电策略影响。
- 应用被彻底关闭后不会继续轮询。要实现关闭后的即时提醒，需要后续接入服务端推送。

Android 13 及以上在首次开启时会请求通知权限。

## 开发验证

```powershell
flutter pub get
flutter analyze
flutter test
flutter build windows --release
flutter build apk --release --flavor admin -t lib/main_admin.dart
flutter build apk --release --flavor service -t lib/main_service.dart
flutter build web --release
```
