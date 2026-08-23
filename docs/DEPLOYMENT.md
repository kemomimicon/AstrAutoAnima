# 本地与服务器部署

## 推荐拓扑

```text
QQ 用户
  │
NapCat ── aiocqhttp ── AstrBot + AAA 插件
                         │
                         ├── ComfyUI API（Quick/HQ/Refine/Reverse）
                         │
                         └── Hub API ── Windows / Android 客户端
```

AstrBot 与 ComfyUI 可在同机，也可分开；配置中的 `127.0.0.1` 永远指“当前进程所在机器”。容器、
WSL 或不同主机部署时必须换成对方实际可达的地址。

## 服务器部署

- 将 AstrBot 数据、ComfyUI 模型、插件数据和 Hub 私密配置放在持久卷，不依赖临时容器层。
- GPU 服务器按需关机前确认云平台是否持久化 `/workspace`；不要把云实例镜像当作唯一备份。
- Hub 保持监听 `127.0.0.1:6278`，通过 HTTPS 反向代理或 VPN 暴露。
- NapCat/QQ 登录数据、模型、LoRA 和生成图单独备份，不进入本项目仓库。
- 自启动脚本应通过真实进程和健康接口判断服务，不能只依据残留的 `screen` 会话。

## 本地 Windows 部署

- 推荐把 AstrBot、ComfyUI 与 Hub 放在同一非系统盘父目录。
- 插件路径使用 Windows 绝对路径；JSON 中反斜杠由配置页处理，不要手工制造无效转义。
- ComfyUI 的 Python 与系统 Python 可能不同，所有自定义节点依赖都安装到前者。
- 使用 `AAA_REVERSE_ALLOWED_ROOTS` 限制反推记录目录。
- 手机访问本机 Hub 时，地址必须使用电脑局域网 IP；Windows 防火墙只放行可信网段。

## 本地 Linux/macOS 部署

目录可放在 `$HOME/aaa-stack` 或 `/srv/aaa`。macOS 的 GPU/节点兼容性取决于 ComfyUI 与模型；
本项目不承诺所有 CUDA 专用采样器和外部节点均可在 Metal 上运行。

## 跨机器部署

若 AstrBot 与 ComfyUI 分开：

- `comfyui_base_url` 指向 ComfyUI 主机可达地址。
- `workflow_path` 是 **AstrBot 进程所在机器**能读取的路径；最稳妥是把 API JSON 同步到 AstrBot。
- ComfyUI 输出图片必须通过其 `/view` API 可取，不能假设共享文件系统。
- Hub 的 `AAH_COMFYUI_ROOT` 只在需要直接读取输出目录时有效；跨机优先走 API。
- 两端时钟保持同步，否则任务时间、历史排序和超时诊断会混乱。

## 数据与备份

至少备份：

```text
ASTRBOT_DATA/config/
ASTRBOT_DATA/plugin_data/astrbot_plugin_comfy_bridge/
Hub 私密 .env 与 lite_users.json
自定义 API 工作流
ComfyUI/models/loras 中自训练 LoRA
训练数据与 caption（如需保留）
```

生成图和缓存按成本决定保留周期。ComfyUI `output` 与插件 `outputs` 可能各有一份，不应长期
无限增长；删除前先做只读容量盘点和备份。
