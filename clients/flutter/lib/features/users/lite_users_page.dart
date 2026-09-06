import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';

class LiteUsersPage extends StatefulWidget {
  const LiteUsersPage({required this.api, super.key});

  final HubApi api;

  @override
  State<LiteUsersPage> createState() => _LiteUsersPageState();
}

class _LiteUsersPageState extends State<LiteUsersPage> {
  late Future<LiteUserListResult> _future = widget.api.getLiteUsers();
  bool _working = false;

  void _refresh() {
    setState(() => _future = widget.api.getLiteUsers());
  }

  void _notice(String message, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error ? Theme.of(context).colorScheme.error : null,
      ),
    );
  }

  Future<T?> _workingCall<T>(Future<T> Function() action) async {
    if (_working) return null;
    setState(() => _working = true);
    try {
      return await action();
    } on HubApiException catch (error) {
      _notice(
        error.statusCode == 409 ? '用户数据已变化，正在刷新。' : error.message,
        error: true,
      );
      if (error.statusCode == 409) _refresh();
      return null;
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _add(String revision) async {
    final draft = await _showUserEditor();
    if (draft == null) return;
    final result = await _workingCall(
      () => widget.api.createLiteUser(
        revision: revision,
        qq: draft.qq,
        label: draft.label,
        allowGroup: draft.allowGroup,
      ),
    );
    if (result == null || !mounted) return;
    _refresh();
    await _showIssuedToken(result);
  }

  Future<void> _edit(LiteUserRecord item, String revision) async {
    final draft = await _showUserEditor(initial: item, qqLocked: true);
    if (draft == null) return;
    final result = await _workingCall(
      () => widget.api.updateLiteUser(
        qq: item.qq,
        revision: revision,
        label: draft.label,
        allowGroup: draft.allowGroup,
      ),
    );
    if (result != null) {
      _notice('用户 ${item.qq} 已更新');
      _refresh();
    }
  }

  Future<void> _setEnabled(
    LiteUserRecord item,
    String revision,
    bool enabled,
  ) async {
    final result = await _workingCall(
      () => widget.api.updateLiteUser(
        qq: item.qq,
        revision: revision,
        enabled: enabled,
      ),
    );
    if (result != null) {
      _notice(enabled ? '用户 ${item.qq} 已启用' : '用户 ${item.qq} 已停用');
      _refresh();
    }
  }

  Future<void> _setAllowGroup(
    LiteUserRecord item,
    String revision,
    bool allowGroup,
  ) async {
    final result = await _workingCall(
      () => widget.api.updateLiteUser(
        qq: item.qq,
        revision: revision,
        allowGroup: allowGroup,
      ),
    );
    if (result != null) {
      _notice(allowGroup ? '已允许该用户调用群聊目标' : '已禁止该用户调用群聊目标');
      _refresh();
    }
  }

  Future<void> _rotate(LiteUserRecord item, String revision) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('换发用户令牌'),
        content: Text(
          '确定为 ${item.label}（${item.qq}）换发令牌？\n\n'
          '旧令牌会立即失效，新令牌只显示这一次。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认换发'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final result = await _workingCall(
      () => widget.api.rotateLiteUserToken(
        qq: item.qq,
        revision: revision,
      ),
    );
    if (result == null || !mounted) return;
    _refresh();
    await _showIssuedToken(result);
  }

  Future<void> _delete(LiteUserRecord item, String revision) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除用户'),
        content: Text(
          '确定删除 ${item.label}（${item.qq}）？\n\n'
          '该用户令牌会立即失效，服务端会保留备份、回收站和审计记录。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final result = await _workingCall(
      () => widget.api.deleteLiteUser(
        qq: item.qq,
        revision: revision,
      ),
    );
    if (result != null) {
      _notice('用户 ${item.qq} 已删除');
      _refresh();
    }
  }

  Future<_UserDraft?> _showUserEditor({
    LiteUserRecord? initial,
    bool qqLocked = false,
  }) async {
    final qqController = TextEditingController(text: initial?.qq ?? '');
    final labelController = TextEditingController(text: initial?.label ?? '');
    final formKey = GlobalKey<FormState>();
    var allowGroup = initial?.allowGroup ?? true;
    final result = await showDialog<_UserDraft>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text(initial == null ? '添加用户' : '编辑用户'),
          content: SizedBox(
            width: 520,
            child: Form(
              key: formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextFormField(
                    controller: qqController,
                    enabled: !qqLocked,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '绑定 QQ 号',
                      prefixIcon: Icon(Icons.account_circle_outlined),
                    ),
                    validator: (value) => RegExp(r'^[1-9][0-9]{4,14}$')
                            .hasMatch(value?.trim() ?? '')
                        ? null
                        : '请输入 5～15 位有效 QQ 号',
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: labelController,
                    maxLength: 120,
                    decoration: const InputDecoration(
                      labelText: '备注名称（可留空）',
                      prefixIcon: Icon(Icons.badge_outlined),
                    ),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('允许调用群聊目标'),
                    subtitle: const Text('关闭后，该令牌只能使用绑定 QQ 的个人私聊目标'),
                    value: allowGroup,
                    onChanged: (value) =>
                        setDialogState(() => allowGroup = value),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                if (!(formKey.currentState?.validate() ?? false)) return;
                Navigator.pop(
                  context,
                  _UserDraft(
                    qq: qqController.text.trim(),
                    label: labelController.text.trim(),
                    allowGroup: allowGroup,
                  ),
                );
              },
              child: Text(initial == null ? '添加并生成令牌' : '保存'),
            ),
          ],
        ),
      ),
    );
    qqController.dispose();
    labelController.dispose();
    return result;
  }

  Future<void> _showIssuedToken(LiteUserIssueResult result) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(result.action == 'rotated' ? '新令牌已生成' : '用户令牌已生成'),
        content: SizedBox(
          width: 680,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${result.user.label}（${result.user.qq}）'),
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: SelectableText(
                  result.token,
                  key: const Key('issued-lite-user-token'),
                ),
              ),
              const SizedBox(height: 14),
              Text(
                '该明文令牌只显示这一次。关闭窗口后无法找回，只能重新换发。请私下交付，不要发送到群聊或公开网盘。',
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ),
        ),
        actions: [
          TextButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: result.token));
              _notice('令牌已复制');
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('复制令牌'),
          ),
          TextButton.icon(
            onPressed: () async {
              final csv = 'qq,token\r\n${result.user.qq},${result.token}\r\n';
              await Clipboard.setData(ClipboardData(text: csv));
              _notice('交付 CSV 已复制');
            },
            icon: const Icon(Icons.table_view_outlined),
            label: const Text('复制交付 CSV'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('我已保存，关闭'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('用户与令牌',
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 4),
                  const Text('管理 QQ 绑定用户、群聊权限和一次性连接令牌'),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip: '刷新',
              onPressed: _working ? null : _refresh,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Icon(Icons.security_outlined),
                const SizedBox(width: 12),
                const Expanded(
                  child: Text(
                    '服务端只保存令牌哈希。已有令牌无法查看；泄露或遗失时请使用“换发令牌”。',
                  ),
                ),
                if (_working)
                  const SizedBox.square(
                    dimension: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        FutureBuilder<LiteUserListResult>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(
                child: Padding(
                  padding: EdgeInsets.all(48),
                  child: CircularProgressIndicator(),
                ),
              );
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final data = snapshot.data!;
            return Column(
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton.icon(
                    onPressed: _working ? null : () => _add(data.revision),
                    icon: const Icon(Icons.person_add_alt_1_outlined),
                    label: const Text('添加用户'),
                  ),
                ),
                const SizedBox(height: 12),
                if (data.items.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(48),
                    child: Center(child: Text('暂无绑定用户')),
                  )
                else
                  ...data.items.map(
                    (item) => _UserCard(
                      item: item,
                      working: _working,
                      onEnabledChanged: (value) =>
                          _setEnabled(item, data.revision, value),
                      onAllowGroupChanged: (value) =>
                          _setAllowGroup(item, data.revision, value),
                      onEdit: () => _edit(item, data.revision),
                      onRotate: () => _rotate(item, data.revision),
                      onDelete: () => _delete(item, data.revision),
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _UserCard extends StatelessWidget {
  const _UserCard({
    required this.item,
    required this.working,
    required this.onEnabledChanged,
    required this.onAllowGroupChanged,
    required this.onEdit,
    required this.onRotate,
    required this.onDelete,
  });

  final LiteUserRecord item;
  final bool working;
  final ValueChanged<bool> onEnabledChanged;
  final ValueChanged<bool> onAllowGroupChanged;
  final VoidCallback onEdit;
  final VoidCallback onRotate;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Wrap(
            spacing: 18,
            runSpacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              CircleAvatar(
                child: Icon(item.enabled ? Icons.person : Icons.person_off),
              ),
              SizedBox(
                width: 250,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.label,
                        style: Theme.of(context).textTheme.titleMedium),
                    SelectableText('QQ ${item.qq}'),
                  ],
                ),
              ),
              SizedBox(
                width: 150,
                child: SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('账号启用'),
                  value: item.enabled,
                  onChanged: working ? null : onEnabledChanged,
                ),
              ),
              SizedBox(
                width: 190,
                child: SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('允许群聊目标'),
                  value: item.allowGroup,
                  onChanged: working ? null : onAllowGroupChanged,
                ),
              ),
              PopupMenuButton<String>(
                enabled: !working,
                onSelected: (value) {
                  switch (value) {
                    case 'edit':
                      onEdit();
                    case 'rotate':
                      onRotate();
                    case 'delete':
                      onDelete();
                  }
                },
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'edit', child: Text('编辑用户')),
                  PopupMenuItem(value: 'rotate', child: Text('换发令牌')),
                  PopupMenuDivider(),
                  PopupMenuItem(value: 'delete', child: Text('删除用户')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _UserDraft {
  const _UserDraft({
    required this.qq,
    required this.label,
    required this.allowGroup,
  });

  final String qq;
  final String label;
  final bool allowGroup;
}
