import 'package:flutter/material.dart';

import '../../core/models.dart';

Future<Map<String, dynamic>?> showPromptEditor(
  BuildContext context, {
  PromptRecord? initial,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (context) => _PromptEditorDialog(initial: initial),
  );
}

class _PromptEditorDialog extends StatefulWidget {
  const _PromptEditorDialog({this.initial});

  final PromptRecord? initial;

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
  late final TextEditingController _weight =
      TextEditingController(text: '${widget.initial?.weight ?? 1}');
  late String _source = widget.initial?.sourceCode ?? 'B';
  late String _safety = widget.initial?.safetyCode ?? 'N';
  late bool _enabled = widget.initial?.enabled ?? true;

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _categories.dispose();
    _weight.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    Navigator.pop(context, {
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
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title:
          Text(widget.initial == null ? '新增提示词' : '编辑 ${widget.initial!.id}'),
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
                  minLines: 7,
                  maxLines: 14,
                  decoration: const InputDecoration(labelText: '提示词'),
                  validator: (value) =>
                      (value?.trim().isEmpty ?? true) ? '提示词不能为空' : null,
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    SizedBox(
                      width: 180,
                      child: DropdownButtonFormField<String>(
                        initialValue: _source,
                        decoration: const InputDecoration(labelText: '来源组'),
                        items: const ['B', 'G', 'D', 'C', 'R']
                            .map((value) => DropdownMenuItem(
                                value: value, child: Text(value)))
                            .toList(),
                        onChanged: (value) => _source = value ?? 'B',
                      ),
                    ),
                    SizedBox(
                      width: 180,
                      child: DropdownButtonFormField<String>(
                        initialValue: _safety,
                        decoration: const InputDecoration(labelText: '级别组'),
                        items: const ['N', 'H', 'S']
                            .map((value) => DropdownMenuItem(
                                value: value, child: Text(value)))
                            .toList(),
                        onChanged: (value) => _safety = value ?? 'N',
                      ),
                    ),
                    SizedBox(
                      width: 120,
                      child: TextFormField(
                        controller: _weight,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(labelText: '权重'),
                        validator: (value) {
                          final parsed = int.tryParse(value ?? '');
                          return parsed == null || parsed < 1 || parsed > 100
                              ? '1–100'
                              : null;
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _categories,
                  decoration: const InputDecoration(
                    labelText: '分类标签',
                    hintText: 'rain, night, portrait',
                  ),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('启用此提示词'),
                  value: _enabled,
                  onChanged: (value) => setState(() => _enabled = value),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: _submit, child: const Text('保存')),
      ],
    );
  }
}
