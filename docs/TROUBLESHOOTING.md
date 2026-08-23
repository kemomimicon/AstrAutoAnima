# 常见错误排查

先遵循三条原则：确认实际运行目录与 Python、只做只读检查、备份后再修改。不要因为 WebUI
打不开就删除整个 `data`、插件数据或 QQ 登录目录。

## 插件没有加载或“重载失败”

检查 AstrBot 实际进程目录和日志，不要把文件装到另一个同名副本。插件目录应直接包含
`main.py` 和 `metadata.yaml`，不能多套一层 ZIP 文件夹。

```bash
python -m py_compile main.py image_runtime.py job_runtime.py llm_runtime.py \
  workflow_runtime.py workflow_registry.py preset_runtime.py prompt_pool_runtime.py
```

常见原因：

- 解压生成了错误文件名（例如 `**init**.py` 而不是 `__init__.py`）。
- AstrBot 正从 Jupyter checkpoint 或旧目录运行。
- 依赖装到了别的 Python。
- 旧插件与本插件同时注册 `/aimg`。

语法检查通过但重载仍失败时，完整重启 AstrBot并查看从 `Loading plugin` 开始的完整 Traceback。

## AstrBot 配置看似被重置

先比较当前 `data/cmd_config.json`、备份文件和 AstrBot 进程工作目录。UTF-8 BOM 本身可由
`utf-8-sig` 读取，不要直接覆盖整个配置。若存在多个 AstrBot 副本，WebUI 与进程可能使用不同
`data` 目录。恢复前先校验 JSON 和创建副本。

## QQ 发消息没有反应

分别验证：

1. NapCat/QQ 真实进程存在。
2. NapCat WebUI 端口在本机监听。
3. OneBot/aiocqhttp 连接状态正常。
4. AstrBot 收到了 FriendMessage/GroupMessage 日志。
5. 白名单、管理员、群聊触发规则和命令前缀允许该用户。

残留的 `screen` 名称不代表 NapCat 存活；`(Dead ???)` 必须清理后重新拉起。Linux 路径区分
大小写，例如 `Napcat` 与 `NapCat` 不是同一目录。

## ComfyUI 8188 拒绝连接或一直加载

```text
GET http://127.0.0.1:8188/system_stats
GET http://127.0.0.1:8188/object_info
```

- `Connection refused`：ComfyUI 未启动或端口/地址错误。
- 进程存在但尚未响应：查看启动日志，首次节点扫描可能较慢。
- `ModuleNotFoundError`：把依赖装进启动 ComfyUI 的那个 Python。
- 前端卡 Logo 但 API 正常：浏览器缓存、反向代理或前端资源问题，不等同于后端崩溃。
- 无卡模式下 CUDA/llama/ONNX 检查失败属于预期；启用 GPU 后重新验证。

## 工作流没有使用提示词或 LoRA

先在 ComfyUI `/history` 查看**实际提交的 API prompt**，不要只看 UI 中打开的工作流。重点检查：

- 配置路径指向的是 API 格式 JSON，不是普通 UI JSON。
- 正面节点 ID、采样器 ID、LoRA 槽 ID 与工作流一致。
- 插件是否在加载后重写/覆盖了工作流。
- LoRA 文件名使用 ComfyUI 返回的相对模型路径，大小写完全一致。
- 动态角色节点 ID 没有与工作流既有节点冲突。
- 改配置后插件已重载，日志显示的路径是新文件。

公开 HQ/Refine 模板中的 `YOUR_*` 是占位符，不替换一定报模型不存在。

## 工作流 JSON 无效或 BOM 错误

- `Unexpected UTF-8 BOM`：读取端使用 `utf-8-sig`，或另存为无 BOM UTF-8。
- `Unexpected token`：文件可能混入 shell 输出、注释或不完整复制。
- ComfyUI UI JSON 与 API JSON 结构不同；插件只能提交 API 格式。
- 用 JSON 校验器确认根对象和所有节点结构，再替换生产文件。

## 反推任务完成但提示 `history 中没有 anima_prompt`

确认 ComfyUI `object_info` 存在 `AnimaReverseCompiler` 和 `AnimaReverseResultSaver`，并使用本包的
反推 API JSON。检查节点 `7`（compiler）、`8`（saver）和插件配置的返回节点。旧工作流虽然会
运行，但不会提供插件期待的结构化输出。

如果记录存在而 `actual_generation_prompt` 为空，检查是否选择了“仅反推”、分类全未勾选，或
compiler 输出没有接到 saver。先读取最新反推 JSON 的 `compiled.anima_prompt` 定位在哪一段丢失。

## 反推保存路径被拒绝

错误包含 `outside AAA_REVERSE_ALLOWED_ROOTS` 时，说明保存目录不在允许根下。在启动 ComfyUI
前设置精确父目录，并重启。不要为了省事放行 `/` 或整个系统盘。

## `/aicn` 不工作

中文转换依赖 AstrBot LLM Provider。配置 `text_provider_id`，或确保当前会话/默认 Provider 可用。
ComfyUI 模型不是文本翻译 Provider。查看日志中的 Provider ID、鉴权和超时错误。

## 随机好图提示“无可用提示词”

公开包的库有意为空。先导入自己的库，并确认：

- `prompts` 是数组，ID 唯一、正文非空。
- `source_code` 为 B/G/D/C/R，`safety_code` 为 N/H/S。
- 条目 `enabled=true`。
- C、R、S 需要显式选择。
- S 与受保护角色组合会回退 N/H。

## 五连抽正在冷却

非管理员账号完成五连抽后有 150 秒 CD。不要通过重启绕过；管理员用于测试不受该限制。

## Hub 返回 401/403

- 401：令牌缺失、格式错误或已轮换。
- 403：令牌有效但账号禁用、QQ 绑定/权限不匹配或接口只允许管理员。
- 确认客户端地址没有重复 `/api/v1`，系统时间正常。
- 注册表只存哈希，无法找回原明文；丢失时生成新令牌。

## Hub 健康正常但客户端不显示图片

依次检查：

1. Hub 版本至少为本包版本，健康接口返回正确版本。
2. 任务详情有附件和可下载 URL，`attachment_saved` 状态合理。
3. Hub 能读取 ComfyUI 输出或通过 `/view` 获取图片。
4. 客户端令牌可访问该任务，任务目标与用户绑定一致。
5. Windows 保存目录存在；Android 使用系统授权的可写目录。
6. 图片没有被服务器清理脚本提前删除。

Windows 偶发返图失败先保留失败任务 ID、时间、Hub 日志和 AstrBot 日志；不要只凭客户端 toast
判断生成失败。生成成功但投递失败可以安全重试投递，不应重复扣额度。

## Android 点击保存但本地没有文件

- 在客户端重新选择保存目录并授予系统目录权限。
- 避免直接写受限制的根目录或其他应用私有目录。
- 在任务详情确认图片能预览，再测试保存。
- 查看系统下载/文件管理器，而不是只看相册索引；媒体扫描可能延迟。

## 生成超时

区分“仍在 ComfyUI 队列”与“工作流失败”。检查 `/queue`、`/history/<prompt_id>` 和 GPU 日志。
HQ/五连/大分辨率需要更长超时；增加超时不能修复 OOM、缺节点或模型不存在。

## 磁盘空间快速增长

常见重复位置：ComfyUI `output` 与插件 `outputs`。另有 `input`、`temp`、反推缩略图、Hub 回收
站、更新备份、Python/模型缓存。先用 `df`/`du` 只读盘点，再按日期和任务引用关系清理；模型、
配置、QQ 登录数据和唯一备份不得误删。

## 收集一份可用的错误报告

请提供：组件版本、发生时间、命令（隐去提示词隐私）、任务 ID、相关健康接口状态、从首次 ERROR
到 Traceback 结尾的日志、实际运行目录/Python，以及是否能在 ComfyUI 手动复现。删除令牌、QQ、
公网 IP、图片元数据和私有路径后再公开提交 Issue。
