import 'package:flutter/material.dart';
import '../../core/hub_api.dart';

/// Catalog reads happen on entry, explicit refresh, or after management returns.
/// Do not poll the registry while the user is editing a prompt.
class PromptGroupSelector extends StatefulWidget {
  const PromptGroupSelector(
      {super.key,
      required this.api,
      required this.value,
      required this.onChanged,
      this.admin = false,
      this.forGeneration = false,
      this.privateTarget = false,
      this.revision = 0});
  final HubApi api;
  final String value;
  final ValueChanged<String> onChanged;
  final bool admin;
  final bool forGeneration;
  final bool privateTarget;
  final int revision;

  @override
  State<PromptGroupSelector> createState() => _PromptGroupSelectorState();
}

class _PromptGroupSelectorState extends State<PromptGroupSelector> {
  late Future<Map<String, dynamic>> _future = _load();
  Future<Map<String, dynamic>> _load() => widget.admin
      ? widget.api.getPromptGroups()
      : widget.api.getLitePromptGroups();
  @override
  void didUpdateWidget(covariant PromptGroupSelector oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api ||
        oldWidget.admin != widget.admin ||
        oldWidget.revision != widget.revision) {
      _future = _load();
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          final rows = <String, String>{};
          final blocked = <String>{};
          for (final row in (snapshot.data?['groups'] as List? ?? const [])
              .whereType<Map>()) {
            final id = '${row['id'] ?? ''}';
            if (id.isNotEmpty) {
              final allowed = row['allow_private'] == true;
              rows[id] =
                  '${row['name'] ?? id} · @$id${allowed ? '' : '（仅群聊抽取）'}';
              if (widget.forGeneration &&
                  (row['enabled'] == false ||
                      (widget.privateTarget && !allowed) ||
                      (!widget.privateTarget && row['allow_group'] == false))) {
                blocked.add(id);
              }
            }
          }
          if (widget.value.isNotEmpty && !rows.containsKey(widget.value)) {
            rows[widget.value] = '@${widget.value}（已选组暂不可用，请核对）';
            blocked.add(widget.value);
          }
          return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  key: ValueKey('custom-group-${widget.value}'),
                  initialValue: widget.value,
                  isExpanded: true,
                  decoration: InputDecoration(
                      labelText: '自定义提示词分组',
                      helperText: snapshot.hasError
                          ? '读取分组失败；原选择保留，可清空或重试'
                          : blocked.contains(widget.value)
                              ? '已选组已停用或不允许此目标，请更换组或投递目标'
                              : '可与来源、内容级别同时筛选；不影响主库分类'),
                  items: [
                    const DropdownMenuItem(value: '', child: Text('不限定自定义分组')),
                    ...rows.entries.map((e) => DropdownMenuItem(
                        value: e.key,
                        enabled: !blocked.contains(e.key),
                        child: Text(e.value)))
                  ],
                  onChanged: (value) => widget.onChanged(value ?? ''),
                ),
                if (snapshot.hasError)
                  TextButton(
                      onPressed: () => setState(() => _future = _load()),
                      child: const Text('重新读取分组')),
              ]);
        },
      );
}
