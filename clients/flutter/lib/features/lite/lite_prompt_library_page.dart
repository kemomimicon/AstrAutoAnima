import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import 'lite_prompt_details_dialog.dart';

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
  int _page = 1;
  late Future<PromptPageResult> _future = _load();

  Future<PromptPageResult> _load() => widget.api.getLitePrompts(
        source: _source,
        safety: _safety,
        query: _queryController.text.trim(),
        page: _page,
      );

  void _refresh({int? page}) {
    setState(() {
      _page = page ?? 1;
      _future = _load();
    });
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
                      items: ['', 'B', 'G', 'D', 'C', 'R', 'P']
                          .map((value) => DropdownMenuItem(
                              value: value,
                              child: Text(value.isEmpty ? '全部' : value)))
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
                      onPressed: _refresh,
                      icon: const Icon(Icons.search),
                      label: const Text('查询')),
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
                      ? item.id
                      : '${item.id} · ${item.name}'),
                  subtitle: Text(item.prompt,
                      maxLines: 3, overflow: TextOverflow.ellipsis),
                  trailing: Wrap(
                    spacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Chip(
                          label: Text('${item.sourceCode}/${item.safetyCode}')),
                      const Tooltip(
                        message: '查看完整提示词',
                        child: Icon(Icons.open_in_new),
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
                  icon: const Icon(Icons.chevron_left),
                ),
                const SizedBox(width: 16),
                Text('${data.page} / ${data.pages}'),
                const SizedBox(width: 16),
                IconButton.filledTonal(
                  onPressed: data.page < data.pages
                      ? () => _refresh(page: data.page + 1)
                      : null,
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
