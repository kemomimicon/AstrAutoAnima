# AstrAutoAnima 0.5.0 Beta：安装后的首次配置与个人服务起步

适用：公开发行 **0.5.0-beta.2**，Windows／Linux 部署，Windows／Android／Web 客户端。本文按本版实际代码和界面编写，2026-09-23 核对。

目标：先让自己通过 App 成功生成、查看并保存一张图，再开放给群友。不要第一步同时测试随机五连、反推、HQ 和所有 LoRA。

不想手改配置文件？新增的 [首次使用配置向导](FIRST_RUN_WIZARD.md) 提供六步中文界面，可配置本机懒人包安装后的连接、投递群、普通用户令牌和词库。Windows 双击版无需另装 Python；远程无桌面服务器暂不支持直接写配置，请按本文相应步骤操作。

## 0. 总顺序与三类密钥

**启动服务 → 确认 QQ 与普通生图 → 配好 Hub 到 AstrBot 的授权 → 管理端连接 → 投递目标 → 用户令牌 → 导入词库 → 用户端验收。**

先分清三个凭据，不能混填：

| 凭据 | 在哪里生成／保存 | 填到哪里 | 给谁 |
| --- | --- | --- | --- |
| Hub 管理员令牌 | 懒人包在安装目录 `runtime-env.json` 的 `AAH_ADMIN_TOKEN` 自动生成 | Admin 管理端连接页“管理员令牌” | 仅服务所有者 |
| Hub 普通用户令牌 | Admin 的“用户”页添加用户时生成，服务端注册表仅存哈希 | Service 用户端连接页“用户令牌” | 每人自己的独立令牌 |
| AstrBot OpenAPI Key | AstrBot WebUI 的 OpenAPI 设置 | Hub 的 `AAH_ASTRBOT_API_KEY` | 仅服务端使用，不发群友 |

**AstrBot 管理员 UID 又是另一套权限**：QQ 中执行 `/aimg_pool_import` 等管理员指令，需要 AstrBot 识别该发送者为管理员；仅拥有 Hub 管理员令牌不会把 QQ 账号自动设为 AstrBot 管理员。

## 1. 找到真正生效的配置目录

### 使用懒人包部署

找到当初选择的**安装目录**，不是 ZIP 下载目录，也不是整合包解压目录。里面应已有：

```text
安装目录/
  Start.cmd 或 Start.sh
  runtime-env.json
  services.json
  下一步.txt
  Hub.log
```

日志在服务启动后生成。新装 AstrBot 通常位于该目录的 `astrbot/`；如果接入了已有 AstrBot／Desktop，就使用其真实数据目录，不能假定都在这里。

1. 先用编辑器私下打开 `runtime-env.json`，不要把整个文件发给别人。
2. 记下 `AAH_PLUGIN_DATA_DIR` 的值，后文称它为 **P**。
3. P 通常是实际 AstrBot `data/plugin_data/astrbot_plugin_comfy_bridge`，不能误用 `data/plugins/astrbot_plugin_comfy_bridge`——后者是插件代码目录。
4. 检查插件配置页的 `prompt_pool_path`、`preset_store_path` 与 Hub 指向相同的数据文件。

默认对应关系：

| 数据 | 默认位置 | Hub 自定义覆盖字段 |
| --- | --- | --- |
| 随机词库 | `P/anima_random_prompt_pool.json` | `AAH_PROMPT_POOL_PATH` |
| 角色／画风预设 | `P/presets.json` | `AAH_PRESET_PATH` |
| 投递群和管理员私聊目标 | `P/hub_state/delivery_targets.json` | `AAH_DELIVERY_TARGETS_PATH` |
| 用户及令牌哈希 | `P/hub_state/lite_users.json` | `AAH_LITE_USERS_PATH` |

如果已有覆盖字段，以覆盖字段为准。Hub 与插件读不同词库，会表现为“App 已导入，QQ 却抽不到”。本版 QQ 返图回执和部分任务关联依赖共享的 P；首次建议 Hub 与 AstrBot 同机并读同一目录，不要只改 URL 就把它们任意拆到两台机器。

### 手动部署

Hub 直接读取**进程环境变量**。仅创建 `.env` 不一定生效；需要自己的启动脚本／服务管理器加载它。懒人包的 Start 入口会读取 `runtime-env.json` 并传给服务。不要同时维护两份互相冲突的配置。

### 修改配置后的生效规则

- 改 `runtime-env.json` 中的令牌、地址、路径或 Bot ID 后，必须**正常重启实际运行的 Hub**。
- **双击 Start 不等于重启**：已占用端口时它会复用现有服务，旧进程不会自动加载新环境变量。
- 用原服务管理方式停止确认过的 Hub，再用原 Start 入口拉起；不要按进程名批量结束所有 Python。
- 在 App 中增删用户、换发令牌一般下一请求即生效，不需要重启。投递目标内容也是请求时读取，修改后重新进入／刷新跑图页面；修改目标文件的配置路径则需重启 Hub。

## 2. 确认基础服务与英文生图

1. 用安装目录 `Start.cmd` 或 `sh Start.sh` 启动。若是 AstrBot Desktop，请手动打开桌面程序。
2. 在服务所在电脑打开：
   - AstrBot：`http://127.0.0.1:6185`，进入自己的管理页面。
   - ComfyUI：`http://127.0.0.1:8188/system_stats`，应返回 JSON。
   - Hub：`http://127.0.0.1:6278/api/v1/health`，应包含 `service: astr-auto-anima-hub`、版本及 `status: ok`。
3. 确认 NapCat 已登录；AstrBot 平台连接在线，机器人已经加入用于测试的群，未禁言。
4. 确认 AAA 插件和 Anima Master **0.7.1** 成功加载；0.9.1 未联调。AM 的配置细节见 [ANIMA_MASTER.md](ANIMA_MASTER.md)。
5. 确认普通 API 工作流中的 UNET／CLIP／VAE 与实际模型匹配。使用向导默认模型时，普通工作流为 `AAA_Quick_Local_api.json`；不是任意 UI 工作流 JSON 都能直接替代 API JSON。
6. 在 QQ 向机器人发送：

```text
/aimg_status
/aimg 1girl, solo, standing, fully clothed, park, daylight
```

此时先不指定角色、画风或高级工作流。如 `/aimg` 被其他插件接管，在 AstrBot 中检查指令冲突。没配置 LLM 时先别用 `/aicn`；普通英文生图不等于中文转换或反推模型已准备好。

**验收：QQ 收到一张普通图。** 只有健康接口通过不代表模型推理通过。未开显卡时可先做配置和连接检查，生图留到 GPU 可用后。

## 3. Hub 到 AstrBot：API Key 和 Bot ID

### 3.1 创建 OpenAPI Key

在 AstrBot WebUI 的“设置 → OpenAPI”创建专供 Hub 使用的 Key。按本机 `/api/v1/docs` 的 Required scope 开通实际接口权限：会话 `chat`、附件 `file`、主动消息／平台查询 `im` 是本项目相关能力；不要为省事默认给所有管理权限。某些状态查询可能还需要对应只读权限，以本机文档和明确的 403 提示为准。[AstrBot 官方 OpenAPI 说明](https://docs.astrbot.app/dev/openapi.html)

把 Key 填入 `AAH_ASTRBOT_API_KEY`。它不是 AstrBot WebUI 登录密码，也不是 Hub 管理员令牌。本文不给出真实 Key 示例。

### 3.2 获取正确的 Bot ID 与 UMO

在测试群里向机器人发送 `/sid`；在自己的机器人私聊里也发送一次。根据回复记录：

- `Bot ID`：AstrBot 的平台实例 ID，填写到 `AAH_ASTRBOT_BOT_ID`。
- `UMO`：当前会话的完整路由，稍后用于投递目标。
- `UID`：你自己的身份标识，可用于 AstrBot 管理员配置。

**Bot ID 不等于机器人 QQ，也不等于群号。** 不要凭习惯猜成 `aiocqhttp`；复制实际实例值。若 `/sid` 在你的版本不可用，使用 AstrBot 的平台配置、会话信息或带授权的 `GET /api/v1/im/bots` 核对。[官方 `/sid` 说明](https://docs-v4.astrbot.app/en/use/command.html)

常见路由形态：

```text
平台实例ID:GroupMessage:群号
平台实例ID:FriendMessage:用户QQ
```

群开启独立会话后，回显会话可能包含额外标识；投递群要核对真实群 ID，使用本版支持的三段群路由，不把“群+个人”的会话标识当群号。

### 3.3 保存并重启 Hub

私下编辑 `runtime-env.json` 中已有字段，保留其他设置：

```text
AAH_ASTRBOT_URL      AstrBot 从 Hub 所在环境可访问的地址
AAH_ASTRBOT_API_KEY  刚创建的 Key
AAH_ASTRBOT_BOT_ID   实际平台实例 ID
AAH_COMFYUI_URL     ComfyUI 从 Hub 所在环境可访问的地址
```

JSON 所有环境值使用字符串，注意逗号、双引号；不要把此字段清单当成完整 JSON 覆盖原文件。改完正常重启 Hub。容器内 `127.0.0.1` 是当前容器，不是另一容器或宿主机。

## 4. 首次连接管理端与管理员令牌

### 4.1 使用已有管理员令牌

1. 从安装目录 `runtime-env.json` 读取 `AAH_ADMIN_TOKEN`。懒人包首次部署已经生成，无需再生成一份。
2. 完整解压 Windows Admin 包，或安装 Android Admin；也可打开 Hub 提供的 Web 页面。
3. 连接页选择“管理端”（若使用固定 Admin 构建，可能无须选择模式）。
4. “工作站地址”填 Hub 根地址，如同机 `http://127.0.0.1:6278`，**不要填 6185、8188，也不要添加 `/api/v1/health`**。
5. “管理员令牌”仅粘贴令牌本身，不含引号或 `Bearer ` 前缀。
6. 点击“连接”，进入“概览”；应能看到“提示词”“预设”“用户”等管理页面。

### 4.2 手机或其他电脑连接

手机上的 `127.0.0.1` 是手机自己。懒人包默认 Hub 只监听回环地址，**仅把手机地址换成电脑 IP 仍可能连不上**。

推荐通过可信 VPN 或 HTTPS 反向代理连接。若仅在受信任家庭局域网使用，可让 Hub 绑定服务器实际局域网地址，并只在防火墙允许该可信网段访问 6278；改监听地址后重启 Hub。不要为此开放 AstrBot／ComfyUI 管理端，更不要把含令牌的服务直接裸露到公网。

### 4.3 没有令牌或需要轮换

仅在私密的本机终端生成，不要在直播、群聊或公开日志中运行：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把生成值填进 `AAH_ADMIN_TOKEN`，正常重启 Hub，再更新自己的 Admin 连接配置。要求至少 32 字符；建议使用上述随机值，不用 QQ 号或常用密码。

当前“用户”页管理的是普通用户令牌，**不是管理员主令牌**。管理员令牌泄漏后必须轮换；不要只停用某个普通用户。

## 5. 配置投递群和管理员私聊

### 5.1 当前入口

本版 App 可以选择“返图目标”，但**没有投递目标的增删改界面**。目标由 Hub 读取 JSON 文件，不能在 App 下拉框里直接手写群号。

默认编辑 `P/hub_state/delivery_targets.json`。父目录不存在时创建该目录；文件已存在则先备份并合并目标，不要直接覆盖原目标列表。保存为 UTF-8 JSON，确认扩展名不是 `.json.txt`。

以下号码与实例 ID 均为演示占位值，必须换成自己的真实信息：

```json
{
  "targets": [
    {
      "id": "test-group",
      "label": "我的测试群",
      "kind": "group",
      "umo": "examplebot:GroupMessage:123456789",
      "allow_safety": ["N"],
      "enabled": true
    },
    {
      "id": "owner-private",
      "label": "我的管理员私聊",
      "kind": "private",
      "umo": "examplebot:FriendMessage:987654321",
      "allow_safety": ["N"],
      "enabled": true
    }
  ]
}
```

- `id`：稳定且不重复的内部名称，推荐英文、数字和连字符；不能使用保留 ID `self-private`。
- `label`：App 中显示的名称。
- `kind`：群为 `group`，私聊为 `private`，必须与 UMO 对应。
- `umo`：实际投递地址；优先核对 `/sid`，不是只填群号。
- `allow_safety`：允许的等级。本例首次只允许 N；该标签不是自动内容安全保证。群目标即使手工写入 S，本版仍拒绝 S 群投递。
- `enabled: false`：临时隐藏该目标，避免误投递。

多加一个群，就在 `targets` 数组再加一项，注意中间逗号。不同机器人平台的目标必须使用各自正确的实例 ID。

如果选择自定义文件位置，在 `runtime-env.json` **新增或修改一个键**：

```json
"AAH_DELIVERY_TARGETS_PATH": "D:/AAA-private/delivery_targets.json"
```

Linux 可用自己的绝对路径。这里是单个字段示例，不是完整配置；Windows JSON 路径建议使用 `/`，避免反斜杠转义错误。路径变更需要重启 Hub。

### 5.2 权限边界和验收

1. 刷新／重新进入用户端跑图页面，“返图目标”应出现配置的群。
2. 管理员只看到配置文件中的目标，不会自动获得“我的 QQ 私聊”，所以建议保留示例中的管理员私聊目标。
3. 绑定个人 QQ 的普通用户会自动得到“我的 QQ 私聊”，目标是该令牌绑定的 QQ，不会随意填写其他人的 QQ。
4. 普通用户只有 `allow_group=true` 时才看到群目标。**本版不是逐人逐群授权：允许群投递的用户会看到全部启用群目标，也不会自动查询其是否为群成员。** 只加入你愿意开放给这些用户的群；否则关闭该用户的群权限。
5. `/aip` 反推从 App 发起时只允许私聊目标；选择群会被拒绝。
6. 就算关闭“生成后发送到 QQ”，也仍要选择目标，仍校验目标权限和级别。

先选择测试群，开启“生成后发送到 QQ”，用普通英文提示词跑一张 N 图。确认 App 记录和群消息均有图后，再开放其他群。QQ 平台限制、机器人禁言或好友关系可能阻止实际发送，单纯保存 JSON 不会保证投递成功。

## 6. 为自己和群友生成普通用户令牌

建议自己也创建一枚普通令牌：管理时使用 Admin；日常跑图使用 Service，避免把管理员令牌发给群友。

### 推荐：App 在线添加

1. 使用管理员令牌连接 Admin。
2. 打开“用户”页，标题为“用户与令牌”；窄屏在导航菜单中找。
3. 点击添加，填写“绑定 QQ 号”和可选备注。
4. 设置“允许调用群聊目标”。仅个人使用可关闭；需要向已配置群投递才开启。
5. 点击“添加并生成令牌”。
6. 弹窗内点击“复制令牌”，私下交付给该用户。明文只显示这一次；“复制交付 CSV”同样含明文，不要发群。
7. 用户打开 Service 端，填写同一个 Hub 地址及自己的用户令牌，点击连接。

在线修改会写入当前 Hub 的用户注册表，不用再手工复制 JSON，也通常不需要重启 Hub。

丢失令牌用“换发用户令牌”；旧令牌立即失效。临时收回权限用“停用”，彻底移除用“删除”。不能从服务器保存的 SHA256 哈希还原明文。

不推荐首次配置旧式共享 `AAH_LITE_TOKEN`：未绑定 QQ 时没有个人私聊路由，多个用户共享身份也不利于区分记录。每人一枚绑定 QQ 的用户令牌更清楚。

### 批量离线工具

解压完整包 `tools/` 下的工具 ZIP，进入工具包根目录：

```text
Windows：tools\start_hub_user_manager.bat
通用：python tools/hub_lite_user_manager.py
```

使用步骤：复制当前服务器 `lite_users.json` 为工作副本 → 打开副本 → 填写 QQ 列表 → 选择新的私密“交付 CSV”位置 → 点击“添加并生成令牌” → 备份并部署修改后的注册表至 Hub 的真实路径 → 逐人私发令牌。

不要在其他管理员同时在线改用户时用旧副本回写，否则会覆盖新用户。首次不存在注册表可以新建，已有用户时不要从空文件重做。完成交付后妥善清理 CSV；备份也按敏感文件保管。

命令行示例（示例 QQ 必须替换）：

```bash
python tools/hub_lite_user_manager.py add --registry ./private/lite_users.json --delivery ./private/new-users.csv --qq 123456789 --no-group
python tools/hub_lite_user_manager.py list --registry ./private/lite_users.json
```

工具不负责把文件上传服务器。修改默认注册表内容后下一次鉴权读取新内容；若改了 `AAH_LITE_USERS_PATH`，则重启 Hub。

## 7. 导入自己的随机词库

公开发行包词库为空，这是脱敏设计，不是安装失败。**普通英文生图不需要词库；“来张好图”需要启用的候选条目。**

### 7.1 先确认两端共用一个文件

检查 AAA 插件 `prompt_pool_path` 和 Hub `AAH_PROMPT_POOL_PATH`（未设置时使用默认 P 路径）指向同一份 `anima_random_prompt_pool.json`。先在 QQ 执行 `/aimg_status` 或启用插件，使其完成空库初始化；不要向另一份插件内置 `data/` 文件导入后误以为运行库已改变。

### 7.2 小批量普通条目：Admin 直接导入

1. Admin 打开“提示词”页。
2. 首次库为空；已有内容时先清除筛选并“导出”，把剪贴板 JSON 保存为备份。导出仅包含当前筛选结果，带筛选的导出不是全库备份。
3. 点击“导入”，在“批量导入提示词”的 JSON 文本框粘贴内容，不是填文件路径。
4. 可使用数组，或包含 `prompts` 数组的对象。下面是可实际测试的普通示例，不是项目私人词库：

```json
{
  "prompts": [
    {
      "name": "公园散步测试",
      "prompt": "1girl, solo, standing, fully clothed, park, daylight",
      "source_code": "B",
      "safety_code": "N",
      "enabled": true,
      "weight": 1,
      "categories": ["park", "daylight"]
    }
  ]
}
```

5. 导入后刷新，选择 B／N，检查名称和正文。
6. 在 QQ 测试 `来张好图抄一抄 B/N`，或在 Service 端选择“来张好图”、来源 B、级别 N、测试目标后提交。

**重要差异：** App 导入会生成新 ID 并追加，不按原 ID 覆盖或去重；重复点导入会重复添加。同 ID 更新、批量清洗或自定义分组应使用下面的离线工具。App 导入接口保留的是当前表单字段，不能依赖它保留 `custom_groups`、`custom_group_definitions` 等完整扩展数据。`categories` 不等于可用 `@组名` 调用的自定义分组。

### 7.3 完整词库、自定义分组和按 ID 更新：本地管理器

```text
Windows：tools\start_prompt_pool_manager.bat
通用：python tools/prompt_pool_manager.py
```

1. 在自己的电脑准备当前运行词库的副本；首次可以新建。
2. 点击“打开”载入副本，用导入功能合并自己审核过的 JSON；需要更新同 ID 时才选择覆盖。
3. 编辑 ID、名称、正文、来源、安全等级、启用状态和权重。
4. 点击“管理自定义分组”创建如 `rain`／雨景、`night`／夜景等组，在条目“自定义分组”填对应 ID，多项用 `|` 分隔。
5. 保存为新的工作文件；先重新打开确认，再执行校验：

```bash
python tools/prompt_pool_manager.py validate ./my-pool.json
python tools/prompt_pool_manager.py group-list ./my-pool.json
```

6. 部署前暂停生成和词库编辑；保留服务器当前库的完整备份。将确认过的完整工作文件同步到真实运行库位置，再重新加载／刷新相关页面。整个过程不要覆盖预设、用户注册表或其他数据。
7. 需要同时保留旧内容时，应先在工作副本合并旧库，不能拿只含新条目的文件直接替换全库。首次替换后可重载 AAA 插件，再用列表抽查。

命令行等价示例（在工作副本上操作）：

```bash
python tools/prompt_pool_manager.py import ./my-pool.json ./incoming.json
python tools/prompt_pool_manager.py import ./my-pool.json ./incoming.json --overwrite
python tools/prompt_pool_manager.py group-add ./my-pool.json --id rain --name 雨景
python tools/prompt_pool_manager.py add ./my-pool.json --id own-0001 --name 雨中公园 --source B --safety N --groups rain --prompt "1girl, solo, raincoat, park, rain"
python tools/prompt_pool_manager.py export ./my-pool.json ./export.json
```

前两条是两种导入策略，**二选一**，不要为同一批数据重复执行。自定义组 ID 不能含空格或 `@ / + ,` 等分隔符；用工具校验。调用示例：

```text
来张好图抄一抄 B/N @rain
来张好图抄一抄 B/N @rain+night
```

多个自定义组按同时匹配处理；只有创建组而没给条目分组，会抽不到。带自定义组的首次验收优先用 QQ 指令；App 的固定来源／级别筛选不等于已具备全部自定义组编辑入口。

### 7.4 服务器文件导入指令：追加，不是替换

把待导入 JSON 放到 **AstrBot 能读到的机器／容器中**，再由 AstrBot 管理员私聊机器人执行：

```text
/aimg_pool_import /实际服务器目录/incoming.json
/aimg_pool_list B/N
/aimg_pool_show 实际条目ID
```

Windows 有空格的路径用英文双引号包住。不能填你个人电脑上但服务器不存在的路径。

这条命令对缺失或重复 ID 会生成新 ID，**不会按同 ID 覆盖原条目**；完整自定义组定义建议通过本地管理器与完整文件部署保留。不要连续重复导入同一个库。

### 7.5 抽不到内容时先查

- 条目是否 `enabled=true`，提示词正文是否非空？
- 是否导入实际运行库，而不是另一个副本？
- 来源与级别是否相交匹配？默认来源为 B/G/D；C/R 需要显式调用；默认等级 N/H，S 需显式选择且不允许 App 群投递。
- 自定义分组是否拼对，`@rain+night` 是否真的有同时属于两组的条目？
- QQ 是否使用了自定义唤醒前缀、群白名单或不同插件配置？

## 8. 角色、画风与个人端的第一次使用

### 8.1 不依赖 LoRA 的最小起步

第一张图把角色／画风留空，用第 2 节的英文提示词。这样可以排除未知 LoRA 名、触发词、画风槽位等问题。

之后在 Admin“预设”页添加自己有权使用的角色和画风，或用 AstrBot 管理员指令。纯文本角色可用：

```text
/aimg_role_text_set 公园向导 --prompt 1girl, brown hair, green jacket
```

LoRA 必须已存在于 ComfyUI 的 `models/loras`，预设中填 ComfyUI 识别的相对名称，不填个人电脑的任意绝对路径。模型强度与 CLIP 强度分开填写。先单 LoRA 验证再叠加，不把其他用户的私有模型名写进公开说明。

### 8.2 Service 个人端验收

1. 安装／打开用户端，用自己的普通令牌连接。
2. 进入跑图页，选择“返图目标”：首次建议“我的 QQ 私聊”。先与机器人建立可用私聊关系。
3. 选择“直接生图 /aimg”，角色和画风留空，级别 N，普通英文提示词，步数／比例先保留默认。
4. “生成后发送到 QQ”：开则发目标会话；关则只在 App 记录看，但仍需要有效目标。
5. “生成完成后自动保存到本地”：开则本次任务完成时尝试下载；这与 QQ 投递开关相互独立，不会自动回填下载全部旧图。
6. 点击“更改保存目录”，Windows 选择自己可写的目录；Android 按系统目录选择器授予访问权限。服务端缓存路径不是手机本地路径。
7. 提交一张，等待队列完成，进入“记录”查看图片；确认本地选定目录存在下载文件。
8. 再选择测试群，验证群投递。最后测试已导入的 B/N 随机词库。

自动保存可能受客户端关闭、网络中断或目录权限影响；失败时先在“记录”查看和手动保存，不要直接重复提交生成。浏览器下载由浏览器权限与保存策略决定，不完全等同原生 Windows／Android。

## 9. 配套工具速查

以下路径相对**解压后的工具包根目录**，不是外层完整包根目录。GUI 需要 Python 的 Tkinter；无桌面服务器可在个人电脑运行 GUI 后传文件，或使用 CLI。

| 工具 | 作用 | 是否会直接改服务器 |
| --- | --- | --- |
| `tools/start_prompt_pool_manager.bat`／`python tools/prompt_pool_manager.py` | 本地词库增删改、按 ID 合并、自定义组、导出与校验 | 只改你选的本地文件；须自己部署 |
| `tools/start_hub_user_manager.bat`／`python tools/hub_lite_user_manager.py` | 本地批量用户及独立令牌、启停、轮换 | 只改选定注册表；须自己部署 |
| `tools/local_prompt_exporter.py` | 旧版轻量筛选导出；参数先看 `--help` | 本地处理，不联网 |
| `Deploy-Windows.cmd`／`Deploy-Linux.sh`（懒人包） | 环境预检、部署、配置、启动 | 按选择操作本机环境；不是日常运行入口 |
| 安装目录 `Start.cmd`／`Start.sh` | 日常启动已有服务 | 会启动，但不会自动重启已运行服务 |
| 完整整合包根目录 `verify_complete_suite.py` | 只读核验发行包完整性 | 不联网、不安装、不修改文件 |

令牌在线管理优先用 Admin“用户”；仅批量离线维护时使用 JSON 工具。投递目标目前没有专用 GUI，以第 5 节 JSON 配置为准。不要把旧 `easy_installer.py`（文件部署辅助器）当成新版完整部署向导。

## 10. 排错对照与完成清单

| 现象 | 优先检查 |
| --- | --- |
| 连接返回 401 | Hub 地址是否正确、管理／用户模式是否对应、令牌是否带引号或空格、是否已轮换、旧 Hub 是否未重启 |
| App 能连但生成提示 API Key 缺失或 403 | `AAH_ASTRBOT_API_KEY`、AstrBot 本机接口 scope、Hub 到 AstrBot 地址；这不是 Hub 用户令牌错误 |
| 群目标为空 | 文件是否在 Hub 实际路径、JSON 格式、目标 `enabled`、用户 `allow_group`、重新进入页面 |
| 管理员没有“我的 QQ 私聊” | 正常；在目标 JSON 配置管理员私聊，或改用绑定 QQ 的普通用户令牌 |
| App 有图但群没图 | 是否开启发送、真实 UMO／Bot ID、QQ 在线／禁言、共享 P、插件与 Hub 是否同版本；查回执，勿盲目重发 |
| `QQ 投递未确认` | 查看插件是否加载、Hub 与插件是否读同一任务数据目录、AstrBot 日志；已生成图片先从记录保存 |
| App 成功导入但 QQ 仍是空库 | 两端词库路径是否一致、插件是否使用其他配置、导入后是否刷新 |
| 导入后重复条目很多 | App／QQ 导入均为追加；回到本地工作副本按 ID 管理，再从备份恢复或清理 |
| 自定义组导入 App 后丢失 | 当前 App 导入接口不保留完整自定义组；使用本地管理器维护并部署完整文件 |
| 手机连不上，同机可用 | 不用手机的 127.0.0.1；检查 Hub 监听地址、VPN／代理、可信防火墙范围 |
| 改配置没有效果 | 修改了错误副本、手动服务未加载环境变量，或 Start 复用了旧进程 |
| 反推群目标被拒绝 | 本版 App 反推仅私聊；切换私聊，不靠改标签绕过规则 |

懒人包日志通常在安装目录的 `Hub.log`、`ComfyUI.log`、`AstrBot.log`；接入现有服务时以原服务日志为准。求助只提供必要错误上下文，先打码令牌、API Key、QQ／群号、服务器地址和私人提示词；不要上传整个运行配置目录。

完成时逐项打勾：

- [ ] 服务健康；普通 QQ 英文生图通过。
- [ ] Hub 配好 AstrBot API Key、真实 Bot ID、相同数据路径。
- [ ] 管理端可连接；管理令牌仅自己持有。
- [ ] 测试群／管理员私聊目标配置正确。
- [ ] 自己的普通用户令牌可用，绑定 QQ 正确。
- [ ] 用户端单张图在 App 可见，并按开关完成 QQ 投递。
- [ ] 本地保存目录已授权，可看到下载图片。
- [ ] 运行词库已备份、导入并通过 B/N 随机抽图。
- [ ] 新用户只拿到自己的令牌，未拿到管理员令牌或服务端配置。

做到这里才算基础个人服务闭环。之后再逐项开启中文转换、反推、HQ、放大和更多群，避免多个依赖同时出错。
