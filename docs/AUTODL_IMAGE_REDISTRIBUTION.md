# AutoDL 镜像第三方来源与再分发核对

本表是公开候选的发布检查，不是法律授权结论。源码仓库不捆绑的第三方内容可能已经预装进云镜像，
两者必须分别核对。公开前记录实际版本/提交、许可证文件、来源和需履行的义务；未知项保持待核对。

| 内容 | 来源 | 当前材料与剩余核对 |
| --- | --- | --- |
| AAA 自有代码 | 本仓库及 build44 候选源码 | 根 LICENSE；尚需公开提交与镜像实际源码对应 |
| AstrBot | https://github.com/AstrBotDevs/AstrBot | 记录安装 4.27.2；固定版本许可证及对应源码待核对 |
| ComfyUI | https://github.com/Comfy-Org/ComfyUI | 记录应用版本 0.21.1；实际 Git 提交、许可证及源码待核对 |
| NapCatQQ/QQ 程序 | https://github.com/NapNeko/NapCatQQ | 分开核对 NapCat 与 QQ 程序的分发条件；不能仅凭开源插件许可推定 QQ 程序可公开分发 |
| Anima Master | https://github.com/YayiMiko/anima-master | 兼容基线 0.7.1；固定版本来源和许可证待核对 |
| Anima/Qwen/VAE | https://huggingface.co/circlestone-labs/Anima | 固定来源 f973fc41ec7545364ac9776c2440285f43ff2a30；三种权重逐项核对模型卡、许可及说明保留要求 |
| AnimaLoraStudio | https://github.com/WalkingMeatAxolotl/AnimaLoraStudio | 基线 0.25.0、d049ccfafbd3ce19cb65570e7172f84ae2195e61；已有上游 GPL/部分 Apache 说明，公开前核对对应源码、修改与许可文本完整 |
| Studio 连接扩展 | build44 可选扩展源码与修改说明 | 不改标为 AAA MIT；公开源码/修改说明对应待核对 |
| Booru Tagger 节点 | https://github.com/nestflow/ComfyUI-Booru-Tagger | 实际提交和许可证待核对 |
| WD 模型 | https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3 | 固定模型版本、许可和标签表来源待核对 |
| CL Tagger 模型 | https://huggingface.co/cella110n/cl_tagger_v2 | 固定模型版本、访问与再分发条件待核对，不绕过授权 |
| SeedVR2 节点 | build44 节点来源清单 | 实际仓库/提交和许可证待核对；镜像不带大权重 |
| G/V 语料与角色词典 | 镜像内来源说明与提供者授权记录 | 提供者已确认 V 可再分发；公开前仍须汇总各来源/许可、确认 G/词典条件；不上传内容到源码仓库 |
| Python/Node/Torch/CUDA 等 | 对应官方发行包及其许可证 | 核对镜像中 license/notices 保留情况；工具链不由 AAA MIT 重新授权 |

JoyCaption 未安装，不宣传为预装能力；可选下载权重按接收者明确选择与许可确认执行。
任何一项不能满足分发条件时，应从公开候选移除该项，保留官方安装/下载入口，并重新验收，
不能把未知状态改成“已获授权”。本轮不操作云端，不因增加此表而修改母版内容。

建议公开证据只保存来源 URL、版本/提交、许可文件的公开地址或哈希、核对日期和结论。
不保存账号、访问 Token、私密分享链接、网盘授权或含个人信息的聊天截图。
