# 本地管理工具

两个 GUI 工具只使用 Python 标准库，不依赖 AstrBot、ComfyUI 或服务器。Windows 双击 `.bat`，
Linux/macOS/终端直接运行 Python 文件。建议 Python 3.10+。

## 提示词库管理器

启动：

```text
Windows: tools\start_prompt_pool_manager.bat
通用:   python tools/prompt_pool_manager.py
```

主要能力：

- 新建/打开 AstrAutoAnima 提示词池。
- 按 ID、正文、B/G/D/C/R 来源组、N/H/S 安全级别筛选。
- 添加、修改、启用/停用、删除单条记录。
- 批量导入 JSON；可选择是否覆盖同 ID。
- 导出全部或当前筛选结果为 JSON/CSV。
- 保存前自动备份，并使用原子替换减少写坏风险。

推荐流程：

1. 在本地复制服务器提示词池作为工作副本。
2. 用“打开”载入，先导出一份备份。
3. 执行筛选、增删改或批量导入。
4. 保存并关闭，再运行工具的校验/重新打开确认。
5. 把新 JSON 上传为临时文件，服务器再次备份生产库后替换或用管理员导入命令。
6. 重载插件并用 `/aimg_pool_show <ID>` 抽查。

命令行帮助：

```bash
python tools/prompt_pool_manager.py --help
```

输入可为包含 `prompts` 数组的对象，也可为记录数组。每条至少应有：

```json
{
  "id": "my-0001",
  "prompt": "your reviewed prompt",
  "source_code": "B",
  "safety_code": "N",
  "source_group": "basic",
  "safety_level": "normal",
  "enabled": true
}
```

本仓库不附带真实库。内容分级和版权/隐私审核由库维护者负责。

## 轻量用户令牌管理器

启动：

```text
Windows: tools\start_hub_user_manager.bat
通用:   python tools/hub_lite_user_manager.py
```

主要能力：

- 创建或打开 Hub 的 `lite_users.json`。
- 批量添加 QQ，每人生成独立令牌。
- 明确操作时轮换某个账号令牌。
- 启用、禁用和查看账号；注册表只保存 SHA-256 哈希。
- 新明文令牌只写入一次性交付 CSV，便于私下发给对应用户。
- 修改前自动备份，写入使用原子替换。

推荐流程：

1. 在离线或管理员电脑打开服务器的 `lite_users.json` 副本。
2. 添加 QQ，选择“交付 CSV”保存到私密目录。
3. 把更新后的注册表上传到 Hub 配置的 `AAH_LITE_USERS_PATH`。
4. 明文令牌逐人私发，不要发群、截图或提交 Git。
5. Hub 重启/重载后，用该用户客户端测试；确认后安全删除交付 CSV。

命令行帮助：

```bash
python tools/hub_lite_user_manager.py --help
```

工具不会从哈希恢复旧令牌。用户丢失令牌时必须“轮换”，旧令牌随即失效。

## 只筛选/导出旧工具

`tools/local_prompt_exporter.py` 保留为轻量只读筛选导出工具。需要完整增删改时使用新的
`prompt_pool_manager.py`。
