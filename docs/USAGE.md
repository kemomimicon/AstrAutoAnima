# 使用手册

以下命令以插件 `0.5.0-beta.1` 为准。具体启用范围仍受 AstrBot 管理员、白名单、群聊规则和
插件配置控制。

## 状态与帮助

```text
/aimg_status
/aimg_manage_help
/aimg_presets
```

`/aimg_status` 应显示 ComfyUI 连通性、工作流路径、节点、LoRA 槽和当前配置。

## 普通生图

```text
/aimg [角色=名称] [画风=名称] [采样器=原有|2m|2m_sde|2m_sde_gpu] \
      [步数=30] [CFG=6] [比例=2:3] [尺寸=1024x1536] <英文提示词>
```

示例：

```text
/aimg 角色=demo_character 画风=demo_style 比例=2:3 采样器=2m_sde 步数=30 CFG=6 1girl, solo, rainy street
```

- `原有` 保留工作流采样器；其余选项会改写 sampler 节点。
- `比例` 使用预设画布，`尺寸` 明确覆盖宽高。
- 角色/画风预设不存在时，行为取决于插件解析策略；上线前用测试角色验证。

## 中文生图

```text
/aicn [角色=名称] [画风=名称] <中文描述>
```

该功能需要 AstrBot 当前会话或插件配置中的文本 LLM Provider。它先把中文转成适合 Anima 的
英文标签，再进入生图。未配置 Provider 时不会凭空具备翻译能力。

## 图片反推

```text
/aip [模式=完整|场景|动作|角色|安全|原始] [角色=名称] [画风=名称]
/aip 仅反推 分类=场景,动作,构图 [角色=名称] [画风=名称]
```

发送命令后 60 秒内在同一私聊/群聊发送图片，插件只捕获第一张。`仅反推` 返回文本而不跑图；
`分类=` 可复选场景、动作、角色、外观、服装、构图、其他。角色/画风预设会作为生成阶段附加
条件，不应污染原始反推记录。

反推工作流使用 WD/CL/JoyCaption 与 `AnimaReverseCompiler`。每次结果写入反推历史，安全等级
始终独立检测。反推结果只是机器推断，应人工复核后再导入提示词池。

## HQ 与已有图精修

```text
/ahq [stable|beauty] [角色=名称] [画风=名称] [放大=1.25] [重绘=0.28] <提示词>
/arefine [light|medium] [任务=job_xxx] [放大=1.25] [重绘=0.25] [补充提示词]
/ajob job_xxx
```

- `stable` 更保守；`beauty` 默认更多步数与更大放大率。
- `/arefine` 可引用已有任务，或按 Bot 提示发送第一张图片。
- `重绘` 越高变化越大；放大修复不是无损放大。
- HQ/Refine 是 Beta，Detailer/Tile 默认关闭。

## 随机好图

公开包提示词池为空，必须先导入自己的审核库。

```text
来张好图抄一抄 [来源/级别] [角色=名称] [画风=名称] [补充提示词]
来张好图五连抽 [来源/级别] [其他参数]
来张好图混沌时刻 [来源/级别] [补充提示词]
来张好图混沌五连抽 [来源/级别]
```

自定义分组使用 `@分组ID`，多个分组用 `+` 连接并要求同时匹配。例如：

```text
来张好图抄一抄 @rain
来张好图五连抽 B/N @rain+night 角色=示例角色
来张好图混沌时刻 @portrait
```

自定义分组可与固定来源/级别组合，前后顺序均可。分组由本地提示词库管理器创建；旧版库
没有 `custom_groups` 字段时仍可直接使用。

来源组：

- `B` basic；`G` generate；`D` discord，默认可抽。
- `C` codex；`R` reverse，只在显式指定时抽取。

安全组：

- `N` normal；`H` nsfw，默认可抽。
- `S` sexual，只在显式指定时抽取。

例如 `C/H` 表示只从 C 来源的 H 条目抽取。单独 `B` 或 `N` 均支持。普通五连抽默认每名普通用户最多一个活动任务，结束即可再次调用；混沌五连仍有 150 秒冷却。
混沌模式每张重新随机角色、画风和比例，要求至少各有一个角色/画风预设。

将不允许进入 S 组的 OC 名称填入插件配置 `sexual_protected_characters`；显式请求 S 时会回退
到 N/H。标签和回退是项目路由规则，不替代人工内容审核。

## 角色与画风预设

LoRA 角色：

```text
/aimg_role_set demo_character loras/demo_character.safetensors|1.0|1.0 --prompt demo_character, character tags
```

底模直出角色：

```text
/aimg_role_text_set 角色名 --prompt character_name, fixed character tags
```

画风组合：

```text
/aimg_style_set 水彩 loras/a.safetensors|0.6|0.6;loras/b.safetensors|0.3|0.3 --prompt watercolor --match #水彩|#watercolor
```

删除预设需要管理员权限：

```text
/aimg_preset_del 角色 demo_character
/aimg_preset_del 画风 水彩
```

## 触发词维护

查询结果会尽量私聊，避免刷群：

```text
/aimg_trigger_list [角色|画风]
/aimg_trigger_show 角色 demo_character
/aimg_trigger_set 角色 demo_character prompt demo_character, character tags
/aimg_trigger_set 画风 水彩 match #水彩|#watercolor
/aimg_trigger_del 画风 水彩 match
```

删除与修改需要管理员权限。若 Bot 无法主动私聊群成员，先与 Bot 建立私聊或检查平台限制。

## QQ 内提示词库管理

```text
/aimg_pool_list [B/N] [@自定义分组] [页码] [关键词]
/aimg_pool_show <ID>
/aimg_pool_export [D/H] [关键词]
/aimg_pool_add B/N <提示词>
/aimg_pool_set <ID> [B/N] <新提示词>
/aimg_pool_enable <ID> <on|off>
/aimg_pool_del <ID>
/aimg_pool_import <服务器 JSON 绝对路径>
```

查看/导出尽量私聊；添加、修改、启停、删除、服务器导入均要求管理员。批量维护更推荐使用
[本地工具](TOOLS.md)，先备份后再把 JSON 上传服务器。

## Hub 与客户端

Hub 管理员可维护全部预设、提示词和任务；普通令牌只获得绑定账号允许的能力。客户端支持：

- 连接检测和服务状态。
- Quick/HQ/Refine/Reverse 任务提交。
- 提示词与预设管理（取决于令牌权限）。
- 任务历史、图片预览与保存。
- Android 自选保存目录；Windows 使用系统保存对话框或配置目录。

返图成功但本地没有图片时，先确认任务记录的 `attachment_saved`、Hub 版本与客户端写入权限，
再参考[排错手册](TROUBLESHOOTING.md)。
