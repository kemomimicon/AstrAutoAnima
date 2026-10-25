import 'package:flutter/material.dart';
import '../../core/hub_api.dart';

const groupPermissionHelp = '群聊等级不是提示词分级。高级用户拥有低级用户权限。\n'
    '4 级：新增角色 / 画风预设等已接入的群高级指令，不等于系统管理员。本版尚未接入 QQ 下载 LoRA / 关闭实例的等级授权。\n'
    '3 级：不限制每日次数；2 级：无冷却但有次数限制；1 级：冷却及每日次数限制；0 级：不响应群内生图。\n'
    '开启等级系统后，未登记该群的账号默认为 0 级；关闭时普通成员按 3 级处理，只有 4 级配置生效。\n'
    '安全模式可以继承全局、强制开启或关闭；群设置不改变其他群。';

class ChatGroupsPage extends StatefulWidget {
  const ChatGroupsPage({required this.api, super.key});
  final HubApi api;
  @override
  State<ChatGroupsPage> createState() => _ChatGroupsPageState();
}

class _ChatGroupsPageState extends State<ChatGroupsPage> {
  Map<String, dynamic>? _data;
  bool _busy = true;
  String? _error;
  List<Map<String, dynamic>> get _groups => (_data?['groups'] as List? ?? [])
      .map((v) => Map<String, dynamic>.from(v as Map))
      .toList();
  List<Map<String, dynamic>> get _users => (_data?['users'] as List? ?? [])
      .map((v) => Map<String, dynamic>.from(v as Map))
      .toList();
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final value = await widget.api.chatGroups();
      if (mounted) {
        setState(() {
          _data = value;
          _error = null;
          _busy = false;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error is HubApiException ? error.message : '群配置读取失败';
          _busy = false;
        });
      }
    }
  }

  Future<void> _enabled(bool enabled) async {
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: Text(enabled ? '启用分群管理？' : '停用分群管理？'),
                content: const Text(
                    '启用后，尚未登记的 QQ 群将停止接单，请先配置群与成员。启用等级制的群，未登记成员为 0 级。按 Bot 适配器 ID 和群号独立生效；停用回到原有全局权限，不会删除设置。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('确认'))
                ]));
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.api.setChatGroupsEnabled(enabled);
      await _load();
    } catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '$error';
        });
      }
    }
  }

  Future<void> _editGroup([Map<String, dynamic>? group]) async {
    final saved = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => _GroupEditor(api: widget.api, group: group));
    if (saved == true) await _load();
  }

  Future<void> _editUser(Map<String, dynamic> group,
      [Map<String, dynamic>? user]) async {
    final saved = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => _GroupUserEditor(
            api: widget.api, group: group, groups: _groups, user: user));
    if (saved == true) await _load();
  }

  Future<void> _removeUser(Map<String, dynamic> user) async {
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('移除群成员配置？'),
                content: Text(
                    '只移除 ${user['qq']} 在此群的授权。等级系统启用时将恢复为 0 级；不删除用户词库、图片或其他群授权。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('确认移除'))
                ]));
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.api
          .deleteChatGroupUser('${user['group_key']}', '${user['qq']}');
      await _load();
    } catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '$error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final available = _data?['available'] == true && _error == null;
    return Scaffold(
        appBar: AppBar(title: const Text('群聊管理'), actions: [
          IconButton(
              tooltip: '手动刷新',
              onPressed: _busy
                  ? null
                  : () {
                      setState(() => _busy = true);
                      _load();
                    },
              icon: const Icon(Icons.refresh)),
          IconButton(
              tooltip: '权限等级说明',
              onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => const AlertDialog(
                      title: Text('权限等级说明'),
                      content: SingleChildScrollView(
                          child: Text(groupPermissionHelp)))),
              icon: const Icon(Icons.help_outline)),
        ]),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          const Text(
              '本版群权限仅支持 QQ；TG / DC 平台切换不代表已支持分群权限。按需读取，保存时同步；无持续刷新。每日额度按 UTC 日期重置。群身份必须匹配 AstrBot 适配器 ID，不能用显示名称代替。'),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null)
            Text(_error!, key: const ValueKey('chat-groups.error')),
          if (_data != null && !available)
            const Text('当前工作站未提供群聊管理；本机模式不经过 Bot。'),
          if (available) ...[
            SwitchListTile(
                title: const Text('启用分群管理'),
                value: _data?['enabled'] == true,
                onChanged: _busy ? null : _enabled),
            FilledButton.icon(
                onPressed: _busy ? null : () => _editGroup(),
                icon: const Icon(Icons.add),
                label: const Text('新增群聊')),
            for (final group in _groups)
              Card(
                  child: ExpansionTile(
                      key: ValueKey('chat-group.${group['key']}'),
                      title: Text('${group['name'] ?? group['key']}'),
                      subtitle: Text(
                          '${group['platform']} · ${group['bot_id']} · ${group['group_id']}\n${group['enabled'] == true ? '启用' : '停用'} / ${group['level_system_enabled'] == true ? '等级制' : '普通权限'}'),
                      children: [
                    Row(children: [
                      TextButton(
                          onPressed: _busy ? null : () => _editGroup(group),
                          child: const Text('编辑群设置')),
                      TextButton(
                          onPressed: _busy ? null : () => _editUser(group),
                          child: const Text('添加成员'))
                    ]),
                    for (final user
                        in _users.where((u) => u['group_key'] == group['key']))
                      ListTile(
                          title: Text('${user['qq']} · ${user['grade']} 级'),
                          subtitle: Text('主要群：${user['primary_group'] ?? ''}'),
                          onTap: _busy ? null : () => _editUser(group, user),
                          trailing: IconButton(
                              tooltip: '移除成员配置',
                              onPressed: _busy ? null : () => _removeUser(user),
                              icon: const Icon(Icons.person_remove_outlined))),
                  ])),
          ],
        ]));
  }
}

class _GroupEditor extends StatefulWidget {
  const _GroupEditor({required this.api, this.group});
  final HubApi api;
  final Map<String, dynamic>? group;
  @override
  State<_GroupEditor> createState() => _GroupEditorState();
}

class _GroupEditorState extends State<_GroupEditor> {
  late final _name =
      TextEditingController(text: '${widget.group?['name'] ?? ''}');
  late final _bot =
      TextEditingController(text: '${widget.group?['bot_id'] ?? ''}');
  late final _group =
      TextEditingController(text: '${widget.group?['group_id'] ?? ''}');
  late final _daily =
      TextEditingController(text: '${widget.group?['daily_limit'] ?? 20}');
  late final _cooldown =
      TextEditingController(text: '${widget.group?['cooldown_seconds'] ?? 60}');
  late String _platform = '${widget.group?['platform'] ?? 'qq'}';
  late bool _enabled = widget.group?['enabled'] != false;
  late bool _levels = widget.group?['level_system_enabled'] == true;
  late String _safety = widget.group?['safety_mode'] == null
      ? 'inherit'
      : widget.group!['safety_mode'] == true
          ? 'on'
          : 'off';
  bool _saving = false;
  String? _error;
  @override
  void dispose() {
    for (final c in [_name, _bot, _group, _daily, _cooldown]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final daily = int.tryParse(_daily.text),
        cooldown = int.tryParse(_cooldown.text);
    if (_name.text.trim().isEmpty ||
        _bot.text.trim().isEmpty ||
        _group.text.trim().isEmpty ||
        daily == null ||
        daily < 1 ||
        cooldown == null ||
        cooldown < 0) {
      setState(() => _error = '请填写名称、适配器 ID、群 ID 和有效限制（每日至少 1 次，冷却至少 0 秒）。');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.saveChatGroup({
        'key': widget.group?['key'] ??
            '$_platform:${_bot.text.trim()}:${_group.text.trim()}',
        'name': _name.text.trim(),
        'platform': _platform,
        'bot_id': _bot.text.trim(),
        'group_id': _group.text.trim(),
        'enabled': _enabled,
        'level_system_enabled': _levels,
        'safety_mode': _safety == 'inherit' ? null : _safety == 'on',
        'daily_limit': daily,
        'cooldown_seconds': cooldown,
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = '保存失败，填写内容保留：$error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
      canPop: !_saving,
      child: AlertDialog(
          title: Text(widget.group == null ? '新增群聊' : '编辑群设置'),
          content: SizedBox(
              width: 480,
              child: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    controller: _name,
                    enabled: !_saving,
                    decoration: const InputDecoration(labelText: '群名称')),
                DropdownButtonFormField<String>(
                    initialValue: _platform,
                    decoration: const InputDecoration(labelText: '平台'),
                    items: [
                      for (final p in ['qq'])
                        DropdownMenuItem(value: p, child: Text(p))
                    ],
                    onChanged: _saving || widget.group != null
                        ? null
                        : (p) => setState(() => _platform = p!)),
                TextField(
                    controller: _bot,
                    enabled: !_saving && widget.group == null,
                    decoration:
                        const InputDecoration(labelText: 'AstrBot 适配器 ID')),
                TextField(
                    controller: _group,
                    enabled: !_saving && widget.group == null,
                    decoration: const InputDecoration(labelText: '群 / 频道 ID')),
                SwitchListTile(
                    title: const Text('此群启用'),
                    value: _enabled,
                    onChanged:
                        _saving ? null : (v) => setState(() => _enabled = v)),
                SwitchListTile(
                    title: const Text('启用用户等级系统'),
                    subtitle: const Text('启用后未登记成员默认为 0 级'),
                    value: _levels,
                    onChanged:
                        _saving ? null : (v) => setState(() => _levels = v)),
                DropdownButtonFormField<String>(
                    initialValue: _safety,
                    decoration: const InputDecoration(labelText: '安全模式'),
                    items: const [
                      DropdownMenuItem(value: 'inherit', child: Text('继承全局')),
                      DropdownMenuItem(value: 'on', child: Text('开启')),
                      DropdownMenuItem(value: 'off', child: Text('关闭'))
                    ],
                    onChanged:
                        _saving ? null : (v) => setState(() => _safety = v!)),
                TextField(
                    controller: _daily,
                    enabled: !_saving,
                    keyboardType: TextInputType.number,
                    decoration:
                        const InputDecoration(labelText: '每日次数（1 / 2 级）')),
                TextField(
                    controller: _cooldown,
                    enabled: !_saving,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '冷却秒数（1 级）')),
                if (_error != null) Text(_error!),
              ]))),
          actions: [
            TextButton(
                onPressed: _saving ? null : () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? '保存中' : '保存'))
          ]));
}

class _GroupUserEditor extends StatefulWidget {
  const _GroupUserEditor(
      {required this.api,
      required this.group,
      required this.groups,
      this.user});
  final HubApi api;
  final Map<String, dynamic> group;
  final List<Map<String, dynamic>> groups;
  final Map<String, dynamic>? user;
  @override
  State<_GroupUserEditor> createState() => _GroupUserEditorState();
}

class _GroupUserEditorState extends State<_GroupUserEditor> {
  List<Map<String, dynamic>> get _compatibleGroups => widget.groups
      .where((g) =>
          g['platform'] == widget.group['platform'] &&
          g['bot_id'] == widget.group['bot_id'])
      .toList();
  late final _id = TextEditingController(text: '${widget.user?['qq'] ?? ''}');
  late int _grade = (widget.user?['grade'] as num?)?.toInt() ?? 1;
  late String _primary = '${widget.user?['primary_group'] ?? ''}';
  bool _saving = false;
  String? _error;
  @override
  void dispose() {
    _id.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_id.text.trim().isEmpty) {
      setState(() => _error = '请填写平台账号 ID');
      return;
    }
    if (_primary.isNotEmpty &&
        !_compatibleGroups.any((g) => g['key'] == _primary)) {
      setState(() => _error = '主要群必须属于同一个平台及 Bot 适配器，请重新选择。');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.saveChatGroupUser({
        'group_key': widget.group['key'],
        'qq': _id.text.trim(),
        'grade': _grade,
        'primary_group': _primary
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = '保存失败，填写内容保留：$error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
      canPop: !_saving,
      child: AlertDialog(
          title: const Text('群成员权限'),
          content: SizedBox(
              width: 420,
              child: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    controller: _id,
                    enabled: !_saving && widget.user == null,
                    decoration:
                        const InputDecoration(labelText: 'QQ / 平台用户 ID')),
                DropdownButtonFormField<int>(
                    initialValue: _grade,
                    decoration: const InputDecoration(labelText: '权限等级'),
                    items: [
                      for (var i = 0; i <= 4; i++)
                        DropdownMenuItem(value: i, child: Text('$i 级'))
                    ],
                    onChanged:
                        _saving ? null : (v) => setState(() => _grade = v!)),
                DropdownButtonFormField<String>(
                    initialValue: _primary,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: '主要跑图群'),
                    items: [
                      const DropdownMenuItem(value: '', child: Text('未指定')),
                      if (_primary.isNotEmpty &&
                          !_compatibleGroups.any((g) => g['key'] == _primary))
                        DropdownMenuItem(
                            value: _primary,
                            enabled: false,
                            child: const Text('不兼容的主要群，请重新选择')),
                      for (final g in _compatibleGroups)
                        DropdownMenuItem(
                            value: '${g['key']}', child: Text('${g['name']}'))
                    ],
                    onChanged:
                        _saving ? null : (v) => setState(() => _primary = v!)),
                const Text('等级仅应用于所选群；不修改其他群成员权限。'),
                if (_error != null) Text(_error!),
              ]))),
          actions: [
            TextButton(
                onPressed: _saving ? null : () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? '保存中' : '保存'))
          ]));
}
