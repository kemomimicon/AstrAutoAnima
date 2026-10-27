import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import '../../core/prompt_catalog.dart';
import '../../core/read_recovery.dart';
import 'prompt_editor_dialog.dart';
import 'prompt_groups_page.dart';
import 'prompt_group_selector.dart';
import 'prompt_catalog_page.dart';

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
  String _customGroup = '';
  int _groupsRevision = 0;
  int _page = 1;
  late Future<PromptPageResult> _future = _load();
  Map<String, dynamic>? _catalog;
  String? _catalogError;
  late final _pageRecovery = ReadRecovery(() => _search(page: _page));
  late final _catalogRecovery = ReadRecovery(_loadCatalog);

  @override
  void initState() {
    super.initState();
    _loadCatalog();
  }

  @override
  void didUpdateWidget(covariant PromptLibraryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) {
      _pageRecovery.succeeded();
      _catalogRecovery.succeeded();
      _catalog = null;
      _source = _safety = _customGroup = '';
      _queryController.clear();
      _page = 1;
      _future = _load();
      _loadCatalog();
    }
  }

  Future<void> _loadCatalog() async {
    _catalogRecovery.begin();
    final api = widget.api;
    try {
      final value = await api.getPromptCatalog();
      if (mounted && widget.api == api) {
        _catalogRecovery.succeeded();
        setState(() {
          _catalog = value;
          _catalogError = null;
        });
      }
    } catch (error) {
      if (mounted && widget.api == api) {
        _catalogRecovery.failed(error);
        setState(() => _catalogError = '词库配置读取失败，未采用其他实例的选项');
      }
    }
  }

  Future<PromptPageResult> _load() async {
    final api = widget.api;
    _pageRecovery.begin();
    try {
      final result = await api.getPrompts(
        source: _source,
        safety: _safety,
        query: _queryController.text.trim(),
        customGroups: _customGroup.isEmpty ? const [] : [_customGroup],
        page: _page,
      );
      if (mounted && widget.api == api) _pageRecovery.succeeded();
      return result;
    } catch (error) {
      if (mounted && widget.api == api) _pageRecovery.failed(error);
      rethrow;
    }
  }

  void _search({int page = 1}) {
    _loadCatalog();
    setState(() {
      _groupsRevision++;
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
    final api = widget.api;
    final value = await showPromptEditor(context, catalog: _catalog,
        onSave: (value) async {
      if (widget.api != api) {
        throw const HubApiException('连接已切换，请返回当前实例后再保存');
      }
      await api.createPrompt(revision: revision, value: value);
    });
    if (value != null && mounted) {
      _notice('提示词已保存');
      _search(page: _page);
    }
  }

  Future<void> _edit(PromptRecord item, String revision) async {
    final api = widget.api;
    final value = await showPromptEditor(context,
        initial: item, catalog: _catalog, onSave: (value) async {
      if (widget.api != api) {
        throw const HubApiException('连接已切换，请返回当前实例后再保存');
      }
      await api.updatePrompt(id: item.id, revision: revision, value: value);
    });
    if (value != null && mounted) {
      _notice('提示词已保存');
      _search(page: _page);
    }
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
        customGroups: _customGroup.isEmpty ? const [] : [_customGroup],
      );
      await Clipboard.setData(ClipboardData(text: value));
      _notice('当前筛选结果已作为 JSON 复制到剪贴板');
    } on HubApiException catch (error) {
      _notice(error.message, error: true);
    }
  }

  Future<void> _openWithRevision(Future<void> Function(String) action) async {
    final api = widget.api;
    try {
      final data = await _future;
      if (mounted && widget.api == api) await action(data.revision);
    } catch (error) {
      _notice('词库尚未加载成功，请刷新后重试：$error', error: true);
    }
  }

  @override
  void dispose() {
    _pageRecovery.dispose();
    _catalogRecovery.dispose();
    _queryController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 700;
    final sourceNames = {
      '': '全部来源',
      for (final row in catalogRows(_catalog, 'editable_sources'))
        '${row['id']}': '${row['name']}',
      if (_source.isNotEmpty &&
          !catalogRows(_catalog, 'editable_sources')
              .any((r) => r['id'] == _source))
        _source: '$_source（已选来源）',
    };
    return ListView(
      key: const PageStorageKey('admin-prompt-library'),
      padding: EdgeInsets.all(compact ? 12 : 24),
      children: [
        Row(
          children: [
            Expanded(
              child:
                  Text('提示词库', style: Theme.of(context).textTheme.titleLarge),
            ),
            FilledButton.icon(
              onPressed: () => _openWithRevision(_add),
              icon: const Icon(Icons.add, size: 18),
              label: const Text('新增'),
            ),
            PopupMenuButton<String>(
              tooltip: '词库操作',
              onSelected: (action) async {
                if (action == 'export') {
                  await _export();
                  return;
                }
                if (action == 'import') {
                  await _openWithRevision(_import);
                  return;
                }
                await Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => action == 'catalog'
                        ? PromptCatalogPage(api: widget.api)
                        : PromptGroupsPage(api: widget.api)));
                if (mounted) {
                  setState(() => _groupsRevision++);
                  _loadCatalog();
                }
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'groups', child: Text('自定义分组')),
                PopupMenuItem(value: 'catalog', child: Text('来源名称与使用规则')),
                PopupMenuItem(value: 'import', child: Text('导入提示词')),
                PopupMenuItem(value: 'export', child: Text('导出并复制')),
              ],
            ),
          ],
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _queryController,
          decoration: InputDecoration(
              isDense: true,
              hintText: '搜索编号、名称或提示词',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: IconButton(
                  tooltip: '查询',
                  onPressed: () => _search(),
                  icon: const Icon(Icons.arrow_forward))),
          onSubmitted: (_) => _search(),
        ),
        if (_catalogError != null)
          TextButton(
              onPressed: _loadCatalog, child: Text('$_catalogError · 重试')),
        Card(
          child: ExpansionTile(
            key: const PageStorageKey('prompt-filters'),
            initiallyExpanded: !compact,
            title: const Text('筛选'),
            subtitle: Text([
              if (_source.isNotEmpty) sourceNames[_source]!,
              if (_safety.isNotEmpty) _safety,
              if (_customGroup.isNotEmpty) '@$_customGroup'
            ].join(' · ').isEmpty
                ? '全部提示词'
                : [
                    if (_source.isNotEmpty) sourceNames[_source]!,
                    if (_safety.isNotEmpty) _safety,
                    if (_customGroup.isNotEmpty) '@$_customGroup'
                  ].join(' · ')),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    SizedBox(
                      width: 150,
                      child: DropdownButtonFormField<String>(
                        initialValue: _source,
                        key: ValueKey(
                            'source-$_source-${_catalog?['revision']}'),
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: '来源组'),
                        items: sourceNames.entries
                            .map((r) => DropdownMenuItem(
                                value: r.key,
                                child: Text(r.value,
                                    overflow: TextOverflow.ellipsis)))
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _source = value ?? ''),
                      ),
                    ),
                    SizedBox(
                      width: 150,
                      child: DropdownButtonFormField<String>(
                        initialValue: _safety,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: '级别组'),
                        items: const [
                          DropdownMenuItem(value: '', child: Text('全部')),
                          DropdownMenuItem(value: 'N', child: Text('N · 健康')),
                          DropdownMenuItem(value: 'H', child: Text('H · 敏感')),
                          DropdownMenuItem(value: 'S', child: Text('S · 成人')),
                        ],
                        onChanged: (value) =>
                            setState(() => _safety = value ?? ''),
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: () {
                        _groupsRevision++;
                        _search();
                      },
                      icon: const Icon(Icons.filter_alt_outlined),
                      label: const Text('查询'),
                    ),
                    SizedBox(
                        width: compact
                            ? MediaQuery.sizeOf(context).width - 64
                            : 320,
                        child: PromptGroupSelector(
                            api: widget.api,
                            admin: true,
                            value: _customGroup,
                            revision: _groupsRevision,
                            onChanged: (value) =>
                                setState(() => _customGroup = value))),
                  ],
                ),
              )
            ],
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
          // Expansion state must not share the list's stored scroll offset.
          key: PageStorageKey<String>('prompt-card-${item.id}'),
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
                  if (item.customGroups.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Wrap(
                        spacing: 6,
                        children: item.customGroups
                            .map((value) => Chip(label: Text('@$value')))
                            .toList()),
                  ],
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
