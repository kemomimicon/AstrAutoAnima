# 下载故障修复：官方、镜像、代理与本地导入

适用于 Windows / Linux 懒人包 **0.5.0-beta.2-network.1** 及以后部署器。
不需要单独的“中国区分支”，按当前网络选择即可。镜像并非保证可用，也不是项目官方服务器。

**2026-10-20 增强需使用本轮候选包；尚未发布到GitHub。** 新增可选ModelScope固定渠道、部分成功响应续传及量化模型清单。旧Release不会自动具备这些行为。

## 本轮新增：ModelScope与保留进度

参考本地Anima LoRA Studio的“按模型选择下载源”做法，不把无限重试当作网络修复，也不向ComfyUI环境额外安装下载SDK。

- 国内HF直连困难时，可在全量部署器选择 `modelscope`。**目前只覆盖Anima Base 1.0三件套**，固定ModelScope提交`79d627c66e8a669625c60f48d2633e61f8982eab`；大小和SHA256已与HF原清单核对一致，不猜测同名仓库。
- 未配置映射的JoyCaption、SeedVR2、WD及AM ZIP明确提示仍走原官方源；这些可用HF镜像、文件代理或本地导入。选择ModelScope意味着同意联系该服务；失败回退原官方源需单独勾选。
- 若服务器仅返回部分数据但curl报告成功，非错误页且小于预期时，保留 `.part` 并再续传最多3次。有进度才续，没进度停止，允许下次继续；不立即以“哈希错”丢掉已下载内容。最终仍必须大小+SHA256通过。
- 请求禁用缓存并要求identity编码，减少缓存重定向和传输编码干扰；不是禁用TLS或内容校验。相同大小但SHA错误、HTML/LFS指针等仍隔离保留，已有错误的最终模型不自动覆盖。

公开源：[ModelScope Anima](https://modelscope.cn/models/circlestone-labs/Anima/files)、[Hugging Face Anima](https://huggingface.co/circlestone-labs/Anima)。不保证所有地区永久稳定；不发送Hub或AstrBot密钥。

## 已遇到报错时怎么继续

1. 等旧部署窗口提示失败，关闭它；不要同时运行两个安装器。
2. 完整解压更新的对应系统懒人包，运行 `Deploy-Windows.cmd` 或 `Deploy-Linux.sh`。
3. 重新填写先前的**独立安装目录**和已有环境路径。向导只允许继续它自己创建的、有 `.aaa-managed-install` 标记的目录；不要为绕过检查手动创建标记。已有服务请正常停止。
4. 在“公开文件下载”区域选择下列一种方式，再勾选需要继续的安装项目。
5. 已有完整模型会校验后跳过，正常 `.part` 文件会续传；确认损坏或无法续传的断点会另存后有限重试，不必卸载环境或删除全部下载。
6. 完成后继续 [首次起步](FIRST_RUN.md) / [AM 配置](ANIMA_MASTER.md)。不要把下载成功当成已完成生图测试。

## 方式如何选

| 方式 | 适合情况 | 填写项 |
| --- | --- | --- |
| `official` 官方直连 | curl 能正常连接官方站点 | 无；不会继承文件代理环境变量或 `.curlrc` |
| `mirror` 自定义镜像 | 官方模型站连接超时 | 自行选择可信的 HTTPS HF 镜像根地址；GitHub 文件镜像可单独设置 |
| `modelscope` 魔搭固定映射 | Anima三件套HF下载困难 | 不需填镜像地址；仅用已核实映射，其余文件仍原官方源 |
| `proxy` 文件下载代理 | 本机已有可用的代理工具 | 完整地址，例如 `http://127.0.0.1:7890`，端口必须对应自己的设置 |
| `local` 本地文件 | 浏览器或另一台机器下载更方便 | 选择本地 UNET、CLIP、VAE 和固定版本 AM ZIP |

**这些选项只控制模型与上游 ZIP 的公开文件下载，包括可选模型；不控制 Git clone、pip、winget，也不修改 Hub/AstrBot API 地址。**
本地模式不是完整离线安装包；首次创建环境仍需要 Python/Git 和 Python 依赖。
可选节点通过 Git 拉取，需另行配置 Git 网络或手动安装；网络受限时先不勾选这些项目。
浏览器使用代理，不代表系统 curl 自动使用同一个代理。

HF 镜像示意：`https://hf.example.invalid`（示意，不可直接使用）。安装器会替换 `huggingface.co`，保留仓库和文件路径。
GitHub 文件镜像示意：`https://gh.example.invalid/files`，实际请求为该前缀 + `/` + 完整官方 URL。**不是所有 GitHub 镜像都支持这种格式，需核对所选服务说明**；不支持则改用代理或本地 ZIP。
未填写的镜像类别仍走官方源；不会偷偷选择第三方站点。镜像下载必须有发布清单 SHA256。
向导提供“选用 HF-Mirror…”按钮，确认后才填入第三方 `https://hf-mirror.com` 并选择镜像模式；不会承诺该站在所有网络下稳定或更快。
可另外勾选“镜像失败回退官方”，默认关闭。开启后只在所选镜像未成功时尝试原官方 URL，使用同一份固定版本文件、大小及 SHA256；不会继续轮询未知镜像。官方直连失败时也不会未经确认自动转到第三方。
镜像/代理 URL 不允许携带账号、密码、查询令牌；不支持在向导里填写认证代理凭据。不要填写 Hub 管理令牌或 AstrBot OpenAPI Key。

## Windows：`CRYPT_E_REVOCATION_OFFLINE / 0x80092013`

这是 Windows curl 无法访问证书吊销检查服务，不等于 ZIP 不存在，也与 AstrBot 401 无关。
先检查系统时间、系统更新和网络/代理。仅当仍是这个错误时，可以明确勾选：

> 仅 Windows：同意证书吊销离线兼容

此选项使用 Schannel `--ssl-revoke-best-effort`：允许吊销信息缺失或离线的情况，仍校验证书链和主机名，仍拒绝已知吊销证书；**会降低离线情况下的吊销检查保障**。默认关闭，不会自动开启，不使用 `-k` / `--insecure` / `--ssl-no-revoke`。
非 Schannel curl 会拒绝该选项；太旧的 curl 不支持参数时请更新系统 curl，或使用本地导入。
参见 [curl 官方选项说明](https://curl.se/docs/manpage.html#--ssl-revoke-best-effort)。

## 手动下载与自动放置

模型官方链接和许可见 [Anima Master 与模型说明](ANIMA_MASTER.md)，精确文件清单在 `tools/model_catalog.json`。
下载三个模型后，在向导顶部分别选择 UNET / CLIP / VAE，取消“下载默认模型”。程序会按原有规则放入 ComfyUI 模型目录；自定义模型不冒充官方哈希已验证的模型。

AM 必须是以下固定提交 ZIP，不要下载当前主分支，也不要重新压缩：

- [Anima Master 0.7.1 固定提交 ZIP](https://codeload.github.com/YayiMiko/anima-master/zip/34375c86b35f1c94fa3ee8129e98c2127706eb5a)
- SHA256：`d797a6811d71f7b6e8782ca1b1afbcd521e29fc05f073988a614cf350b142b38`

在“本地 AM ZIP”中选择文件，同时勾选“安装核心上游 Anima Master 0.7.1”。程序先核对哈希再解包；已有 0.7.1 保留不覆盖，其他版本不自动降级。

## 错误码与恢复

- `5 / 6 / 7 / 28`：代理解析、DNS、连接或传输超时。换下载方式；不是模型损坏的证据。
- `35 + 0x80092013`：按上面的 Windows 专项说明处理。
- `60`：证书验证失败；检查系统和代理证书，不关闭验证。
- `22`：HTTP 错误。核对 URL、镜像服务规则；`416` 可能是断点不受支持。
- `33 / 36 / 416`：服务器不接受当前续传。增强版先另存问题断点，再尝试一次从头下载；仍失败时换源或手动导入。
- `SHA256 不匹配`：文件不会提升为可安装的最终文件。增强版输出期望/实际哈希和大小，隔离问题断点并有限重下；不要跳过校验。

瞬时网络故障每轮最多重试两次，每次新启动 curl 从实际已下载字节续传；HTTP/2 错误下一次尝试 HTTP/1.1。401/403 和证书错误不做盲目重试。连接超时 20 秒，低于 1 KiB/s 持续 45 秒会中止该次传输；每 15 秒报告大小及本轮平均速度。
每次 curl 传输有四小时上限（不是全部尝试合计四小时）。校验或续传恢复的从头重试最多一次，另加用户显式开启的官方回退，次数有限。此修复不承诺任一地区/运营商一定可连通。

## 哈希、断点和空间说明

- 内置 Anima / WD / JoyCaption 模型清单改用固定仓库提交，不再将固定哈希与会变化的 `resolve/main` 混用。下载后先检查大小及 SHA256，合格才成为最终模型文件。
- 修正 WD `selected_tags.csv` 缺少 SHA256 导致镜像模式被安装器拒绝的问题；补齐词表哈希和所有内置模型文件大小。已核对的大模型原 SHA256 与官方元数据一致，不需要降低校验要求。
- 识别 HTML 错误页、Git LFS 指针等常见非模型内容。问题文件保留在同目录的 `.part.rejected.时间.随机值`，不自动删除；它会继续占空间，可检查后自行处理。已有最终模型不匹配时停止，不自动覆盖。
- 同一目标使用操作系统文件锁，阻止两个本工具进程同时下载。很小的 `.download.lock` 文件会保留，文件存在不代表仍在下载；进程退出后锁会释放，不需手动删除锁文件。
- 开始传输前检查剩余字节所需空间及 32 MiB 余量。隔离旧断点后从头下载会需要额外空间。模型搬运、其他组件和同时运行的程序也会占空间，此检查不等于整个部署容量保证。
- 完整断点可直接校验恢复；即使网络末尾报错，已完整且哈希正确的文件也无需重新下载。校验期间需要读取整个大文件，不要因进度暂时不动就关闭程序。

## Linux 无桌面计划文件

在自己的 JSON 计划中增加（镜像例子仅示意，需替换）：

```json
{
  "download_mode": "mirror",
  "hf_mirror": "https://hf.example.invalid",
  "github_mirror": "",
  "download_proxy": "",
  "revoke_best_effort": false,
  "fallback_official": false,
  "am_archive": ""
}
```

代理则使用 `download_mode: "proxy"` 并填 `download_proxy`；本地导入使用 `local`，填好三个模型路径和 `am_archive`。Linux 保持 `revoke_best_effort: false`。
这是**追加字段示例**，不是完整部署计划，其他字段沿用 `examples/deployment-plan.linux.json` 并填写实际路径。

## 本次验证记录与尚未验证范围（2026-10-18）

- Windows 工具回归：112 项，111 项通过、1 项仅 Linux flock 测试按平台跳过。完整回归曾出现 socket 清理 ResourceWarning；独立 HTTPS 测试启用资源跟踪复跑未出现该警告，无测试失败。
- 真实系统 curl + 本机 HTTPS：续传、忽略 Range 后重新下载、HTTP 200 错误网页、连接中断后续传四项通过。仅在测试进程通过 `--cacert` 信任临时测试证书，没有修改系统信任，也未关闭 TLS 校验。
- 使用实际下载器分别从官方和 HF-Mirror 下载固定版本 WD `selected_tags.csv`：均为 308,468 bytes，均通过 SHA256 `298633d94d0031d2081c0893f29c82eab7f0df00b08483ba8f29d1e979441217`。
- Anima UNET / CLIP / VAE、WD ONNX、JoyCaption Q6_K 与 mmproj 共六个大文件的清单哈希、大小已与各官方仓库 API 元数据核对；没有重新下载六个大文件来声称完整实测。固定版本与校验值见两个 JSON 清单。
- 官方和镜像的小范围读取在测试网络成功，不代表国内各运营商长期稳定。用户现场长时间大文件下载、断线恢复、代理配置，以及 Linux 实机下载仍待验证；没有用户现场网络及 Linux 运行环境，不能替代这些验收。
- 本次未发布 GitHub 或替换 Release 资产；现有 ZIP 不会因源码已修复而自动更新。
