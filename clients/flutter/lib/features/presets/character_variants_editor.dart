import 'package:flutter/material.dart';

/// Controlled editor: changes are committed only with the parent preset form.
class CharacterVariantsEditor extends StatelessWidget {
  const CharacterVariantsEditor(
      {super.key,
      required this.items,
      required this.onChanged,
      required this.defaultPrompt});
  final List<Map<String, dynamic>> items;
  final ValueChanged<List<Map<String, dynamic>>> onChanged;
  final String defaultPrompt;

  Future<void> _edit(BuildContext context, int? index) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _VariantDialog(
          initial: index == null ? null : items[index],
          defaultPrompt: defaultPrompt),
    );
    if (result == null) return;
    final next = items.map((e) => Map<String, dynamic>.from(e)).toList();
    if (index == null) {
      next.add(result);
    } else {
      next[index] = result;
    }
    onChanged(next);
  }

  Future<void> _remove(BuildContext context, int index) async {
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: const Text('删除角色造型'),
              content: Text('删除“${items[index]['name']}”？保存角色预设后生效，默认造型不受影响。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('确认删除')),
              ],
            ));
    if (confirmed == true) onChanged([...items]..removeAt(index));
  }

  @override
  Widget build(BuildContext context) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('角色造型 · 默认保留'),
            subtitle: Text('上方固定提示词为默认。新增造型请填写完整触发词组，将替换默认词组。')),
        for (var i = 0; i < items.length; i++)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${const {
                  'clothing': '服装',
                  'appearance': '造型',
                  'other': '其他'
                }[items[i]['category']] ?? '其他'} · ${items[i]['name']}'),
            subtitle: Text('${items[i]['description'] ?? ''}'),
            onTap: () => _edit(context, i),
            trailing: IconButton(
                tooltip: '删除造型',
                onPressed: () => _remove(context, i),
                icon: const Icon(Icons.delete_outline)),
          ),
        TextButton.icon(
            onPressed: items.length >= 64 ? null : () => _edit(context, null),
            icon: const Icon(Icons.add),
            label: const Text('新增服装 / 造型 / 其他')),
      ]);
}

class _VariantDialog extends StatefulWidget {
  const _VariantDialog({this.initial, required this.defaultPrompt});
  final Map<String, dynamic>? initial;
  final String defaultPrompt;
  @override
  State<_VariantDialog> createState() => _VariantDialogState();
}

class _VariantDialogState extends State<_VariantDialog> {
  final _form = GlobalKey<FormState>();
  late final _name =
      TextEditingController(text: widget.initial?['name'] as String? ?? '');
  late final _description = TextEditingController(
      text: widget.initial?['description'] as String? ?? '');
  late final _prompt = TextEditingController(
      text: widget.initial?['prompt'] as String? ?? widget.defaultPrompt);
  late String _category = widget.initial?['category'] as String? ?? 'clothing';
  @override
  void dispose() {
    _name.dispose();
    _description.dispose();
    _prompt.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.initial == null ? '新增角色造型' : '编辑角色造型'),
        content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
                child: Form(
                    key: _form,
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      DropdownButtonFormField<String>(
                          initialValue: _category,
                          decoration: const InputDecoration(labelText: '分类'),
                          items: const [
                            DropdownMenuItem(
                                value: 'clothing', child: Text('服装')),
                            DropdownMenuItem(
                                value: 'appearance', child: Text('造型')),
                            DropdownMenuItem(value: 'other', child: Text('其他'))
                          ],
                          onChanged: (v) =>
                              setState(() => _category = v ?? 'clothing')),
                      TextFormField(
                          controller: _name,
                          maxLength: 80,
                          decoration:
                              const InputDecoration(labelText: '名称（如汉服、双马尾）'),
                          validator: (v) =>
                              v == null || v.trim().isEmpty ? '请填写名称' : null),
                      TextFormField(
                          controller: _description,
                          maxLength: 2000,
                          minLines: 2,
                          maxLines: 4,
                          decoration: const InputDecoration(labelText: '补充说明')),
                      TextFormField(
                          controller: _prompt,
                          maxLength: 10000,
                          minLines: 3,
                          maxLines: 8,
                          decoration:
                              const InputDecoration(labelText: '完整角色触发词组'),
                          validator: (v) =>
                              v == null || v.replaceAll(',', '').trim().isEmpty
                                  ? '请填写触发词'
                                  : null),
                    ])))),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () {
                if (!_form.currentState!.validate()) return;
                Navigator.pop(context, <String, dynamic>{
                  'id': widget.initial?['id'] ??
                      'v_${DateTime.now().microsecondsSinceEpoch}',
                  'category': _category,
                  'name': _name.text.trim(),
                  'description': _description.text.trim(),
                  'prompt': _prompt.text.trim(),
                });
              },
              child: const Text('完成')),
        ],
      );
}
