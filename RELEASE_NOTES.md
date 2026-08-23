# AstrAutoAnima 0.3.1-beta.1

首次完整公开 Beta：AstrBot 插件、HQ/Refine/Reverse/Training 工作流、自定义节点、Hub 服务、
Windows/Android 客户端源码与二进制、提示词批量管理工具和用户令牌管理工具。

安装前必读：

- 只验证 AstrBot 绘画大师（Anima Master）`0.7.2`；上游 `0.8.0` 尚未测试。
- 公开提示词池为 0 条，需导入自己的审核库。
- 工作流已经脱敏，`YOUR_*` 模型、LoRA、训练路径占位符必须填写。
- 不包含模型、LoRA、QQ 数据、令牌、私人预设、生成图和服务器配置。
- HQ、Refine、Reverse、Training 仍为 Beta，请先在测试实例验证。

验证结果：插件 66 项、Hub 37 项、管理工具 4 项、Flutter 9 项测试通过；Flutter Analyze 0 问题；
JSON/Python/隐私扫描通过。

详细安装和排错请阅读仓库 `README.md` 与 `docs/`。
