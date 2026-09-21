import 'package:flutter/material.dart';

import '../../core/models.dart';
import '../../core/hub_api.dart';
import 'palette_dialog.dart';
import 'character_variants_editor.dart';

Future<Map<String, dynamic>?> showPresetEditor(
  BuildContext context, {
  required String kind,
  PresetSummary? initial,
  HubApi? api,
  Future<void> Function(Map<String, dynamic>)? onSave,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (context) => _PresetEditorDialog(
        kind: kind, initial: initial, api: api, onSave: onSave),
  );
}

class _PresetEditorDialog extends StatefulWidget {
  const _PresetEditorDialog(
      {required this.kind, this.initial, this.api, this.onSave});
  final Future<void> Function(Map<String, dynamic>)? onSave;
  final HubApi? api;

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
  bool _saving = false;
  late List<Map<String, dynamic>> _variants = widget.initial?.variants
          .map((e) => Map<String, dynamic>.from(e))
          .toList() ??
      [];

  bool get _isStyle => widget.kind == 'style';

  Future<void> _selectLora() async {
    try {
      final catalog = await widget.api!.getLoraCatalog();
      if (!mounted) return;
      final candidates = catalog.items
          .where((item) =>
              item.present &&
              item.enabled &&
              item.category == (_isStyle ? 'style' : 'character'))
          .toList()
        ..sort((a, b) {
          final category = _isStyle ? 'style' : 'character';
          final order = (a.category == category ? 0 : 1)
              .compareTo(b.category == category ? 0 : 1);
          return order != 0 ? order : a.displayName.compareTo(b.displayName);
        });
      String query = '';
      final picked = await showDialog<LoraCatalogItem>(
          context: context,
          builder: (context) => StatefulBuilder(
                builder: (context, update) => AlertDialog(
                  title: Text(_isStyle ? '从 LoRA 库添加画风' : '从 LoRA 库选择角色'),
                  content: SizedBox(
                      width: 620,
                      height: 420,
                      child: Column(children: [
                        TextField(
                            decoration:
                                const InputDecoration(labelText: '搜索显示名或文件路径'),
                            onChanged: (value) => update(
                                () => query = value.trim().toLowerCase())),
                        Expanded(
                            child: ListView(children: [
                          for (final item in candidates.where((item) =>
                              '${item.displayName} ${item.path}'
                                  .toLowerCase()
                                  .contains(query)))
                            ListTile(
                                title: Text(item.displayName),
                                subtitle:
                                    Text('${item.category} · ${item.path}'),
                                onTap: () => Navigator.pop(context, item)),
                          if (candidates.isEmpty)
                            const Text('没有可用 LoRA，请先扫描并检查文件。'),
                        ])),
                      ])),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('取消'))
                  ],
                ),
              ));
      if (picked == null || !mounted) return;
      setState(() {
        final line = '${picked.path}|1.0|1.0';
        if (_isStyle) {
          final loras = _loras.text.trim().isEmpty
              ? <Map<String, dynamic>>[]
              : _parseLoras();
          if (!loras.any((item) => item['name'] == picked.path)) {
            _loras.text = [_loras.text.trim(), line]
                .where((s) => s.isNotEmpty)
                .join('\n');
          }
        } else {
          _loras.text = line;
        }
        if (_name.text.trim().isEmpty) _name.text = picked.displayName;
        final tags = [
          ..._prompt.text.split(','),
          ...picked.recommendedPrompt.split(',')
        ].map((s) => s.trim()).where((s) => s.isNotEmpty).toSet();
        _prompt.text = tags.join(', ');
        _parseError = null;
      });
    } catch (error) {
      if (mounted) setState(() => _parseError = '读取 LoRA 库失败：$error');
    }
  }

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

  Future<void> _submit() async {
    if (_saving) return;
    if (!_formKey.currentState!.validate()) return;
    try {
      final loras = _parseLoras();
      if (!_isStyle && _variants.isNotEmpty && loras.isEmpty) {
        throw const FormatException('新增造型需要指定角色 LoRA');
      }
      final value = <String, dynamic>{
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
        if (!_isStyle) 'variants': _variants,
      };
      setState(() {
        _saving = true;
        _parseError = null;
      });
      if (widget.onSave != null) await widget.onSave!(value);
      if (mounted) Navigator.pop(context, value);
    } catch (error) {
      if (mounted) setState(() => _parseError = '保存未确认：$error。内容已保留，请核实后再操作。');
    } finally {
      if (mounted) setState(() => _saving = false);
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
                      hintText: '@shiratama | shiratama',
                      helperText: '正向提示词包含任一词时匹配画风（需开启插件自动匹配）；多个词以 | 分隔。',
                      helperMaxLines: 3,
                    ),
                  ),
                  TextButton(
                      onPressed: () => setState(() {
                            _match.text = {
                              ..._match.text.split(RegExp(r'[|｜\n]')),
                              ..._prompt.text.split(',')
                            }
                                .map((s) => s.trim())
                                .where((s) => s.isNotEmpty)
                                .toSet()
                                .join(' | ');
                          }),
                      child: const Text('将固定提示词填入匹配词（可再编辑）')),
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
                if (widget.api != null)
                  TextButton.icon(
                      onPressed: _selectLora,
                      icon: const Icon(Icons.library_add),
                      label: const Text('从 LoRA 库选择（自动填写路径）')),
                if (!_isStyle)
                  CharacterVariantsEditor(
                    items: _variants,
                    defaultPrompt: _prompt.text,
                    onChanged: (items) => setState(() => _variants = items),
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
        if (_isStyle && widget.api != null)
          TextButton(
              onPressed: () async {
                try {
                  final loras = _parseLoras();
                  if (loras.isEmpty) throw const FormatException('请先添加LoRA');
                  final result = await showPalette(context, widget.api!, {
                    'name': _name.text.trim(),
                    'prompt': _prompt.text.trim(),
                    'loras': loras
                        .map((e) => {
                              'path': e['name'],
                              'strength': e['strength_model'],
                              'strength_clip': e['strength_clip']
                            })
                        .toList()
                  });
                  if (result != null && mounted) {
                    setState(() {
                      _loras.text = (result['loras'] as List)
                          .map((e) =>
                              '${e['path']}|${e['strength']}|${e['strength_clip'] ?? e['strength']}')
                          .join('\n');
                    });
                  }
                } on FormatException catch (error) {
                  if (mounted) setState(() => _parseError = error.message);
                }
              },
              child: const Text('调配（试跑后保存为全服预设）')),
        TextButton(
            onPressed: _saving ? null : () => Navigator.pop(context),
            child: const Text('取消')),
        FilledButton(
            onPressed: _saving ? null : _submit,
            child: Text(_saving ? '正在保存并核对…' : '保存')),
      ],
    );
  }
}
