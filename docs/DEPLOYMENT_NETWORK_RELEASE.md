# 0.5.0-beta.2-network.1 部署器修订

本修订只更新安装下载工具、说明和打包流程；插件、Hub、工作流和客户端版本不变。
适用于安装时连接 Hugging Face 超时、Windows curl 吊销检查离线，或需要本地导入 AM ZIP 的用户。

## 下载哪个包

- Windows：`AstrAutoAnima-lazy-bundle-windows-0.5.0-beta.2-network.1.zip`
- Linux：`AstrAutoAnima-lazy-bundle-linux-0.5.0-beta.2-network.1.zip`
- 源码：`AstrAutoAnima-0.5.0-beta.2-network.1-source.zip`
- 独立工具源码：`AstrAutoAnima-tools-0.5.0-beta.2-network.1.zip`（不代替完整懒人包）

完整解压相应系统的懒人包，运行 `Deploy-Windows.cmd` / `Deploy-Linux.sh`。
安装器内新增“公开文件下载”面板；具体填写方式见 [下载指南](DOWNLOAD_NETWORK.md)。
已成功安装的用户无需为此重装服务或重新下载模型。
此前失败的用户可以重新选择原来的受管理安装目录；不要手工清空目录、删除配置或模型。

## 改动

- 官方 / 自定义 HTTPS 镜像 / 文件代理 / 本地导入四种方式。
- 固定 Anima Master 0.7.1 ZIP 可本地选择，仍核对固定提交、SHA256 和解包路径。
- 针对超时、HTTP 错误、证书验证与吊销离线、续传失败的不同提示。
- Windows Schannel 吊销离线兼容必须明确勾选，默认关闭；不关闭 TLS 验证。
- 超时和重试有上限，显示文件增长进度；保留 `.part`，匹配哈希的完整断点文件不重复下载。
- 镜像下载须有官方哈希；不向第三方发送项目服务密钥，不提供内置私人代理或令牌。

## 验证与边界

修订包含网络路由、凭据拒绝、错误分类、哈希拒绝、本地 ZIP 与断点恢复测试，并沿用 Windows CMD / PowerShell 本机回归。
实际官方 AM 固定 ZIP 下载、SHA256 校验与临时目录解包已测试；没有把测试文件安装到现有服务。
不代表中国各运营商、任意镜像或代理已逐一联网实测，也不代表完成了全新机器的 GPU 生图验收。
Git / pip / winget 网络不受此面板控制；首次环境创建仍可能需要单独处理这些下载。

发布包不含模型、私人随机词库、服务器密钥、运行配置或炼丹炉额外接口。
