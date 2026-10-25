import 'package:flutter/material.dart';

import '../../core/hub_api.dart';

/// AAA admission only. AstrBot owns adapter credentials and online status.
class PlatformSwitchboardPage extends StatefulWidget {
  const PlatformSwitchboardPage({required this.api, super.key});
  final HubApi api;

  @override
  State<PlatformSwitchboardPage> createState() =>
      _PlatformSwitchboardPageState();
}

class _PlatformSwitchboardPageState extends State<PlatformSwitchboardPage> {
  late Future<Map<String, dynamic>> _future =
      widget.api.getPlatformSwitchboard();
  bool _saving = false;

  void _refresh() {
    setState(() {
      _future = widget.api.getPlatformSwitchboard();
    });
  }

  void _notice(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _change(String key, bool enabled) async {
    if (_saving) return;
    if (enabled && key != 'qq') {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('确认开始接单'),
          content: const Text(
            '此开关只允许 AAA 接收来自该平台的新生图任务；不会创建 Bot、设置令牌或证明 Bot 已在线。'
            '请先在 AstrBot「机器人」面板配置适配器，并在目标平台测试文本与图片收发。'
            '现有安全模式和共用生图队列仍会生效。',
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('确认开启')),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    setState(() => _saving = true);
    try {
      for (var attempt = 0; attempt < 3; attempt++) {
        final latest = await widget.api.getPlatformSwitchboard();
        final switches = Map<String, bool>.from(latest['accept_new'] as Map);
        switches[key] = enabled;
        try {
          await widget.api.savePlatformSwitchboard(
            revision: '${latest['revision']}',
            acceptNew: switches,
          );
          _refresh();
          _notice(enabled ? 'AAA 已允许该平台接收新任务' : 'AAA 已停止该平台接收新任务；已接收任务继续处理');
          return;
        } on HubApiException catch (error) {
          if (error.statusCode == 409 && attempt < 2) continue;
          rethrow;
        }
      }
    } on HubApiException catch (error) {
      _notice(error.message);
    } on Exception catch (error) {
      _notice('保存失败：$error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String _adapterHint(String state) => switch (state) {
        'configured_enabled' => 'AstrBot 配置已启用；在线状态请在 AstrBot 核对',
        'configured_disabled' => 'AstrBot 已配置但未启用',
        'not_configured' => 'AstrBot 尚未配置',
        _ => '无法读取 AstrBot 配置；请到其机器人面板核对',
      };

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Bot 平台切换板'), actions: [
          IconButton(
              onPressed: _refresh,
              icon: const Icon(Icons.refresh),
              tooltip: '刷新状态'),
        ]),
        body: FutureBuilder<Map<String, dynamic>>(
          future: _future,
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              if (snapshot.hasError) {
                return Center(child: Text('${snapshot.error}'));
              }
              return const Center(child: CircularProgressIndicator());
            }
            final data = snapshot.data!;
            final switches =
                Map<String, dynamic>.from(data['accept_new'] as Map);
            final adapters =
                Map<String, dynamic>.from(data['adapter_configuration'] as Map);
            return ListView(padding: const EdgeInsets.all(20), children: [
              const Text('从哪来，回哪去；QQ、Telegram、Discord 共用同一生图队列。'
                  '开关只控制 AAA 新任务，不切换 AstrBot 账号，也不改动已排队任务。'),
              const SizedBox(height: 16),
              for (final entry in const <(String, String, String)>[
                ('qq', 'QQ', '现有 NapCat / AstrBot 通道'),
                ('telegram', 'Telegram', '在 AstrBot 机器人面板配置 Telegram Bot'),
                ('discord', 'Discord', '在 AstrBot 机器人面板配置 Discord Bot'),
              ])
                Card(
                    child: SwitchListTile(
                  key: ValueKey('platform.${entry.$1}'),
                  title: Text(entry.$2),
                  subtitle: Text(
                      '${entry.$3}\n${_adapterHint((adapters[entry.$1] ?? 'unknown').toString())}'),
                  isThreeLine: true,
                  value: switches[entry.$1] == true,
                  onChanged:
                      _saving ? null : (value) => _change(entry.$1, value),
                )),
              const SizedBox(height: 12),
              const Text(
                  'Discord 可使用 AstrBot 原生斜杠指令；Telegram 可使用 BotFather 的命令菜单。'
                  '具体指令、权限及平台在线状态仍以 AstrBot 与对应平台为准。'),
            ]);
          },
        ),
      );
}
