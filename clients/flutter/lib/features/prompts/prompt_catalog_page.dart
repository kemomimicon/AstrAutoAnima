import 'dart:convert';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/prompt_catalog.dart';

class PromptCatalogPage extends StatefulWidget {
  const PromptCatalogPage({super.key, required this.api});
  final HubApi api;
  @override
  State<PromptCatalogPage> createState() => _PromptCatalogPageState();
}

class _PromptCatalogPageState extends State<PromptCatalogPage> {
  late Future<Map<String, dynamic>> _future = widget.api.getPromptCatalog();

  Future<void> _edit(
      Map<String, dynamic> row, Map<String, dynamic> catalog) async {
    final configuration =
        Map<String, dynamic>.from(catalog['configuration'] as Map);
    final original = catalogRows(configuration)
        .where((r) => r['id'] == row['id'])
        .firstOrNull;
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _SourceEditor(
          row: row,
          save: (value) async {
            // Merge unrelated source edits, but never overwrite this source's concurrent edit.
            for (var attempt = 0; attempt < 3; attempt++) {
              final latest = await widget.api.getPromptCatalog();
              final config =
                  Map<String, dynamic>.from(latest['configuration'] as Map);
              final rows = catalogRows(config);
              final current =
                  rows.where((r) => r['id'] == value['id']).firstOrNull;
              if (jsonEncode(current) != jsonEncode(original)) {
                throw const HubApiException('此来源规则已被修改，内容已保留；请复制后重新核对。');
              }
              rows.removeWhere((r) => r['id'] == value['id']);
              rows.add(value);
              try {
                await widget.api.savePromptCatalog(
                    revision: '${config['revision']}', sources: rows);
                return;
              } on HubApiException catch (error) {
                if (error.statusCode != 409 || attempt == 2) rethrow;
              }
            }
          }),
    );
    if (result == true && mounted) {
      setState(() => _future = widget.api.getPromptCatalog());
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('词库来源与规则')),
        body: FutureBuilder<Map<String, dynamic>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return Center(
                  child: TextButton(
                      onPressed: () => setState(
                          () => _future = widget.api.getPromptCatalog()),
                      child: const Text('读取失败，点击重试')));
            }
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            final data = snapshot.data!;
            if (data['configuration'] == null) {
              return const Center(child: Text('请先升级 Hub，旧服务器不支持动态规则管理。'));
            }
            final configured = catalogRows(
                Map<String, dynamic>.from(data['configuration'] as Map));
            final rows = <String, Map<String, dynamic>>{
              for (final r in catalogRows(data)) '${r['id']}': r,
              for (final r in catalogRows(data, 'editable_sources'))
                '${r['id']}': r,
              for (final r in configured) '${r['id']}': r,
            };
            return ListView(padding: const EdgeInsets.all(16), children: [
              const Text('仅修改当前服务器。名称与使用规则保存后按需同步，不需要重新安装客户端。'
                  '来源 ID 是旧指令兼容标识；自建分类请使用“自定义分组”。'
                  '允许级别是筛选范围，不会批量修改已有条目的分级，也不能解除群聊安全限制。'),
              const SizedBox(height: 12),
              for (final row in rows.values)
                Card(
                    child: ListTile(
                  title: Text('${row['name']} · ${row['id']}'),
                  subtitle: Text('${row['enabled'] == false ? '已停用' : '启用'}'
                      ' · ${catalogLevels(row).join('/')}'
                      ' · ${row['allow_group'] == false ? '禁止群聊' : '群聊按安全规则'}'),
                  trailing: const Icon(Icons.edit_outlined),
                  onTap: () => _edit(row, data),
                )),
            ]);
          },
        ),
      );
}

class _SourceEditor extends StatefulWidget {
  const _SourceEditor({required this.row, required this.save});
  final Map<String, dynamic> row;
  final Future<void> Function(Map<String, dynamic>) save;
  @override
  State<_SourceEditor> createState() => _SourceEditorState();
}

class _SourceEditorState extends State<_SourceEditor> {
  late final _name = TextEditingController(text: '${widget.row['name']}');
  late bool _enabled = widget.row['enabled'] != false;
  late bool _group = widget.row['allow_group'] != false;
  late bool _private = widget.row['allow_private'] != false;
  late Set<String> _levels = catalogLevels(widget.row).toSet();
  late String _default = '${widget.row['default_safety'] ?? 'N'}';
  bool _busy = false;
  String? _error;
  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty ||
        _levels.isEmpty ||
        !_levels.contains(_default)) {
      setState(() => _error = '请填写名称，并选择至少一种级别及其中的默认级别。');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.save({
        'id': widget.row['id'],
        'name': _name.text.trim(),
        'enabled': _enabled,
        'allow_group': _group,
        'allow_private': _private,
        'safety_codes': _levels.toList()..sort(),
        'default_safety': _default
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
      canPop: !_busy,
      child: AlertDialog(
        title: const Text('修改来源规则'),
        content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
                child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                    controller: _name,
                    maxLength: 100,
                    decoration: const InputDecoration(labelText: '显示名称')),
                SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('启用来源'),
                    value: _enabled,
                    onChanged: (v) => setState(() => _enabled = v)),
                CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('允许群聊（仍受安全规则限制）'),
                    value: _group,
                    onChanged: (v) => setState(() => _group = v ?? false)),
                CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('允许私聊 / 本机'),
                    value: _private,
                    onChanged: (v) => setState(() => _private = v ?? false)),
                Text(widget.row['id'] == 'V' ? '独立通常库内容级别（单选）' : '允许抽取的内容级别'),
                Wrap(spacing: 8, children: [
                  for (final code in ['N', 'H', 'S'])
                    FilterChip(
                        label: Text(code),
                        selected: _levels.contains(code),
                        onSelected: (value) => setState(() {
                              if (widget.row['id'] == 'V') {
                                _levels = {code};
                                _default = code;
                              } else {
                                value
                                    ? _levels.add(code)
                                    : _levels.remove(code);
                                if (!_levels.contains(_default) &&
                                    _levels.isNotEmpty) {
                                  _default = _levels.first;
                                }
                              }
                            })),
                ]),
                if (_levels.isNotEmpty)
                  DropdownButtonFormField<String>(
                      key: ValueKey('$_default${_levels.join()}'),
                      initialValue: _default,
                      decoration: const InputDecoration(labelText: '默认抽取级别'),
                      items: _levels
                          .map(
                              (c) => DropdownMenuItem(value: c, child: Text(c)))
                          .toList(),
                      onChanged: (v) => setState(() => _default = v!)),
                if (_error != null)
                  SelectableText(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
              ],
            ))),
        actions: [
          TextButton(
              onPressed: _busy ? null : () => Navigator.pop(context),
              child: const Text('取消')),
          FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_busy ? '保存中…' : '保存')),
        ],
      ));
}
