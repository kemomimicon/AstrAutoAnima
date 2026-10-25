# 第三方组件与模型说明

本仓库发布 AstrAutoAnima 自有代码、脱敏工作流和自定义节点。新增可选 Studio 连接器
单独保留上游 GPL 许可、对应源码和修改说明；它不适用本项目 MIT 许可。其他下列软件或模型不捆绑分发。
部署者必须从官方来源获取，并遵守当时版本的许可证与平台规则。

| 组件 | 官方来源 | 说明 |
| --- | --- | --- |
| AstrBot | <https://github.com/AstrBotDevs/AstrBot> | Bot 框架；本项目测试 4.x |
| ComfyUI | <https://github.com/Comfy-Org/ComfyUI> | 工作流执行环境 |
| NapCatQQ | <https://github.com/NapNeko/NapCatQQ> | QQ 接入；遵守其仓库许可及 QQ 平台规则 |
| Anima Master | <https://github.com/YayiMiko/anima-master> | 测试版本 0.7.1；0.9.1 未验证 |
| Anima | <https://huggingface.co/circlestone-labs/Anima> | 模型许可证独立，使用前阅读模型卡 |
| ComfyUI-Booru-Tagger | <https://github.com/nestflow/ComfyUI-Booru-Tagger> | 反推外部节点 |
| JoyCaption GGUF 节点 | <https://github.com/judian17/ComfyUI-joycaption-beta-one-GGUF> | 反推外部节点 |
| WD-EVA02 tagger | <https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3> | 模型不在本仓库 |
| CL Tagger v2 | <https://huggingface.co/cella110n/cl_tagger_v2> | 可能需要授权；不得绕过访问条件 |
| JoyCaption Q6_K | <https://huggingface.co/mradermacher/llama-joycaption-beta-one-hf-llava-GGUF> | GGUF 不在本仓库 |
| JoyCaption mmproj | <https://huggingface.co/concedo/llama-joycaption-beta-one-llava-mmproj-model-f16> | 必须与主模型匹配 |
| Flutter | <https://github.com/flutter/flutter> | 客户端构建工具链 |
| AnimaLoraStudio | <https://github.com/WalkingMeatAxolotl/AnimaLoraStudio> | WalkingMeatAxolotl 与贡献者开发；可选独立项目，非 AAA 自研训练引擎。兼容基线 0.25.x，GPL-3.0，部分组件 Apache-2.0；详情见 `optional/studio/README.txt` |

感谢 AnimaLoraStudio 将数据整理、打标、训练和测试串成清晰的工作台；项目版本管理、
双语界面和 XY 对比非常适合逐步调试和学习。欢迎访问原仓库支持作者、阅读教程和贡献反馈。
AAA 仅提供安装与接入适配，不代表上游为 AAA 背书。自动安装默认关闭，首次使用需明确同意许可；
接入助手不覆盖现有 Studio，不操作训练数据，也不自动开放公网端口。

用户自行添加的模型、LoRA、提示词和图片由用户负责确认授权、隐私、肖像权和内容合规。本项目
的 MIT 许可证不覆盖它们，也不授予任何第三方素材的再分发权。
