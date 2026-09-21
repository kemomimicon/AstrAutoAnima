# AstrAutoAnima 本地工具

提示词与令牌管理工具均可离线运行。一键部署助手也默认离线；只有用户主动勾选外部组件时
才会访问网络。

## 完整提示词库管理器

```text
Windows: start_prompt_pool_manager.bat
通用:   python prompt_pool_manager.py gui
```

支持新建、搜索、添加、修改、删除、启停、JSON 批量导入以及 JSON/CSV 导出；保存前自动备份。
可自由创建业务分组并为条目设置多个 `custom_groups`，运行时用 `@group` 或 `@a+b` 筛选。
命令行包含 `validate/add/import/delete/export/group-list/group-add/group-delete/gui` 子命令：

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

## 一键部署助手

从仓库根目录双击 `一键部署_AstrAutoAnima.bat`，或运行：

```bash
python tools/deploy_project.py
```

向导会预检、备份、按选项准备独立环境、生成配置并启动服务。外部环境、节点、模型和依赖安装默认关闭。
仅更新文件的旧助手仍保留在 `easy_installer.py`；新的完整流程见 `../docs/EASY_INSTALL.md`。

完整流程、安全边界和示例见 [`../docs/TOOLS.md`](../docs/TOOLS.md)。公开仓库不附带任何真实
提示词语料、QQ 号或明文令牌。
