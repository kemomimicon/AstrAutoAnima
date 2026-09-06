import 'package:flutter/material.dart';

import '../../core/models.dart';

Future<Map<String, dynamic>?> showPresetEditor(
  BuildContext context, {
  required String kind,
  PresetSummary? initial,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (context) => _PresetEditorDialog(kind: kind, initial: initial),
  );
}

class _PresetEditorDialog extends StatefulWidget {
  const _PresetEditorDialog({required this.kind, this.initial});

  final String kind;
  final PresetSummary? initial;

  @override
  State<_PresetEditorDialog> createState() => _PresetEditorDialogState();
}

class _PresetEditorDialogState extends State<_PresetEditorDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name =
      TextEditingController(text: widget.initial?.name ?? '');
  late final TextEditingController _prompt =
      TextEditingController(text: widget.initial?.prompt ?? '');
  late final TextEditingController _match = TextEditingController(
    text: widget.initial?.match.join(' | ') ?? '',
  );
  late final TextEditingController _loras = TextEditingController(
    text: widget.initial?.loras.map((item) {
          final model = item['strength_model'] ?? 1.0;
          final clip = item['strength_clip'] ?? model;
          return '${item['name'] ?? ''}|$model|$clip';
        }).join('\n') ??
        '',
  );
  String? _parseError;

  bool get _isStyle => widget.kind == 'style';

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _match.dispose();
    _loras.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> _parseLoras() {
    final result = <Map<String, dynamic>>[];
    for (final raw in _loras.text.split('\n')) {
      final line = raw.trim();
      if (line.isEmpty) continue;
      final parts = line.split('|').map((value) => value.trim()).toList();
      if (parts.length > 3 || parts.first.isEmpty) {
        throw const FormatException('LoRA 格式应为 文件名|model|clip');
      }
      final model = parts.length >= 2 && parts[1].isNotEmpty
          ? double.tryParse(parts[1])
          : 1.0;
      final clip = parts.length >= 3 && parts[2].isNotEmpty
          ? double.tryParse(parts[2])
          : model;
      if (model == null ||
          clip == null ||
          model < -5 ||
          model > 5 ||
          clip < -5 ||
          clip > 5) {
        throw const FormatException('LoRA 权重必须是 -5 到 5 的数字');
      }
      result.add({
        'name': parts.first,
        'strength_model': model,
        'strength_clip': clip,
      });
    }
    if (_isStyle && result.isEmpty) {
      throw const FormatException('画风预设至少需要一个 LoRA');
    }
    if (!_isStyle && result.length > 1) {
      throw const FormatException('角色预设最多只能使用一个 LoRA');
    }
    if (!_isStyle && result.isEmpty && _prompt.text.trim().isEmpty) {
      throw const FormatException('无 LoRA 的底模角色必须填写固定提示词');
    }
    return result;
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    try {
      final loras = _parseLoras();
      Navigator.pop(context, {
        'name': _name.text.trim(),
        'prompt': _prompt.text.trim(),
        'match': _isStyle
            ? _match.text
                .split(RegExp(r'[|｜\n]'))
                .map((value) => value.trim())
                .where((value) => value.isNotEmpty)
                .toList()
            : <String>[],
        'loras': loras,
      });
    } on FormatException catch (error) {
      setState(() => _parseError = error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = _isStyle ? '画风' : '角色';
    return AlertDialog(
      title: Text(widget.initial == null ? '新增$title预设' : '编辑$title预设'),
      content: SizedBox(
        width: 700,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _name,
                  decoration: InputDecoration(labelText: '$title名称'),
                  validator: (value) =>
                      (value?.trim().isEmpty ?? true) ? '名称不能为空' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _prompt,
                  minLines: 3,
                  maxLines: 8,
                  decoration: const InputDecoration(labelText: '固定提示词'),
                ),
                if (_isStyle) ...[
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _match,
                    decoration: const InputDecoration(
                      labelText: '自动匹配触发词',
                      hintText: '@soft_style | soft_style',
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                TextFormField(
                  controller: _loras,
                  minLines: 4,
                  maxLines: 12,
                  decoration: InputDecoration(
                    labelText: _isStyle ? 'LoRA 列表（每行一个）' : '角色 LoRA（可留空）',
                    hintText: 'anima_lora/name/model.safetensors|0.8|0.8',
                  ),
                ),
                if (_parseError != null) ...[
                  const SizedBox(height: 10),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      _parseError!,
                      style:
                          TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                  ),
                ],
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
