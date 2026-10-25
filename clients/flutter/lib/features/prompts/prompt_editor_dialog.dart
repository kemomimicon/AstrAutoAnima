import 'package:flutter/material.dart';

import '../../core/models.dart';
import '../../core/prompt_catalog.dart';

Future<Map<String, dynamic>?> showPromptEditor(
  BuildContext context, {
  PromptRecord? initial,
  Map<String, dynamic>? catalog,
  Future<void> Function(Map<String, dynamic>)? onSave,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    barrierDismissible: false,
    builder: (context) =>
        _PromptEditorDialog(initial: initial, catalog: catalog, onSave: onSave),
  );
}

class _PromptEditorDialog extends StatefulWidget {
  const _PromptEditorDialog({this.initial, this.catalog, this.onSave});

  final PromptRecord? initial;
  final Map<String, dynamic>? catalog;
  final Future<void> Function(Map<String, dynamic>)? onSave;

  @override
  State<_PromptEditorDialog> createState() => _PromptEditorDialogState();
}

class _PromptEditorDialogState extends State<_PromptEditorDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name =
      TextEditingController(text: widget.initial?.name ?? '');
  late final TextEditingController _prompt =
      TextEditingController(text: widget.initial?.prompt ?? '');
  late final TextEditingController _categories = TextEditingController(
    text: widget.initial?.categories.join(', ') ?? '',
  );
  late final TextEditingController _customGroups = TextEditingController(
    text: widget.initial?.customGroups.join(', ') ?? '',
  );
  late final TextEditingController _weight =
      TextEditingController(text: '${widget.initial?.weight ?? 1}');
  late String _source = widget.initial?.sourceCode ??
      (catalogRows(widget.catalog, 'editable_sources').firstOrNull?['id']
              as String? ??
          'G');
  late String _safety = widget.initial?.safetyCode ?? 'N';
  late bool _enabled = widget.initial?.enabled ?? true;
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _categories.dispose();
    _customGroups.dispose();
    _weight.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final value = <String, dynamic>{
      'name': _name.text.trim(),
      'prompt': _prompt.text.trim(),
      'source_code': _source,
      'safety_code': _safety,
      'enabled': _enabled,
      'weight': int.parse(_weight.text),
      'categories': _categories.text
          .split(RegExp(r'[,，\n]'))
          .map((value) => value.trim())
          .where((value) => value.isNotEmpty)
          .toList(),
      'custom_groups': _customGroups.text
          .split(RegExp(r'[,，\n]'))
          .map((value) => value.trim().toLowerCase())
          .where((value) => value.isNotEmpty)
          .toList(),
    };
    if (widget.onSave == null) {
      Navigator.pop(context, value);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave!(value);
      if (mounted) Navigator.pop(context, value);
    } catch (error) {
      if (mounted) setState(() => _error = '未保存：$error\n填写内容已保留，可复制提示词或核对后重试。');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sources = {
      for (final row in catalogRows(widget.catalog, 'editable_sources'))
        '${row['id']}': '${row['name']}',
      _source: catalogRows(widget.catalog, 'editable_sources')
              .where((row) => row['id'] == _source)
              .firstOrNull?['name'] as String? ??
          _source
    };
    return PopScope(
        canPop: !_saving,
        child: AlertDialog(
          insetPadding:
              const EdgeInsets.symmetric(horizontal: 12, vertical: 16),
          titlePadding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
          contentPadding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
          title: Text(widget.initial == null ? '新增提示词' : '编辑提示词',
              style: Theme.of(context).textTheme.titleLarge),
          content: SizedBox(
            width: 680,
            child: Form(
              key: _formKey,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextFormField(
                      controller: _name,
                      decoration: const InputDecoration(labelText: '显示名称（可选）'),
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _prompt,
                      minLines: 5,
                      maxLines: 10,
                      decoration: const InputDecoration(labelText: '提示词'),
                      validator: (value) =>
                          (value?.trim().isEmpty ?? true) ? '提示词不能为空' : null,
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          flex: 2,
                          child: DropdownButtonFormField<String>(
                            initialValue: _source,
                            decoration: const InputDecoration(labelText: '来源组'),
                            isExpanded: true,
                            items: sources.entries
                                .map((entry) => DropdownMenuItem(
                                    value: entry.key,
                                    child: Text(entry.value,
                                        overflow: TextOverflow.ellipsis)))
                                .toList(),
                            onChanged: (value) => _source = value ?? _source,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: DropdownButtonFormField<String>(
                            initialValue: _safety,
                            isExpanded: true,
                            decoration: const InputDecoration(labelText: '级别组'),
                            items: const ['N', 'H', 'S']
                                .map((value) => DropdownMenuItem(
                                    value: value, child: Text(value)))
                                .toList(),
                            onChanged: (value) => _safety = value ?? 'N',
                          ),
                        ),
                      ],
                    ),
                    ExpansionTile(
                      tilePadding: EdgeInsets.zero,
                      title: const Text('更多设置'),
                      subtitle: const Text('分组、标签、权重与启用状态'),
                      children: [
                        if (widget.initial != null)
                          SelectableText('编号：${widget.initial!.id}'),
                        SizedBox(
                          width: 120,
                          child: TextFormField(
                            controller: _weight,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(labelText: '权重'),
                            validator: (value) {
                              final parsed = int.tryParse(value ?? '');
                              return parsed == null ||
                                      parsed < 1 ||
                                      parsed > 100
                                  ? '1–100'
                                  : null;
                            },
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _categories,
                          decoration: const InputDecoration(
                            labelText: '分类标签',
                            hintText: 'rain, night, portrait',
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _customGroups,
                          decoration: const InputDecoration(
                            labelText: '自定义分组 ID（可选）',
                            hintText: 'my_fantasy, night_scene',
                          ),
                          validator: (value) {
                            for (final group
                                in (value ?? '').split(RegExp(r'[,，\n]'))) {
                              final id = group.trim().toLowerCase();
                              if (id.isNotEmpty &&
                                  !RegExp(r'^[a-z0-9][a-z0-9_-]{0,63}$')
                                      .hasMatch(id)) {
                                return '组 ID 仅能使用英文、数字、_、-';
                              }
                            }
                            return null;
                          },
                        ),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('启用此提示词'),
                          value: _enabled,
                          onChanged: (value) =>
                              setState(() => _enabled = value),
                        ),
                      ],
                    ),
                    if (_error != null)
                      Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: SelectableText(_error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error))),
                  ],
                ),
              ),
            ),
          ),
          actions: [
            TextButton(
                onPressed: _saving ? null : () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
                onPressed: _saving ? null : _submit,
                child: Text(_saving ? '保存中…' : '保存')),
          ],
        ));
  }
}
