import 'package:flutter/material.dart';
import '../../core/builtin_features.dart';

class BuiltinFeaturesPage extends StatelessWidget {
  const BuiltinFeaturesPage({this.localMode = false, super.key});
  final bool localMode;
  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('内置功能与连接方案')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text('这些功能已随项目集成，不需要重复安装。开关只控制本设备界面；服务器能力和账号权限仍由服务端校验。'),
        ListTile(
            title: const Text('本机工作站'),
            subtitle: Text(localMode
                ? '当前使用本机 Hub 直连 ComfyUI；下载和中文转换 API 可按需联网。'
                : 'Windows 管理端选择本机模式后出现。完整部署同样保留；切换客户端不会修改 Hub 启动模式。')),
        ValueListenableBuilder<bool>(
            valueListenable: qqComposerEnabled,
            builder: (context, value, child) => SwitchListTile(
                title: const Text('QQ 指令拼装 / 复制'),
                subtitle: Text(localMode
                    ? '已内置，本机模式隐藏入口；切回在线模式时按此设置显示。'
                    : '只复制到剪贴板；手动粘贴到 QQ，不自动发送。'),
                value: value,
                onChanged: (next) => saveBuiltinFeature(
                    'qq_composer', qqComposerEnabled, next))),
        ValueListenableBuilder<bool>(
            valueListenable: bilingualTagsEnabled,
            builder: (context, value, child) => SwitchListTile(
                title: const Text('中英双语提示词候选'),
                subtitle: const Text('本地候选词库，不把输入发送给翻译服务器。中文生图 LLM 是另一项独立功能。'),
                value: value,
                onChanged: (next) => saveBuiltinFeature(
                    'bilingual_tags', bilingualTagsEnabled, next))),
        ValueListenableBuilder<bool>(
            valueListenable: connectionGuidanceEnabled,
            builder: (context, value, child) => Column(children: [
                  SwitchListTile(
                      title: const Text('展开远程连接方案说明'),
                      subtitle: const Text('只显示说明，不自动安装组网工具，不开放端口。'),
                      value: value,
                      onChanged: (next) => saveBuiltinFeature(
                          'connection_guidance',
                          connectionGuidanceEnabled,
                          next)),
                  if (value)
                    const Padding(
                        padding: EdgeInsets.all(16),
                        child: Text('局域网：电脑和手机在同一可信网络；不要把管理端口映射到公网。\n\n'
                            '私有组网：双方安装并加入受控私网，只授权自己的设备；依赖第三方服务与客户端。\n\n'
                            '受保护隧道：需自行配置 HTTPS、身份验证和访问策略；配置失误仍可能暴露服务。\n\n'
                            '直接公网：风险最高，需 HTTPS、强令牌、防火墙和及时更新。不要直接公开 AstrBot 6185、ComfyUI 8188 或 Studio 8765。\n\n'
                            '客户端连接 Hub（默认 6278）。修改这里的显示选项不会改变系统防火墙或服务器监听地址。')),
                ])),
        ListTile(
            title: const Text('Bot 平台 / 群聊管理'),
            subtitle: Text(localMode
                ? '当前本机执行模式不提供：无需 AstrBot，也不会调用群管理接口。'
                : '远程管理模式按服务端能力显示；平台适配器及 Bot 账号仍需部署者配置。')),
      ]));
}
