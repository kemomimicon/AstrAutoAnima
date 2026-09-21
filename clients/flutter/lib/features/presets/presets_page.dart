import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import 'preset_editor_dialog.dart';

class PresetsPage extends StatefulWidget {
  const PresetsPage({required this.api, super.key});

  final HubApi api;

  @override
  State<PresetsPage> createState() => _PresetsPageState();
}

class _PresetsPageState extends State<PresetsPage> {
  late Future<PresetListResult> _future = widget.api.getPresets();
  int _segment = 0;
  String _search = '';
  final _searchController = TextEditingController();
  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _verifySaved(String kind, Map<String, dynamic> value) async {
    final data = await widget.api.getPresets();
    final items = kind == 'style' ? data.styles : data.characters;
    if (!items.any((p) =>
        p.name == value['name'] &&
        p.prompt ==
            (value['prompt'] as String)
                .trim()
                .replaceAll(RegExp(r'^[,\s]+|[,\s]+$'), ''))) {
      throw const FormatException('服务器回读未找到刚保存的预设，请检查写入/读取路径或并发修改');
    }
    if (mounted) {
      setState(() {
        _future = Future.value(data);
        _search = '';
        _searchController.clear();
      });
    }
  }

  void _refresh() {
    setState(() => _future = widget.api.getPresets());
  }

  void _notice(String message, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error ? Theme.of(context).colorScheme.error : null,
      ),
    );
  }

  String get _kind => _segment == 0 ? 'style' : 'character';

  Future<void> _runMutation(Future<MutationResult> Function() action) async {
    try {
      final result = await action();
      _notice('操作成功：${result.resource}');
      _refresh();
    } on HubApiException catch (error) {
      _notice(
        error.message,
        error: true,
      );
      if (error.statusCode == 409) _refresh();
    }
  }

  Future<void> _add() async {
    final kind = _kind;
    final value = await showPresetEditor(context, kind: kind, api: widget.api,
        onSave: (value) async {
      // Creation does not overwrite an existing preset. Read a fresh revision
      // on every explicit save attempt, rather than capturing the page's old
      // revision for the entire lifetime of this dialog. The server still
      // checks both duplicate names and writes racing this GET.
      final latest = await widget.api.getPresets();
      final items = kind == 'style' ? latest.styles : latest.characters;
      if (items.any((item) => item.name == value['name'])) {
        throw const FormatException('同名预设已存在，请更换名称或取消后编辑原预设；未覆盖原内容');
      }
      await widget.api
          .createPreset(kind: kind, revision: latest.revision, value: value);
      await _verifySaved(kind, value);
    });
    if (value != null) _notice('保存并回读确认成功：${value['name']}');
  }

  Future<void> _edit(PresetSummary item, String revision) async {
    final value = await showPresetEditor(context,
        kind: item.kind, initial: item, api: widget.api, onSave: (value) async {
      await widget.api.updatePreset(
          kind: item.kind,
          originalName: item.name,
          revision: revision,
          value: value);
      await _verifySaved(item.kind, value);
    });
    if (value != null) _notice('保存并回读确认成功：${value['name']}');
  }

  Future<void> _delete(PresetSummary item, String revision) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除预设'),
        content: Text('确定删除 ${item.name}？服务端会保留备份和回收站副本。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _runMutation(
      () => widget.api.deletePreset(
        kind: item.kind,
        name: item.name,
        revision: revision,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('角色与画风',
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 4),
                  const Text('查看 LoRA、固定提示词和自动匹配串'),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip: '刷新',
              onPressed: _refresh,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        const SizedBox(height: 20),
        SegmentedButton<int>(
          segments: const [
            ButtonSegment(
                value: 0, icon: Icon(Icons.brush_outlined), label: Text('画风')),
            ButtonSegment(
                value: 1, icon: Icon(Icons.face_outlined), label: Text('角色')),
          ],
          selected: {_segment},
          onSelectionChanged: (value) => setState(() => _segment = value.first),
        ),
        const SizedBox(height: 16),
        TextField(
            controller: _searchController,
            decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                labelText: '搜索预设名称、LoRA、提示词或匹配词',
                border: OutlineInputBorder()),
            onChanged: (value) =>
                setState(() => _search = value.trim().toLowerCase())),
        const SizedBox(height: 16),
        FutureBuilder<PresetListResult>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(
                child: Padding(
                  padding: EdgeInsets.all(48),
                  child: CircularProgressIndicator(),
                ),
              );
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final data = snapshot.data!;
            final items = (_segment == 0 ? data.styles : data.characters)
                .where((item) =>
                    '${item.name} ${item.prompt} ${item.match.join(' ')} ${item.loras.map((l) => l['name']).join(' ')}'
                        .toLowerCase()
                        .contains(_search))
                .toList();
            return Column(
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton.icon(
                    onPressed: _add,
                    icon: const Icon(Icons.add),
                    label: Text('新增${_segment == 0 ? '画风' : '角色'}'),
                  ),
                ),
                const SizedBox(height: 12),
                if (items.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(48),
                    child: Center(child: Text('暂无预设')),
                  )
                else
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final columns = constraints.maxWidth >= 900
                          ? 3
                          : constraints.maxWidth >= 580
                              ? 2
                              : 1;
                      final width =
                          (constraints.maxWidth - (columns - 1) * 12) / columns;
                      return Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        children: items
                            .map(
                              (item) => SizedBox(
                                width: width,
                                child: _PresetCard(
                                  item: item,
                                  onEdit: () => _edit(item, data.revision),
                                  onDelete: () => _delete(item, data.revision),
                                ),
                              ),
                            )
                            .toList(),
                      );
                    },
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _PresetCard extends StatelessWidget {
  const _PresetCard({
    required this.item,
    required this.onEdit,
    required this.onDelete,
  });

  final PresetSummary item;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(item.kind == 'style' ? Icons.brush : Icons.face),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(item.name,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                if (item.textOnly)
                  const Tooltip(
                    message: '底模直出角色',
                    child: Icon(Icons.text_fields, size: 18),
                  ),
                PopupMenuButton<String>(
                  onSelected: (value) {
                    if (value == 'edit') {
                      onEdit();
                    } else {
                      onDelete();
                    }
                  },
                  itemBuilder: (context) => const [
                    PopupMenuItem(value: 'edit', child: Text('编辑')),
                    PopupMenuItem(value: 'delete', child: Text('删除')),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 14),
            Text(
              item.prompt.isEmpty ? '未配置固定提示词' : item.prompt,
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                Chip(label: Text('${item.loras.length} LoRA')),
                ...item.match.take(2).map((value) => Chip(label: Text(value))),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
