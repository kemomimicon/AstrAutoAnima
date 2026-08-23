import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/session_store.dart';

class ConnectionPage extends StatefulWidget {
  const ConnectionPage({required this.onConnected, super.key});

  final Future<void> Function(HubSession session) onConnected;

  @override
  State<ConnectionPage> createState() => _ConnectionPageState();
}

class _ConnectionPageState extends State<ConnectionPage> {
  final _formKey = GlobalKey<FormState>();
  final _urlController = TextEditingController(text: 'http://127.0.0.1:6278');
  final _tokenController = TextEditingController();
  bool _working = false;
  bool _obscureToken = true;
  HubAccessMode _mode = HubAccessMode.lite;
  String? _error;

  @override
  void dispose() {
    _urlController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _working = true;
      _error = null;
    });
    final session = HubSession(
      baseUrl: _urlController.text.trim().replaceAll(RegExp(r'/+$'), ''),
      token: _tokenController.text.trim(),
      mode: _mode,
    );
    try {
      final api = HubApi(baseUrl: session.baseUrl, token: session.token);
      await api.checkHealth();
      if (session.isAdmin) {
        await api.getWorkstationStatus();
      } else {
        await api.getLitePresets();
      }
      await widget.onConnected(session);
    } on HubApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(30),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(
                        Icons.hub_outlined,
                        size: 48,
                        color: Theme.of(context).colorScheme.primary,
                      ),
                      const SizedBox(height: 18),
                      Text(
                        '连接工作站',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _mode == HubAccessMode.admin
                            ? '使用管理员令牌连接完整管理端'
                            : '使用用户令牌连接轻量跑图端',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                      const SizedBox(height: 28),
                      SegmentedButton<HubAccessMode>(
                        segments: const [
                          ButtonSegment(
                            value: HubAccessMode.lite,
                            icon: Icon(Icons.person_outline),
                            label: Text('用户端'),
                          ),
                          ButtonSegment(
                            value: HubAccessMode.admin,
                            icon: Icon(Icons.admin_panel_settings_outlined),
                            label: Text('管理端'),
                          ),
                        ],
                        selected: {_mode},
                        onSelectionChanged: (value) =>
                            setState(() => _mode = value.first),
                      ),
                      const SizedBox(height: 18),
                      TextFormField(
                        controller: _urlController,
                        decoration: const InputDecoration(
                          labelText: '工作站地址',
                          prefixIcon: Icon(Icons.dns_outlined),
                          hintText: 'https://hub.example.com',
                        ),
                        keyboardType: TextInputType.url,
                        validator: (value) {
                          final uri = Uri.tryParse(value?.trim() ?? '');
                          if (uri == null ||
                              !uri.hasScheme ||
                              !uri.hasAuthority ||
                              !{'http', 'https'}.contains(uri.scheme)) {
                            return '请输入完整的 HTTP(S) 地址';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 14),
                      TextFormField(
                        controller: _tokenController,
                        obscureText: _obscureToken,
                        decoration: InputDecoration(
                          labelText:
                              _mode == HubAccessMode.admin ? '管理员令牌' : '用户令牌',
                          prefixIcon: const Icon(Icons.key_outlined),
                          suffixIcon: IconButton(
                            onPressed: () => setState(
                              () => _obscureToken = !_obscureToken,
                            ),
                            icon: Icon(
                              _obscureToken
                                  ? Icons.visibility_outlined
                                  : Icons.visibility_off_outlined,
                            ),
                          ),
                        ),
                        validator: (value) =>
                            (value?.trim().isEmpty ?? true) ? '请输入连接令牌' : null,
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 16),
                        Text(
                          _error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ],
                      const SizedBox(height: 24),
                      FilledButton.icon(
                        onPressed: _working ? null : _connect,
                        icon: _working
                            ? const SizedBox.square(
                                dimension: 18,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.link),
                        label: Text(_working ? '正在检测…' : '连接'),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _mode == HubAccessMode.admin
                            ? '管理员令牌拥有增删改权限，请勿分享。'
                            : '用户令牌只有只读权限；生成的指令会复制到剪贴板，由你在 QQ 中确认发送。',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
