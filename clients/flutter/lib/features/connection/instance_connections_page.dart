import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../../core/connection_profile.dart';
import '../../core/hub_api.dart';
import '../../core/session_store.dart';

typedef ProfilePreflight = Future<void> Function(HubSession session);

Future<void> preflightProfile(HubSession session) async {
  validateProfileEndpoint(session.baseUrl, session.deployment);
  if (!session.isConfigured) throw const HubApiException('该连接的令牌缺失，请编辑后填写。');
  final api = HubApi(baseUrl: session.baseUrl, token: session.token);
  try {
    if (await api.getExecutionMode() != session.deployment.name) {
      throw const HubApiException('Hub 执行模式与连接配置不一致；未切换当前连接。');
    }
    if (session.isAdmin) {
      await api.getWorkstationStatus();
    } else {
      await api.getLitePresets();
    }
  } finally {
    api.dispose();
  }
}

class InstanceConnectionsPage extends StatefulWidget {
  const InstanceConnectionsPage(
      {required this.store,
      required this.current,
      required this.onActivate,
      this.scope = 'manager',
      this.preflight = preflightProfile,
      this.allowLocal,
      this.allowService = true,
      super.key});
  final SessionStore store;
  final HubSession current;
  final String scope;
  final Future<void> Function(HubSession) onActivate;
  final ProfilePreflight preflight;
  final bool? allowLocal;
  final bool allowService;
  @override
  State<InstanceConnectionsPage> createState() =>
      _InstanceConnectionsPageState();
}

class _InstanceConnectionsPageState extends State<InstanceConnectionsPage> {
  List<ConnectionProfile> _profiles = [];
  bool _busy = true;
  String? _error;
  bool get _localAllowed =>
      widget.allowLocal ??
      (!kIsWeb && defaultTargetPlatform == TargetPlatform.windows);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows =
          await widget.store.profiles(widget.scope, migrate: widget.current);
      if (mounted) {
        setState(() {
          _profiles = rows;
          _busy = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = '读取连接列表失败，未修改保存内容。';
          _busy = false;
        });
      }
    }
  }

  Future<void> _activate(ConnectionProfile profile) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final session = await widget.store.profileSession(widget.scope, profile);
      if (!await _confirmTransport(session) || !mounted) return;
      await widget.preflight(session);
      if (!mounted) return;
      // Parent replaces the complete navigator/session tree. No inactive polling.
      await widget.onActivate(session);
    } catch (error) {
      if (mounted) {
        setState(() => _error =
            error is HubApiException ? error.message : '连接校验或保存失败；当前连接保持不变。');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirmTransport(HubSession session) async {
    final uri =
        Uri.parse(validateProfileEndpoint(session.baseUrl, session.deployment));
    if (uri.scheme == 'https' ||
        {'127.0.0.1', 'localhost', '::1'}.contains(uri.host)) {
      return true;
    }
    return await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
                    title: const Text('确认明文 HTTP 连接风险'),
                    content: Text(
                        '将向 ${uri.host} 发送 Hub 令牌。HTTP 不加密，局域网也可能被监听；不建议用于公网。建议改用 HTTPS 或受控私有组网。取消不会发出任何验证请求。'),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(context, false),
                          child: const Text('取消')),
                      FilledButton(
                          onPressed: () => Navigator.pop(context, true),
                          child: const Text('了解风险，继续连接'))
                    ])) ??
        false;
  }

  Future<void> _remove(ConnectionProfile profile) async {
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('移除保存的连接？'),
                content: Text(
                    '只从本设备移除“${profile.label}”及其保存令牌。不关闭实例、不删除远端图片或任务，当前会话可继续使用。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('移除连接'))
                ]));
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.store.removeProfile(widget.scope, profile.id);
      await _load();
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '移除失败，请重试；远端不受影响。';
        });
      }
    }
  }

  Future<void> _edit([ConnectionProfile? profile]) async {
    final result = await showDialog<({String label, HubSession session})>(
        context: context,
        builder: (_) => _ProfileEditor(
            profile: profile,
            allowLocal: _localAllowed,
            allowService: widget.allowService));
    if (result == null || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      var session = result.session;
      if (session.token.isEmpty && profile != null) {
        // Never forward a previous instance's token to an edited endpoint/mode.
        if (profile.baseUrl != session.baseUrl ||
            profile.mode != session.mode ||
            profile.deployment != session.deployment) {
          throw const HubApiException('修改地址或模式后必须重新填写该连接自己的令牌。');
        }
        session = await widget.store.profileSession(widget.scope, profile);
      }
      if (!await _confirmTransport(session) || !mounted) {
        if (mounted) setState(() => _busy = false);
        return;
      }
      await widget.preflight(session);
      await widget.store.saveProfile(widget.scope,
          id: profile?.id, label: result.label, session: session);
      await _load();
    } catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = error is HubApiException ? error.message : '保存连接失败，未切换当前连接。';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('设备与实例连接')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text(
            '保存多个 Hub 地址，按需切换。只连接当前选中的一个，不轮询离线实例；切换不取消远端任务。令牌分别保存在设备安全存储中。'),
        Text('当前：${widget.current.baseUrl}'),
        if (_busy) const LinearProgressIndicator(),
        if (_error != null)
          Padding(
              padding: const EdgeInsets.all(12),
              child: Text(_error!, key: const ValueKey('profile.error'))),
        for (final profile in _profiles)
          Card(
              child: ListTile(
            key: ValueKey('profile.${profile.id}'),
            title: Text(profile.label),
            subtitle: Text(
                '${profile.baseUrl}\n${profile.deployment == HubDeploymentMode.local ? '本机工作站' : profile.mode == HubAccessMode.admin ? '在线管理' : '在线服务'}'),
            isThreeLine: true,
            onTap: _busy ||
                    (profile.deployment == HubDeploymentMode.local &&
                        !_localAllowed) ||
                    (profile.mode == HubAccessMode.lite && !widget.allowService)
                ? null
                : () => _activate(profile),
            trailing: PopupMenuButton<String>(
                enabled: !_busy,
                onSelected: (value) =>
                    value == 'edit' ? _edit(profile) : _remove(profile),
                itemBuilder: (_) => const [
                      PopupMenuItem(value: 'edit', child: Text('编辑')),
                      PopupMenuItem(value: 'remove', child: Text('移除连接'))
                    ]),
          )),
        const SizedBox(height: 12),
        FilledButton.icon(
            key: const ValueKey('profile.add'),
            onPressed: _busy ? null : () => _edit(),
            icon: const Icon(Icons.add),
            label: const Text('新增连接')),
      ]));
}

class _ProfileEditor extends StatefulWidget {
  const _ProfileEditor(
      {this.profile, required this.allowLocal, required this.allowService});
  final ConnectionProfile? profile;
  final bool allowLocal;
  final bool allowService;
  @override
  State<_ProfileEditor> createState() => _ProfileEditorState();
}

class _ProfileEditorState extends State<_ProfileEditor> {
  late final _label = TextEditingController(text: widget.profile?.label ?? '');
  late final _url = TextEditingController(text: widget.profile?.baseUrl ?? '');
  final _token = TextEditingController();
  late WindowsWorkspaceMode _mode =
      widget.profile?.deployment == HubDeploymentMode.local
          ? WindowsWorkspaceMode.local
          : widget.profile?.mode == HubAccessMode.lite
              ? WindowsWorkspaceMode.onlineService
              : WindowsWorkspaceMode.onlineAdmin;
  String? _error;
  @override
  void dispose() {
    _label.dispose();
    _url.dispose();
    _token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
          title: Text(widget.profile == null ? '新增 Hub 连接' : '编辑 Hub 连接'),
          content: SizedBox(
              width: 440,
              child: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    controller: _label,
                    maxLength: 80,
                    decoration: const InputDecoration(labelText: '设备 / 实例名称')),
                DropdownButtonFormField<WindowsWorkspaceMode>(
                    initialValue: _mode,
                    isExpanded: true,
                    items: [
                      if (widget.allowLocal ||
                          _mode == WindowsWorkspaceMode.local)
                        const DropdownMenuItem(
                            value: WindowsWorkspaceMode.local,
                            child: Text('本机工作站')),
                      const DropdownMenuItem(
                          value: WindowsWorkspaceMode.onlineAdmin,
                          child: Text('在线管理')),
                      if (widget.allowService ||
                          _mode == WindowsWorkspaceMode.onlineService)
                        const DropdownMenuItem(
                            value: WindowsWorkspaceMode.onlineService,
                            child: Text('在线服务'))
                    ],
                    onChanged: (value) => setState(() {
                          _mode = value!;
                          _token.clear();
                        })),
                TextField(
                    controller: _url,
                    decoration: const InputDecoration(
                        labelText: 'Hub 地址（不是 AstrBot 6185）')),
                TextField(
                    controller: _token,
                    obscureText: true,
                    enableSuggestions: false,
                    autocorrect: false,
                    decoration: InputDecoration(
                        labelText: widget.profile == null
                            ? '该连接的令牌'
                            : '令牌（地址和模式不变时可留空）')),
                const Text('不自动安装、不开放端口；公网连接请使用 HTTPS 和访问控制。'),
                if (_error != null) Text(_error!),
              ]))),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
                onPressed: () {
                  try {
                    if (_label.text.trim().isEmpty) {
                      throw const FormatException('请填写名称');
                    }
                    final url =
                        validateProfileEndpoint(_url.text, _mode.deployment);
                    Navigator.pop(context, (
                      label: _label.text.trim(),
                      session: HubSession(
                          baseUrl: url,
                          token: _token.text.trim(),
                          mode: _mode.access,
                          deployment: _mode.deployment)
                    ));
                  } on FormatException catch (error) {
                    setState(() => _error = error.message);
                  }
                },
                child: const Text('校验并保存'))
          ]);
}
