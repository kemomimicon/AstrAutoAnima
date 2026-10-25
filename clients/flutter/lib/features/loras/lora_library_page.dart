import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import 'civitai_download_page.dart';
import 'lora_share_dialog.dart';

class LoraLibraryPage extends StatefulWidget {
  const LoraLibraryPage({required this.api, super.key});

  final HubApi api;

  @override
  State<LoraLibraryPage> createState() => _LoraLibraryPageState();
}

class _LoraLibraryPageState extends State<LoraLibraryPage> {
  late Future<LoraCatalogResult> _future = widget.api.getLoraCatalog();
  String _query = '';
  String _category = 'all';

  void _reload() {
    setState(() {
      _future = widget.api.getLoraCatalog();
    });
  }

  Future<void> _share(LoraCatalogItem item) async {
    await showLoraShareDialog(context, item);
  }

  Map<String, dynamic> _editable(LoraCatalogItem item) => {
        'display_name': item.displayName,
        'source_url': item.sourceUrl,
        'category': item.category,
        'recommended_prompt': item.recommendedPrompt,
        'enabled': item.enabled,
      };

  bool _matches(LoraCatalogItem item, Map<String, dynamic> value) =>
      _editable(item).entries.every((entry) => value[entry.key] == entry.value);

  Future<void> _edit(LoraCatalogItem item) async {
    final api = widget.api;
    final value = await showDialog<Map<String, dynamic>>(
      context: context,
      barrierDismissible: false,
      builder: (context) => _LoraEditor(
          item: item,
          onSave: (value) async {
            // Read a fresh catalog revision, but never overwrite changed metadata.
            final latest = await api.getLoraCatalog();
            if (!mounted || widget.api != api) {
              throw const HubApiException('连接已切换，未提交本次编辑。');
            }
            final matches = latest.items
                .where((row) => row.path == item.path && row.present);
            if (matches.isEmpty) {
              throw const HubApiException('该 LoRA 已移除，请取消编辑后重新扫描。',
                  statusCode: 409);
            }
            final current = matches.first;
            final alreadySaved = _matches(current, value);
            if (!alreadySaved && !_matches(current, _editable(item))) {
              throw const HubApiException(
                  '该 LoRA 已被其他操作修改，未覆盖。编辑内容仍保留，请取消后刷新并核对。',
                  statusCode: 409);
            }
            if (!alreadySaved) {
              await api.updateLora(
                  path: item.path, revision: latest.revision, value: value);
            }
            final saved = await api.getLoraCatalog();
            if (!saved.items.any((row) =>
                row.path == item.path && row.present && _matches(row, value))) {
              throw const HubApiException('保存后回读不一致，编辑内容已保留，请核对服务器记录。');
            }
            if (mounted && widget.api == api) {
              setState(() {
                _future = Future.value(saved);
              });
            }
          }),
    );
    if (value != null && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('LoRA 已保存并回读确认')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                  child: Text('LoRA 资产库',
                      style: Theme.of(context).textTheme.headlineSmall)),
              FilledButton.icon(
                  onPressed: _reload,
                  icon: const Icon(Icons.sync),
                  label: const Text('重新扫描')),
              IconButton(
                  tooltip: '从 Civitai 下载 LoRA',
                  icon: const Icon(Icons.cloud_download),
                  onPressed: () async {
                    await Navigator.of(context).push(MaterialPageRoute<void>(
                        builder: (_) => CivitaiDownloadPage(api: widget.api)));
                    if (mounted) _reload();
                  }),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
              '读取 ComfyUI/models/loras 下的 .safetensors。只有分类为“画风”的可被用户加入个人预设。'),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: TextField(
                  decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search), labelText: '搜索名称或目录'),
                  onChanged: (value) =>
                      setState(() => _query = value.trim().toLowerCase()),
                ),
              ),
              const SizedBox(width: 12),
              DropdownMenu<String>(
                initialSelection: _category,
                label: const Text('分类'),
                dropdownMenuEntries: const [
                  DropdownMenuEntry(value: 'all', label: '全部'),
                  DropdownMenuEntry(value: 'unclassified', label: '未分类'),
                  DropdownMenuEntry(value: 'style', label: '画风'),
                  DropdownMenuEntry(value: 'character', label: '角色'),
                  DropdownMenuEntry(value: 'other', label: '其他'),
                ],
                onSelected: (value) =>
                    setState(() => _category = value ?? 'all'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: FutureBuilder<LoraCatalogResult>(
              future: _future,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('读取失败：${snapshot.error}'));
                }
                final result = snapshot.data!;
                final items = result.items.where((item) {
                  final matchesCategory =
                      _category == 'all' || item.category == _category;
                  final haystack =
                      '${item.displayName}\n${item.path}'.toLowerCase();
                  return item.present &&
                      matchesCategory &&
                      (_query.isEmpty || haystack.contains(_query));
                }).toList();
                if (items.isEmpty) {
                  return const Center(child: Text('没有匹配的 LoRA。'));
                }
                return ListView.separated(
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final item = items[index];
                    return Card(
                      child: ListTile(
                        enabled: item.present,
                        leading: Icon(item.category == 'style'
                            ? Icons.palette_outlined
                            : item.category == 'character'
                                ? Icons.person_outline
                                : Icons.extension_outlined),
                        title: Text(item.displayName),
                        subtitle: Text(
                            '${_categoryLabel(item.category)} · ${item.path}${item.present ? '' : ' · 文件已移除'}\n${item.recommendedPrompt.isEmpty ? '未设置推荐触发词' : item.recommendedPrompt}',
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis),
                        isThreeLine: true,
                        trailing:
                            Row(mainAxisSize: MainAxisSize.min, children: [
                          IconButton(
                              tooltip: '分享链接和触发词',
                              icon: const Icon(Icons.share_outlined),
                              onPressed: () => _share(item)),
                          IconButton(
                              tooltip: '编辑 LoRA',
                              icon: const Icon(Icons.edit_outlined),
                              onPressed: () => _edit(item)),
                        ]),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  static String _categoryLabel(String value) =>
      const {
        'unclassified': '未分类',
        'style': '画风',
        'character': '角色',
        'other': '其他',
      }[value] ??
      value;
}

class _LoraEditor extends StatefulWidget {
  const _LoraEditor({required this.item, required this.onSave});
  final LoraCatalogItem item;
  final Future<void> Function(Map<String, dynamic>) onSave;

  @override
  State<_LoraEditor> createState() => _LoraEditorState();
}

class _LoraEditorState extends State<_LoraEditor> {
  late final _name = TextEditingController(text: widget.item.displayName);
  late final _source = TextEditingController(text: widget.item.sourceUrl);
  late final _prompt =
      TextEditingController(text: widget.item.recommendedPrompt);
  late String _category = widget.item.category;
  late bool _enabled = widget.item.enabled;
  bool _saving = false;
  String? _error;

  Future<void> _save() async {
    if (_saving || _name.text.trim().isEmpty) return;
    final value = <String, dynamic>{
      'display_name': _name.text.trim(),
      'source_url': _source.text.trim(),
      'category': _category,
      'recommended_prompt': _prompt.text.trim(),
      'enabled': _enabled,
    };
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave(value);
      if (mounted) {
        setState(() => _saving = false);
        await WidgetsBinding.instance.endOfFrame;
        if (mounted) Navigator.pop(context, value);
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is HubApiException
            ? (error.statusCode == 409
                ? '数据版本冲突；未强行覆盖。${error.message}'
                : error.message)
            : '保存未确认，编辑内容仍保留：$error');
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _source.dispose();
    _prompt.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
        canPop: !_saving,
        child: AlertDialog(
          title: const Text('编辑 LoRA'),
          content: SizedBox(
            width: 560,
            child: SingleChildScrollView(
              child: AbsorbPointer(
                  absorbing: _saving,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SelectableText(widget.item.path,
                          style: Theme.of(context).textTheme.bodySmall),
                      if (_error != null)
                        Text(_error!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      const SizedBox(height: 12),
                      TextField(
                          controller: _name,
                          decoration:
                              const InputDecoration(labelText: '客户端显示名称')),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _category,
                        decoration: const InputDecoration(labelText: '分类'),
                        items: const [
                          DropdownMenuItem(
                              value: 'unclassified', child: Text('未分类')),
                          DropdownMenuItem(value: 'style', child: Text('画风')),
                          DropdownMenuItem(
                              value: 'character', child: Text('角色')),
                          DropdownMenuItem(value: 'other', child: Text('其他')),
                        ],
                        onChanged: (value) =>
                            setState(() => _category = value ?? 'unclassified'),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                          controller: _source,
                          decoration: const InputDecoration(
                              labelText: '公开来源链接（分享用）',
                              helperText: 'Civitai 下载自动记录；其他来源手动填写，不填令牌或下载签名。'),
                          maxLines: 2),
                      const SizedBox(height: 12),
                      TextField(
                          controller: _prompt,
                          minLines: 3,
                          maxLines: 8,
                          decoration: const InputDecoration(
                              labelText: '推荐触发词',
                              hintText: '用户可一键追加到个人预设触发词框')),
                      SwitchListTile(
                          value: _enabled,
                          title: const Text('允许客户端使用'),
                          onChanged: (value) =>
                              setState(() => _enabled = value)),
                    ],
                  )),
            ),
          ),
          actions: [
            TextButton(
                onPressed: _saving ? null : () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: Text(_saving ? '保存并确认中…' : '保存'),
            ),
          ],
        ));
  }
}
