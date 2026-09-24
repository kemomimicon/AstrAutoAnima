# 本地管理工具

## 新手推荐：安装后配置向导

[首张图启动向导 1.1](FIRST_RUN_WIZARD.md) 将连接授权、投递群、用户令牌、词库导入、角色词典装配、确认保存、实际首图验收和离线帮助集中在九步中文界面。
Windows 可用独立双击版，或运行 `tools/start_first_run_wizard.cmd`；有桌面的 Linux 运行 `sh tools/start_first_run_wizard.sh`。
它用于已存在的本机懒人包安装，不会自动远程修改云服务器、重启服务或重置旧用户令牌。
双击版已内置词库与用户管理器，直接从第 ⑤ / ⑨ 页打开，无须另外安装 Python。所有工具都应先编辑工作副本；向导未保存时不要用另一窗口同时改运行文件。
按目的选择工具、模型装配和逐步生图流程见 [首图逐项操作](FIRST_IMAGE_WALKTHROUGH.md)。

## 原有管理器

三个 GUI 工具只使用 Python 标准库，不依赖 AstrBot、ComfyUI 或服务器。Windows 双击 `.bat`，
Linux/macOS/终端直接运行 Python 文件。建议 Python 3.10+。

## 提示词库管理器

启动：

```text
Windows: tools\start_prompt_pool_manager.bat
通用:   python tools/prompt_pool_manager.py
```

主要能力：

- 新建/打开 AstrAutoAnima 提示词池。
- 按 ID、正文、B/G/D/C/R 来源组、N/H/S 安全级别和任意自定义分组筛选。
- 新建、重命名、删除任意自定义分组；删除分组时同步移除所有条目的成员关系。
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
  "custom_groups": ["rain", "night"],
  "enabled": true
}
```

固定来源组与安全组用于兼容现有指令和安全路由，不妨碍你建立完全不同的业务分类。自定义
分组 ID 长度为 1–64，不能包含空格或 `@ / + ,`。在 QQ 中以 `@rain` 或
`@rain+night` 调用。图形界面点击“管理自定义分组”即可维护；命令行示例：

```bash
python tools/prompt_pool_manager.py group-add pool.json --id rain --name 雨景
python tools/prompt_pool_manager.py add pool.json --id my-001 --groups rain,night --prompt "..."
python tools/prompt_pool_manager.py group-list pool.json
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

## 一键部署助手

```text
Windows: 一键部署_AstrAutoAnima.bat
Linux:   sh 一键部署_AstrAutoAnima.sh
通用:    python tools/easy_installer.py
```

它负责预检、备份和复制本项目组件；不会安装 AstrBot、ComfyUI 或 NapCat。外部节点、模型和
Python requirements 均默认关闭，逐项勾选才允许联网或修改 ComfyUI Python。详见
[一键部署懒人包](EASY_INSTALL.md)。

## 只筛选/导出旧工具

`tools/local_prompt_exporter.py` 保留为轻量只读筛选导出工具。需要完整增删改时使用新的
`prompt_pool_manager.py`。
