# Android · 0.5.3-beta.1 / build45

2026-11-24 修订 `candidate.3-admin-entries`：管理端概览恢复 NapCat 登录助手及 QQ 状态卡，实例页恢复优云账户余额查询；保留 `/aref` 自动模式和画风预设选择。已安装上一份 build45 候选 APK 的用户可用本目录同用途 APK 覆盖安装，服务端同时应用本次更新包。

本目录提供两个完整通用 APK，均包含 ARM64、ARMv7 与 x86_64 架构，适用 Android 7.0 及以上。按用途安装即可，也可以同时安装两款。

- Android-Admin：管理端，使用 Hub 管理员令牌管理词库、预设、角色画廊等。
- Android-Service：个人使用端，使用自己的用户令牌连接 Hub 跑图、查看记录和下载图片；无需手机运行 Python 服务。

## 从 build44 更新

1. 先完成 Hub/插件的 build45 更新，再更新手机客户端。
2. 保留旧 APK；在旧客户端确认并保存 Hub 地址与对应令牌。
3. 将同用途新版 APK 发送到手机，在系统文件管理器中打开安装。需要时允许当前文件管理器安装应用。
4. 直接覆盖安装，不需要卸载旧版。两款新 APK 的包名及签名分别与 build44 发布包相同，版本代码由 44 升至 45；覆盖安装保留现有应用数据。
5. 打开后连接原 Hub，确认词库与预设可见，再使用新增功能。Turbo 与 SnapRef 的模型/节点配置在服务器端完成。

安卓管理端包名：`com.reln.astrautoanima.hubclient.admin`

安卓个人端包名：`com.reln.astrautoanima.hubclient.service`

## 首次连接

手机填写手机实际能访问的 Hub 地址，例如同一局域网的 `http://电脑局域网IP:6278` 或已配置的 HTTPS 域名。手机的 `127.0.0.1` 指手机自身；电脑上的 SSH 本机转发地址不能直接当作手机地址。

Hub 令牌用于本客户端连接 Hub。AstrBot 登录密码、AstrBot OpenAPI Key 和 NapCat WebUI Token 各有自己的用途，不填进 Hub 令牌栏。

连接后先使用既有普通生图，再按 `docs/NEXT_ANIMA_FEATURES.md` 使用 Turbo、多人预设、角色画廊和 `/aref`。

## 回退手机客户端

先保存 Hub 地址、对应令牌和未提交内容，并将需要保留的图片复制到手机公共目录。服务器端的数据按“00_更新与回退说明.txt”保留和恢复。

Android 通常不接受直接覆盖安装较低版本。需要退回 build44 时，保存上述信息后卸载对应的 build45 应用，再安装保留的旧 APK 并重新连接。卸载会清除该应用的本机数据；不要在保存连接信息和图片前操作。

管理员端和个人端是两个独立应用，卸载其中一款不替代另一款的操作。手机客户端的卸载不会删除服务器上的模型、词库、任务记录或密钥。

## 包校验

`ANDROID_SHA256SUMS.txt` 为两款 APK 的 SHA256；`verification/android-apk-verification.json` 记录包名、版本、签名对照、三种架构及 APK 对齐校验。当前为本地候选包，尚未发布；手机上的安装、连接和生图作为实机验收。

如出现“签名不一致”，先保留当前应用和数据，记录旧版来源再反馈，不要直接卸载。项目 GitHub 或 bilibili：ケモミミロリコン。
