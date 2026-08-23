# ComfyUI AstrAutoAnima Workflow Tools

这是本项目炼丹工作流 v2 和反推工作流 Beta 所需的最小自定义节点包。

包含：

- `AnimaCaptionBatchGuard`：在保存 caption 前检查数量、空值、控制文本和重复率。
- `AnimaImageBatchChunker`：把最多 256 张的加载结果拆成 64 张一批（显存紧张时改 32），再交给 WD/CL 推理。
- `AnimaTrainingTagFusion`：以 WD 为稳定基线，限制 CL-only 长尾数量，过滤元数据/质量词并记录冲突。
- `AnimaDatasetTypeResolver`：提供 `AUTO / CHARACTER / STYLE / CLOTHING` 炼丹方向；手动选择永远覆盖 AUTO。
- `AnimaTrainingCaptionCompiler`：按炼丹方向决定哪些稳定标签交给 trigger 学、哪些标签继续写入 caption。
- `AnimaReverseCompiler`：整理 WD、CL Tagger 和 JoyCaption 的输出，生成分类结果与 Anima prompt。
- `AnimaReverseResultSaver`：保存反推 JSON、JSONL 索引和可选缩略图。

服务器常见安装目录：

```text
/workspace/ComfyUI/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools
```

安装完成后重启 ComfyUI。节点分类位于：

```text
AstrAutoAnima/Training
AstrAutoAnima/Reverse
```

方向策略：

- `CHARACTER`：吸收高频稳定外观标签；默认仍描述服装，减少“角色 = 固定衣服”的粘连。
- `STYLE`：吸收高频稳定画法标签，保留主体、外观、服装、动作、场景和构图。
- `CLOTHING`：吸收高频稳定服装标签，保留人物、动作、场景和构图。
- `AUTO`：只在分数和领先差距都达标时采用；否则返回 `AMBIGUOUS` 并要求手动选择。

`AnimaTrainingCaptionCompiler.trigger_word_override` 留空时，不会自行插入 trigger；应继续由下游
`AnimaCaptionPrepare(trigger_mode=folder_name)` 添加文件夹名。填入 override 时，它会作为 caption 第一项。

当前方向工作流不默认连接 JoyCaption。附件中的 Joy 节点没有经过“按图片记录对齐”的 batch
适配，直接接入可能只处理 batch 第一张。`AnimaTrainingTagFusion` 保留了可选的 `joy_caption`
输入，待服务端具备逐图对齐适配器后再启用。

反推工作流还依赖：

- `nestflow/ComfyUI-Booru-Tagger`
- `judian17/ComfyUI-joycaption-beta-one-GGUF`
- CL Tagger v2.00 的 Hugging Face 授权和模型文件
- JoyCaption Beta One Q6_K GGUF 与匹配的 F16 mmproj

`AnimaReverseResultSaver` 默认只允许写入 `/workspace`（服务器）或 ComfyUI 当前目录
（本地部署）。如 AstrBot 与 ComfyUI 位于不同目录，请在启动 ComfyUI 前设置
`AAA_REVERSE_ALLOWED_ROOTS`。Linux/macOS 用 `:`、Windows 用 `;` 分隔多个允许根目录。

`AnimaReverseCompiler` 的 `custom` 模式支持复选 `scene/action/character/appearance/`
`clothing/composition/other`；`include_safety=true` 会在自定义模式中过滤敏感标签，
但安全级别始终独立检测并写入记录。
