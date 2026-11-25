# AstrAutoAnima QQ 指令版 · 0.5.3-beta.1 / build45 / qq.1

## 1. 包怎么用

推荐链路：QQ → NapCat/OneBot v11 → AstrBot 本插件 → ComfyUI → 图片回复原 QQ 会话。
不需要安装 Hub、Admin/Service 客户端，不需要 Hub 令牌或 AstrBot OpenAPI Key。
普通英文生图不需要 LLM API；中文翻译和重跑的自然语言修改使用 AstrBot 自己配置的文本 Provider。

配套包中的 `astrbot_plugin_comfy_bridge-0.5.3-beta.1-build45-qq.1.zip` 是 AstrBot 安装文件。
在 AstrBot 插件管理中选择从本地 ZIP 安装这个文件，**不要把外层说明总包当插件上传**。
插件 ZIP 根目录直接包含 main.py、metadata.yaml、_conf_schema.json，另附 data/workflows 工作流。
若当前 AstrBot 界面没有本地 ZIP 入口，正常退出 AstrBot，将内层插件 ZIP 解压到实际
`data/plugins/astrbot_plugin_comfy_bridge/` 后再启动；不要多套一层同名文件夹。

已有同名插件先备份代码、实际 `data/config` 插件配置及 `data/plugin_data/astrbot_plugin_comfy_bridge`。
新装默认配置已指向包内工作流；更新安装会保留旧配置，需要按第4节核对。
本包不包含个人词库、角色预设、模型权重、账号、密钥或服务器配置。

## 2. 需要的环境

本版插件声明兼容 AstrBot 4.17 至 4.x；Windows 与 Linux 均可部署。
使用支持 Anima 的 ComfyUI；套件验收环境为 PyTorch CUDA 12.8，实际硬件按自己的驱动与上游配置。
本项目的 Anima Master 兼容基线是 **0.7.1**；0.9.1 不是本包的固定基线。
如与 Anima Master 同时安装，检查 /aimg 等命令是否冲突，一个入口由一个插件处理。

环境安装见官方页面，本包只讲本项目接入：

- AstrBot：https://github.com/AstrBotDevs/AstrBot 、https://docs.astrbot.app/
- ComfyUI：https://github.com/Comfy-Org/ComfyUI 、https://docs.comfy.org/
- NapCat：https://github.com/NapNeko/NapCatQQ 、https://napneko.github.io/
- Anima Master：https://github.com/YayiMiko/anima-master
- Anima 基础模型和许可：https://huggingface.co/circlestone-labs/Anima

## 3. NapCat 与 AstrBot 接通

以下为两个程序在同一台电脑、都非 Docker 的配置：

1. AstrBot 消息平台新增 OneBot v11 / aiocqhttp，启用。
2. AstrBot 反向 WebSocket 监听主机填 127.0.0.1，端口6199。
3. 自行设置 OneBot Token，NapCat 对应连接使用同一个值。
4. NapCat 登录机器人 QQ，网络配置新增 WebSocket 客户端，URL填 `ws://127.0.0.1:6199/ws`，消息格式选 Array。
5. 两端保存，确认 AstrBot 显示平台连接在线。机器人加入测试群后，先 @机器人发送 /sid 验证收消息。
6. 需要管理词库或预设的账号，在 AstrBot 配置中登记为管理员。

Docker / 跨电脑时，URL中的127.0.0.1要改为 NapCat 实际能访问的 AstrBot 地址，并配置相应端口。
ComfyUI 地址同理，以 AstrBot 进程所在环境能访问为准。
QQ 官方机器人可接收单次指令，但其群聊回复次数和时限与 NapCat 不同；五连推荐 NapCat/OneBot。

## 4. 放好模型，核对插件设置

默认三件套（各文件名需与工作流一致）：

| 文件 | ComfyUI下的位置 |
| --- | --- |
| anima-base-v1.0.safetensors | models/diffusion_models/ |
| qwen_3_06b_base.safetensors | models/text_encoders/ |
| qwen_image_vae.safetensors | models/vae/ |

模型下载地址、大小、SHA256和同哈希 ModelScope 来源见配套 `模型下载清单.json`。
模型需自行下载并接受相应许可；本包不下载、不移动或替换已有模型。

AstrBot → 插件 → 本插件设置：

| 配置键 | 本包新装默认值 / 填写方法 |
| --- | --- |
| comfyui_base_url | http://127.0.0.1:8188；不同机器自行改可达地址 |
| workflow_path | data/workflows/AAA_QQ_Quick_api.json |
| positive_prompt_node_id / negative_prompt_node_id | 11 / 12 |
| sampler_node_id / latent_node_id | 19 / 28 |
| style_lora_mode | dynamic |
| style_lora_node_ids | 留空；本包基础模板没有固定画风槽 |
| hq_workflow_path | data/workflows/AAA_QQ_HQ_api.json |
| refine_workflow_path | data/workflows/AAA_QQ_Refine_api.json |
| hq_use_seedvr2 | false；HQ先使用普通二次采样 |
| reverse_workflow_path | data/workflows/Anima_WD_Only_Reverse_api.json |
| comfyui_output_root | 本机对应ComfyUI的output绝对路径，使用随机画风等功能时填写 |

这些相对工作流路径相对于**插件目录**，不需要复制到ComfyUI才能被插件调用。
也可以在ComfyUI加载包内JSON修改模型后以API格式另存，再把插件路径改为新文件的绝对路径。
自定义模型时改Quick节点1/2/3；HQ和Anima精修改44/45/15。不要将UI格式JSON当成API格式。
默认画布1024×1536。默认Quick为9个节点，输出节点9；不需要填写46、47、48、49。

安装后由 AstrBot 安装插件 requirements.txt：aiohttp、Pillow。
手动处理依赖时，用启动 AstrBot 的同一个 Python 执行 `python -m pip install -r requirements.txt`。
保存配置并重新加载插件；涉及升级Python模块时正常重启AstrBot。

## 5. 第一张图

在测试群 @机器人或私聊发送：

```text
/aimg_status
/aimg 1girl, solo, standing, fully clothed, park, daylight
```

收到图片后再试参数：

```text
/aimg 比例=2:3 步数=30 CFG=5 1girl, solo, long coat, rainy street
/aimg 尺寸=1024x1024 采样器=2m_sde 步数=30 CFG=6 mountain landscape, daylight
/ahelp
/aimg_manage_help
```

参数之间用空格，CFG用半角数字。普通指令的提示词优先使用英文tag。
没有LLM时先用/aimg；/aicn不承担模型翻译服务的安装。

## 6. 角色、画风与LoRA

以下保存命令由管理员执行，名字可自定义：

```text
/aimg_role_text_set 示例角色 --prompt original_character, blue hair, blue eyes
/aimg_role_set 示例LoRA角色 character/example.safetensors|1.0|1.0 --prompt your_trigger
/aimg_style_set 水彩 style/watercolor.safetensors|0.6|0.6 --prompt watercolor
/aimg_presets
/aimg 角色=示例角色 画风=水彩 1girl, solo, fully clothed, garden
/aimg_preset_del 角色 示例角色
/aimg_preset_del 画风 水彩
```

LoRA名填写ComfyUI接口列出的**精确相对文件名**，从models/loras目录起算。
不要习惯性再加一层loras/；Windows子目录分隔符以/object_info列出的值为准。
纯文本角色不需要LoRA。底模角色词典是另一种可选来源；包内插件tools目录附词典安装工具和说明。
混沌模式至少准备一个角色预设，并准备可选画风；公开包不会附带作者的角色与画风库。

## 7. 导入词库并抽图

公开随机库为空，先用管理员添加自己的普通条目：

```text
/aimg_pool_add B/N mountain landscape, lake, daylight
/aimg_pool_add B/N garden, flowers, sunlight
/aimg_pool_list B/N
/aimg_pool_show 上一步列出的ID
/aimg_random B/N
/aimg_random5 B/N
/aimg_chaos B/N
/aimg_chaos5 B/N
```

中文别名：抽一抽、五连抽、混沌时刻、混沌五连。也支持“来张好图抄一抄”“来张好图五连抽”。
自定义分组可用 `@rain`，交集用 `@rain+night`；先在库中给条目登记相应custom_groups。
五连需要足够数量的启用条目；演示加两条只是验证添加，不足时先继续添加。

批量JSON导入：把文件上传到 **AstrBot所在机器**，再由管理员执行：

```text
/aimg_pool_import D:/你的目录/reviewed_prompts.json
/aimg_pool_import /你的目录/reviewed_prompts.json
/aimg_pool_export B/N
/aimg_pool_enable 条目ID off
/aimg_pool_set 条目ID B/N garden, soft daylight
/aimg_pool_del 条目ID
```

Windows路径推荐正斜杠；上述两条导入命令按自己的系统二选一。导入参数必须指向服务器真实文件。
配套“词库示例.json”只有一条普通风景条目，可复制编辑；保留不同ID，不要将示例当成完整库。
插件独立版使用QQ管理员导入，无需安装面向Hub的在线导入工具。
N/H/S分别为normal/nsfw/sexual；普通测试使用N。群聊、私聊和管理员权限仍按插件原规则执行。

## 8. HQ、精修与重跑

```text
/ahq stable 1girl, solo, fully clothed, park, daylight
/ahq beauty 角色=示例角色 1girl, solo, fully clothed, garden
/arefine light 任务=job_实际ID
/arefine medium 任务=job_实际ID 补充环境细节
/ajob job_实际ID
```

Anima精修需要明确写light或medium；也可回复插件刚生成的图片后发送`/arefine light`。
`/arefine`不带档位会选择SeedVR2，需先装相应扩展和模型。
SeedVR2模板单独放在可选扩展目录；下载其DiT/VAE并安装对应节点后再填写seedvr2_workflow_path。
本包不启用图像或VAE分块；高分辨率先核对显存，按需要降低目标尺寸。

回复机器人刚发的原图消息：

```text
/aremake
/aremake 固定种子
/aremake 固定种子 步数=32 CFG=5
/aecho
/astyle
```

不写固定种子时更换种子；固定种子且不改条件，重复同图是正常结果。
重跑的自然语言内容修改使用AstrBot已有文本Provider；缺少Provider时使用参数调整或普通/aimg。
保留QQ原图消息及插件job_store。转发、旧版未关联图片或删掉任务记录后，引用可能无法定位。
/aecho 查看已保存的当次实际提示词；收藏使用独立的可复用文本，二者分别读取快照。

## 9. 图片反推（可选）与中文生图

普通/aimg、五连、HQ和Anima精修不依赖反推节点。
需要反推时：将配套 `ComfyUI自定义节点/ComfyUI-AstrAutoAnima-Workflow-Tools` 复制到ComfyUI/custom_nodes；
使用ComfyUI实际Python安装该目录requirements.txt，另装依赖清单中的ComfyUI-Booru-Tagger及WD模型，重启ComfyUI。
WD-only模板不依赖JoyCaption。外部节点固定来源和模型落点见“工作流与扩展说明.txt”。

```text
/aip 仅反推
/aip 仅反推 分类=场景,动作,构图
/aip 角色=示例角色 画风=水彩 分类=场景,动作,服装
/aicn 穿长风衣的女孩站在雨后的公园里
```

/aip后按提示在60秒内发送一张图片；仅反推只返回文字，不启动后续生图。
分类为逗号分隔，可复选。/aicn需要AstrBot文本Provider。

## 10. 排错与数据位置

| 现象 | 处理 |
| --- | --- |
| QQ不响应 | 核对NapCat登录、OneBot在线、@唤醒、白名单和命令冲突；先发/sid |
| ComfyUI连接失败 | 在AstrBot所在机器核对8188可达；容器内127.0.0.1不是宿主机 |
| 工作流不存在 | 新装用本包默认相对路径；旧配置填第4节路径或自己的API文件 |
| 节点不存在 | Quick映射必须为11/12/19/28，不能沿用其他工作流节点号 |
| 缺少基础MODEL/CLIP或节点46不存在 | 本包Quick用dynamic且style_lora_node_ids留空；自定义图按实际连接配置 |
| lora_name not in list | 填ComfyUI列出的完整相对名，包括真实子目录，不加多余loras/前缀 |
| 没有可抽词条 | 导入库并核对来源、分级、enabled；五连准备足量条目 |
| 混沌不可用 | 先登记角色/画风预设，核对LoRA列表和冷却提示 |
| 反推无anima_prompt | 检查本包反推编译/保存节点已加载、工作流节点7/8及插件设置 |
| 中文或文字调整失败 | 配置AstrBot文本Provider；普通英文/aimg可独立使用 |
| 找不到原任务 | 用新生成的机器人原图消息回复；查看job_store和实际图片是否仍存在 |
| 已生图却没有QQ图片 | 查NapCat发送回执和AstrBot日志；保留任务，避免重复生成 |

默认数据在AstrBot实际工作目录的 `data/plugin_data/astrbot_plugin_comfy_bridge/`：
anima_random_prompt_pool.json为主库，kp_prompt_pool.json为独立K库，presets.json为预设，job_store为任务与图片关联，outputs为返图缓存。
配置中填写了自定义路径时以该路径为准。插件代码目录data是公共模板目录，不能替代持久数据目录。
管理员 `/aimg_cleanup` 会立即按配置保留期清理插件返图缓存；执行前先保存重要图片，任务记录不会让已删图片重新出现。
反馈请给插件版本qq.1、命令、时间和错误片段，不发送密钥或完整私人库。

反馈入口：bilibili——ケモミミロリコン。

## 11. build45 新功能

- `/aturbo 场景描述`：Anima Turbo 独立模型，默认 10 步、CFG 1。
- 引用一张图片发送 `/aref 场景描述`：默认参考角色和画风。
- `/aref 画风=预设名称 场景描述` 或 `/aref char 画风=预设名称 场景描述`：参考角色，并应用画风预设。
- `/aref cs 场景描述`：显式全部参考；纯画风 style 留待后续方案。
- `/amulti 预览` 与 `/amulti 预设`：按角色预设分段生成多人图。

配置与完整指令见套件内《新功能与模型配置.md》。Turbo、SnapRef、预设多人工作流也已放入插件 data/workflows。SnapRef 节点与模型需按说明安装，适配器由专用节点加载。

引用收藏、取消收藏和举报需配套 AAA Hub，独立插件的基础生图无需 Hub。
本版修正了收藏成功后 QQ 确认消息超时的误报，失败回执不会重新提交收藏，也不会中断后续多选收藏。
配套新版 Hub 后，收藏保存基础场景、动作和用户补充，排除叠加预设和可识别的人物特征；已有收藏不自动改写。
