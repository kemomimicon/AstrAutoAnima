import '../../core/courtyard_theme.dart';
import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import '../../core/prompt_catalog.dart';
import 'lite_prompt_details_dialog.dart';
import '../prompts/prompt_group_selector.dart';

class LitePromptLibraryPage extends StatefulWidget {
  const LitePromptLibraryPage({required this.api, super.key});

  final HubApi api;

  @override
  State<LitePromptLibraryPage> createState() => _LitePromptLibraryPageState();
}

class _LitePromptLibraryPageState extends State<LitePromptLibraryPage> {
  final _queryController = TextEditingController();
  String _source = '';
  String _safety = '';
  String _customGroup = '';
  int _groupsRevision = 0;
  int _page = 1;
  late Future<PromptPageResult> _future = _load();
  Map<String, dynamic>? _catalog;
  @override
  void initState() {
    super.initState();
    _loadCatalog();
  }

  @override
  void didUpdateWidget(covariant LitePromptLibraryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) {
      _catalog = null;
      _source = _safety = _customGroup = '';
      _queryController.clear();
      _page = 1;
      _future = _load();
      _loadCatalog();
    }
  }

  Future<void> _loadCatalog() async {
    final api = widget.api;
    try {
      final catalog = await api.getPromptCatalog();
      if (mounted && widget.api == api) setState(() => _catalog = catalog);
    } catch (_) {
      // Keep the current filter and the user's text. Server still validates all reads.
    }
  }

  Future<PromptPageResult> _load() => widget.api.getLitePrompts(
        source: _source,
        safety: _safety,
        query: _queryController.text.trim(),
        customGroups: _customGroup.isEmpty ? const [] : [_customGroup],
        page: _page,
      );

  void _refresh({int? page}) {
    _loadCatalog();
    setState(() {
      _page = page ?? 1;
      _future = _load();
    });
  }

  Future<void> _favorite(PromptRecord item) async {
    try {
      if (item.sourceCode == 'P') {
        await widget.api.unfavoritePrompt(item.id);
      } else {
        await widget.api.favoritePrompt(item.id);
      }
      if (mounted) _refresh(page: _page);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  @override
  void dispose() {
    _queryController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<PromptPageResult>(
      future: _future,
      builder: (context, snapshot) => ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('提示词浏览', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 4),
          const Text('只读同步工作站中当前启用的提示词'),
          const SizedBox(height: 18),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Wrap(
                spacing: 12,
                runSpacing: 12,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  SizedBox(
                    width: 300,
                    child: TextField(
                      controller: _queryController,
                      decoration: const InputDecoration(labelText: '编号、名称或提示词'),
                      onSubmitted: (_) => _refresh(),
                    ),
                  ),
                  SizedBox(
                    width: 150,
                    child: DropdownButtonFormField<String>(
                      initialValue: _source,
                      decoration: const InputDecoration(labelText: '来源'),
                      key: ValueKey('$_source-${_catalog?['revision']}'),
                      isExpanded: true,
                      items: {
                        '': '全部',
                        for (final row in catalogRows(_catalog))
                          if (row['browseable'] == true)
                            '${row['id']}': '${row['name']}',
                        if (_source.isNotEmpty &&
                            !catalogRows(_catalog)
                                .any((r) => r['id'] == _source))
                          _source: '$_source（已选来源）',
                      }
                          .entries
                          .map((row) => DropdownMenuItem(
                              value: row.key,
                              child: Text(row.value,
                                  overflow: TextOverflow.ellipsis)))
                          .toList(),
                      onChanged: (value) {
                        _source = value ?? '';
                        _refresh();
                      },
                    ),
                  ),
                  SizedBox(
                    width: 150,
                    child: DropdownButtonFormField<String>(
                      initialValue: _safety,
                      decoration: const InputDecoration(labelText: '分级'),
                      items: ['', 'N', 'H', 'S']
                          .map((value) => DropdownMenuItem(
                              value: value,
                              child: Text(value.isEmpty ? '全部' : value)))
                          .toList(),
                      onChanged: (value) {
                        _safety = value ?? '';
                        _refresh();
                      },
                    ),
                  ),
                  FilledButton.tonalIcon(
                      onPressed: () {
                        _groupsRevision++;
                        _refresh();
                      },
                      icon: const CourtyardIcon(Icons.search),
                      label: const Text('查询')),
                  SizedBox(
                      width: 320,
                      child: PromptGroupSelector(
                          api: widget.api,
                          value: _customGroup,
                          revision: _groupsRevision,
                          onChanged: (value) {
                            _customGroup = value;
                            _refresh();
                          })),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          if (snapshot.connectionState == ConnectionState.waiting)
            const Center(
                child: Padding(
                    padding: EdgeInsets.all(40),
                    child: CircularProgressIndicator()))
          else if (snapshot.hasError)
            Card(
                child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Text('读取失败：${snapshot.error}')))
          else if (snapshot.data case final data?) ...[
            Text('共 ${data.total} 条 · 第 ${data.page}/${data.pages} 页'),
            const SizedBox(height: 10),
            ...data.items.map(
              (item) => Card(
                child: ListTile(
                  onTap: () => showLitePromptDetailsDialog(context, item),
                  title: Text(item.name.isEmpty
                      ? (item.originalId.isEmpty ? item.id : item.originalId)
                      : '${item.originalId.isEmpty ? item.id : item.originalId} · ${item.name}'),
                  subtitle: Text(item.prompt,
                      maxLines: 3, overflow: TextOverflow.ellipsis),
                  trailing: Wrap(
                    spacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Chip(
                          label: Text(item.isUnreviewedOfflineScene
                              ? '${item.sourceCode} · 未审核'
                              : '${item.sourceCode}/${item.safetyCode}')),
                      IconButton(
                          tooltip: item.sourceCode == 'P' ? '取消收藏' : '点赞收藏',
                          onPressed: () => _favorite(item),
                          icon: CourtyardIcon(item.sourceCode == 'P'
                              ? Icons.thumb_up
                              : Icons.thumb_up_outlined)),
                      const Tooltip(
                        message: '查看完整提示词',
                        child: CourtyardIcon(Icons.open_in_new),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton.filledTonal(
                  onPressed: data.page > 1
                      ? () => _refresh(page: data.page - 1)
                      : null,
                  icon: const CourtyardIcon(Icons.chevron_left),
                ),
                const SizedBox(width: 16),
                Text('${data.page} / ${data.pages}'),
                const SizedBox(width: 16),
                IconButton.filledTonal(
                  onPressed: data.page < data.pages
                      ? () => _refresh(page: data.page + 1)
                      : null,
                  icon: const CourtyardIcon(Icons.chevron_right),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
