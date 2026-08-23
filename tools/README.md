# AstrAutoAnima 本地工具

本目录工具均可离线运行，不连接 AstrBot、ComfyUI 或服务器。

## 完整提示词库管理器

```text
Windows: start_prompt_pool_manager.bat
通用:   python prompt_pool_manager.py gui
```

支持新建、搜索、添加、修改、删除、启停、JSON 批量导入以及 JSON/CSV 导出；保存前自动备份。
命令行包含 `validate/add/import/delete/export/gui` 子命令：

```bash
python prompt_pool_manager.py --help
python prompt_pool_manager.py validate your_pool.json
```

## Hub 用户令牌管理器

```text
Windows: start_hub_user_manager.bat
通用:   python hub_lite_user_manager.py gui
```

支持创建/打开 `lite_users.json`、批量追加用户、轮换令牌和启用/禁用账号。注册表只保存 SHA-256
哈希；明文令牌仅在创建时写入一次性交付 CSV。

```bash
python hub_lite_user_manager.py --help
python hub_lite_user_manager.py list path/to/lite_users.json
```

## 只读导出器

`local_prompt_exporter.py` 是旧版轻量筛选/导出工具，不会修改输入库。需要增删改时使用完整管理器。

完整流程、安全边界和示例见 [`../docs/TOOLS.md`](../docs/TOOLS.md)。公开仓库不附带任何真实
提示词库、QQ 号或明文令牌。
