# AstrAutoAnima Hub Client

Windows/Android 管理与用户子客户端。

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
flutter build apk --release
```
