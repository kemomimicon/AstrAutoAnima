# 公共版发布验证

## 本地已运行

- 插件：完整 pytest 收集 218 项通过、20 项私人语料 / 迁移快照测试跳过；公开行为使用独立或合成数据。
- Hub：149 项测试通过，包含鉴权、任务套组、安全审核、图片存储、QQ 投递、无炼丹炉路由以及导入不写文件检查。
- 工具：35 项测试通过，包含 Windows 原生 CMD 中文/空格/括号路径、PowerShell 5.1 语法与缺 Python/Tk 的探测回退、Desktop/portable 目录识别、AM 版本保护、模型目录映射、ZIP 穿越和续传链接拒绝，以及重复部署保留配置 / 词库 / 令牌。
- 训练环境兼容辅助脚本：4 项 pytest 通过（不依赖炼丹炉服务）。
- Flutter：58 项测试通过，静态分析无问题；含加载失败、减弱动画、点击拦截和提前销毁的开屏测试。另导出实际 Flutter 动画帧，人工检查角色与文字布局。
- Python 语法 / JSON 结构、空词库、敏感文件 / 模式扫描通过。
- Windows 懒人包解压后离线预检通过且未写入目标目录；Linux 包结构及入口 shell 语法检查通过。
- 项目授权美术白名单 97 个文件；哈希校验通过，未包含私人工作草稿或用户运行数据。

Windows 管理端和普通端在隔离目录构建。Android / Web 以同一脱敏源码构建；发布页只附成功产生并校验的产物。Android 工具链目前有 Gradle / AGP / Kotlin 将来弃用警告，不是运行测试结论。

原生客户端在不含本机用户名的独立构建路径编译，并分离调试符号；符号文件不公开。源文件隐私扫描之外，还用 `scripts/verify_release_archives.py <附件目录>` 检查实际 ZIP/APK，避免编译器嵌入本机构建路径。

## 可复现命令

```bash
python scripts/privacy_scan.py .
python scripts/validate_release.py .
python -m pip install -e hub/service -r plugin/astrbot_plugin_comfy_bridge/requirements.txt
python scripts/run_public_tests.py tools
python scripts/run_public_tests.py plugin --pytest
python scripts/run_public_tests.py hub --pytest
python -m pytest tools/tests/test_anima_training_env_guard.py -q -p no:cacheprovider
```

`run_public_tests.py` 将运行时工作目录隔离，避免测试回退路径在源码树产生数据库。
Flutter 在另外复制的构建目录运行 `flutter pub get`、`flutter analyze`、`flutter test` 和平台构建，不能把构建缓存再装回源包。

## 尚未代表完成的验收

- 没有在此次发布过程中操作生产服务器、QQ 会话或个人云账号。
- 没有做全新 Windows / Linux 所有硬件组合的大模型下载安装与 GPU 实际生图。
- Windows 本地完成实测；CI 在 Windows 与 Ubuntu Python 3.11/3.12 上重复验证，状态以 GitHub Actions 对应提交为准。尚未做 Linux GPU 全栈验收。
- 安装向导的自动配置 / 守卫测试通过，不代表外网下载速度、驱动、llama-cpp CUDA 构建一定成功。
- 第三方模型、节点及 Anima Master 0.9.1 的兼容性不在本版保证内；已联调绘画大师版本为 0.7.1。
- Web 使用常规 JavaScript 发布构建；Wasm 预检存在依赖兼容提示，不声称支持 Wasm 发布。Android 工具链弃用提示留待独立升级，不在部署修复中冒险更换。

请先使用测试实例验证 Quick → 返图 → 历史 / 下载 → HQ / 反推，再逐步开放群友。

升级补充验收：真实 Hub 子进程已在隔离目录启动并通过健康接口，原有令牌和自定义端口保留；新增 AstrBot 初始化使用官方 `init --yes`，避免后台等待交互。测试未操作生产服务。
