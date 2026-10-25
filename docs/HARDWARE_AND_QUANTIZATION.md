# 配置建议、低显存量化部署与效果取舍

核对日期：2026-10-20。面向 AAA 安装中心、JoyCaption 反推及 SeedVR2 **单张图片**。

**不分块修订**：依据项目既往画质反馈，不启用图像Tiling，也关闭VAE编码/解码分块；不再将分块列为OOM补救方案。上一版依赖分块的SeedVR2 8GB最低档建议撤回。已有用户需在副本中手动检查，下载新工具不会改掉旧工作流。

**先说明边界：下面的最低档是可尝试的部署起点，不是官方统一最低要求，也不是本项目逐卡实测保证。** 显存峰值受分辨率、画面比例、上下文、节点版本、驱动、精度和同时驻留的模型影响；不能用 GGUF 文件大小推断能否跑完。推荐档同样不保证任意 4K/8K 或视频任务。不要据此直接购买显卡，先用自己的机器验收。

## 1. 选哪一档

以下为本项目的保守规划建议，主要面向 NVIDIA CUDA；Windows 与 Linux 使用同一容量参考，但驱动/依赖安装方式不同。AMD、Intel、Apple Silicon 需按各节点后端单独验证，不按“同样显存”直接换算。

| 用途 | 最低可尝试档（专用显存 / 系统内存） | 推荐档（专用显存 / 系统内存） | 起步方案 |
| --- | --- | --- | --- |
| 仅客户端或 Hub 连接远端 GPU | 无本地 GPU / 8GB RAM | 无本地 GPU / 16GB RAM | 模型在服务端，本地不必下载 |
| 本地基础 Anima 单图 | 8GB / 16GB，优先32GB | 12–16GB / 32GB | batch=1，先768级尺寸；成功后逐级加大 |
| JoyCaption 低显存反推 | 8GB / 32GB | 12–16GB / 32GB | 最低档 Q4_K_M；推荐 Q6_K；匹配 F16 mmproj |
| SeedVR2 单图放大 | 整图最低要求尚未实测；不承诺8GB | 16–24GB / 32–64GB，仅为试配规划 | Q4或Q8；CPU卸载、小尺寸、关闭图像/VAE分块 |
| 生图→反推→放大串行使用 | 整链最低要求尚未验证 | 24GB / 64GB，仅为试配规划 | 不并行、不保留前一模型；每段先单独验收 |
| JoyCaption 非量化或 SeedVR2 7B 高质量探索 | 不作为小白最低档 | 24–32GB / 64GB及以上 | 先单模块；依然需要按输出尺寸调参 |

普通部署建议64位系统、至少4个现代CPU核心；推荐6–8核及SSD。CPU卸载很依赖内存带宽/PCIe，慢不是网络故障。Windows“共享GPU内存”不是等量专用显存；系统页面文件也不能代替显存，频繁换页可能看似卡死。

磁盘建议：基础环境预留约50GB空闲SSD；反推+放大全套建议80–120GB空闲。是容量规划余量，不是固定安装大小。Python/CUDA轮子、缓存、多个量化版本、输入/输出、更新备份另外占用；失败文件 `.part.rejected.*` 也会保留。

JoyCaption 官方说明原生 BF16 模型本身约需17GB显存，适合24GB及以上显卡；本表的8GB档依靠量化与卸载，并非原生模型要求。[JoyCaption 上游说明](https://github.com/fpgaminer/joycaption#vram-requirements)

SeedVR2上游的低显存示例不能代替本项目关闭所有图像/VAE分块后的实测。当前只保留量化、CPU卸载和小尺寸诊断建议，无法给出已验证的整图最低显存。BlockSwap指模型层在CPU/GPU间调度，不是把图片切片拼接，可保留作内存管理。[SeedVR2 上游说明](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler#usage)

## 2. JoyCaption：最低档和推荐档

在“安装与启动中心 → ⑤扩展”选择以下**一个**档，不必两个都下载：

| 档位 | 模型文件 | 主模型+mmproj磁盘体积（十进制GB） | 说明 |
| --- | --- | --- | --- |
| 最低可尝试 | `llama-joycaption-beta-one-hf-llava.Q4_K_M.gguf` | 5.80GB | 8GB卡优先单图，必要时部分CPU卸载 |
| 推荐 | `llama-joycaption-beta-one-hf-llava.Q6_K.gguf` | 7.47GB | 12–16GB卡留余量，细节/关系描述通常更稳妥 |

两档共用 `llama-joycaption-beta-one-llava-mmproj-model-f16.gguf`（约0.88GB），都放入 `ComfyUI/models/llava_gguf/`。完整默认链还需WD模型约1.26GB。Q4+WD约7.06GB，Q6+WD约8.73GB。模型文件大小来自固定仓库元数据，不等于运行显存。

操作步骤：

1. 用“JoyCaption低显存Q4”或“WD+JoyCaption完整反推”补装所需文件。已有正常节点不盲目升级；模型下载不会修改现有工作流。
2. 备份当前反推工作流，另存低配副本。在 `JJC_JoyCaption_Custom_GGUF` 节点中选择对应 `gguf_model`，保留匹配的 `mmproj_file`。本包模板是节点6，但自定义流程应按节点类型确认，不照抄ID。
3. **8GB尝试档**：`n_gpu_layers=16` 作为保守起点，显存允许再增加；OOM时可降至8或0作CPU慢速诊断。`-1`表示尽量全GPU，不适合所有低配机器。`n_ctx=4096`先保留，`max_new_tokens=768`保留完整JSON所需空间，`unload_after_generate=true`。这些是试运行参数，不是自动调参。
4. **12–16GB推荐档**：Q6、`n_gpu_layers=-1`、`n_ctx=4096`、输出768 tokens，仍建议 `unload_after_generate=true`，防止与下一段Anima/SeedVR2争显存；OOM回退部分CPU卸载。
5. 先仅反推一张图片，确认JSON完整、类别有内容，再连接生图。改UI工作流后还要重新导出API格式并在插件指向新副本；仅修改下载勾选不会切换运行模型。输入图不要为了省内存无差别压成低质量JPEG。

GPU版PyTorch可用**不代表**llama_cpp具备GPU后端。用实际ComfyUI Python验证llama_cpp及其GPU offload；不要复制任意cu124安装命令覆盖现有5090等环境。节点要求GGUF主模型与视觉投影配套。[所用节点说明](https://github.com/judian17/ComfyUI-joycaption-beta-one-GGUF#usage)

量化代价：Q4可能较Q6更易漏掉细小配饰、混淆关系或生成不准确标签；这是风险提示，**没有本项目质量下降百分比实测**。降低输入分辨率还会损失小字、纹理；缩短上下文/输出可能截断JSON，这是与量化不同的问题。Q2/Q3不作为默认推荐。CPU卸载主要牺牲速度，不等于主动降低模型精度。

## 3. SeedVR2：不分块试配方案（最低显存待实测）

扩展页提供“SeedVR2整图3B Q4试配”和“SeedVR2整图3B Q8”，均包含DiT及相同VAE：

| 档位 | DiT文件 | DiT+VAE磁盘体积 | 推荐起步 |
| --- | --- | --- | --- |
| 小尺寸诊断 | `seedvr2_ema_3b-Q4_K_M.gguf` | 2.50GB | 单图，先512长边；不保证8GB显卡可跑 |
| 整图推荐试配 | `seedvr2_ema_3b-Q8_0.gguf` | 4.16GB | 16–24GB VRAM/32–64GB RAM规划，先1024长边；未实测 |

VAE为 `ema_vae_fp16.safetensors`（约0.50GB），全部放在 `ComfyUI/models/SEEDVR2/`。GGUF是独立文件，不是把FP16文件改扩展名。兼容节点应能在DiT模型列表显示该GGUF；没有选项先检查版本，**不能**通过重命名绕过。[量化发布者说明](https://huggingface.co/cmeka/SeedVR2-GGUF)

当前公共API模板 `Anima_SeedVR2_Refine_Beta_api.json` 目标仍为4096；**关闭分块不等于4096能在低显存上运行。** 在副本中按节点类型调小目标并确认两项tiled都是false：

| 节点/参数（本包示例ID） | 小尺寸诊断档，非最低硬件保证 | 16–24GB推荐试配起点 |
| --- | --- | --- |
| DiT（2）`model` | 3B Q4_K_M | 3B Q8_0 |
| DiT `blocks_to_swap` | 32 | 16；OOM再逐步加至32 |
| DiT `swap_io_components` | true | true |
| DiT / VAE `offload_device`、`cache_model` | cpu / false | cpu / false |
| VAE（3）`model` | `ema_vae_fp16.safetensors` | 相同 |
| VAE `encode_tiled` / `decode_tiled` | **false / false** | **false / false** |
| 图像Tiling节点 | 不接入 | 不接入 |
| Upscaler（4）`resolution` / `max_resolution` | 512 / 512 | 768 / 1024 |
| Upscaler `batch_size` | 1 | 1 |
| DiT `attention_mode` | sdpa | sdpa |

`resolution`是短边目标，`max_resolution`约束长边（以实际安装节点说明为准）；输入太大时，上述验证档可能缩小图片，这是为了先证明链路可运行，不是最终画质目标。成功后再逐级提高，查看实际输出尺寸和峰值显存/内存。不要一开始加视频批量、torch.compile或第三方加速内核。

**经AAA提交时还要检查覆盖值**：公共Registry的 `seedvr2_refine_v1.profiles.seedvr2.enhance.target_resolution` 默认仍是4096，插件原生路径会用它覆盖工作流里的resolution/max_resolution。使用自己的Registry副本，将该值设成诊断用512或试配用1024，并检查客户端是否又指定了更大的目标；以实际提交任务参数为准。只改ComfyUI画布可能不够。

不启用图像切片拼接，也不启用VAE分块，旧模板遗留的tile_size/overlap字段在tiled=false时不生效，不需调整。发生OOM先降低输入/输出尺寸、只跑一张、释放其他驻留模型；CPU卸载/BlockSwap不能保证解决整图激活内存不足。仍失败就停用SeedVR2或换更大显存，不自动转为分块。

质量风险：3B相比7B可能重建更简化；Q4相比Q8/FP16可能带来纹理不稳、细节变化。SeedVR2本来就是生成式重建，可能改动脸部、文字和饰品，不是无损放大。关闭分块只避开相关风险，并不保证没有其他画质变化；降分辨率仍会损失细节。没有量化A/B实测，不承诺“完全无损”或精确损失百分比。

模型卸载参数见[SeedVR2节点文档](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler)。节点接口可能更新；先在独立副本验收，不自动覆盖旧工作流、卸载已有Tiling节点或强制更新正常节点。

## 4. 下载渠道与方案验收

- Anima三件套：官方HF、经SHA256核对的ModelScope固定版本、用户选定HF镜像、代理或本地导入。`modelscope`只覆盖有清单映射的Anima文件；JoyCaption/SeedVR2仍使用原HF源，不能误以为全部走魔搭。
- JoyCaption/SeedVR2量化：使用扩展页的固定提交清单，可选择HF镜像或文件代理；不会默默下载两个档位，也不下载未经核实的同名模型。
- SDK不是稳定性的保证。参考Studio的分源思路，但不复制其个人密钥配置，不额外向ComfyUI安装下载SDK，不跳过SHA校验。见[下载与续传说明](DOWNLOAD_NETWORK.md)。

小白验收顺序：基础图 → 仅反推 → 单图放大 → 串行接续。每段记录模型名/量化、节点提交、输入输出尺寸、RAM/VRAM峰值、耗时和错误。至少抽查10张不同普通场景，看小饰品、人物一致性、纹理、文字及JSON完整性。先保留原图和原配置；一次只改一个参数。

本轮验证的是文件元数据、下载恢复逻辑与向导，不是上述8GB/16GB显卡的实测性能；没有发布GPU benchmark。遇OOM先回退尺寸/并发/驻留配置，别靠重装全部环境或跳过哈希解决。
