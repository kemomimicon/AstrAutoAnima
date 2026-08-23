# 贡献指南

1. 从 `main` 建立分支，提交聚焦且可回滚的修改。
2. 不提交真实提示词库、令牌、QQ 信息、模型、LoRA、生成图或服务器快照。
3. 修改工作流时同时说明节点 ID、输入输出、依赖节点和兼容 Profile。
4. 修改插件/Hub/客户端协议时同时更新对应测试与中文文档。
5. 提交前运行 `python scripts/validate_release.py .` 和 `python scripts/privacy_scan.py .`。
6. Issue/日志先做脱敏；安全漏洞按 [SECURITY.md](SECURITY.md) 私下报告。

Pull Request 请写明：动机、变更范围、验证环境、回滚方式，以及是否影响 Anima Master 0.7.2。
