# V · 国风古韵离线资源（可选）

`local` 与 `full` 部署均可勾选安装。在 `full` 部署中，通过 `Start-Local` 使用本机能力；远程词库与 `runtime-env.full.json` 保持原设置。资源独立存放，不写入用户主词库 JSON、预设或远程库。运行时按中华通常库范围筛选，原数据库保持完整，以便校验和保留来源记录。

本机无需安装原 ComfyUI 节点，不需要 LLM、API Key 或联网翻译。这里仅随公开源码提供安装代码、声明与说明，不包含数据库。上游 `README.md`、`SOURCES.md` 及每条记录的来源元数据必须保留。**公开再分发仍待逐来源核对，现阶段资源模块仅作为本地私有候选；保留署名不代表许可证审核已通过。**

AAA 在新建 V 组任务时默认补上 `1girl, solo`，不修改原数据库。人物选项可改为 `1boy`、`1woman`、`1man`；选择“不指定人物 Tag”只取消默认人物标签，仍保留 `solo`。锁定后沿用已保存选项。用户附加内容及预设保持原样，不会被这个开关删除；如需改变人物类型，应使用人物选项，避免手动补充相反标签造成冲突。记录和收藏保存补齐后的源串，重跑沿用任务快照，不重复补前缀；旧任务不回填新规则。

## 组装本地私有候选模块

在发布源码目录执行；`--source` 指向包含 `data/cards.sqlite3` 的原资源根目录，`--output` 必须位于公开源码目录之外。仅读取四个白名单文件：`data/cards.sqlite3`、`data/catalog_manifest.json`、`README.md`、`SOURCES.md`。不读取周边文件、密钥或原 ComfyUI 节点代码。

```powershell
python tools/package_gufeng_resource.py --source "D:/GuFengPromptCards" --output "D:/AAA-private/gufeng-private-candidate-0.4.0.zip"
python tools/package_gufeng_resource.py --source "D:/GuFengPromptCards" --output "D:/AAA-private/gufeng-private-candidate-0.4.0.zip" --apply
```

第一条仅校验，不写文件；第二条流式创建一份压缩模块并回读校验，不暂存另一份约 997 MiB 数据库。会检查磁盘空间，不覆盖已有候选文件。数据库固定 SHA256：`2ce071962a67e97b0d60874dc6be033dfaf849f39c455bcd58ed3caf8aacea07`，目录清单版本 `0.4.0`。

原始完整节点 ZIP 不是安装模块，不可直接导入。此打包命令仅生成私有资源 ZIP，不生成或修改正式公开懒人包。待完成逐来源再分发核对后，才能另外决定公开包资源形式。

## 勾选或命令行安装

一键部署向导的“本机离线词库”中勾选“安装 V · 国风古韵”，选择上一步的私有资源 ZIP。默认不选。也可在已有部署计划上追加：

```powershell
python tools/deploy_project.py --plan examples/deployment-plan.windows.json --install-gufeng --gufeng-module "D:/AAA-private/gufeng-private-candidate-0.4.0.zip"
python tools/deploy_project.py --plan examples/deployment-plan.windows.json --install-gufeng --gufeng-module "D:/AAA-private/gufeng-private-candidate-0.4.0.zip" --apply
```

先填写计划的安装目录、已有 ComfyUI 等路径。第一条只预检，第二条执行已有部署流程。Linux 使用相应计划及本地 ZIP 路径。也可在 JSON 计划中设置 `"install_gufeng": true` 与 `"gufeng_module": "/path/to/module.zip"`。路径参数本身不表示安装同意，需要同时勾选或设置安装选项。

安装结果：

- `hub/resources/gufeng/cards.sqlite3`：独立数据库。
- 同目录 `catalog_manifest.json`、`UPSTREAM_README.md`、`SOURCES.md`、`resource-module.json`：版本、署名与完整性记录。
- 只有显式选装并完成校验后，才向 `runtime-env.local.json` 添加 `AAH_LOCAL_GUFENG_CATALOG_PATH`；local 当前启动配置同步该值。

相同 SHA256 的资源重复安装会直接复用，local 升级 full 也不产生数据库备份副本。不同文件、不同本机路径配置、链接目录或校验失败会停止，原文件保留；不会自行删除冲突/中断文件。已经安装的资源不会因下一次取消勾选而被删除。首次安装仍需满足部署向导自身的 Python/ComfyUI 环境要求，资源模块本身不联网。
