import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/models.dart';

class PresetSections extends StatelessWidget {
  const PresetSections(
      {required this.api,
      required this.presets,
      this.admin = false,
      super.key});
  final HubApi api;
  final Widget presets;
  final bool admin;
  @override
  Widget build(BuildContext context) => DefaultTabController(
      length: 2,
      child: Column(children: [
        const TabBar(tabs: [Tab(text: '画风预设'), Tab(text: '任务套组')]),
        Expanded(
            child: TabBarView(
                children: [presets, TaskSuitesPage(api: api, admin: admin)])),
      ]));
}

class TaskSuiteSelector extends StatefulWidget {
  const TaskSuiteSelector(
      {required this.api,
      required this.value,
      required this.onChanged,
      super.key});
  final HubApi api;
  final String value;
  final ValueChanged<String> onChanged;
  @override
  State<TaskSuiteSelector> createState() => _TaskSuiteSelectorState();
}

class _TaskSuiteSelectorState extends State<TaskSuiteSelector> {
  late Future<Map<String, dynamic>> _future = widget.api.getTaskSuites();
  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, state) {
        if (state.hasError) {
          return Row(children: [
            const Expanded(child: Text('套组加载失败，请重试；不会自动改用普通生图')),
            IconButton(
                onPressed: () =>
                    setState(() => _future = widget.api.getTaskSuites()),
                icon: const Icon(Icons.refresh))
          ]);
        }
        if (!state.hasData) return const LinearProgressIndicator();
        final items =
            (state.data!['items'] as List).cast<Map<String, dynamic>>();
        return Row(children: [
          Expanded(
              child: DropdownButtonFormField<String>(
                  key: ValueKey(
                      '${widget.value}-${items.map((i) => i['id']).join()}'),
                  initialValue: items.any((i) => i['id'] == widget.value)
                      ? widget.value
                      : '',
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: '选择任务套组'),
                  items: [
                    const DropdownMenuItem(
                        value: '', child: Text('请选择（在预设页新增）')),
                    ...items.map((i) => DropdownMenuItem(
                        value: i['id'] as String,
                        child: Text(
                            '${i['name']} · ${(i['rows'] as List).length} 项')))
                  ],
                  onChanged: (v) => widget.onChanged(v ?? ''))),
          IconButton(
              tooltip: '刷新套组',
              onPressed: () =>
                  setState(() => _future = widget.api.getTaskSuites()),
              icon: const Icon(Icons.refresh)),
        ]);
      });
}

class TaskSuitesPage extends StatefulWidget {
  const TaskSuitesPage({required this.api, this.admin = false, super.key});
  final HubApi api;
  final bool admin;
  @override
  State<TaskSuitesPage> createState() => _TaskSuitesPageState();
}

class _TaskSuitesPageState extends State<TaskSuitesPage> {
  late Future<Map<String, dynamic>> _future = widget.api.getTaskSuites();
  void _reload() => setState(() => _future = widget.api.getTaskSuites());
  Future<void> _edit(Map<String, dynamic>? item, String revision) async {
    final saved = await showDialog<bool>(
        context: context,
        builder: (_) => _SuiteEditor(
            api: widget.api,
            admin: widget.admin,
            initial: item,
            revision: revision));
    if (saved == true) _reload();
  }

  Future<void> _delete(Map<String, dynamic> item, String revision) async {
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('删除任务套组？'),
                content: Text('${item['name']}\n不会删除图片或现有角色、画风预设。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('删除'))
                ]));
    if (yes != true) return;
    try {
      await widget.api.deleteTaskSuite(item['id'], revision);
      _reload();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, state) {
        if (state.hasError) {
          return Center(
              child: TextButton(
                  onPressed: _reload, child: const Text('加载失败，点击重试')));
        }
        if (!state.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final data = state.data!;
        final items = (data['items'] as List).cast<Map<String, dynamic>>();
        return ListView(padding: const EdgeInsets.all(16), children: [
          Row(children: [
            Expanded(
                child: FilledButton.icon(
                    onPressed: () => _edit(null, data['revision']),
                    icon: const Icon(Icons.add),
                    label: const Text('新增套组预设'))),
            IconButton(onPressed: _reload, icon: const Icon(Icons.refresh))
          ]),
          const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('同一个基础提示词，按角色与画风组合逐行生成。个人套组仅自己可用；全局套组供所有用户选择。')),
          for (final item in items)
            Card(
                child: ListTile(
                    title: Text(item['name']),
                    subtitle: Text(
                        '${item['scope'] == 'global' ? '全局' : '个人'} · ${(item['rows'] as List).length} 项'),
                    onTap: item['editable'] == true
                        ? () => _edit(item, data['revision'])
                        : null,
                    trailing: item['editable'] == true
                        ? IconButton(
                            onPressed: () => _delete(item, data['revision']),
                            icon: const Icon(Icons.delete_outline))
                        : const Icon(Icons.public))),
        ]);
      });
}

class _SuiteEditor extends StatefulWidget {
  const _SuiteEditor(
      {required this.api,
      required this.admin,
      required this.revision,
      this.initial});
  final HubApi api;
  final bool admin;
  final String revision;
  final Map<String, dynamic>? initial;
  @override
  State<_SuiteEditor> createState() => _SuiteEditorState();
}

class _SuiteEditorState extends State<_SuiteEditor> {
  late final _name = TextEditingController(text: widget.initial?['name'] ?? '');
  late String _scope = widget.initial?['scope'] ?? 'personal';
  late final List<Map<String, dynamic>> _rows = widget.initial == null
      ? [_empty()]
      : (widget.initial!['rows'] as List)
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
  late final Future<List<Object>> _data = Future.wait([
    widget.api.getLitePresets(),
    widget.api.getPersonalStyles(),
    widget.api.getCharacterFavorites()
  ]);
  bool _saving = false;
  String _error = '';
  static Map<String, dynamic> _empty() => {
        'character_kind': 'preset',
        'character': '',
        'style_kind': 'global',
        'style': ''
      };
  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty ||
        _rows.any((r) =>
            '${r['character']}'.trim().isEmpty || '${r['style']}'.isEmpty)) {
      setState(() => _error = '请填写名称和每行角色、画风');
      return;
    }
    setState(() {
      _saving = true;
      _error = '';
    });
    try {
      await widget.api.saveTaskSuite({
        'name': _name.text.trim(),
        'scope': _scope,
        'rows': _rows
      }, widget.revision, id: widget.initial?['id']);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
          title: Text(widget.initial == null ? '新增套组预设' : '编辑套组预设'),
          content: SizedBox(
              width: 700,
              child: FutureBuilder<List<Object>>(
                  future: _data,
                  builder: (context, state) {
                    if (state.hasError) {
                      return const Text('角色/画风选项加载失败，请关闭后重试。');
                    }
                    if (!state.hasData) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    final presets = state.data![0] as PresetListResult;
                    final personal = state.data![1] as PersonalStyleListResult;
                    final favorites =
                        state.data![2] as CharacterFavoriteListResult;
                    final characters = <String, String>{
                      for (final p in presets.characters)
                        'preset:${p.name}': '全局 · ${p.name}',
                      for (final f in favorites.items)
                        'favorite:${f.tag}': '收藏 · ${f.name}',
                      'text:': '自行输入角色文本'
                    };
                    final styles = <String, String>{
                      for (final p in presets.styles)
                        'global:${p.name}': '全局 · ${p.name}',
                      for (final p in personal.items)
                        'personal:${p.slot}': '个人 · ${p.name}'
                    };
                    Widget choose(Map<String, String> choices, String value,
                            String label, ValueChanged<String> changed) =>
                        DropdownButtonFormField<String>(
                            key: ValueKey('$label-$value-${choices.length}'),
                            initialValue:
                                choices.containsKey(value) ? value : '',
                            isExpanded: true,
                            decoration: InputDecoration(labelText: label),
                            items: [
                              const DropdownMenuItem(
                                  value: '', child: Text('请选择')),
                              ...choices.entries.map((e) => DropdownMenuItem(
                                  value: e.key, child: Text(e.value)))
                            ],
                            onChanged: _saving
                                ? null
                                : (v) {
                                    if (v != null && v.isNotEmpty) changed(v);
                                  });
                    return SingleChildScrollView(
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                      TextField(
                          controller: _name,
                          maxLength: 80,
                          decoration: const InputDecoration(labelText: '套组名称')),
                      if (widget.admin)
                        SwitchListTile(
                            title: const Text('保存为全局套组'),
                            subtitle: const Text('全局套组不能引用个人画风或私人收藏'),
                            value: _scope == 'global',
                            onChanged: _saving
                                ? null
                                : (v) => setState(
                                    () => _scope = v ? 'global' : 'personal')),
                      for (int i = 0; i < _rows.length; i++)
                        Card(
                            child: Padding(
                                padding: const EdgeInsets.all(12),
                                child: Column(children: [
                                  Row(children: [
                                    Text('第 ${i + 1} 项'),
                                    const Spacer(),
                                    IconButton(
                                        tooltip: '上移',
                                        onPressed: i == 0 || _saving
                                            ? null
                                            : () => setState(() {
                                                  final row = _rows.removeAt(i);
                                                  _rows.insert(i - 1, row);
                                                }),
                                        icon: const Icon(Icons.arrow_upward)),
                                    IconButton(
                                        tooltip: '删除此行',
                                        onPressed: _rows.length == 1 || _saving
                                            ? null
                                            : () => setState(
                                                () => _rows.removeAt(i)),
                                        icon: const Icon(Icons.close))
                                  ]),
                                  Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Expanded(
                                            child: choose(
                                                characters,
                                                '${_rows[i]['character_kind']}:${_rows[i]['character_kind'] == 'text' ? '' : _rows[i]['character']}',
                                                '角色',
                                                (v) => setState(() {
                                                      final pos =
                                                          v.indexOf(':');
                                                      _rows[i][
                                                              'character_kind'] =
                                                          v.substring(0, pos);
                                                      _rows[i]['character'] =
                                                          v.substring(pos + 1);
                                                    }))),
                                        const SizedBox(width: 12),
                                        Expanded(
                                            child: choose(
                                                styles,
                                                '${_rows[i]['style_kind']}:${_rows[i]['style']}',
                                                '画风',
                                                (v) => setState(() {
                                                      final pos =
                                                          v.indexOf(':');
                                                      _rows[i]['style_kind'] =
                                                          v.substring(0, pos);
                                                      _rows[i]['style'] =
                                                          v.substring(pos + 1);
                                                    })))
                                      ]),
                                  if (_rows[i]['character_kind'] == 'text')
                                    TextFormField(
                                        key: ObjectKey(_rows[i]),
                                        initialValue: _rows[i]['character'],
                                        maxLength: 1000,
                                        decoration: const InputDecoration(
                                            labelText: '角色文本 / 中文名'),
                                        onChanged: (v) =>
                                            _rows[i]['character'] = v),
                                ]))),
                      TextButton.icon(
                          onPressed: _rows.length >= 20 || _saving
                              ? null
                              : () => setState(() => _rows.add(_empty())),
                          icon: const Icon(Icons.add),
                          label: const Text('新增一条（最多 20 项）')),
                      if (_error.isNotEmpty)
                        Text(_error,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      FilledButton(
                          onPressed: _saving ? null : _save,
                          child: Text(_saving ? '保存中…' : '保存')),
                    ]));
                  })),
          actions: [
            TextButton(
                onPressed: _saving ? null : () => Navigator.pop(context),
                child: const Text('取消'))
          ]);
}
