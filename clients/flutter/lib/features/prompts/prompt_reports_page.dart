import '../../core/courtyard_theme.dart';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';

class PromptReportsPage extends StatefulWidget {
  const PromptReportsPage({required this.api, super.key});
  final HubApi api;
  @override
  State<PromptReportsPage> createState() => _PromptReportsPageState();
}

class _PromptReportsPageState extends State<PromptReportsPage> {
  late Future<Map<String, dynamic>> _future = widget.api.promptReports();
  final Set<String> _busy = {};
  Future<void> _resolve(String id, String action) async {
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: Text(action == 'trash' ? '将该词库条目移入垃圾库？' : '忽略这条举报？'),
                content: Text(action == 'trash'
                    ? '原条目会停用并留存到trash；不会删除图片或其他片段。'
                    : '不会修改提示词库。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      style: action == 'trash'
                          ? FilledButton.styleFrom(
                              backgroundColor:
                                  Theme.of(context).colorScheme.error,
                              foregroundColor:
                                  Theme.of(context).colorScheme.onError)
                          : null,
                      onPressed: () => Navigator.pop(context, true),
                      child: Text(action == 'trash' ? '确认停用并移入垃圾库' : '确认忽略举报'))
                ]));
    if (yes != true || !_busy.add(id)) return;
    if (mounted) setState(() {});
    try {
      await widget.api.resolvePromptReport(id, action);
      if (mounted) setState(() => _future = widget.api.promptReports());
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    } finally {
      _busy.remove(id);
      if (mounted) setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, snapshot) =>
          ListView(padding: const EdgeInsets.all(24), children: [
            Row(children: [
              const Expanded(child: Text('提示词举报审核')),
              IconButton(
                  tooltip: '刷新',
                  onPressed: () =>
                      setState(() => _future = widget.api.promptReports()),
                  icon: const CourtyardIcon(Icons.refresh))
            ]),
            if (snapshot.hasError) Text('${snapshot.error}'),
            if (!snapshot.hasData && !snapshot.hasError)
              const LinearProgressIndicator(),
            for (final raw in (snapshot.data?['items'] as List? ?? []))
              Card(
                  child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                                '${raw['prompt_id']} · ${raw['owner']} · ${raw['status']}'),
                            Image.network(
                                widget.api.resolveUrl(
                                    '/api/v1/admin/prompt-reports/${raw['id']}/image'),
                                headers: widget.api.authorizationHeaders,
                                height: 240,
                                errorBuilder: (_, __, ___) =>
                                    const Text('图片不可用或当前安全策略不允许查看')),
                            SelectableText(
                                '${raw['snapshot']['prompt']['prompt']}'),
                            SelectableText('${raw['snapshot']['command']}'),
                            if (raw['status'] == 'pending')
                              Row(children: [
                                IconButton(
                                    tooltip: '移入垃圾库（需确认）',
                                    icon: const CourtyardIcon(
                                        Icons.delete_outline),
                                    onPressed: _busy.contains(raw['id']) ||
                                            (raw['prompt_id'] ?? '')
                                                .toString()
                                                .isEmpty
                                        ? null
                                        : () => _resolve(raw['id'], 'trash')),
                                IconButton(
                                    tooltip: '忽略举报（需确认）',
                                    icon: const CourtyardIcon(Icons.close),
                                    onPressed: _busy.contains(raw['id'])
                                        ? null
                                        : () => _resolve(raw['id'], 'dismiss')),
                              ])
                          ]))),
          ]));
}
