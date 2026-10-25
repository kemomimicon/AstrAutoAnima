# AstrAutoAnima 0.5.2-1.44 · AutoDL 公开镜像

把 QQ、AstrBot 与 ComfyUI/Anima 连成一套完整跑图工作站：基础生图、HQ、已有图精修、图片反推、
角色与画风预设、随机词库、图片记录，以及 Windows、Android 和 Web 管理入口。

镜像内置 AAA build44、Anima Master 0.7.1、ComfyUI、基础模型三件套、WD 反推、Studio 0.25.0、
G 组词库、V 国风古韵资源和角色词典。SeedVR2、JoyCaption、CL 与 QQ 接入可按用途装配。

## 1. 启动

选择 24GB 显存、50GB 数据盘的实例，在 JupyterLab 终端执行：

```bash
bash /root/AAA-Start.sh
```

首次启动会校验并释放运行环境，生成自己的登录密码和令牌，启动 ComfyUI、AstrBot、Hub 与 Studio。
再次启动仍使用同一个命令。

## 2. 打开网页

下载完整发行包内的 SSH 隧道工具，在自己的电脑填写 AutoDL 控制台提供的 SSH 主机、端口和密码。

| 服务 | 通过 SSH 隧道访问 |
| --- | --- |
| AAA 管理端 | http://127.0.0.1:6278 |
| AstrBot | http://127.0.0.1:6185 |
| ComfyUI | http://127.0.0.1:8188 |
| Studio | AAA 管理端 → 扩展 → AnimaLoraStudio |
| NapCat | 安装并启动后访问 http://127.0.0.1:6099 |

首次密码和令牌查询：

```bash
bash /root/AAA-Credentials.sh --show initial
bash /root/AAA-Credentials.sh --show hub --profile full
```

首次登录 AstrBot 后修改密码，将自己的凭据保存在密码管理器中。录屏、截图和反馈日志中请收起凭据。
用途对照见同目录 `CREDENTIALS.md`。

## 3. 接通管理端和个人端

1. 登录 AstrBot，进入“设置 → OpenAPI”，创建完整 API Key，并授予 chat、file、message 等实际接口权限。
2. 在 AAA 管理端填写 AstrBot 地址、完整 API Key 和平台 Bot ID。
3. 创建个人用户令牌，填写实际投递群或私聊目标。
4. 个人端填入 Hub 地址和个人令牌，先生成一张英文提示词图片。

基础工作流已绑定 Anima Base 1.0、Qwen 编码器和 VAE。角色、画风 LoRA 放入 ComfyUI 模型目录后，
在管理端建立自己的预设。HQ 与精修使用已配置的独立工作流。

## 4. 词库、词典与 Studio

- G 组词库已装配，可继续导入自己的分组和条目。
- V 国风古韵已接通完整服务和本机工作站两种模式，可在来张好图中选择。
- 角色词典可在管理端查询和装配；LoRA 文件与角色预设按自己的模型选择。
- Studio 已安装独立环境，复用基础模型；在管理端的扩展页打开，即可准备数据、配置训练项目。
- 可视化词库编辑器、批量导入导出、令牌管理、搬家与路径修复工具均在对应发行包的工具目录。

## 5. 按需扩展

SeedVR2 3B FP16 与 VAE 使用已校验的 ModelScope 固定文件：

```bash
python3 /opt/aaa-image-052144/optional_models.py \
  --profile seedvr2-fp16 --mode modelscope --apply --accept-model-license
```

下载后用下面两条命令重启 ComfyUI，再在管理端选择 SeedVR2。图像及 VAE 分块保持关闭。

```bash
bash /opt/aaa-image-052144/Service.sh comfy stop --apply --confirm-idle
bash /root/AAA-Start.sh
```
JoyCaption、量化模型与 NapCat 安装入口见仓库 `docs/EXTENSIONS_GUIDE.md`、`docs/NAPCAT_SETUP.md`。
QQ 使用者完成扫码登录后，将 NapCat WebSocket 客户端连接到 `ws://127.0.0.1:6199/ws`，
两端填写同一个 OneBot Token。

## 6. 验收与反馈

RTX 4090 D 已完成基础 1024×1536、HQ/精修 1280×1920、WD 反推及分类选择、
SeedVR2 3B FP16 整图 682×1024 验收，QQ 投递由维护者验证。

遇到问题，欢迎在 **bilibili 联系「ケモミミロリコン」**，附上组件版本、操作步骤和报错截图。

项目与下载：https://github.com/kemomimicon/AstrAutoAnima

## 模型与组件许可

基础模型采用 CircleStone Non-Commercial License，模型权利由 CircleStone Labs 直接向使用者授予。
完整模型许可、署名及第三方来源随镜像保存在 `/opt/aaa-image-052144/licenses`。
Studio、ComfyUI、AstrBot、节点和各模型分别保留对应上游许可证。
