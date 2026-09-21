import 'package:flutter/material.dart';
import '../../core/hub_api.dart';

class VisualPresetFields extends StatefulWidget {
  const VisualPresetFields(
      {super.key,
      required this.api,
      required this.values,
      required this.onChanged});
  final HubApi api;
  final Map<String, String> values;
  final ValueChanged<Map<String, String>> onChanged;
  @override
  State<VisualPresetFields> createState() => _VisualPresetFieldsState();
}

class _VisualPresetFieldsState extends State<VisualPresetFields> {
  late Future<Map<String, dynamic>> _catalog = widget.api.getVisualPresets();
  static const slots = [
    ('lighting_key', '主光', 'lighting', 'key'),
    ('lighting_effect', '效果光', 'lighting', 'effect'),
    ('material_primary', '主材质', 'material', 'primary_material'),
    ('material_detail_1', '细节材质 1', 'material', 'detail_material'),
    ('material_detail_2', '细节材质 2', 'material', 'detail_material'),
    ('material_surface', '表面效果', 'material', 'surface_effect'),
  ];
  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: _catalog,
        builder: (context, snapshot) {
          if (!snapshot.hasData && !snapshot.hasError) {
            return const LinearProgressIndicator();
          }
          final data = snapshot.data;
          if (data == null || data['available'] != true) {
            return Column(children: [
              const Text('光影材质库无法读取。可重试或清空已选项；基础生图不受影响。'),
              TextButton(
                  onPressed: () =>
                      setState(() => _catalog = widget.api.getVisualPresets()),
                  child: const Text('重新读取')),
              TextButton(
                  onPressed: () => widget.onChanged({}),
                  child: const Text('清空光影材质')),
            ]);
          }
          final all = [
            ...(data['lighting'] as List? ?? []),
            ...(data['material'] as List? ?? [])
          ].whereType<Map>().toList();
          return Column(children: [
            for (final slot in slots)
              Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Builder(builder: (context) {
                    final rows = all
                        .where((r) =>
                            r['category'] == slot.$3 &&
                            (r['role'] ?? r['exclusive_group']) == slot.$4)
                        .toList();
                    final value = widget.values[slot.$1] ?? '';
                    final exists =
                        value.isEmpty || rows.any((r) => r['id'] == value);
                    return DropdownButtonFormField<String>(
                      key: ValueKey('${slot.$1}:$value'),
                      initialValue: value,
                      isExpanded: true,
                      decoration: InputDecoration(
                          labelText: slot.$2,
                          helperText: exists ? null : '此预设已失效，请重新选择'),
                      items: [
                        const DropdownMenuItem(value: '', child: Text('无')),
                        if (!exists)
                          DropdownMenuItem(
                              value: value, child: Text('失效：$value')),
                        for (final row in rows)
                          DropdownMenuItem(
                              value: '${row['id']}',
                              child: Text(
                                  '${row['name_zh'] ?? row['name'] ?? row['id']}',
                                  overflow: TextOverflow.ellipsis)),
                      ],
                      onChanged: (selected) {
                        final next = {
                          ...widget.values,
                          slot.$1: selected ?? ''
                        };
                        final ids =
                            next.values.where((v) => v.isNotEmpty).toSet();
                        final conflict = all.any((row) =>
                            ids.contains(row['id']) &&
                            (row['avoid_with'] as List? ?? [])
                                .any(ids.contains));
                        if (conflict) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text('所选光影／材质存在冲突，请先将冲突项设为“无”')));
                          return;
                        }
                        widget.onChanged(next);
                      },
                    );
                  })),
          ]);
        },
      );
}
