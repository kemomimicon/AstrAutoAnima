# AstrBot ComfyUI Anima 工作流桥接插件

当前版本：`0.3.1-beta.1`

本插件通过 AstrBot 接收 QQ 私聊或群聊指令，将提示词、角色预设、画风预设、画布尺寸等参数写入 ComfyUI API 工作流，等待任务完成后把图片发回原会话。

插件只修改每次任务在内存中的工作流副本，不会覆盖 ComfyUI 中保存的原始工作流文件。

本 Beta 以正式版 `0.2.10` 为完整母版，保留五连抽、混沌时刻、提示词池管理、
动态 LoRA、画布、采样器、`/aicn` 与 `/aip`，并新增 HQ、已有图片放大重修、
Workflow Registry 及可追溯 Job/Asset 元数据。

## HQ 与已有图片放大重修（0.3.1 Beta）

```text
/ahq [stable|beauty] [角色=名称] [画风=名称] [放大=1.25] [重绘=0.28] <提示词>
/arefine [light|medium] [任务=job_xxx] [放大=1.25] [重绘=0.25] [补充提示词]
/ajob job_xxx
```

- `/ahq stable`：默认 ER-SDE、34 步、CFG 4.5；潜空间放大 1.25 倍后以 18 步、0.28 重绘。
- `/ahq beauty`：默认 DPM++ 2M SDE GPU、38 步、CFG 4.5；放大 1.5 倍后以 20 步、0.30 重绘。
- `/arefine light`：针对已有图的轻度精修，默认放大 1.25 倍、0.25 重绘。
- `/arefine medium`：针对已有图的中度精修，默认放大 1.5 倍、0.35 重绘。
- `/arefine` 可直接携带/回复图片；若图片来自本插件的新任务，也可写 `任务=job_xxx`。
- 使用新任务记录时会恢复最终提示词和实际 LoRA 组合；旧图片缺少元数据时会明确提示，
  不会猜测角色或画风。
- `放大=` 允许 1.0–2.0，`重绘=` 允许 0–1；均只修改本次任务。
- Beta 默认不启用 Face/Hand Detailer、ControlNet Tile 或额外模型。
- `/ajob` 私聊返回任务状态、工作流版本、Profile、父任务和图片资产数量。

两套新工作流都继续使用现有 Anima UNET、Qwen CLIP、Qwen VAE 和动态 LoRA，
无需下载新模型或安装第三方节点包。运行前安装 `Anima_Workflow_Pack_0.2.0-beta.1`。

## 中文生图与专用反推（0.3 Beta）

```text
/aicn [角色=名称] [画风=名称] <中文提示词>
/aip [模式=完整/场景/动作/角色/安全/原始] [角色=名称] [画风=名称] [额外提示词]
/aip [仅反推] 分类=场景,动作,构图 [角色=名称] [画风=名称] [额外提示词]
```

- `/aicn` 使用 AstrBot 文本 Provider 转成英文 Danbooru-style tags，再进入原有生图链路。
- `/aip` 可携带或引用图片；没有图片时等待同一 QQ 在同一会话发送第一张图片，默认 60 秒。
- 专用反推工作流以 WD-EVA02 和 CLTagger v2 输出标签，以 JoyCaption Beta One Q6_K
  补充场景、动作、角色与构图语义，再由 `AnimaReverseCompiler` 分类组合。
- 每次结果保存结构化 JSON、来源、图片哈希、角色/画风和最终提示词，并以
  `pending_review` 状态进入反推历史；不会自动混入随机提示词库。
- 指令可以写 `模式=场景`，也可以直接写 `/aip 场景`。可用模式为
  `完整、场景、动作、角色、安全、原始`。
- `分类=` 支持复选 `场景、动作、角色、外观、服装、构图、其他、安全`；
  其中“安全”表示过滤敏感标签，安全级别仍会始终检测并返回。
- 加入 `仅反推`（兼容 `只反推`、`不跑图`）后，只返回分区结果、合并提示词、
  安全级别和反推记录 ID，不会提交生图工作流。

例子：

```text
/aicn 角色=demo_character 画风=demo_style 雨夜里坐在行李箱上
/aip 模式=场景 画风=demo_style rainy night
/aip 安全 角色=demo_character
/aip 仅反推 分类=场景,动作,构图
/aip 分类=角色,外观,服装 角色=demo_character 画风=demo_style
```

专用反推复选需要先安装 `Anima_Workflow_Pack_0.2.0-beta.1`。只有关闭
`reverse_workflow_enabled` 时才回退到旧的 AstrBot 图片 Provider。

## 主要功能

- `/aimg` 原样提示词生图。
- “来张好图抄一抄”随机提示词单抽。
- “来张好图五连抽”抽取五个不同条目并依次生成。
- “混沌时刻”随机组合一个角色、画风、画面比例和提示词，支持五连抽。
- B/G/D/C/R 来源分组与 N/H/S 内容分级。
- 提示词库分页查看、单条查看、导入、导出、修改、停用和可恢复删除。
- 角色/画风触发词私聊查看及管理员在线删改。
- 角色 LoRA、底模直出角色固定串及画风 LoRA 组合预设。
- 动态标准 `LoraLoader` 链，单个画风默认最多支持 16 个 LoRA。
- 自定义画布尺寸和常用长宽比。
- 保留原工作流采样设置，并可按任务选择 DPM++ 2M、DPM++ 2M SDE 或 DPM++ 2M SDE GPU。
- 支持用户在单次任务中自定义 Steps 和 CFG，不覆盖工作流文件。
- 指定角色禁止使用 S 组的保护规则。
- 提示词池自动升级、旧配置保留及迁移前备份。

## 环境要求

- AstrBot `>=4.17,<5`。
- NapCat/OneBot 11 接入时使用 AstrBot 的 `aiocqhttp` 平台适配器。
- AstrBot 服务器能够访问 ComfyUI API，默认地址为 `http://127.0.0.1:8188`。
- 工作流必须使用 ComfyUI 的 **Save (API Format)** 导出，而不是普通界面工作流 JSON。

当前默认工作流节点：

| 用途 | 默认节点 ID |
|---|---:|
| 正向提示词 | 11 |
| 负向提示词 | 12 |
| 采样器 | 19 |
| 画布 `EmptyLatentImage` | 28 |
| 原画风 LoRA 定位节点 | 46、47、48、49 |
| 动态角色 LoRA | 900001 |
| 动态画风 LoRA 起始节点 | 900100 |

如果更换工作流，应在插件配置中同步修改对应节点 ID。

## 安装与升级

将安装包上传到服务器，例如：

```text
/workspace/astrbot_plugin_comfy_bridge-0.2.10.zip
```

确认 AstrBot 实际运行目录后，将安装包解压到：

```text
/workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge
```

覆盖升级前建议备份：

```bash
cp -a \
/workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge \
/workspace/backups/comfy_bridge_before_update

cp -a \
/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge \
/workspace/backups/comfy_bridge_data_before_update
```

覆盖后执行语法检查：

```bash
cd /workspace/astrbot-runtime/data/plugins/astrbot_plugin_comfy_bridge

python -m py_compile \
main.py \
job_runtime.py \
workflow_registry.py \
workflow_runtime.py \
preset_runtime.py \
prompt_pool_runtime.py

grep '^version:' metadata.yaml
```

随后在 AstrBot WebUI 重载插件。若配置页没有出现新字段，请完整重启 AstrBot，并在浏览器按 `Ctrl+F5` 强制刷新。

## 快速开始

检查插件、ComfyUI、工作流和提示词池状态：

```text
/aimg_status
```

私聊获取 0.2.10 管理指令速查：

```text
/aimg_manage_help
```

普通生图：

```text
/aimg 1girl, solo, holding umbrella, rainy street
```

HQ 与重修：

```text
/ahq stable 角色=demo_character 画风=demo_style rainy street, holding umbrella
/ahq beauty 放大=1.5 重绘=0.30 1girl, solo, detailed background
/arefine light
/arefine medium 任务=job_20260821T120000_xxxxxxxxxx
/ajob job_20260821T120000_xxxxxxxxxx
```

随机单抽：

```text
来张好图抄一抄
```

随机五连抽：

```text
来张好图五连抽 D/N
```

## `/aimg` 普通生图

语法：

```text
/aimg [角色=名称] [画风=名称] [采样器=原有|2m|2m_sde|2m_sde_gpu] [步数=30] [CFG=6] [角色权重=数值] [画风倍率=数值] [比例=比例] [尺寸=宽x高] <提示词>
```

示例：

```text
/aimg 角色=demo_character 画风=demo_style 角色权重=0.8 比例=2:3 1girl, solo, rainy street
```

支持的前置参数：

| 参数 | 作用 |
|---|---|
| `角色=` / `role=` | 选择角色预设 |
| `画风=` / `style=` | 选择画风预设 |
| `角色权重=` / `role_strength=` | 同时覆盖角色 model 与 CLIP 权重 |
| `角色模型=` / `role_model=` | 只覆盖角色 model 权重 |
| `角色CLIP=` / `role_clip=` | 只覆盖角色 CLIP 权重 |
| `画风倍率=` / `style_scale=` | 将画风预设中全部 LoRA 权重乘以该倍率 |
| `采样器=` / `sampler=` | `原有` 保留工作流设置；`2m`、`2m_sde`、`2m_sde_gpu` 启用相应 DPM++ 预设 |
| `步数=` / `steps=` | 单次任务覆盖 Steps，范围 1–200 |
| `CFG=` | 单次任务覆盖 CFG，范围 0–30 |
| `比例=` / `ratio=` | 使用内置长宽比 |
| `尺寸=` / `size=` | 直接指定宽高，例如 `1280x960` |
| `宽=`、`高=` | 分别指定宽度或高度，未指定的一边使用默认值 |

参数必须写在用户提示词之前。参数留空或写“默认”时，不覆盖对应预设值。

### 采样器预设

| 指令值 | ComfyUI `sampler_name` | Steps | CFG | Scheduler |
|---|---|---:|---:|---|
| 不写 / `原有` | 保留 API 工作流当前值（现为 `er_sde`） | 保留（现为 30） | 保留（现为 5） | 保留（现为 `normal`） |
| `2m` | `dpmpp_2m` | 30 | 6 | `normal` |
| `2m_sde` | `dpmpp_2m_sde` | 30 | 6 | `normal` |
| `2m_sde_gpu` | `dpmpp_2m_sde_gpu` | 30 | 6 | `normal` |

示例：

```text
/aimg 采样器=2m 1girl, solo, rainy street
/aimg 采样器=2m_sde 步数=36 CFG=5.5 1girl, solo, moonlit garden
/aimg 采样器=2m_sde_gpu 步数=30 CFG=6 1girl, solo, rainy street
来张好图抄一抄 D/N 采样器=2m 雨夜
来张好图混沌时刻 采样器=2m_sde_gpu
```

兼容别名：`采样器=dpm` 等同于 `采样器=2m`，`采样器=sde` 等同于 `采样器=2m_sde`，`采样器=gpu` 等同于 `采样器=2m_sde_gpu`。三个 DPM++ 预设的采样器名、步数、CFG 和调度器均可在 AstrBot 插件配置页分别修改；用户还可通过 `步数=` 和 `CFG=` 仅覆盖当前任务。这些参数必须位于真正的用户提示词之前。

## 随机提示词单抽

推荐指令：

```text
来张好图抄一抄 [来源组/级别组] [角色=名称] [画风=名称] [采样器=原有|2m|2m_sde|2m_sde_gpu] [步数=30] [CFG=6] [尺寸参数] [补充提示词]
```

兼容指令：

```text
来张好图抽一抽
/aimg_random
/抽一抽
/抄一抄
```

示例：

```text
来张好图抄一抄 D/N
来张好图抄一抄 C/H 角色=demo_character 画风=demo_style 雨夜
来张好图抄一抄 G 比例=1:1 校园
来张好图抄一抄 S 画风=demo_style
```

来源或级别代码必须紧跟在指令后，放在所有 `角色=`、`画风=` 等参数之前。

### 来源分组

| 代码 | 名称 | 用途 | 默认参与 |
|---|---|---|---|
| B | basic | 基础及审核汇总提示词 | 是 |
| G | generate | AI 批量生成测试提示词 | 是 |
| D | discord | Discord 公开分享提示词 | 是 |
| C | codex | “法典”提示词库 | 否，必须显式调用 |
| R | reverse | 未来反推保留库 | 否，当前暂无条目 |

### 内容级别

| 代码 | 名称 | 说明 | 默认参与 |
|---|---|---|---|
| N | normal | 正常至约 R15，含内衣或较大身体暴露 | 是 |
| H | nsfw | 完整裸体或无性行为的 R18 内容 | 是 |
| S | sexual | 性行为或性器官强调描写 | 否，必须显式调用 |

### 单独代码的含义

```text
来张好图抄一抄 B
```

表示只选 B 来源，级别使用默认 N/H，即 `B/N,H`。

```text
来张好图抄一抄 N
```

表示来源使用默认 B/G/D，只选 N，即 `B,G,D/N`。

```text
来张好图抄一抄 C
```

表示显式选择 C 来源，级别使用默认 N/H，即 `C/N,H`。

```text
来张好图抄一抄 S
```

表示从默认 B/G/D 来源中只选 S。C 组的 S 内容必须使用 `C/S`。

不填写任何分组时，实际范围为：

```text
B/G/D + N/H
```

## 五连抽

支持的指令：

```text
来张好图五连抽 [来源组/级别组] [其他参数] [补充提示词]
来张好图抄五张 [来源组/级别组] [其他参数] [补充提示词]
/aimg_random5 [来源组/级别组] [其他参数] [补充提示词]
/五连抽 [来源组/级别组] [其他参数] [补充提示词]
```

示例：

```text
来张好图五连抽 D/N 角色=demo_character 画风=demo_style
来张好图五连抽 C/H 比例=1:1
来张好图抄五张 B/N 尺寸=1280x960 雨夜
```

五连抽规则：

- 每次抽取五个不同的提示词 ID。
- 五张图按顺序逐张提交，适合单卡运行。
- 某一张失败不会阻止后续图片继续生成。
- 非管理员以发送者账号为单位计算 150 秒冷却。
- AstrBot 管理员不受五连抽冷却限制。
- 指令通过参数检查并成功抽取条目后开始计算冷却；即使后续生成失败，冷却仍然有效。
- 冷却记录保存在内存中，插件或 AstrBot 重启后会清空。

冷却时长可通过 `five_draw_cooldown_seconds` 配置调整，设为 `0` 可关闭。

## 混沌时刻

混沌时刻在每一张图开始前分别随机选择：

- 一个已有角色预设，包括 LoRA 角色和底模直出角色。
- 一个已有画风预设。
- 一个内置画面比例。
- 一条符合来源组和级别组条件的随机提示词。

单抽指令：

```text
来张好图混沌时刻 [来源组/级别组] [补充提示词]
/aimg_chaos [来源组/级别组] [补充提示词]
/混沌时刻 [来源组/级别组] [补充提示词]
```

五连抽指令：

```text
来张好图混沌五连抽 [来源组/级别组] [补充提示词]
来张好图混沌五连 [来源组/级别组] [补充提示词]
/aimg_chaos5 [来源组/级别组] [补充提示词]
/混沌五连 [来源组/级别组] [补充提示词]
```

示例：

```text
来张好图混沌时刻 D/N 雨夜
来张好图混沌五连抽 C/H
```

混沌五连沿用普通五连抽的非管理员 150 秒冷却。每一张会重新随机角色、画风和比例；用户写入的 `角色=`、`画风=`、`比例=`、`尺寸=` 会被混沌随机结果覆盖。若随机到 S 组保护角色，该张自动回退到 N/H，其他张不受影响。

混沌时刻至少需要一个角色预设和一个画风预设，否则会拒绝执行并提示先建立预设。

## 画布尺寸与比例

默认尺寸为：

```text
1024x1536
```

内置比例：

| 比例 | 实际尺寸 |
|---|---:|
| 1:1 | 1024×1024 |
| 2:3 | 1024×1536 |
| 3:2 | 1536×1024 |
| 3:4 | 960×1280 |
| 4:3 | 1280×960 |
| 9:16 | 864×1536 |
| 16:9 | 1536×864 |

示例：

```text
/aimg 比例=16:9 1girl, solo, cinematic landscape
来张好图抄一抄 D/N 比例=1:1
来张好图五连抽 B/N 尺寸=1280x960
```

自定义尺寸限制：

- 宽高分别介于 512 至 2048。
- 宽高都必须是 32 的倍数。
- 默认总像素上限为 `2359296`，约等于 `1536×1536`。
- 超出限制会在提交 ComfyUI 前返回参数错误。

## 角色预设

查看已有预设：

```text
/aimg_presets
```

### LoRA 角色

仅 AstrBot 管理员可以创建或覆盖：

```text
/aimg_role_set demo_character anima_lora/demo_character/demo_character.safetensors|1.0|1.0 --prompt demo_character, wings, angel, halo
```

LoRA 条目格式：

```text
文件名|model权重|clip权重
```

使用：

```text
/aimg 角色=demo_character 1girl, solo
来张好图抄一抄 D/N 角色=demo_character
```

### 底模直出角色

对于 Anima 底模可以直接识别、不需要 LoRA 的角色，可保存纯提示词预设：

```text
/aimg_role_text_set 角色名 --prompt character_name, fixed character tags
```

该预设被调用时只追加固定提示词，不创建角色 LoRA 节点。

## 画风预设

创建或覆盖画风预设，仅限 AstrBot 管理员：

```text
/aimg_style_set 雨夜 anima_lora/a.safetensors|0.6|0.6;anima_lora/b.safetensors|0.3|0.3 --prompt rainy night, wet ground --match #雨夜|#rainstyle
```

规则：

- 多个 LoRA 用英文分号 `;` 分隔。
- 每个条目格式为 `文件名|model权重|clip权重`。
- `--prompt` 设置调用该画风时自动添加的固定触发词。
- `--match` 使用 `|` 分隔一个或多个自动匹配字符串。
- `画风倍率=` 可以整体调整当前画风全部 LoRA 的强度。

### 动态画风加载

默认配置：

```text
style_lora_mode=dynamic
max_dynamic_style_loras=16
```

动态模式会在每次任务的内存工作流中创建标准 `LoraLoader` 链，不受原四槽数量限制，也不会修改磁盘上的工作流 JSON。

`style_lora_node_ids` 仍用于定位基础 MODEL/CLIP 接线。插件会在本次任务中旁路这些旧槽，并把动态链的最终 MODEL/CLIP 接回采样器以及正负提示词节点。

如需完全沿用旧四槽工作流，可设置：

```text
style_lora_mode=fixed
```

## S 组角色保护

在插件配置中找到：

```text
S 组禁用角色名单
```

多个角色可使用英文逗号、中文逗号、分号或换行分隔：

```text
demo_character
demo_character_2
lunawolf
```

角色名按不区分大小写的精确名称匹配。若角色存在多个别名，应把每个可用别名都加入名单。

当受保护角色请求 S 组时：

```text
来张好图抄一抄 C/S 角色=demo_character
```

插件会保留 C 来源，但把内容级别强制改为 N/H，并向用户说明保护规则已生效。

## 删除预设

仅 AstrBot 管理员可以删除：

```text
/aimg_preset_del 画风 雨夜
/aimg_preset_del 角色 demo_character
```

英文类型也可使用：

```text
/aimg_preset_del style 雨夜
/aimg_preset_del role demo_character
```

## 触发词查询与在线维护

查看类指令允许普通用户使用。无论指令来自私聊还是群聊，实际内容统一发到调用者私聊；群内只显示一条发送成功回执。

```text
/aimg_trigger_list
/aimg_trigger_list 画风
/aimg_trigger_list 角色
/aimg_trigger_show 画风 demo_style
/aimg_trigger_show 角色 demo_character
```

`aimg_trigger_show` 会显示固定 `prompt`、画风自动匹配 `match` 以及对应 LoRA 文件和权重。

修改已有触发词仅限 AstrBot 管理员：

```text
/aimg_trigger_set 画风 demo_style prompt demo_style, artist style
/aimg_trigger_set 画风 demo_style match demo_style|@demo_style
/aimg_trigger_set 角色 demo_character prompt demo_character, wings, angel, halo
```

画风 `match` 的多个匹配串用 `|` 分隔。角色没有 `match` 字段，只使用 `prompt` 固定串。

清空字段或删除整个预设同样仅限管理员：

```text
/aimg_trigger_del 画风 demo_style prompt
/aimg_trigger_del 画风 demo_style match
/aimg_trigger_del 角色 demo_character prompt
/aimg_trigger_del 角色 demo_character all
```

`all` 会删除整个角色或画风预设，效果等同于 `/aimg_preset_del`。

## 提示词库自助管理

### 查询与单条查看

普通用户可分页查询。结果统一私聊发送，每页 10 条：

```text
/aimg_pool_list
/aimg_pool_list B
/aimg_pool_list D/H
/aimg_pool_list C/N 3
/aimg_pool_list D/N 1 rainy street
```

参数顺序为：`[来源/级别] [页码] [关键词]`。筛选代码可以只写 `B` 或 `N`，不写时查询全部来源和全部级别。

查看一条完整记录：

```text
/aimg_pool_show good-001
```

### 导出复制

```text
/aimg_pool_export
/aimg_pool_export D/H
/aimg_pool_export C/N rainy
```

插件会生成带 `prompts` 数组的 JSON，并通过 QQ 私聊文件发送。NapCat 若拒绝文件发送，插件会保留服务器文件并返回绝对路径。

### 添加、修改和停用

以下写操作全部仅限 AstrBot 管理员：

```text
/aimg_pool_add B/N 1girl, solo, rainy street, holding umbrella
/aimg_pool_set good-001 1girl, solo, new prompt
/aimg_pool_set good-001 D/H 1girl, solo, revised prompt
/aimg_pool_enable good-001 off
/aimg_pool_enable good-001 on
```

添加时必须同时指定一个来源组和一个级别组。修改时若省略 `B/N`，会保留原分组。

### 整条删除

```text
/aimg_pool_del good-001
```

删除仅限管理员。条目会从主池移除，同时：

- 原记录写入 `prompt_pool_trash.json`，便于人工恢复。
- ID 写入主池的 `deleted_prompt_ids` 墓碑列表。
- 后续插件提示词库升级不会把已删除的内置 ID 自动加回来。
- 每次修改前会在 `prompt_pool_backups` 目录自动保存主池快照。

### 批量导入

先把 JSON 上传到服务器，再由管理员执行：

```text
/aimg_pool_import /workspace/imports/new_prompts.json
```

导入文件可以是 JSON 数组，也可以是包含 `prompts` 数组的对象。每条至少需要 `prompt`；推荐同时提供 `id`、`source_code` 和 `safety_code`。缺省分组为 `B/N`，ID 缺失或冲突时会自动生成新 ID。

## 提示词拼接顺序

随机好图生成时，主要拼接顺序为：

1. 全局正向前缀与通用质量词。
2. 画风固定触发词。
3. 角色固定触发词或底模角色串。
4. 用户补充提示词。
5. 随机抽中的提示词。
6. 全局正向后缀。

随机指令未指定画风时，会旁路工作流中的画风 LoRA 槽位；未指定角色时，不创建角色 LoRA 节点。

普通 `/aimg` 未指定画风时，会保留基础工作流当前的 LoRA 构成。

## 0.2.10 内置提示词库统计

| 项目 | 原始记录 | 启用记录 |
|---|---:|---:|
| 全部 | 7471 | 7389 |
| B | 450 | 389 |
| G | 300 | 300 |
| D | 2005 | 2001 |
| C | 4716 | 4699 |
| R | 0 | 0 |
| N | 4324 | 4256 |
| H | 1306 | 1297 |
| S | 1841 | 1836 |

`/aimg_status` 中的“来源组记录”和“级别组记录”显示原始记录数；其中重复记录会保留但处于禁用状态。

## 重要配置

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `comfyui_base_url` | `http://127.0.0.1:8188` | ComfyUI API 地址 |
| `workflow_path` | `/workspace/ComfyUI/user/default/workflows/anima_custom_flow_api.json` | API 工作流路径 |
| `preset_store_path` | `.../plugin_data/.../presets.json` | 角色和画风预设存储路径 |
| `prompt_pool_path` | `.../plugin_data/.../anima_random_prompt_pool.json` | 持久化提示词池路径 |
| `sexual_protected_characters` | 空 | S 组禁用角色名单 |
| `five_draw_cooldown_seconds` | `150` | 非管理员五连抽冷却 |
| `latent_node_id` | `28` | 画布节点 |
| `default_width` / `default_height` | `1024` / `1536` | 默认画布尺寸 |
| `max_canvas_pixels` | `2359296` | 最大画布总像素数 |
| `dpm_sampler_*` | `dpmpp_2m` / `30` / `6` / `normal` | DPM++ 2M 预设 |
| `dpm_2m_sde_sampler_*` | `dpmpp_2m_sde` / `30` / `6` / `normal` | DPM++ 2M SDE 预设 |
| `dpm_2m_sde_gpu_sampler_*` | `dpmpp_2m_sde_gpu` / `30` / `6` / `normal` | DPM++ 2M SDE GPU 预设 |
| `style_lora_mode` | `dynamic` | 动态链或旧固定槽模式 |
| `max_dynamic_style_loras` | `16` | 单个画风最大 LoRA 数 |
| `max_concurrency` | `1` | 同时生成任务数，单卡建议为 1 |
| `timeout_seconds` | `300` | 单次生成超时 |
| `max_images` | `4` | 单个 ComfyUI 任务最多返回图片数 |

## 数据持久化

默认预设文件：

```text
/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge/presets.json
```

默认提示词池：

```text
/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge/anima_random_prompt_pool.json
```

提示词回收站、自动备份和导出文件默认位于同一目录：

```text
prompt_pool_trash.json
prompt_pool_backups/
exports/
```

这两个文件位于插件目录之外，覆盖升级插件时不会被直接替换。

当安装包内的 `catalog_revision` 更高时，插件会增量合并新条目：

- 通常保留持久化池中同 ID 条目的用户修改。
- 0.2.9 对重新整理并重新编号的 D 来源目录执行整组替换；自定义的非 `discord-*` ID 仍会保留。
- 尊重 `deleted_prompt_ids` 删除墓碑，不重新加入管理员已删除的内置条目。
- 添加安装包中新增的条目。
- 更新必要的分组与路由元数据。
- 迁移前自动生成提示词池备份。

正式升级前仍建议手动备份整个 `plugin_data/astrbot_plugin_comfy_bridge` 目录。

## 状态检查

发送：

```text
/aimg_status
```

正常情况下可以看到：

- ComfyUI 连接地址。
- 当前 API 工作流路径。
- 节点数、输出节点和 LoRA 节点。
- 画风加载模式和预设数量。
- 提示词池总数、来源组与级别组。
- S 组保护角色数量。
- 默认画布和画布节点。
- 五连抽冷却时间。

## 常见问题

### 插件配置页没有新字段

1. 确认插件目录中的 `metadata.yaml` 显示正确版本。
2. 确认 `_conf_schema.json` 包含对应字段。
3. 完整重启 AstrBot，而不只是重载插件。
4. 浏览器按 `Ctrl+F5` 强制刷新。

### 群内查询后没有收到私聊

- 先主动私聊机器人发送任意一条消息，让 NapCat/AstrBot 建立好友私聊会话。
- 确认 QQ 账号允许机器人向该用户发起私聊。
- 查询目标按 `平台实例ID:FriendMessage:发送者QQ` 构造，只会发给指令调用者。
- 如果主动私聊失败，可直接在与机器人的私聊中重新执行查询或导出指令。

### 提示“所选范围暂无可用提示词”

- R 组当前为空。
- 检查是否写了不存在的来源/级别组合。
- C 和 S 都必须显式触发；例如 C 组性内容应写 `C/S`。
- 受保护角色请求 S 时会自动回退到 N/H。

### 工作流 JSON 无效

必须使用 ComfyUI 的 **Save (API Format)** 导出。普通界面工作流通常含有 `nodes`、`links`，不能直接提交给 `/prompt` API。

### 更换工作流后尺寸或提示词没有变化

检查以下节点 ID 是否与新工作流一致：

```text
positive_prompt_node_id
negative_prompt_node_id
sampler_node_id
latent_node_id
style_lora_node_ids
```

### 动态 LoRA 节点 ID 冲突

如果工作流已经使用 `900100` 及其后续 ID，请把 `dynamic_style_node_id_start` 改到一段未使用的数字区间。

### 五连抽正在冷却

冷却按发送者账号计算，不按群号计算。管理员身份来自 AstrBot 管理员 ID 配置，不等同于 QQ 群管理员。

### ComfyUI 生成超时

- 检查 ComfyUI 是否仍在 `8188` 监听。
- 检查 GPU 显存与任务队列。
- 五连抽会依次执行五次完整工作流，耗时约为单张的五倍。
- 必要时提高 `timeout_seconds`，但应先确认任务没有实际报错。

## 尚未发布的功能

- `/aip` 高质量图片反推与 60 秒图片等待流程。
- `/aicn` 中文提示词转换。
- R 反推提示词库。
- 多人图工作流分流。

这些功能将在反推模型、节点和独立 API 工作流完成质量验证后加入后续版本。
