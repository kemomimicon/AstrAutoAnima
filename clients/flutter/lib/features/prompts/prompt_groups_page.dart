import 'package:flutter/material.dart';
import 'dart:convert';

import '../../core/hub_api.dart';

class PromptGroupsPage extends StatefulWidget {
  const PromptGroupsPage({required this.api, super.key});
  final HubApi api;

  @override
  State<PromptGroupsPage> createState() => _PromptGroupsPageState();
}

class _PromptGroupsPageState extends State<PromptGroupsPage> {
  late Future<Map<String, dynamic>> _future = widget.api.getPromptGroups();

  void _refresh() {
    setState(() {
      _future = widget.api.getPromptGroups();
    });
  }

  List<Map<String, dynamic>> _rows(Map<String, dynamic> data) =>
      (data['groups'] as List? ?? const [])
          .whereType<Map>()
          .map((value) => Map<String, dynamic>.from(value))
          .toList();

  Future<void> _edit(Map<String, dynamic>? original) async {
    final id = TextEditingController(text: '${original?['id'] ?? ''}');
    final name = TextEditingController(text: '${original?['name'] ?? ''}');
    var privateAllowed = original?['allow_private'] == true;
    var groupAllowed = original?['allow_group'] != false;
    var enabled = original?['enabled'] != false;
    final levels = (original?['safety_codes'] as List? ?? ['N', 'H', 'S'])
        .cast<String>()
        .toSet();
    final value = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
          builder: (context, update) => AlertDialog(
                title: Text(original == null ? '新增提示词分组' : '修改提示词分组'),
                content: SizedBox(
                    width: 420,
                    child: SingleChildScrollView(
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                      TextField(
                          controller: id,
                          enabled: original == null,
                          decoration: const InputDecoration(
                              labelText: '组 ID · 英文、数字、_、-')),
                      TextField(
                          controller: name,
                          decoration: const InputDecoration(labelText: '显示名称')),
                      CheckboxListTile(
                          value: privateAllowed,
                          title: const Text('允许 QQ 私聊抽取'),
                          onChanged: (value) =>
                              update(() => privateAllowed = value ?? false)),
                      CheckboxListTile(
                          value: groupAllowed,
                          title: const Text('允许群聊抽取'),
                          onChanged: (v) =>
                              update(() => groupAllowed = v ?? false)),
                      SwitchListTile(
                          value: enabled,
                          title: const Text('启用分组'),
                          onChanged: (v) => update(() => enabled = v)),
                      const Text('允许抽取的内容级别（不修改条目自身分级）'),
                      Wrap(spacing: 8, children: [
                        for (final code in ['N', 'H', 'S'])
                          FilterChip(
                              label: Text(code),
                              selected: levels.contains(code),
                              onSelected: (v) => update(() {
                                    v ? levels.add(code) : levels.remove(code);
                                  })),
                      ]),
                      const Text('此处是提示词分组，不是用户权限等级。保存后才同步到服务端。'),
                    ]))),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, {
                            'id': id.text.trim().toLowerCase(),
                            'name': name.text.trim(),
                            'allow_private': privateAllowed,
                            'allow_group': groupAllowed,
                            'enabled': enabled,
                            'safety_codes': levels.toList()..sort(),
                          }),
                      child: const Text('保存')),
                ],
              )),
    );
    // showDialog completes when popped, before its reverse transition ends.
    Future<void>.delayed(const Duration(milliseconds: 350), () {
      id.dispose();
      name.dispose();
    });
    if (value == null || !mounted) return;
    if (!RegExp(r'^[a-z0-9][a-z0-9_-]{0,63}$')
            .hasMatch(value['id'] as String) ||
        (value['name'] as String).isEmpty ||
        levels.isEmpty) {
      _notice('组 ID 或显示名称不合法');
      return;
    }
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        final latest = await widget.api.getPromptGroups();
        final groups = _rows(latest);
        final existing =
            groups.where((row) => row['id'] == value['id']).toList();
        if (original == null && existing.isNotEmpty) {
          _notice('组 ID 已存在，请编辑原分组');
          return;
        }
        if (original != null &&
            (existing.length != 1 ||
                jsonEncode(existing.single) != jsonEncode(original))) {
          _notice('该分组本身已被修改，未覆盖；请刷新核对');
          return;
        }
        groups.removeWhere((row) => row['id'] == value['id']);
        groups.add(value);
        await widget.api.savePromptGroups(
            revision: '${latest['revision']}', groups: groups);
        _refresh();
        _notice('分组已保存');
        return;
      } on HubApiException catch (error) {
        if (error.statusCode == 409 && attempt < 2) continue;
        _notice(error.message);
        return;
      }
    }
  }

  void _notice(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('提示词自定义分组')),
        body: FutureBuilder<Map<String, dynamic>>(
          future: _future,
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              if (snapshot.hasError) {
                return Center(child: Text('${snapshot.error}'));
              }
              return const Center(child: CircularProgressIndicator());
            }
            final groups = _rows(snapshot.data!);
            return ListView(padding: const EdgeInsets.all(20), children: [
              const Text('分组只在新增、修改或手动导入时同步；不会持续刷新。私聊抽取未登记分组将被拒绝。'),
              const SizedBox(height: 16),
              FilledButton.icon(
                  onPressed: () => _edit(null),
                  icon: const Icon(Icons.add),
                  label: const Text('新增分组')),
              for (final row in groups)
                Card(
                    child: ListTile(
                  title: Text('${row['name']} · @${row['id']}'),
                  subtitle: Text('${row['enabled'] == false ? '已停用 · ' : ''}'
                      '${row['allow_group'] == false ? '禁止群聊' : '允许群聊'} · '
                      '${row['allow_private'] == true ? '允许私聊' : '不允许私聊'} · '
                      '${(row['safety_codes'] as List? ?? [
                            'N',
                            'H',
                            'S'
                          ]).join('/')}'),
                  trailing: const Icon(Icons.edit_outlined),
                  onTap: () => _edit(row),
                )),
            ]);
          },
        ),
      );
}
