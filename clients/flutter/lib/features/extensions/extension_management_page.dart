import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/hub_api.dart';
import 'studio_workbench.dart';

/// Separately installed connector status and administrator workbench entry.
class ExtensionManagementPage extends StatefulWidget {
  const ExtensionManagementPage(
      {required this.api, required this.id, required this.name, super.key});
  final HubApi api;
  final String id;
  final String name;
  @override
  State<ExtensionManagementPage> createState() =>
      _ExtensionManagementPageState();
}

class _ExtensionManagementPageState extends State<ExtensionManagementPage> {
  late Future<Map<String, dynamic>> _status =
      widget.api.extensionStatus(widget.id);
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.name), actions: [
          IconButton(
              tooltip: '重新检查连接器',
              icon: const Icon(Icons.refresh),
              onPressed: () => setState(
                  () => _status = widget.api.extensionStatus(widget.id))),
        ]),
        body: FutureBuilder<Map<String, dynamic>>(
            future: _status,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              final data = snapshot.data;
              return Center(
                  child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 800),
                      child: ListView(
                          shrinkWrap: true,
                          padding: const EdgeInsets.all(24),
                          children: [
                            const Icon(Icons.science_outlined, size: 56),
                            const SizedBox(height: 16),
                            Text('${widget.name}管理',
                                style:
                                    Theme.of(context).textTheme.headlineSmall),
                            const SizedBox(height: 16),
                            Text(snapshot.hasError
                                ? '无法读取连接器状态。请返回刷新扩展入口，或检查 Hub 连接。'
                                : '${data?['message'] ?? '状态未知'}'),
                            if (data != null) ...[
                              const SizedBox(height: 12),
                              Text('连接器版本：${data['version'] ?? '未知'}'),
                              Text(
                                  '启用状态：${data['enabled'] == true ? '已启用' : '未启用'}'),
                              if (widget.id == 'anima-lora-studio' &&
                                  data['ui']?['launch_available'] == true)
                                FilledButton.icon(
                                  icon: const Icon(Icons.open_in_browser),
                                  label: const Text('进入炼丹炉工作台'),
                                  onPressed: () => Navigator.of(context).push(
                                      MaterialPageRoute<void>(
                                          builder: (_) => StudioWorkbench(
                                              api: widget.api))),
                                ),
                            ],
                            const Divider(height: 32),
                            if (widget.id == 'anima-lora-studio') ...[
                              Text('AnimaLoraStudio · 第三方开源项目',
                                  style: Theme.of(context).textTheme.titleMedium),
                              const SizedBox(height: 8),
                              const Text('由 WalkingMeatAxolotl 与贡献者开发。'
                                  '它把数据整理、打标、训练与出图测试汇成一套清晰的工作台，'
                                  '项目版本管理与双语界面对入门尤其友好。感谢原作者的持续打磨！'
                                  'AAA 仅提供可选安装与连接适配，不是该训练引擎的作者。'),
                              const SelectableText(
                                  'https://github.com/WalkingMeatAxolotl/AnimaLoraStudio'),
                              TextButton.icon(
                                icon: const Icon(Icons.copy_outlined),
                                label: const Text('复制原项目链接 · 欢迎支持作者'),
                                onPressed: () async {
                                  await Clipboard.setData(const ClipboardData(
                                      text: 'https://github.com/WalkingMeatAxolotl/AnimaLoraStudio'));
                                  if (context.mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(content: Text('已复制原项目链接')));
                                  }
                                },
                              ),
                              const Text('当前连接器验证 Studio 0.25.x，不代表上游最新版。'
                                  'GPL-3.0 与其他第三方许可见扩展包内声明；模型许可独立。'
                                  '公开包 optional/studio 提供安装说明，tools/studio_optional.py '
                                  '提供默认只预检的安装助手。'),
                              const Divider(height: 32),
                            ],
                            const Text('这是独立可选扩展。AAA 不迁移、复制或删除炼丹炉的项目、数据集和模型。'),
                            const SizedBox(height: 12),
                            const Text('需要独立安装 Studio 0.25 连接器并启动原有 Studio 服务。'
                                '退出页面只关闭连接，不会停止后台训练。无卡实例请勿启动 GPU 任务。'),
                          ])));
            }),
      );
}
