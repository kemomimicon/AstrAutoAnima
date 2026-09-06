import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import 'prompt_editor_dialog.dart';

class PromptLibraryPage extends StatefulWidget {
  const PromptLibraryPage({required this.api, super.key});

  final HubApi api;

  @override
  State<PromptLibraryPage> createState() => _PromptLibraryPageState();
}

class _PromptLibraryPageState extends State<PromptLibraryPage> {
  final _queryController = TextEditingController();
  String _source = '';
  String _safety = '';
  int _page = 1;
  late Future<PromptPageResult> _future = _load();

  Future<PromptPageResult> _load() => widget.api.getPrompts(
        source: _source,
        safety: _safety,
        query: _queryController.text.trim(),
        page: _page,
      );

  void _search({int page = 1}) {
    setState(() {
      _page = page;
      _future = _load();
    });
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

  Future<void> _runMutation(Future<MutationResult> Function() action) async {
    try {
      final result = await action();
      _notice('操作成功：${result.resource}');
      _search(page: _page);
    } on HubApiException catch (error) {
      _notice(
        error.statusCode == 409 ? '数据已被其他操作更新，正在刷新。' : error.message,
        error: true,
      );
      if (error.statusCode == 409) _search(page: _page);
    }
  }

  Future<void> _add(String revision) async {
    final value = await showPromptEditor(context);
    if (value == null) return;
    await _runMutation(
      () => widget.api.createPrompt(revision: revision, value: value),
    );
  }

  Future<void> _edit(PromptRecord item, String revision) async {
    final value = await showPromptEditor(context, initial: item);
    if (value == null) return;
    await _runMutation(
      () => widget.api.updatePrompt(
        id: item.id,
        revision: revision,
        value: value,
      ),
    );
  }

  Future<void> _delete(PromptRecord item, String revision) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除提示词'),
        content: Text('确定删除 ${item.id}？服务端会保留备份和回收站副本。'),
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
      () => widget.api.deletePrompt(id: item.id, revision: revision),
    );
  }

  Future<void> _import(String revision) async {
    final controller = TextEditingController();
    final raw = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('批量导入提示词'),
        content: SizedBox(
          width: 700,
          child: TextField(
            controller: controller,
            minLines: 12,
            maxLines: 20,
            decoration: const InputDecoration(
              labelText: 'JSON',
              hintText: '{"prompts": [{"prompt": "...", "source_code": "B"}]}',
            ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('导入'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (raw == null || raw.trim().isEmpty) return;
    try {
      final decoded = jsonDecode(raw);
      final records = decoded is List
          ? decoded
          : decoded is Map
              ? decoded['prompts']
              : null;
      if (records is! List) {
        throw const FormatException('必须是数组或包含 prompts 数组的对象');
      }
      final prompts = records
          .whereType<Map>()
          .map((value) => Map<String, dynamic>.from(value))
          .toList();
      if (prompts.isEmpty) {
        throw const FormatException('没有可导入的条目');
      }
      await _runMutation(
        () => widget.api.importPrompts(revision: revision, prompts: prompts),
      );
    } on FormatException catch (error) {
      _notice('JSON 格式错误：$error', error: true);
    }
  }

  Future<void> _export() async {
    try {
      final value = await widget.api.exportPrompts(
        source: _source,
        safety: _safety,
        query: _queryController.text.trim(),
      );
      await Clipboard.setData(ClipboardData(text: value));
      _notice('当前筛选结果已作为 JSON 复制到剪贴板');
    } on HubApiException catch (error) {
      _notice(error.message, error: true);
    }
  }

  @override
  void dispose() {
    _queryController.dispose();
    super.dispose();
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
                  Text('提示词库',
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 4),
                  const Text('分组检索、编辑、导入导出与安全删除'),
                ],
              ),
            ),
            OutlinedButton.icon(
              onPressed: _export,
              icon: const Icon(Icons.copy_all_outlined),
              label: const Text('导出并复制'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 12,
              runSpacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SizedBox(
                  width: 280,
                  child: TextField(
                    controller: _queryController,
                    decoration: const InputDecoration(
                      labelText: '编号、名称或提示词',
                      prefixIcon: Icon(Icons.search),
                    ),
                    onSubmitted: (_) => _search(),
                  ),
                ),
                SizedBox(
                  width: 150,
                  child: DropdownButtonFormField<String>(
                    initialValue: _source,
                    decoration: const InputDecoration(labelText: '来源组'),
                    items: const [
                      DropdownMenuItem(value: '', child: Text('全部')),
                      DropdownMenuItem(value: 'B', child: Text('B · Basic')),
                      DropdownMenuItem(value: 'G', child: Text('G · Generate')),
                      DropdownMenuItem(value: 'D', child: Text('D · Discord')),
                      DropdownMenuItem(value: 'C', child: Text('C · Codex')),
                      DropdownMenuItem(value: 'R', child: Text('R · Reverse')),
                      DropdownMenuItem(value: 'P', child: Text('P · Liked')),
                    ],
                    onChanged: (value) => _source = value ?? '',
                  ),
                ),
                SizedBox(
                  width: 150,
                  child: DropdownButtonFormField<String>(
                    initialValue: _safety,
                    decoration: const InputDecoration(labelText: '级别组'),
                    items: const [
                      DropdownMenuItem(value: '', child: Text('全部')),
                      DropdownMenuItem(value: 'N', child: Text('N · Normal')),
                      DropdownMenuItem(value: 'H', child: Text('H · NSFW')),
                      DropdownMenuItem(value: 'S', child: Text('S · Sexual')),
                    ],
                    onChanged: (value) => _safety = value ?? '',
                  ),
                ),
                FilledButton.icon(
                  onPressed: _search,
                  icon: const Icon(Icons.filter_alt_outlined),
                  label: const Text('查询'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        FutureBuilder<PromptPageResult>(
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
            return Column(
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text('共 ${data.total} 条'),
                    OutlinedButton.icon(
                      onPressed: () => _import(data.revision),
                      icon: const Icon(Icons.file_upload_outlined),
                      label: const Text('导入'),
                    ),
                    FilledButton.icon(
                      onPressed: () => _add(data.revision),
                      icon: const Icon(Icons.add),
                      label: const Text('新增'),
                    ),
                    IconButton(
                      onPressed: data.page > 1
                          ? () => _search(page: data.page - 1)
                          : null,
                      icon: const Icon(Icons.chevron_left),
                    ),
                    Text('${data.page} / ${data.pages}'),
                    IconButton(
                      onPressed: data.page < data.pages
                          ? () => _search(page: data.page + 1)
                          : null,
                      icon: const Icon(Icons.chevron_right),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                ...data.items.map(
                  (item) => _PromptCard(
                    item: item,
                    onEdit: () => _edit(item, data.revision),
                    onDelete: () => _delete(item, data.revision),
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _PromptCard extends StatelessWidget {
  const _PromptCard({
    required this.item,
    required this.onEdit,
    required this.onDelete,
  });

  final PromptRecord item;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: ExpansionTile(
          leading: CircleAvatar(
              child: Text('${item.sourceCode}/${item.safetyCode}')),
          title: Text(item.id),
          subtitle: Text(
            item.prompt,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          trailing: PopupMenuButton<String>(
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
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SelectableText(item.prompt),
                  if (item.categories.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 6,
                      children: item.categories
                          .map((value) => Chip(label: Text(value)))
                          .toList(),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
