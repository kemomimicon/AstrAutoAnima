# 常见错误排查

安装时不知道是否结束：本地 `progress-candidate.1` 修订提供常驻状态灯、文件进度、等待计时和完成／待配置／失败弹窗，见[安装进度说明](INSTALL_PROGRESS.md)。蓝色表示进行中，灰色跳过通常是复用已有环境；黄色待配置不是重新安装的指令。安装期间可用“保存安装日志”反馈具体错误。

改名/移动后 Hub 工作目录不存在：不要新建空 Hub、重下模型或换密钥。Windows 先停止服务，用[搬家工具](RELOCATION_WINDOWS.md)对已改名目录“就地修复”；还没搬则完整复制后修复、保留原目录。修复前自动备份，不改模型/词库内容与密钥值。外部服务、基础 Python 丢失和目录联接等情况需另行核对，不强杀或联网重装。

先遵循三条原则：确认实际运行目录与 Python、只做只读检查、备份后再修改。不要因为 WebUI
打不开就删除整个 `data`、插件数据或 QQ 登录目录。

## 已安装用户：恢复起点

本页也适用于二次启动、搬目录、升级失败和遗忘凭据，不需要重新完成首次配置。
向导“故障恢复（不重装）”可在未读取 `runtime-env.json` 时打开；它只显示指引，
不自动重置密码、不猜配置路径、不停止服务、不自动恢复备份。

1. 记下最后一次成功时间、本次更新包名和发生错误的组件。先暂停新任务。
2. 找到实际启动入口，分清 AstrBot Desktop、AstrBot Launcher、AAA 的 Start、手动 Python 或 Docker。
3. 保留当前配置和更新前备份；备份也包含凭据，不公开上传。
4. 每次只改一项，修改后只重启相关服务。反复点 Start 可能只是复用旧进程。
5. 先验收普通英文单图，再测试 LoRA、反推、HQ、五连和 QQ 投递。生成与投递分别验收。

| 现象 | 先检查 | 不要做 |
| --- | --- | --- |
| 登录页面出现但进不去 | 哪一类凭据、是否选错服务 | 用 Hub 令牌登录 AstrBot |
| 页面打不开 | 服务启动日志、地址和端口 | 清空 data、重装全部环境 |
| 配置或词库突然为空 | 实际运行目录是否变了 | 导入公开空库覆盖旧库 |
| 更新后失败 | 组件版本和更新前备份 | 同时降级插件、Torch、ComfyUI |
| 队列超时 | 已有任务 ID、队列和历史 | 反复点生成造成重复任务 |
| 图片已生成但没收到 | 任务附件、投递和下载分别检查 | 直接重新生成 |

## AstrBot 密码忘了（Windows / Linux）

WebUI 登录密码、AstrBot OpenAPI Key、Hub 管理员令牌、普通用户令牌是四种不同凭据。
重置其中一种不能解决另外一种的鉴权失败；不要把密码或完整日志发到群里。

**先找初始密码：** 默认用户名通常是 `astrbot`，密码是随机生成的，不是固定默认密码。
在本机启动日志中搜索 `Initial password`。改过密码后旧初始密码无效。

- Windows AstrBot Desktop：按 Win+R，输入 `%USERPROFILE%\.astrbot\logs`，在 `backend.log` 中查找。
  常见配置为 `%USERPROFILE%\.astrbot\data\cmd_config.json`；先确认文件存在且属于正在运行的实例。
- 可视化 AstrBot Launcher 的用户目录通常为 `%USERPROFILE%\.astrbot_launcher`，不能套用 Desktop 路径。
- AAA 懒人包或 Linux 手动部署：以原启动入口的工作目录/日志为准，不假设全部都在 `/workspace`。

**找不到日志或已改过密码：** 先正常停止实际 AstrBot，再备份其 `data/cmd_config.json`。
uv/pip 安装且有 AstrBot CLI 的环境，在原工作目录、原环境执行 `astrbot password`，按提示输入，
然后从原入口重新启动。若提示命令不存在或不支持，停止，不要为找回密码另装一套 AstrBot。
较旧版本可先查看原启动命令的 `--help`；仅在支持时用 `astrbot run --reset-password`，
源码入口相应为 `python main.py --reset-password`，保留原端口等参数。此命令会启动服务，勿与旧进程并行。

没有 CLI 的桌面/源码环境，官方另提供配置重置法：停止后端并备份准确的配置文件后，
仅在 `dashboard` 对象内删除以下存在的字段及值：
`username`、`password`、`pbkdf2_password`、`password_storage_upgraded`、`password_change_required`、`jwt_secret`。
保留 `dashboard` 本身及 host、port、SSL 和其它配置，检查 JSON 逗号与结构，再从原入口启动。
不熟悉 JSON 的用户先让维护者确认路径和版本，不要照抄整个示例覆盖配置。
删除 jwt_secret 会使已有面板登录会话需要重新登录；它不是 OpenAPI Key 或 Hub 令牌。

**验收：** 从新启动日志取随机密码 → 登录实际 WebUI → 设置个人新密码 → 重新登录。
不自动改动 AAA 中的 OpenAPI Key，也不生成新的 Hub 令牌。

依据：[AstrBot 官方 FAQ](https://github.com/AstrBotDevs/AstrBot/wiki/zh-faq#管理面板的密码忘记了)、
[CLI](https://docs.astrbot.app/en/use/cli.html)、
[Desktop 日志说明](https://github.com/AstrBotDevs/AstrBot-desktop/issues/170)。核对日期：2026-10-17。

## 401：分清是哪个服务拒绝

| 出错地址/场景 | 应使用什么 | 恢复方式 |
| --- | --- | --- |
| AstrBot 面板登录 | WebUI 用户名和密码 | 看上一节，不填 API Key |
| AstrBot `/api/v1/chat` | AstrBot OpenAPI 完整 Key | 在原 AstrBot 创建/复制完整 Key，更新 Hub 对应字段并重启 Hub |
| Hub `/api/v1/...` | Hub 管理员或普通用户令牌 | 按账户用途检查，见下节 |

先用 URL 确认对象，端口以实际配置为准。6185/6278 只是常见值。
AstrBot v4.28.0 已验证完整 Key 为 `abk_` 开头的47位，列表里的12位前缀不是密钥。
该长度不是所有未来版本的通用规则；若新版格式不同，提交版本和错误，不发送密钥正文。
健康接口成功只能证明服务在线，不等于鉴权通过。403 通常还需查权限，不能一直换令牌重试。

## Hub 令牌丢失或需要换发

- 管理员令牌：先在服务机器上确认正在使用的 `runtime-env.json` / `.env`，私下查看，不能共享配置。
  只有丢失或泄漏才轮换。现有向导可读取原配置，在“授权”暂存新管理员令牌，预览、备份并保存后重启实际 Hub。
  所有使用旧管理员令牌的管理端都需更新；普通用户令牌不因此自动换发。
- 普通用户令牌：注册表仅存哈希，不能反推出原文。由管理员在 Admin 用户管理中为对应用户换发，
  私下交付，并让用户更新 Service 客户端；不要为了找回令牌删账号重建或清空注册表。
- 无法登录 Admin 且无可用运行配置：先恢复可信配置备份或联系维护者，不能靠随便生成一串字符绕过认证。

**验收：** Admin 能读取用户/目标；Service 用自己的令牌读取自己的记录，并生成普通单图。
确认旧令牌失效后再处理备份，切勿截图公开令牌。

## runtime-env.json 丢失、路径不存在或数据突然为空

先打开原 Start.cmd/Start.sh 所在目录，确认是否搬过文件夹或启动了另一份副本。
纯手动部署可能只用 `.env`，无需为向导伪造 `runtime-env.json`。
不要创建空目录让检查“通过”：这样可能把新空库当成原运行数据。

1. 对照真实服务日志、插件桥接状态及原配置中的工作流/数据目录，确认实际实例。
2. 找原安装目录和 `.backup_first_run_`、更新前备份。凭据和 QQ 登录态不要上传求助。
3. 若只是数据盘未挂载，先恢复挂载，不做空库初始化。
4. 若搬目录，先备份并逐项修正真实绝对路径；不在 Windows 上直接保存 Linux 路径配置。
5. 恢复前核对版本与备份时间，只恢复需要的文件，避免丢失备份之后新增的词库、用户和任务。

**验收：** 状态页路径正确 → 词库/角色/用户数量符合预期 → 原图任务记录可读 → 普通单图成功。
没有可信备份时，停止覆盖操作，记录目前文件位置交维护者定位。

## 更新失败与安全回退

先保留完整日志，确认更新的是插件、Hub、节点还是客户端。公开0.5.0与本地开发0.5.2不能混用补丁。
有更新前的可用备份时：暂停任务 → 停止对应服务 → 备份当前现场 → 只恢复被更新的代码 → 原入口重启。
不覆盖个人 data、plugin_data、词库、预设、令牌和工作流，不盲删新增文件。
涉及数据格式迁移的版本必须核对迁移/回退说明，不能只降代码强行打开新数据。
无备份或文件范围不明确时提供当前版本及更新包名，让维护者给对应回退方案。
依次验收健康、鉴权、普通生图、单次重跑；不要同时回退 ComfyUI、Torch 和驱动。

## Windows KSampler：hostbuf_file_reader_read failed

这是底层加载失败摘要，不能单凭这一行断言是 AAA 补丁、显存不足或模型损坏。
先保存完整 Traceback 和此前约30行，比较同一模型/参数在 ComfyUI 直接运行是否失败。
可在支持的 ComfyUI 版本做单变量测试：仅给 ComfyUI 启动参数加 `--disable-dynamic-vram`，
移除冲突的 `--enable-dynamic-vram`（先记录），正常退出后端并重启。
Desktop/第三方启动器入口不确定就发设置截图，不修改节点代码。
参数不识别则撤销；内存占用、速度可能改变，出现 OOM 时保留日志并恢复原参数。
不是把参数填到提示词里，也不是通用修复承诺。不要盲装历史问题提到的旧版依赖。
参考：[上游 Windows 同名问题](https://github.com/Comfy-Org/ComfyUI/issues/15492)。

## Windows 安装路径、编码和下载失败

- PowerShell 中文乱码伴随 ParserError：核对部署包版本，使用已修正的 Windows 入口；不要通过删中文或关闭安全软件猜修。
- `Invalid argument` 且路径含多余引号：重新用目录选择器选择真实目录，不把引号或命令粘进路径框。
- ZIP 未完整解压、目标目录不存在：先确认完整解压和实际路径；不要把运行文件移入 ZIP。
- Hugging Face 超时：参考 [下载网络说明](DOWNLOAD_NETWORK.md)，按明确选项选择镜像或手动下载，核对模型文件和校验值。
- `CRYPT_E_REVOCATION_OFFLINE`：按网络说明处理证书吊销查询问题，不使用全局关闭 TLS 验证的办法。
- `model not in list` / LoRA 找不到：以目标 ComfyUI 节点枚举的完整相对路径为准；Windows 正反斜杠问题使用对应兼容补丁，别随意去目录前缀。

## 恢复后逐项验收与反馈模板

1. AstrBot、ComfyUI、Hub 分别在线，版本与实际启动目录正确。
2. AstrBot 面板登录、Hub 管理员授权、普通用户授权分别成功。
3. 原词库、角色预设、工作流和记录没有被空文件覆盖。
4. 普通英文单图 batch=1 返回图片，然后按需要验证保存、QQ私聊/群投递、LoRA和反推。
5. 不重复提交超时任务，先按已有任务 ID 查询；恢复不等于所有高级工作流都已验收。

可复制下面填写（不要粘贴任何凭据）：

```text
系统及部署方式：
出错组件和版本：
最后成功时间 / 最近改动或更新包：
实际启动入口（隐去用户名等隐私）：
报错时间和任务 ID：
健康检查 / 鉴权 / 普通生图分别结果：
ComfyUI 直接运行同一工作流的结果：
有无更新前备份：
已尝试的一项改动 / 是否已恢复：
附脱敏完整日志（报错前约30行直到Traceback结尾）：
```

不要提交 `.env`、`runtime-env.json`、完整 `cmd_config.json`、QQ登录文件、私人图片或提示词。
没有完整日志时先发启动器截图和错误文字，不能根据客户端一句摘要确认唯一根因。

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

普通五连抽默认限制同一普通用户一个活动任务，完成后即可再次调用；混沌五连仍有 150 秒冷却。不要通过重启绕过；管理员身份以 AstrBot 配置为准。

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
