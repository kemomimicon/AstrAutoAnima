import '../../core/courtyard_theme.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/session_store.dart';
import '../lite/qq_command_composer_page.dart';

enum ConnectionRoute { standard, local, qq, lan, tailnet, tunnel, directPublic }

class ConnectionPage extends StatefulWidget {
  const ConnectionPage({
    required this.onConnected,
    this.fixedMode,
    this.fixedDeployment,
    this.onBack,
    this.initialSession,
    this.initialError,
    this.offlineTool,
    super.key,
  });

  final Future<void> Function(HubSession session) onConnected;
  final HubAccessMode? fixedMode;
  final HubDeploymentMode? fixedDeployment;
  final VoidCallback? onBack;
  final HubSession? initialSession;
  final String? initialError;
  final Widget? offlineTool;

  @override
  State<ConnectionPage> createState() => _ConnectionPageState();
}

class _ConnectionPageState extends State<ConnectionPage> {
  final _formKey = GlobalKey<FormState>();
  final _urlController = TextEditingController(
    text: kIsWeb ? Uri.base.origin : 'http://127.0.0.1:6278',
  );
  final _tokenController = TextEditingController();
  bool _working = false;
  bool _obscureToken = true;
  late HubAccessMode _mode;
  String? _error;
  ConnectionRoute _route = ConnectionRoute.standard;
  bool _showAdvancedRoutes = false;
  bool _acknowledgeDirect = false;

  String get _routeNote => switch (_route) {
        ConnectionRoute.local => '本机 Hub 直连 ComfyUI，不经过 AstrBot／QQ；仅限此电脑，Hub 必须启用 local 模式。',
        ConnectionRoute.qq => '只复制文字到 QQ；无入站端口、无需 Hub 令牌，但依赖 Bot 在线，不能管理文件。',
        ConnectionRoute.lan => '适合同一局域网。离家后不可直连；请勿把管理端口映射到公网。',
        ConnectionRoute.tailnet => '手机和电脑均须加入同一私有组网；只授权自己的设备。需安装第三方客户端。',
        ConnectionRoute.tunnel =>
          '需自行配置隧道、HTTPS 和身份验证；外部服务与访问策略错误会带来暴露风险。本应用不会自动开隧道。',
        ConnectionRoute.directPublic =>
          '高风险：公开端口会接收互联网流量。必须自行配置 HTTPS、强认证和防火墙；切勿暴露 6185/8188/8765。',
        ConnectionRoute.standard => '连接已有 Hub；服务器地址由部署者提供。个人电脑建议优先 QQ 指令或私有组网。',
      };

  @override
  void initState() {
    super.initState();
    _mode = widget.fixedDeployment == HubDeploymentMode.local
        ? HubAccessMode.admin : widget.fixedMode ?? HubAccessMode.lite;
    if (widget.fixedDeployment == HubDeploymentMode.local) {
      _route = ConnectionRoute.local;
    }
    if (widget.initialSession?.baseUrl.isNotEmpty ?? false) {
      _urlController.text = widget.initialSession!.baseUrl;
      _tokenController.text = widget.initialSession!.token;
      _mode = widget.fixedDeployment == HubDeploymentMode.local
          ? HubAccessMode.admin
          : widget.fixedMode ?? widget.initialSession!.mode;
    }
    _error = widget.initialError;
  }

  @override
  void dispose() {
    _urlController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (_route == ConnectionRoute.qq) {
      Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => const QqCommandComposerPage()));
      return;
    }
    if (_route == ConnectionRoute.directPublic && !_acknowledgeDirect) {
      setState(() => _error = '请先确认公网暴露风险；推荐使用私有组网。');
      return;
    }
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _working = true;
      _error = null;
    });
    final session = HubSession(
      baseUrl: _urlController.text.trim().replaceAll(RegExp(r'/+$'), ''),
      token: _tokenController.text.trim(),
      mode: _route == ConnectionRoute.local ? HubAccessMode.admin : _mode,
      deployment: _route == ConnectionRoute.local
          ? HubDeploymentMode.local : HubDeploymentMode.remote,
    );
    final api = HubApi(baseUrl: session.baseUrl, token: session.token);
    try {
      final serverMode = await api.getExecutionMode();
      if (session.deployment.name != serverMode) {
        throw HubApiException('工作站运行在 $serverMode 模式，请核对连接方式和 Hub 配置。');
      }
      if (session.isAdmin) {
        await api.getWorkstationStatus();
      } else {
        await api.getLitePresets();
      }
      if (!mounted) return;
      await widget.onConnected(session);
    } on HubApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      api.dispose();
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
                      const CourtyardWelcome(),
                      const SizedBox(height: 18),
                      Text(
                        widget.fixedDeployment == HubDeploymentMode.local
                            ? '连接本机工作站' : '连接工作站',
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
                      if (widget.fixedDeployment != HubDeploymentMode.local) SwitchListTile(
                        title: const Text('显示高级远程方式'),
                        value: _showAdvancedRoutes,
                        onChanged: (value) => setState(() {
                          _showAdvancedRoutes = value;
                          if (!value &&
                              {
                                ConnectionRoute.tailnet,
                                ConnectionRoute.tunnel,
                                ConnectionRoute.directPublic,
                              }.contains(_route)) {
                            _route = ConnectionRoute.standard;
                          }
                        }),
                      ),
                      if (widget.fixedDeployment != HubDeploymentMode.local) DropdownButtonFormField<ConnectionRoute>(
                        key: ValueKey(
                            'route-$_showAdvancedRoutes-${_route.name}'),
                        initialValue: _route,
                        isExpanded: true,
                        decoration:
                            const InputDecoration(labelText: '连接方式（互斥）'),
                        items: [
                          const DropdownMenuItem(
                              value: ConnectionRoute.standard,
                              child: Text('现有 Hub 连接')),
                          if (!kIsWeb &&
                              defaultTargetPlatform == TargetPlatform.windows &&
                              widget.fixedDeployment == null &&
                              widget.fixedMode != HubAccessMode.lite)
                            const DropdownMenuItem(
                                value: ConnectionRoute.local,
                                child: Text('本机工作站 · 不经过 Bot')),
                          const DropdownMenuItem(
                              value: ConnectionRoute.qq,
                              child: Text('个人部署：复制 QQ 指令')),
                          const DropdownMenuItem(
                              value: ConnectionRoute.lan,
                              child: Text('局域网直连 Hub')),
                          if (_showAdvancedRoutes) ...const [
                            DropdownMenuItem(
                                value: ConnectionRoute.tailnet,
                                child: Text('私有组网直连 Hub')),
                            DropdownMenuItem(
                                value: ConnectionRoute.tunnel,
                                child: Text('受保护隧道连接 Hub')),
                            DropdownMenuItem(
                                value: ConnectionRoute.directPublic,
                                child: Text('直接公网端口 · 高风险')),
                          ],
                        ],
                        onChanged: (value) => setState(() {
                          _route = value ?? ConnectionRoute.standard;
                          if (_route == ConnectionRoute.local) {
                            _mode = HubAccessMode.admin;
                            _urlController.text = 'http://127.0.0.1:6278';
                          }
                          _error = null;
                        }),
                      ),
                      const SizedBox(height: 8),
                      Text(_routeNote,
                          style: Theme.of(context).textTheme.bodySmall),
                      if (widget.onBack != null)
                        TextButton.icon(
                          onPressed: _working ? null : widget.onBack,
                          icon: const Icon(Icons.swap_horiz),
                          label: const Text('返回工作站选择'),
                        ),
                      if (_route == ConnectionRoute.directPublic)
                        CheckboxListTile(
                          title: const Text('我已核对 HTTPS、访问控制与实际开放端口'),
                          value: _acknowledgeDirect,
                          onChanged: (value) => setState(
                              () => _acknowledgeDirect = value ?? false),
                        ),
                      if (widget.fixedMode == null && _route != ConnectionRoute.local) ...[
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
                      ],
                      if (_route != ConnectionRoute.qq)
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
                            if (_route == ConnectionRoute.tunnel ||
                                _route == ConnectionRoute.directPublic) {
                              if (uri.scheme != 'https') {
                                return '远程公开入口必须使用 HTTPS';
                              }
                            }
                            if ({6185, 8188, 8765}.contains(uri.port)) {
                              return '这里填写 Hub 地址，不是 AstrBot、ComfyUI 或 Studio 端口';
                            }
                            if (_route == ConnectionRoute.local &&
                                !{'127.0.0.1', 'localhost', '::1'}.contains(uri.host)) {
                              return '本机模式只能连接 127.0.0.1';
                            }
                            return null;
                          },
                        ),
                      const SizedBox(height: 14),
                      if (_route != ConnectionRoute.qq)
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
                          validator: (value) => (value?.trim().isEmpty ?? true)
                              ? '请输入连接令牌'
                              : null,
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
                        label: Text(_route == ConnectionRoute.qq
                            ? '打开离线 QQ 指令'
                            : _working
                                ? '正在检测…'
                                : '连接'),
                      ),
                      if (widget.offlineTool != null) ...[
                        const SizedBox(height: 10),
                        OutlinedButton.icon(
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => Scaffold(
                                appBar: AppBar(title: const Text('云实例管理')),
                                body: widget.offlineTool!,
                              ),
                            ),
                          ),
                          icon: const Icon(Icons.cloud_outlined),
                          label: const Text('Hub 离线？管理云实例'),
                        ),
                      ],
                      const SizedBox(height: 12),
                      Text(
                        _mode == HubAccessMode.admin
                            ? '管理员令牌拥有增删改权限，请勿分享。'
                            : '用户令牌只允许访问自己的跑图、记录、预设和提示词。',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      if (kIsWeb) ...[
                        const SizedBox(height: 10),
                        Text(
                          'iPhone 安装：使用 Safari 打开本页，点“分享”→“添加到主屏幕”。',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
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
