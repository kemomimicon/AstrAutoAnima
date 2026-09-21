# 工作流设置与 Beta 边界

## 先完成 Quick

部署向导根据用户选定的 UNET、CLIP、VAE，在本地生成 `AAA_Quick_Local_api.json`。正向 / 负向 / 采样 / 画布节点是 `11 / 12 / 19 / 28`，保存节点 `9`。不植入任何作者角色、画风 LoRA 或固定人物提示词。

自己使用其他工作流时，请导出 **API 格式**，并同步 AstrBot 插件设置中的节点 ID。仅改 ComfyUI 编辑器上显示的工作流，不代表插件读取的磁盘 API JSON 已变化。

## 高级模板

| 模板 | 必需额外内容 | 注意 |
| --- | --- | --- |
| HQ / Refine | Anima 模型，基础 ComfyUI 节点 | 先替换 `YOUR_ANIMA_*` 模型；HQ 可沿用二次采样，SeedVR2 链路需额外启用 |
| Detail Repair | Impact-Pack、Impact-Subpack、检测模型 / SAM | 不含检测模型权重，不能只装 JSON；脸部默认建议关闭 |
| SeedVR2 Refine | SeedVR2 节点、DiT / VAE | 本版模板为原生整图放大 + VAE 分块，不是旧 Tiling 的同一拓扑；替换 `YOUR_SEEDVR2_*` |
| Reverse | Booru Tagger、JoyCaption GGUF + 配套 mmproj | 可选择场景、动作、角色等类别；只返回提示词与继续生图是两种模式 |
| Safety Audit | CLTagger 模型、Booru Tagger | 审核默认关闭，需用户明确启用并校准；模型判断不是安全保证 |
| Caption Train 辅助模板 | 用户自行提供训练系统与依赖 | 仅保留独立 caption 辅助工具，不包含 LoRA Studio 服务 / 代理 / 客户端入口 |

发布包中的 `YOUR_STYLE_LORA_1...4` 不是有效模型。若不使用固定 LoRA，请在 ComfyUI 中正确旁路 / 移除这些节点并重新导出 API；若保留，必须换成自己的文件。动态预设仍在每次请求的内存图中修改，不应写回磁盘基础模板。

模板和节点依赖参见 `comfyui/dependency_manifest.json`，其中模型路径相对于自己的 ComfyUI 根目录。选配下载开关只安装指定内容，不自动接受所有第三方授权。

## 验收顺序

1. `/system_stats` 返回正常，确认实际运行 Python 是安装依赖的那个环境。
2. `/object_info` 中存在所选模板要求的节点；不靠“自启动显示已提交”判断就绪。
3. 先用一张普通图片 / 一条普通提示词测试，再加入角色 / 画风。
4. 从 `/history` 或插件任务记录核对真正提交的 API 节点及参数，不能只看编辑器显示。
5. 检查记录、返图、下载、仅提示词反推、HQ / 精修分别是否工作，再开放给群友。

GPU 显存不足时缩小尺寸、降低放大倍率或串行运行；不可据此宣称任意显卡都支持全部高级模板。
