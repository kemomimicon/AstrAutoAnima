AnimaLoraStudio 可选扩展（第三方项目，不是 AAA 自研训练引擎）
================================================================

原项目：https://github.com/WalkingMeatAxolotl/AnimaLoraStudio
作者：WalkingMeatAxolotl 与 AnimaLoraStudio 贡献者。

我们很喜欢 AnimaLoraStudio 把数据整理、打标、训练和出图测试放在同一工作台的设计。
完整的流程引导、项目/版本管理以及 XY 对比，让原本零散的炼丹步骤容易理解、容易复查；
中英双语界面也降低了入门门槛。感谢作者持续打磨这样实用的开源工具！
如果它帮到了你，欢迎前往原仓库 Star、阅读教程、提交有复现步骤的反馈或参与贡献。

AAA 仅负责可选安装助手、鉴权代理和子路径/手机滚动适配，不宣称拥有上游的成果，
不代表上游背书 AAA，也不承诺任何硬件配置下都可成功训练。

版本与许可
----------
接入兼容基线：Studio 0.25.x；新装固定 0.25.0，提交：
d049ccfafbd3ce19cb65570e7172f84ae2195e61
这不是上游最新版。现有 0.26/0.27 或更新安装请独立使用，不要降级；
新版本的嵌入兼容性需另行测试。原项目最新版能力可能多于此兼容基线。
AAA 连接器：0.1.1，含手机测试页滚动修复。
Studio 主要许可 GPL-3.0；部分组件 Apache-2.0，见随包 LICENSE 与 THIRD_PARTY_NOTICES。
本扩展的上游前端/修改部分不改标为 MIT；源码与修改说明随连接器附带。
模型、训练集和用户素材分别遵守各自许可；本包不含权重或用户数据。

安装边界
--------
默认只预检，明确加 --apply --accept-license 才执行。
要求 Python 3.10+、Git；若要自动建立依赖环境还需 Node.js 18+ 和 npm。
安装依赖会联网下载，可能占数 GB 至更多空间；训练需要合适的 GPU/驱动/内存。
安装助手支持 Windows/Linux；不能据此认为 macOS 已完成 GPU 训练兼容验收。
独立新目录、新 venv，不共享或修改 ComfyUI/Hub 的 Python，不重启或停止任何现有服务。
不拉模型、不开放防火墙、不创建端口映射。Studio 仅监听 127.0.0.1:8765。
请勿把 Studio 的 8765 直接暴露公网；通过具备管理员鉴权的 Hub 可选入口访问。
退出工作台不会终止训练。主服务不会因为未安装此扩展而无法生图。

新装示例（替换路径，保留英文参数）
--------------------------------
Windows:
  py -3 tools\studio_optional.py --destination D:\AI\AnimaLoraStudio
确认预检后建立依赖和前端：
  py -3 tools\studio_optional.py --destination D:\AI\AnimaLoraStudio --install-dependencies --apply --accept-license

Linux:
  python3 tools/studio_optional.py --destination /opt/ai/AnimaLoraStudio
  python3 tools/studio_optional.py --destination /opt/ai/AnimaLoraStudio --install-dependencies --apply --accept-license

父目录必须已存在，新装目标必须不存在；工具不会覆盖已有安装。
仅下载源码时不加 --install-dependencies；首次运行上游启动脚本仍会安装依赖。
构建成功后服务尚未启动，按助手打印的命令手动运行（仅本机监听）。

接入 AAA（现有 Studio）
----------------------
先确认 Studio 自身可打开、版本为 0.25.x，AAA 使用包含连接器接口的新版本。
--plugin-data 必须填实际插件数据目录，不是 data/plugins 下的代码目录。
  py -3 tools\studio_optional.py --existing D:\AI\AnimaLoraStudio --plugin-data D:\AI\AAA\plugin-data
确认输出后在同一条命令末尾加 --apply --accept-license。
也可以在新装命令上添加 --plugin-data，安装成功后直接登记连接器。
若设置了 AAH_EXTENSIONS_ROOT，用 --extensions-root 替代 --plugin-data。
安装器不修改 .env，不需要读取管理员令牌。
默认上游为 http://127.0.0.1:8765；非默认端口需手动配置 AAH_ANIMA_STUDIO_UPSTREAM。
刷新管理端侧栏扩展；未出现入口时先核对 Hub/客户端版本，勿反复覆盖安装。

已有注册项时安全停止；本助手不负责升级或覆盖旧连接器。
失败时保留新建目录和安装锁，输出中的清单/日志用于排查；不强制清除、重装或降级。
接入会备份旧 active.json（若存在），不会备份/改动训练数据或图片。
本机测试覆盖预检、拒绝覆盖、路径/ZIP 校验和注册表保护；真实训练及安卓 WebView
仍需在用户环境按发布验收清单检查。
