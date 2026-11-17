# 下一版：Turbo、角色画廊、多人预设与 SnapRef

开发分支：`codex/next-turbo-gallery-multi-snapref-20261117`。

这次新增四个入口，继续使用现有 AstrBot 接单、生成队列、内容审核、任务记录和 QQ 返图链路。管理端与服务端需一起更新；发布版本号将在整版验收后统一确定。

| 功能 | QQ 入口 | 管理端入口 |
| --- | --- | --- |
| Anima Turbo | `/aturbo` | 跑图方式 → Anima Turbo |
| SnapRef 参考生图 | `/aref char`、`/aref cs` | 跑图方式 → 参考生图 SnapRef |
| 角色预设多人图 | `/amulti 预设`、`/amulti 预览` | 跑图方式 → 多人图；画廊可复制双人指令 |
| 角色画廊 | 使用卡片对应的角色预设名称 | 画风画廊 → 角色画廊 |

新增管理端生成方式使用 AstrBot 执行。Start-Local 的独立执行器继续提供其原有跑图方式。

## 工作流安装与配置

插件已内置以下 API 工作流，完整源码中的 `comfyui/workflows/` 也包含相同副本：

| 文件 | 可选的插件配置项 | 默认采样 |
| --- | --- | --- |
| `Anima_Turbo_api.json` | `turbo_txt2img_anima_path` | Euler / simple，10 步，CFG 1 |
| `Anima_SnapRef_api.json` | `snapref_anima_path` | er_sde / normal，34 步，CFG 4.5 |
| `Anima_Preset_Multi_api.json` | `preset_multi_anima_path` | er_sde / normal，34 步，CFG 4.5 |

路径留空时使用内置模板。若模型文件名或节点需要调整，将对应模板复制到自己的工作流目录，编辑后在配置项填写该副本路径。三个模板分别注册，已有的 Quick/HQ/精修配置保持原样。旧 Registry 中没有新 ID 时，插件从附加 Registry 读取新定义，无需改写用户 Registry。

默认模型文件位置：

```text
ComfyUI/models/diffusion_models/anima-base-v1.0.safetensors
ComfyUI/models/diffusion_models/anima-turbo-v1.1.safetensors
ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors
ComfyUI/models/vae/qwen_image_vae.safetensors
```

基础多人图、SnapRef 使用 Anima base；Turbo 使用独立 Turbo 模型。模型由使用者按各自许可下载，更新代码不会自动下载或替换权重。

## Anima Turbo

```text
/aturbo 1girl, reading a book, warm afternoon light
```

```text
/aturbo 角色=我的角色 画风=我的画风 步数=10 CFG=1 a garden, full body
```

保留角色造型、画风、比例等现有参数用法。默认采用 Turbo 模板参数；普通生成的全局 30 步、CFG 5 等配置不会覆盖它。显式设置其他 CFG 会提示改为 1。

Turbo 模型定位、推荐步数和 CFG 依据 [Anima 官方模型页](https://huggingface.co/circlestone-labs/Anima)。本次先提供单段快速生图，二段采样作为后续独立工作流评估。

## SnapRef：`/aref`

实现对接 [ArcAnima/SnapRef](https://github.com/ArcAnima/SnapRef)，节点契约核对版本为 [`87bdacd`](https://github.com/ArcAnima/SnapRef/tree/87bdacd94cdb7a1ff8f8a0bbbddf6e517758bbd8)。AAA 调用其 ComfyUI 节点；本仓库不打包上游实现或模型权重。上游代码使用 Apache-2.0，模型权重以其发布页列出的适用许可为准。

1. 按上游 README 将 `comfyui_nodes/snapref/` 安装到 `ComfyUI/custom_nodes/snapref/`，在 **ComfyUI 使用的 Python 环境**中安装上游要求的依赖，然后重启 ComfyUI。
2. 下载上游发布的 `snapref_v2a.safetensors`，放到 `ComfyUI/models/loras/`。虽放在 loras 目录，它需要 **SnapRef Advanced** 节点，不能作为普通 LoRA 加载。
3. 在 ComfyUI 打开 `Anima_SnapRef_api.json`，确认 `SnapRef Advanced` 可用、适配器名称正确。
4. 在 QQ 引用参考图，或将图片和命令一起发送：

```text
/aref char sitting beside a window, gentle morning light
```

```text
/aref cs full body, walking through a flower garden
```

`char` 参考角色身份，`cs` 同时参考角色和画风。省略模式默认 `char`。首版每次使用一张参考图，提示词填写目标动作、构图与场景。管理端选择同名跑图方式、上传参考图并填写提示词即可。

本模式使用参考图提供身份，不叠全局角色/画风预设。模板的 `strength=0` 是上游对数强度的默认值，不是普通 LoRA 的“权重关闭”。可在专用工作流副本中调整参考参数。

任务会保存参考图资产和完整工作流。引用结果使用不带修改的 `/aremake` 可按记录重跑；SnapRef 重跑会核对原始参考图内容并重新上传，不依赖旧的 ComfyUI 临时输入名。新模式的文字修改重跑另行安排，使用 `/aturbo`、`/aref` 或 `/amulti 预设` 提交新的描述即可。

## 多人预设与最终提示词预览

先准备已有角色预设，例如“角色甲”“角色乙”。英文触发词和详细外貌保存在预设或独立特征档案中，命令里的预设名可以是中文。

```text
/amulti 预览
人物1：角色甲 | | standing on the left, holding a book
人物2：角色乙 | | sitting on the right, waving
场景：a quiet garden, soft daylight
互动：looking at each other
```

预览只返回最终提示词。确认后，把第一行改为 `/amulti 预设` 即可生成。

```text
/amulti 预设 比例=3:2
人物1：角色甲 | | standing on the left, holding a book
人物2：角色乙::winter_coat | | sitting on the right, waving
场景：a quiet garden, soft daylight
互动：looking at each other
```

`::winter_coat` 是造型 ID，使用对应造型的完整提示词替换默认服装。人物行格式为 `预设名 | 本次补充外貌 | 本次动作、服装或位置`，两边的 `|` 保留，补充部分可以为空。

支持 2–4 人。每个人物的触发词、外貌和动作以逗号连接、句号结束，段落之间空行；最后追加总人数、互动和场景。不经过自动改写。现有手写 `/amulti` 和 `/amulti 自动` 仍按原用法工作。

人物预设的 LoRA 按人物顺序接入，并保存各自的预设、特征和权重快照。它们作用于同一模型；人物归属由分段提示词引导，不代表区域蒙版绑定。建议先用双人、清楚的左右位置进行实图调整。

## 角色画廊与独立特征

1. 管理端进入“画风画廊 → 角色画廊 → 添加角色卡”。
2. 填写当前角色预设完整名称及造型 ID；默认造型填 `default`。
3. 可以导入“双人特征实验室” `profiles/` 中的单个人物 JSON。档案中的耳种、形状、内外颜色、尾巴、发眼颜色等细节按原样保存，只使用已确认字段。
4. 封面可从已完成的 Hub 任务保存：同时填写任务 ID 与图片 ID。封面沿用已有图片审核规则。
5. 勾选“向已登录用户展示此卡片”并保存。只有已展示卡片中的已确认特征参与预设多人图；草稿留给管理员继续整理。
6. 选择两张已展示角色卡，点击“复制双人预览指令”，粘贴到 QQ 后补充场景和动作。

特征与封面放在实际 `presets.json` 同目录的 `character_gallery/`，与原预设分开。首次读画廊不写数据；保存时先备份旧目录清单，再原子替换新清单。保存失败时编辑框保留输入。角色原提示词或 LoRA 变化后，需要重新读取该预设、核对特征并保存。

不会改写模型、词库、令牌或现有角色预设。

## 本轮开发验收

本地已覆盖新指令、工作流参数、参考图上传、参考图重跑恢复、人物分段与造型替换、特征草稿/确认、封面权限、保存冲突及管理端交互；具体测试记录见 [开发验收记录](NEXT_ANIMA_ACCEPTANCE.md)。

下一步整版实图验收：Turbo 8/10/12 步对比；SnapRef char/cs 对比；双人、双人 LoRA、四人及固定种子重跑；Windows/QQ 和 Linux/Hub 各走一次。验收后统一更新版本号和发布包。
