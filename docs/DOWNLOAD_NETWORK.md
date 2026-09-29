# 下载故障修复：官方、镜像、代理与本地导入

适用于 Windows / Linux 懒人包 **0.5.0-beta.2-network.1** 及以后部署器。
不需要单独的“中国区分支”，按当前网络选择即可。镜像并非保证可用，也不是项目官方服务器。

## 已遇到报错时怎么继续

1. 等旧部署窗口提示失败，关闭它；不要同时运行两个安装器。
2. 完整解压更新的对应系统懒人包，运行 `Deploy-Windows.cmd` 或 `Deploy-Linux.sh`。
3. 重新填写先前的**独立安装目录**和已有环境路径。向导只允许继续它自己创建的、有 `.aaa-managed-install` 标记的目录；不要为绕过检查手动创建标记。已有服务请正常停止。
4. 在“公开文件下载”区域选择下列一种方式，再勾选需要继续的安装项目。
5. 已有完整模型会校验后跳过，`.part` 文件会续传，不必卸载环境或删除全部下载。
6. 完成后继续 [首次起步](FIRST_RUN.md) / [AM 配置](ANIMA_MASTER.md)。不要把下载成功当成已完成生图测试。

## 方式如何选

| 方式 | 适合情况 | 填写项 |
| --- | --- | --- |
| `official` 官方直连 | curl 能正常连接官方站点 | 无；不会继承文件代理环境变量或 `.curlrc` |
| `mirror` 自定义镜像 | 官方模型站连接超时 | 自行选择可信的 HTTPS HF 镜像根地址；GitHub 文件镜像可单独设置 |
| `proxy` 文件下载代理 | 本机已有可用的代理工具 | 完整地址，例如 `http://127.0.0.1:7890`，端口必须对应自己的设置 |
| `local` 本地文件 | 浏览器或另一台机器下载更方便 | 选择本地 UNET、CLIP、VAE 和固定版本 AM ZIP |

**这些选项只控制模型与上游 ZIP 的公开文件下载，包括可选模型；不控制 Git clone、pip、winget，也不修改 Hub/AstrBot API 地址。**
本地模式不是完整离线安装包；首次创建环境仍需要 Python/Git 和 Python 依赖。
可选节点通过 Git 拉取，需另行配置 Git 网络或手动安装；网络受限时先不勾选这些项目。
浏览器使用代理，不代表系统 curl 自动使用同一个代理。

HF 镜像示意：`https://hf.example.invalid`（示意，不可直接使用）。安装器会替换 `huggingface.co`，保留仓库和文件路径。
GitHub 文件镜像示意：`https://gh.example.invalid/files`，实际请求为该前缀 + `/` + 完整官方 URL。**不是所有 GitHub 镜像都支持这种格式，需核对所选服务说明**；不支持则改用代理或本地 ZIP。
未填写的镜像类别仍走官方源；不会偷偷选择第三方站点。镜像下载必须有发布清单 SHA256，缺哈希的可选模型请用官方或代理。
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
- `33 / 36 / 416`：服务器不接受当前续传。保留 `.part`，换支持 Range 的源，或手动下载完整文件导入。
- `SHA256 不匹配`：文件不会提升为可安装的最终文件。不要跳过校验；保留问题文件另行核对/重新下载。

现在最多重试两次，连接超时 20 秒，低于 1 KiB/s 持续 45 秒会中止该次传输；大文件每 15 秒报告大小。
实际下载有四小时单次上限，慢速链路可断点重试。此修复不承诺任一地区/运营商一定可连通。

## Linux 无桌面计划文件

在自己的 JSON 计划中增加（镜像例子仅示意，需替换）：

```json
{
  "download_mode": "mirror",
  "hf_mirror": "https://hf.example.invalid",
  "github_mirror": "",
  "download_proxy": "",
  "revoke_best_effort": false,
  "am_archive": ""
}
```

代理则使用 `download_mode: "proxy"` 并填 `download_proxy`；本地导入使用 `local`，填好三个模型路径和 `am_archive`。Linux 保持 `revoke_best_effort: false`。
这是**追加字段示例**，不是完整部署计划，其他字段沿用 `examples/deployment-plan.linux.json` 并填写实际路径。
