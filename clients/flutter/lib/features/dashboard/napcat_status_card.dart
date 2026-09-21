import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import 'napcat_login_dialog.dart';

class NapcatStatusCard extends StatefulWidget {
  const NapcatStatusCard({required this.api, super.key});
  final HubApi api;
  @override
  State<NapcatStatusCard> createState() => _NapcatStatusCardState();
}

class _NapcatStatusCardState extends State<NapcatStatusCard>
    with WidgetsBindingObserver {
  Timer? _timer;
  bool _busy = false;
  bool _active = true;
  String _state = 'unknown';
  String _message = '正在查询…';
  DateTime? _checked;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (_active && (ModalRoute.of(context)?.isCurrent ?? true)) _refresh();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _active = state == AppLifecycleState.resumed;
    if (_active) _refresh();
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final value = await widget.api.napcatStatus();
      if (!mounted) return;
      setState(() {
        _state = value['state']?.toString() ?? 'unknown';
        _message = value['require_2fa'] == true
            ? '需要双重验证，请打开登录助手；无法自动确认在线状态。'
            : value['message']?.toString() ?? '状态未知';
        _checked = DateTime.now();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = 'unknown';
        _message = '暂时无法查询，请检查 Hub / NapCat 连接及版本；不代表 QQ 已掉线。';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Card(
          child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(_state == 'online' ? Icons.check_circle : Icons.info_outline,
                color: _state == 'online'
                    ? Colors.green
                    : _state == 'offline'
                        ? Theme.of(context).colorScheme.error
                        : null),
            const SizedBox(width: 8),
            const Expanded(child: Text('NapCat · QQ 登录状态')),
            IconButton(
                tooltip: '刷新 QQ 状态',
                onPressed: _busy ? null : _refresh,
                icon: const Icon(Icons.refresh)),
          ]),
          Text(_message),
          const SizedBox(height: 8),
          Text(
              '前台每 30 秒检查 · 上次成功读取：${_checked?.toLocal().toString().split('.').first ?? "尚无"}'),
          const Text('此状态由 NapCat 报告，不代表 QQ 消息投递链路已验证。'),
          TextButton.icon(
              icon: const Icon(Icons.login),
              label: const Text('打开登录助手'),
              onPressed: () async {
                await showDialog<void>(
                    context: context,
                    builder: (_) => NapcatLoginDialog(api: widget.api));
                if (mounted) await _refresh();
              }),
        ]),
      ));
}
