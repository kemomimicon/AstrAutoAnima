# AstrAutoAnima 0.4.0 正式版

2026-09-11 附件修订：同名 `Anima_Workflow_Pack-0.5.0.zip` 已替换为脱敏的
`0.5.0-beta.2` 内容，修复训练环境隔离安装器处理多行 Popen、末尾逗号及 UTF-8 参数的问题。
工具包、源码附件和懒人包同步更新，校验值以新的 SHA256SUMS.txt 为准。
v0.4.0 Git 标签保留原始发布快照；修订源码位于 main。客户端和插件运行逻辑无需更新。

这是首个按统一稳定版本号发布的完整套件，包含 AstrBot 插件、Hub、Web/Windows/Android
客户端源码、自定义节点、六套高级工作流模板、本地提示词管理器、令牌管理器和一键部署助手。

## 本版重点

- 插件、Hub 和客户端统一升级到 `0.4.0`。
- 同步当前 Quick/HQ/Refine/SeedVR2/Reverse/Training 能力、任务历史、图片保存、用户管理、
  LoRA/角色词典与个人画风配置。
- 随机提示词支持任意自定义分组：`@rain`；`@rain+night` 表示同时属于两组。
- 本地提示词库编辑器可创建、重命名、删除自定义分组，并批量导入/导出 JSON 或 CSV。
- 新增图形化一键部署助手：自动探测常见目录、部署前预检、覆盖前备份；所有外部下载与依赖
  安装默认关闭，只在用户主动勾选后执行。
- 公开包移除私人/第三方提示词语料、令牌、QQ 数据、预设、真实模型/LoRA 名、生产路径、
  图片、日志和私人启动素材。

## 兼容性

- AstrBot：`>=4.17,<5`。
- AstrBot 绘画大师（Anima Master）：只完整联调 `0.7.2`。
- 上游 `0.8.0` 尚未回归测试；升级前必须备份并在测试实例验证。
- Python：3.10+。

## 发布包边界

公开主提示词池和 K 池均为 0 条。`examples/prompt_pool.custom-groups.example.json` 只有两条
普通内容的格式示例，用户需要自行导入有权使用且已经审核的语料。模型、外部节点及基础环境
不随包分发。

HQ、Refine、SeedVR2、Reverse 与 Training 工作流仍是实验性模板。其 `YOUR_*` 占位符必须
在 ComfyUI 中替换后重新导出 API JSON，不能直接用于生产。

安装前阅读 [一键部署说明](docs/EASY_INSTALL.md)、[详细安装](docs/INSTALL.md) 和
[排错手册](docs/TROUBLESHOOTING.md)。

## 客户端构建说明

GitHub Release 中的 Android APK 是社区测试签名构建，可直接用于侧载验证，但不等同于
Google Play 的正式签名包。计划二次分发或上架应用商店时，请自行配置独立 keystore、保护
签名密钥，并重新构建。Windows 与 Web 构建不包含服务器地址、Hub 令牌或云平台密钥。
