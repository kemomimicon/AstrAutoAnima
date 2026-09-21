import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import '../presets/palette_dialog.dart';
import '../loras/lora_share_dialog.dart';

class PersonalPresetsPage extends StatefulWidget {
  const PersonalPresetsPage({required this.api, super.key});

  final HubApi api;

  @override
  State<PersonalPresetsPage> createState() => _PersonalPresetsPageState();
}

class _PersonalPresetsPageState extends State<PersonalPresetsPage> {
  late Future<(PersonalStyleListResult, LoraCatalogResult)> _future = _load();

  Future<(PersonalStyleListResult, LoraCatalogResult)> _load() async {
    final values = await Future.wait([
      widget.api.getPersonalStyles(),
      widget.api.getStyleLoras(),
    ]);
    return (
      values[0] as PersonalStyleListResult,
      values[1] as LoraCatalogResult
    );
  }

  void _reload() => setState(() => _future = _load());

  Future<void> _edit(
    int slot,
    PersonalStyle? initial,
    PersonalStyleListResult styles,
    LoraCatalogResult catalog,
  ) async {
    final value = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => _PersonalStyleEditor(
          api: widget.api, initial: initial, catalog: catalog.items),
    );
    if (value == null) return;
    try {
      await widget.api.savePersonalStyle(
          slot: slot, revision: styles.revision, value: value);
      _reload();
    } on HubApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> _delete(int slot, PersonalStyleListResult styles) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除个人画风？'),
        content: Text('槽位 $slot 会立即清空。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.api
          .deletePersonalStyle(slot: slot, revision: styles.revision);
      _reload();
    } on HubApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Expanded(
                child: Text('我的画风预设',
                    style: Theme.of(context).textTheme.headlineSmall)),
            IconButton(
                onPressed: _reload,
                tooltip: '刷新',
                icon: const Icon(Icons.refresh)),
          ]),
          const SizedBox(height: 8),
          const Text('每名用户最多保存 3 个方案；每个方案最多组合 16 个管理员标记为“画风”的 LoRA。'),
          const SizedBox(height: 16),
          Expanded(
            child: FutureBuilder<(PersonalStyleListResult, LoraCatalogResult)>(
              future: _future,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('读取失败：${snapshot.error}'));
                }
                final (styles, catalog) = snapshot.data!;
                return LayoutBuilder(builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 1000
                      ? 3
                      : constraints.maxWidth >= 620
                          ? 2
                          : 1;
                  return GridView.builder(
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: columns,
                        crossAxisSpacing: 14,
                        mainAxisSpacing: 14,
                        childAspectRatio: 1.15),
                    itemCount: 3,
                    itemBuilder: (context, index) {
                      final slot = index + 1;
                      PersonalStyle? item;
                      for (final candidate in styles.items) {
                        if (candidate.slot == slot) item = candidate;
                      }
                      return Card(
                        child: InkWell(
                          borderRadius: BorderRadius.circular(18),
                          onTap: () => _edit(slot, item, styles, catalog),
                          child: Padding(
                            padding: const EdgeInsets.all(18),
                            child: item == null
                                ? Column(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                        const Icon(Icons.add_circle_outline,
                                            size: 42),
                                        const SizedBox(height: 12),
                                        Text('槽位 $slot',
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleLarge),
                                        const Text('点击创建画风方案'),
                                      ])
                                : Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                        Row(children: [
                                          CircleAvatar(child: Text('$slot')),
                                          const SizedBox(width: 10),
                                          Expanded(
                                              child: Text(item.name,
                                                  style: Theme.of(context)
                                                      .textTheme
                                                      .titleLarge)),
                                          IconButton(
                                              onPressed: () =>
                                                  _delete(slot, styles),
                                              icon: const Icon(
                                                  Icons.delete_outline),
                                              tooltip: '删除'),
                                        ]),
                                        const SizedBox(height: 12),
                                        Text('${item.loras.length} 个 LoRA',
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleMedium),
                                        const SizedBox(height: 6),
                                        Expanded(
                                            child: Text(
                                                item.prompt.isEmpty
                                                    ? '未设置固定触发词'
                                                    : item.prompt,
                                                maxLines: 6,
                                                overflow:
                                                    TextOverflow.ellipsis)),
                                        const Align(
                                            alignment: Alignment.bottomRight,
                                            child: Icon(Icons.edit_outlined)),
                                      ]),
                          ),
                        ),
                      );
                    },
                  );
                });
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _PersonalStyleEditor extends StatefulWidget {
  const _PersonalStyleEditor(
      {required this.api, required this.catalog, this.initial});
  final HubApi api;
  final List<LoraCatalogItem> catalog;
  final PersonalStyle? initial;

  @override
  State<_PersonalStyleEditor> createState() => _PersonalStyleEditorState();
}

class _PersonalStyleEditorState extends State<_PersonalStyleEditor> {
  late final _name = TextEditingController(text: widget.initial?.name ?? '');
  late final _prompt =
      TextEditingController(text: widget.initial?.prompt ?? '');
  late final List<PersonalStyleLora> _loras = [...?widget.initial?.loras];

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _addLora() async {
    if (_loras.length >= 16) return;
    final selected = _loras.map((item) => item.path).toSet();
    final choice = await showDialog<_LoraChoice>(
      context: context,
      builder: (context) => _LoraPicker(
          items: widget.catalog
              .where((item) => !selected.contains(item.path))
              .toList()),
    );
    if (choice == null) return;
    setState(() {
      _loras.add(
          PersonalStyleLora(path: choice.item.path, strength: choice.strength));
      if (choice.addPrompt && choice.item.recommendedPrompt.trim().isNotEmpty) {
        final current = _prompt.text.trim().replaceAll(RegExp(r',+$'), '');
        _prompt.text = [
          if (current.isNotEmpty) current,
          choice.item.recommendedPrompt.trim()
        ].join(', ');
      }
    });
  }

  Future<void> _editStrength(int index) async {
    final item = _loras[index];
    final strength = await showDialog<double>(
      context: context,
      builder: (context) => _StrengthEditor(initial: item.strength),
    );
    if (strength == null) return;
    setState(() {
      _loras[index] = PersonalStyleLora(path: item.path, strength: strength);
    });
  }

  @override
  Widget build(BuildContext context) {
    final names = {
      for (final item in widget.catalog) item.path: item.displayName
    };
    return AlertDialog(
      title: Text(widget.initial == null ? '创建个人画风' : '编辑个人画风'),
      content: SizedBox(
        width: 680,
        height: 620,
        child: Column(children: [
          TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: '画风名称')),
          const SizedBox(height: 12),
          TextField(
              controller: _prompt,
              minLines: 3,
              maxLines: 6,
              decoration: const InputDecoration(labelText: '固定触发词')),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
                child: Text('LoRA 槽位（${_loras.length}/16）',
                    style: Theme.of(context).textTheme.titleMedium)),
            FilledButton.tonalIcon(
                onPressed: _loras.length >= 16 || widget.catalog.isEmpty
                    ? null
                    : _addLora,
                icon: const Icon(Icons.add),
                label: const Text('添加 LoRA')),
          ]),
          const SizedBox(height: 8),
          Expanded(
            child: _loras.isEmpty
                ? const Center(child: Text('至少添加 1 个画风 LoRA'))
                : ReorderableListView.builder(
                    itemCount: _loras.length,
                    onReorderItem: (oldIndex, newIndex) => setState(() {
                      final item = _loras.removeAt(oldIndex);
                      _loras.insert(newIndex, item);
                    }),
                    itemBuilder: (context, index) {
                      final item = _loras[index];
                      return ListTile(
                        key: ValueKey(item.path),
                        leading: const Icon(Icons.drag_handle),
                        title: Text(names[item.path] ?? item.path),
                        subtitle: Text(
                            '强度 ${item.strength.toStringAsFixed(2)} · ${item.path}',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis),
                        trailing: Wrap(
                          spacing: 2,
                          children: [
                            IconButton(
                              tooltip: '修改强度',
                              icon: const Icon(Icons.tune),
                              onPressed: () => _editStrength(index),
                            ),
                            IconButton(
                                tooltip: '移除',
                                icon: const Icon(Icons.remove_circle_outline),
                                onPressed: () =>
                                    setState(() => _loras.removeAt(index))),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('取消')),
        TextButton(
            onPressed: _loras.isEmpty
                ? null
                : () async {
                    final result = await showPalette(context, widget.api, {
                      'name': _name.text.trim(),
                      'prompt': _prompt.text.trim(),
                      'loras': _loras.map((e) => e.toJson()).toList()
                    });
                    if (result != null && mounted) {
                      setState(() {
                        _loras.clear();
                        for (final item in result['loras'] as List) {
                          _loras.add(PersonalStyleLora(
                              path: item['path'] as String,
                              strength: (item['strength'] as num).toDouble()));
                        }
                      });
                    }
                  },
            child: const Text('调配')),
        FilledButton(
          onPressed: () {
            if (_name.text.trim().isEmpty || _loras.isEmpty) {
              ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('请填写名称并至少添加一个 LoRA。')));
              return;
            }
            Navigator.pop(context, {
              'name': _name.text.trim(),
              'prompt': _prompt.text.trim(),
              'loras': _loras.map((item) => item.toJson()).toList(),
            });
          },
          child: const Text('确认'),
        ),
      ],
    );
  }
}

class _LoraChoice {
  const _LoraChoice(this.item, this.strength, this.addPrompt);
  final LoraCatalogItem item;
  final double strength;
  final bool addPrompt;
}

class _LoraPicker extends StatefulWidget {
  const _LoraPicker({required this.items});
  final List<LoraCatalogItem> items;

  @override
  State<_LoraPicker> createState() => _LoraPickerState();
}

class _LoraPickerState extends State<_LoraPicker> {
  LoraCatalogItem? _selected;
  double _strength = 1;
  bool _addPrompt = true;
  late final _strengthText = TextEditingController(text: '1.0');

  @override
  void dispose() {
    _strengthText.dispose();
    super.dispose();
  }

  void _setStrengthFromSlider(double value) {
    final next = value.clamp(0.0, 2.5);
    setState(() {
      _strength = next;
      _strengthText.text = next.toStringAsFixed(2);
    });
  }

  void _acceptTypedStrength(String value) {
    final typed = double.tryParse(value);
    if (typed == null || !typed.isFinite) return;
    setState(() => _strength = typed.clamp(-5.0, 5.0));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('添加画风 LoRA'),
      content: SizedBox(
        width: 620,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          DropdownButtonFormField<LoraCatalogItem>(
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'LoRA'),
            items: widget.items
                .map((item) => DropdownMenuItem(
                    value: item,
                    child: Text('${item.displayName} · ${item.path}',
                        overflow: TextOverflow.ellipsis)))
                .toList(),
            onChanged: (value) => setState(() => _selected = value),
          ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
                child: Slider(
                    value: _strength.clamp(0.0, 2.5),
                    min: 0,
                    max: 2.5,
                    divisions: 100,
                    label: _strength.toStringAsFixed(2),
                    onChanged: _setStrengthFromSlider)),
            SizedBox(
              width: 90,
              child: TextField(
                controller: _strengthText,
                keyboardType: const TextInputType.numberWithOptions(
                    decimal: true, signed: true),
                decoration: const InputDecoration(labelText: '强度'),
                onChanged: _acceptTypedStrength,
              ),
            ),
          ]),
          CheckboxListTile(
            value: _addPrompt,
            onChanged: _selected?.recommendedPrompt.isNotEmpty == true
                ? (value) => setState(() => _addPrompt = value ?? true)
                : null,
            title: const Text('一键添加推荐触发词'),
            subtitle: Text(
                _selected?.recommendedPrompt.isNotEmpty == true
                    ? _selected!.recommendedPrompt
                    : '该 LoRA 未配置推荐触发词',
                maxLines: 3,
                overflow: TextOverflow.ellipsis),
          ),
          TextButton.icon(
            onPressed: _selected == null
                ? null
                : () => showLoraShareDialog(context, _selected!),
            icon: const Icon(Icons.share_outlined),
            label: const Text('分享所选 LoRA 链接和触发词'),
          ),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(
          onPressed: _selected == null
              ? null
              : () {
                  final typed = double.tryParse(_strengthText.text);
                  final strength = (typed ?? _strength).clamp(-5.0, 5.0);
                  Navigator.pop(
                    context,
                    _LoraChoice(_selected!, strength, _addPrompt),
                  );
                },
          child: const Text('确定'),
        ),
      ],
    );
  }
}

class _StrengthEditor extends StatefulWidget {
  const _StrengthEditor({required this.initial});
  final double initial;

  @override
  State<_StrengthEditor> createState() => _StrengthEditorState();
}

class _StrengthEditorState extends State<_StrengthEditor> {
  late double _value = widget.initial;
  late final TextEditingController _text =
      TextEditingController(text: widget.initial.toStringAsFixed(2));

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('修改 LoRA 强度'),
      content: SizedBox(
        width: 420,
        child: Row(children: [
          Expanded(
            child: Slider(
              value: _value.clamp(0.0, 2.5),
              min: 0,
              max: 2.5,
              divisions: 100,
              label: _value.toStringAsFixed(2),
              onChanged: (value) => setState(() {
                _value = value;
                _text.text = value.toStringAsFixed(2);
              }),
            ),
          ),
          SizedBox(
            width: 100,
            child: TextField(
              controller: _text,
              keyboardType: const TextInputType.numberWithOptions(
                  decimal: true, signed: true),
              decoration: const InputDecoration(
                labelText: '手动值',
                helperText: '可超出滑条',
              ),
              onChanged: (text) {
                final parsed = double.tryParse(text);
                if (parsed != null && parsed.isFinite) {
                  setState(() => _value = parsed.clamp(-5.0, 5.0));
                }
              },
            ),
          ),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(
          onPressed: () {
            final parsed = double.tryParse(_text.text);
            Navigator.pop(context, (parsed ?? _value).clamp(-5.0, 5.0));
          },
          child: const Text('保存'),
        ),
      ],
    );
  }
}
