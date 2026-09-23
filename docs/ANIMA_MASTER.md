# 核心上游 Anima Master 与默认模型

## 版本纠正

本项目的核心上游是 **Anima Master 0.7.1**。此前文档中的 0.7.2 是错误指引，现已更正。截至 2026-09-23 核对，上游最新为 **0.9.1**，不是 0.8.0；0.9.1 未完成本项目联调，不自动升级到该版本。

官方仓库：[YayiMiko/anima-master](https://github.com/YayiMiko/anima-master)。安装器固定 0.7.1 官方提交 `34375c86b35f1c94fa3ee8129e98c2127706eb5a`，下载后校验 SHA256，再安装到实际 AstrBot 数据目录的 `data/plugins/astrbot_plugin_anima_master`。

勾选“安装核心上游 Anima Master 0.7.1”才会下载。已有 0.7.1 保留代码，不覆盖；发现其他版本则停止该步骤，要求人工备份处理，不偷偷降级。CLI 模式按所选选项安装依赖；Desktop 由其插件管理器处理依赖，不能向嵌入式环境盲目 pip 升级。

## 默认模型：Anima Base 1.0

模型不随 ZIP 分发。勾选下载并接受许可后，安装器从[官方模型仓库](https://huggingface.co/circlestone-labs/Anima)获取以下三件套（总计约 5.63 GB 十进制，不含 PyTorch/缓存），按文件哈希与大小校验。已明确选择的本地模型优先，不重复下载该项。

| 文件 / 下载链接 | 自动保存位置（相对 ComfyUI） |
| --- | --- |
| [anima-base-v1.0.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/diffusion_models/anima-base-v1.0.safetensors?download=true) | `models/diffusion_models/` |
| [qwen_3_06b_base.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/text_encoders/qwen_3_06b_base.safetensors?download=true) | `models/text_encoders/` |
| [qwen_image_vae.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/vae/qwen_image_vae.safetensors?download=true) | `models/vae/` |

也可用浏览器手动下载后在向导选择本地文件。下载中断会保留 `.part` 供重试；未通过校验不会变成正式模型。不要拿下载了几 MB 的文件当作完整模型。

请先阅读仓库中的模型卡和许可：模型权重使用与生成图片的许可不是同一件事；尤其注意权重的非商业用途条款。项目代码许可不覆盖模型权重。

三件套齐全时生成 `user/default/workflows/AAA_Quick_Local_api.json`（普通生图，不含私人 LoRA）。保留已有同名工作流，不覆盖；HQ/反推/放大模板要另配所需节点和模型。

## 安装后的 AM 配置

1. 启动/重载 AstrBot，在插件页确认 **Anima Master 0.7.1** 和 AAA 桥接插件都成功加载。不要仅凭文件存在判断成功。
2. AM 的 ComfyUI 地址填实际可访问地址；同机默认 `http://127.0.0.1:8188`。容器中的 127.0.0.1 指容器本身，不一定是宿主机。
3. 若使用向导的 Quick：开启自定义工作流，选择上面的 **API JSON**；覆盖工作流参数保持关闭。确认 UNET/CLIP/VAE 三个文件名与 ComfyUI 列表一致。
4. 千代预设默认不启用，ComfyUI 自动拉起默认关闭，以免 AM 与本项目启动器启动两份服务。
5. 已有配置只补缺失键，**保留已有值优先**。因此旧的工作流路径、地址或模型选择不会自动纠正；需在插件配置页核对后保存。修改前产生本地配置备份，备份可能含密钥，不可上传。
6. 中文转英文/提示词优化仍需要 AstrBot 中可用的模型 Provider；在 AM 提示词设置中选择可用 Provider。没接 LLM API 时先用不优化的英文普通生图验证，安装 AM 不等于自动获得 API 服务。
7. 依次验证 ComfyUI `/system_stats`、AAA `/aimg_status`、普通英文生图一张，再测试 `/aicn` 与反推。服务健康、插件加载、模型推理是不同层级的验收。

核心上游安装不替代 NapCat 登录、AstrBot 平台 Bot ID 与 OpenAPI 授权。地址、密钥、QQ 数据和私人词库仍不包含在公共包中。
