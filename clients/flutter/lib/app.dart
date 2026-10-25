import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'features/gallery/gallery_page.dart';
import 'features/extensions/extension_management_page.dart';
import 'features/platforms/platform_switchboard_page.dart';

import 'core/app_edition.dart';
import 'core/admin_navigation.dart';
import 'core/courtyard_theme.dart';
import 'core/character_use_request.dart';
import 'core/hub_api.dart';
import 'core/notification_service.dart';
import 'core/server_online_tracker.dart';
import 'core/session_store.dart';
import 'features/connection/connection_page.dart';
import 'features/connection/workstation_choice_page.dart';
import 'features/connection/instance_connections_page.dart';
import 'features/users/chat_groups_page.dart';
import 'features/characters/character_dictionary_page.dart';
import 'features/cloud/compshare_instance_page.dart';
import 'features/dashboard/dashboard_page.dart';
import 'features/lite/lite_generate_page.dart';
import 'features/lite/lite_job_history_page.dart';
import 'features/lite/lite_prompt_library_page.dart';
import 'features/lite/personal_presets_page.dart';
import 'features/loras/lora_library_page.dart';
import 'features/presets/presets_page.dart';
import 'features/presets/task_suites_page.dart';
import 'features/prompts/prompt_library_page.dart';
import 'features/splash/service_splash.dart';
import 'features/users/lite_users_page.dart';
import 'features/settings/settings_drawer.dart';
import 'features/settings/storage_management_page.dart';
import 'features/prompts/prompt_reports_page.dart';

class AstrAutoAnimaApp extends StatefulWidget {
  const AstrAutoAnimaApp({
    required this.store,
    required this.notificationService,
    required this.initialSession,
    this.edition = AppEdition.unified,
    this.apiFactory,
    super.key,
  });

  final SessionStore store;
  final NotificationService notificationService;
  final HubSession initialSession;
  final AppEdition edition;
  final HubApi Function(HubSession)? apiFactory;

  @override
  State<AstrAutoAnimaApp> createState() => _AstrAutoAnimaAppState();
}

class _AstrAutoAnimaAppState extends State<AstrAutoAnimaApp> {
  late HubSession _session = widget.initialSession;
  HubSession? _connectionDraft;
  WindowsWorkspaceMode? _selectedWorkspace;
  String? _selectionError;
  bool _choosing = false;
  int _sessionEpoch = 0;

  Future<void> _activateProfile(HubSession session) async {
    if (widget.edition.isService ||
        (!_showChoice && widget.edition.isAdmin && !session.isAdmin) ||
        (session.deployment == HubDeploymentMode.local && !_showChoice)) {
      throw const HubApiException('此客户端模式不允许切换到该连接；当前连接未修改。');
    }
    final workspace = session.deployment == HubDeploymentMode.local
        ? WindowsWorkspaceMode.local
        : session.isAdmin
            ? WindowsWorkspaceMode.onlineAdmin
            : WindowsWorkspaceMode.onlineService;
    if (_showChoice) {
      await widget.store.saveForWorkspace(workspace, session);
    } else {
      await widget.store.save(session);
    }
    if (!mounted) return;
    setState(() {
      _selectedWorkspace = _showChoice ? workspace : null;
      _session = session;
      _connectionDraft = null;
      _selectionError = null;
      _sessionEpoch++;
    });
  }

  bool get _showChoice =>
      !kIsWeb &&
      defaultTargetPlatform == TargetPlatform.windows &&
      !widget.edition.isService;

  @override
  void initState() {
    super.initState();
    appThemeMode.addListener(_themeChanged);
    appSkin.addListener(_themeChanged);
    unawaited(loadAppTheme());
  }

  void _themeChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    appThemeMode.removeListener(_themeChanged);
    appSkin.removeListener(_themeChanged);
    super.dispose();
  }

  Future<void> _connected(HubSession session) async {
    if (_showChoice && _selectedWorkspace != null) {
      await widget.store.saveForWorkspace(_selectedWorkspace!, session);
    } else {
      await widget.store.save(session);
    }
    if (mounted) {
      setState(() {
        _session = session;
        _connectionDraft = null;
        _selectionError = null;
        _sessionEpoch++;
      });
    }
  }

  Future<void> _disconnect() async {
    if (_showChoice && _selectedWorkspace != null) {
      await widget.store.clearForWorkspace(_selectedWorkspace!);
    } else {
      await widget.store.clearForDeployment(_session.deployment);
    }
    if (mounted) {
      setState(() {
        _sessionEpoch++;
        _session = HubSession(
            baseUrl: '',
            token: '',
            mode: _selectedWorkspace?.access ?? _session.mode,
            deployment: _selectedWorkspace?.deployment ?? _session.deployment);
      });
    }
  }

  Future<void> _selectWorkspace(WindowsWorkspaceMode workspace) async {
    if (_choosing) return;
    setState(() => _choosing = true);
    String? error;
    HubSession session;
    try {
      session = await widget.store.loadForWorkspace(workspace);
    } catch (_) {
      session = HubSession(
          baseUrl: '',
          token: '',
          mode: workspace.access,
          deployment: workspace.deployment);
      error = '读取已保存的连接失败，请重新填写地址和令牌。';
    }
    if (session.isConfigured) {
      final api = HubApi(baseUrl: session.baseUrl, token: session.token);
      try {
        final mode = await api.getExecutionMode();
        if (mode != workspace.deployment.name) {
          error = '地址当前运行 $mode 模式，请核对所选工作站。';
        } else if (session.isAdmin) {
          await api.getWorkstationStatus();
        } else {
          await api.getLitePresets();
        }
      } on HubApiException catch (exc) {
        error = '已保存的连接暂不可用：${exc.message}';
      } finally {
        api.dispose();
      }
    }
    if (mounted) {
      setState(() {
        _choosing = false;
        _selectedWorkspace = workspace;
        _selectionError = error;
        _connectionDraft = error == null ? null : session;
        _session = error == null
            ? session
            : HubSession(
                baseUrl: '',
                token: '',
                mode: workspace.access,
                deployment: workspace.deployment);
        _sessionEpoch++;
      });
    }
  }

  void _switchWorkspace() {
    setState(() {
      _selectedWorkspace = null;
      _selectionError = null;
      _connectionDraft = null;
      _session = const HubSession(baseUrl: '', token: '');
      _sessionEpoch++;
    });
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF5B6CFF),
      brightness: Brightness.light,
    );
    final requiredMode = _showChoice && _selectedWorkspace != null
        ? _selectedWorkspace!.access
        : switch (widget.edition) {
            AppEdition.admin => HubAccessMode.admin,
            AppEdition.service => HubAccessMode.lite,
            AppEdition.unified => null,
          };
    final sessionAllowed = _session.isConfigured &&
        (requiredMode == null || _session.mode == requiredMode) &&
        (_selectedWorkspace == null ||
            _session.deployment == _selectedWorkspace!.deployment);
    final home = _showChoice && _selectedWorkspace == null
        ? WorkstationChoicePage(onSelect: _selectWorkspace, loading: _choosing)
        : sessionAllowed
            ? _session.deployment == HubDeploymentMode.local
                ? LiteShell(
                    session: _session,
                    store: widget.store,
                    notificationService: widget.notificationService,
                    onDisconnect: _disconnect,
                    onActivateProfile:
                        widget.edition.isService ? null : _activateProfile,
                    apiFactory: widget.apiFactory,
                    onSwitch: _showChoice ? _switchWorkspace : null,
                  )
                : _session.isAdmin
                    ? HubShell(
                        session: _session,
                        store: widget.store,
                        notificationService: widget.notificationService,
                        onDisconnect: _disconnect,
                        onActivateProfile:
                            widget.edition.isService ? null : _activateProfile,
                        apiFactory: widget.apiFactory,
                        onSwitch: _showChoice ? _switchWorkspace : null,
                      )
                    : LiteShell(
                        session: _session,
                        store: widget.store,
                        notificationService: widget.notificationService,
                        onDisconnect: _disconnect,
                        onActivateProfile:
                            widget.edition.isService ? null : _activateProfile,
                        apiFactory: widget.apiFactory,
                        onSwitch: _showChoice ? _switchWorkspace : null,
                      )
            : ConnectionPage(
                onConnected: _connected,
                fixedMode: requiredMode,
                fixedDeployment:
                    _showChoice ? _selectedWorkspace?.deployment : null,
                onBack: _showChoice ? _switchWorkspace : null,
                initialSession: _connectionDraft,
                initialError: _selectionError,
                offlineTool:
                    widget.edition.isAdmin && requiredMode != HubAccessMode.lite
                        ? const CompShareInstancePage()
                        : null,
              );
    return MaterialApp(
      // Recreate navigator AND shell on switch. Old dialogs, routes, IndexedStack
      // histories, polling timers and late responses cannot survive into B.
      key: ValueKey('hub-session-$_sessionEpoch'),
      themeMode: appThemeMode.value,
      debugShowCheckedModeBanner: false,
      title: widget.edition.title,
      theme: appSkin.value == 'courtyard'
          ? courtyardTheme(Brightness.light)
          : ThemeData(
              useMaterial3: true,
              colorScheme: colorScheme,
              scaffoldBackgroundColor: const Color(0xFFF6F7FB),
              cardTheme: const CardThemeData(
                elevation: 0,
                margin: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.all(Radius.circular(18)),
                ),
              ),
              inputDecorationTheme: const InputDecorationTheme(
                filled: true,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.all(Radius.circular(14)),
                  borderSide: BorderSide.none,
                ),
              ),
            ),
      darkTheme: appSkin.value == 'courtyard'
          ? courtyardTheme(Brightness.dark)
          : ThemeData(
              useMaterial3: true,
              colorScheme: ColorScheme.fromSeed(
                seedColor: const Color(0xFF94A0FF),
                brightness: Brightness.dark,
              ),
            ),
      home: widget.edition.isService ? ServiceSplash(child: home) : home,
    );
  }
}

class LiteShell extends StatefulWidget {
  const LiteShell({
    required this.session,
    required this.store,
    required this.notificationService,
    required this.onDisconnect,
    this.onSwitch,
    this.onActivateProfile,
    this.apiFactory,
    super.key,
  });

  final HubSession session;
  final SessionStore store;
  final NotificationService notificationService;
  final Future<void> Function() onDisconnect;
  final VoidCallback? onSwitch;
  final Future<void> Function(HubSession)? onActivateProfile;
  final HubApi Function(HubSession)? apiFactory;

  @override
  State<LiteShell> createState() => _LiteShellState();
}

class _LiteShellState extends State<LiteShell> {
  int _index = 0;
  int _characterRequestSequence = 0;
  final ValueNotifier<CharacterUseRequest?> _characterRequest =
      ValueNotifier(null);
  final ServerOnlineTracker _serverTracker = ServerOnlineTracker();
  Timer? _serverMonitorTimer;
  bool _serverOnlineReminderEnabled = false;
  bool? _serverReachable;
  bool _checkingServer = false;
  late final HubApi _api;

  @override
  void initState() {
    super.initState();
    _api = widget.apiFactory?.call(widget.session) ??
        HubApi(baseUrl: widget.session.baseUrl, token: widget.session.token);
    unawaited(_loadServerOnlineReminder());
  }

  @override
  void dispose() {
    _serverMonitorTimer?.cancel();
    _api.dispose();
    _characterRequest.dispose();
    super.dispose();
  }

  Future<void> _loadServerOnlineReminder() async {
    final enabled = await widget.store.loadServerOnlineReminderEnabled();
    if (!mounted) return;
    setState(() => _serverOnlineReminderEnabled = enabled);
    if (enabled) _startServerMonitor();
  }

  Future<void> _setServerOnlineReminder(bool enabled) async {
    if (enabled) {
      var permitted = false;
      try {
        permitted = await widget.notificationService.requestPermission();
      } on Exception {
        permitted = false;
      }
      if (!permitted) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('未获得系统通知权限，无法开启提醒。')),
          );
        }
        return;
      }
    }
    await widget.store.saveServerOnlineReminderEnabled(enabled);
    if (!mounted) return;
    setState(() {
      _serverOnlineReminderEnabled = enabled;
      if (!enabled) _serverReachable = null;
    });
    if (enabled) {
      _startServerMonitor();
    } else {
      _stopServerMonitor();
    }
  }

  void _startServerMonitor() {
    _serverMonitorTimer?.cancel();
    _serverTracker.reset();
    unawaited(_checkServer());
    _serverMonitorTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => unawaited(_checkServer()),
    );
  }

  void _stopServerMonitor() {
    _serverMonitorTimer?.cancel();
    _serverMonitorTimer = null;
    _serverTracker.reset();
  }

  Future<void> _checkServer() async {
    if (!_serverOnlineReminderEnabled || _checkingServer) return;
    _checkingServer = true;
    var online = false;
    try {
      await _api.checkHealth();
      online = true;
    } on HubApiException {
      online = false;
    } finally {
      _checkingServer = false;
    }
    final shouldNotify = _serverTracker.update(online);
    if (!mounted) return;
    if (mounted && _serverReachable != online) {
      setState(() => _serverReachable = online);
    }
    if (shouldNotify) {
      try {
        await widget.notificationService.showServerOnline(
          baseUrl: widget.session.baseUrl,
        );
      } on Exception {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('服务器已上线，但系统通知发送失败。')),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final localMode = widget.session.deployment == HubDeploymentMode.local;
    final pages = [
      LiteGeneratePage(
        api: _api,
        localMode: localMode,
        characterRequest: _characterRequest,
        serverOnlineReminderEnabled: _serverOnlineReminderEnabled,
        serverReachable: _serverReachable,
        onServerOnlineReminderChanged: _setServerOnlineReminder,
      ),
      LiteJobHistoryPage(api: _api, localMode: localMode),
      localMode
          ? PresetsPage(api: _api)
          : PresetSections(api: _api, presets: PersonalPresetsPage(api: _api)),
      if (localMode) LoraLibraryPage(api: _api),
      LitePromptLibraryPage(api: _api),
      CharacterDictionaryPage(
        api: _api,
        onUseCharacter: (item, strong) {
          _characterRequest.value = CharacterUseRequest(
            tag: item.tag,
            mode: strong ? 'strong' : 'weak',
            sequence: ++_characterRequestSequence,
          );
          setState(() => _index = 0);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('已把 ${item.tag} 添加到使用角色框')),
          );
        },
      ),
    ];
    final destinations = [
      NavigationDestination(
        icon: CourtyardIcon(Icons.auto_awesome_outlined),
        selectedIcon: CourtyardIcon(Icons.auto_awesome),
        label: '跑图',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.photo_library_outlined),
        selectedIcon: CourtyardIcon(Icons.photo_library),
        label: '记录',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.tune_outlined),
        selectedIcon: CourtyardIcon(Icons.tune),
        label: '预设',
      ),
      if (localMode)
        const NavigationDestination(
          icon: CourtyardIcon(Icons.extension_outlined),
          label: 'LoRA',
        ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.library_books_outlined),
        selectedIcon: CourtyardIcon(Icons.library_books),
        label: '提示词',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.translate_outlined),
        selectedIcon: CourtyardIcon(Icons.translate),
        label: '角色词典',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 820;
        final content = IndexedStack(index: _index, children: pages);
        return Scaffold(
          drawer: SettingsDrawer(
              onDisconnect: widget.onDisconnect,
              onSwitch: widget.onSwitch,
              onConnections: widget.onActivateProfile == null
                  ? null
                  : () {
                      Navigator.pop(context);
                      Navigator.push(
                          context,
                          MaterialPageRoute<void>(
                              builder: (_) => InstanceConnectionsPage(
                                  store: widget.store,
                                  current: widget.session,
                                  onActivate: widget.onActivateProfile!)));
                    },
              localMode: localMode,
              onGallery: () {
                Navigator.pop(context);
                Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                        builder: (_) => GalleryPage(api: _api)));
              }),
          appBar: AppBar(
            title: Text(localMode ? '本机工作站' : 'AstrAutoAnima Lite'),
            actions: [
              if (widget.onSwitch != null)
                IconButton(
                  tooltip: '切换工作站',
                  onPressed: widget.onSwitch,
                  icon: const Icon(Icons.swap_horiz),
                ),
              if (wide)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Center(
                    child: Text(
                      widget.session.baseUrl,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ),
              IconButton(
                tooltip: '断开工作站',
                onPressed: widget.onDisconnect,
                icon: const CourtyardIcon(Icons.logout),
              ),
              const SizedBox(width: 8),
            ],
          ),
          body: wide
              ? Row(
                  children: [
                    NavigationRail(
                      selectedIndex: _index,
                      onDestinationSelected: (value) =>
                          setState(() => _index = value),
                      labelType: NavigationRailLabelType.all,
                      destinations: destinations
                          .map(
                            (item) => NavigationRailDestination(
                              icon: item.icon,
                              selectedIcon: item.selectedIcon,
                              label: Text(item.label),
                            ),
                          )
                          .toList(),
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(child: content),
                  ],
                )
              : content,
          bottomNavigationBar: wide
              ? null
              : NavigationBar(
                  labelBehavior:
                      NavigationDestinationLabelBehavior.onlyShowSelected,
                  selectedIndex: _index,
                  onDestinationSelected: (value) =>
                      setState(() => _index = value),
                  destinations: destinations,
                ),
        );
      },
    );
  }
}

class HubShell extends StatefulWidget {
  const HubShell({
    required this.session,
    required this.store,
    required this.notificationService,
    required this.onDisconnect,
    this.onSwitch,
    this.onActivateProfile,
    this.apiFactory,
    super.key,
  });

  final HubSession session;
  final SessionStore store;
  final NotificationService notificationService;
  final Future<void> Function() onDisconnect;
  final VoidCallback? onSwitch;
  final Future<void> Function(HubSession)? onActivateProfile;
  final HubApi Function(HubSession)? apiFactory;

  @override
  State<HubShell> createState() => _HubShellState();
}

class _HubShellState extends State<HubShell> {
  bool _chatGroupsAvailable = false;
  Future<void> _loadCapabilities() async {
    try {
      final caps = await _api.capabilities();
      if (mounted) {
        setState(() {
          _chatGroupsAvailable = caps['execution_mode'] == 'remote' &&
              (caps['features'] as Map?)?['chat_groups'] == true;
          _navigation.includeChatGroups = _chatGroupsAvailable;
        });
      }
    } catch (_) {/* Older servers retain all existing basic navigation. */}
  }

  List<Map<String, dynamic>> _extensions = [];
  bool _loadingExtensions = false;

  Future<void> _refreshExtensions({bool notify = false}) async {
    if (_loadingExtensions) return;
    _loadingExtensions = true;
    try {
      final response = await _api.extensions();
      final rows = (response['extensions'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .where((e) =>
              e['enabled'] == true &&
              e['state'] != 'broken_package' &&
              RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$').hasMatch('${e['id']}'))
          .toList();
      rows.sort((a, b) => '${a['id']}'.compareTo('${b['id']}'));
      if (mounted) setState(() => _extensions = rows);
    } catch (_) {
      if (mounted) {
        setState(() => _extensions = []);
        if (notify) {
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('扩展列表暂不可用；基础页面仍可使用。')));
        }
      }
    } finally {
      _loadingExtensions = false;
    }
  }

  List<Widget> _extensionEntries() => [
        if (widget.onActivateProfile != null)
          ListTile(
              key: const ValueKey('instances.connections'),
              leading: const Icon(Icons.dns_outlined),
              title: const Text('设备与实例连接'),
              subtitle: const Text('切换当前 Hub · 不关闭远端任务'),
              onTap: _openConnections),
        ListTile(
          key: const ValueKey('platform.switchboard'),
          leading: const Icon(Icons.hub_outlined),
          title: const Text('Bot 平台切换板'),
          subtitle: const Text('QQ / Telegram / Discord'),
          onTap: () {
            _scaffoldKey.currentState?.closeDrawer();
            Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => PlatformSwitchboardPage(api: _api)));
          },
        ),
        for (final extension in _extensions)
          ListTile(
            key: ValueKey('extension.${extension['id']}'),
            leading: const Icon(Icons.science_outlined),
            title: Text('${extension['name']}'),
            subtitle: const Text('独立扩展'),
            onTap: () {
              _scaffoldKey.currentState?.closeDrawer();
              Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => ExtensionManagementPage(
                      api: _api,
                      id: '${extension['id']}',
                      name: '${extension['name']}')));
            },
          ),
      ];
  final _navigation = AdminNavigation(includeStoragePreview: true);
  int get _index => _navigation.page;
  final _scaffoldKey = GlobalKey<ScaffoldState>();

  void _openSettings() {
    _scaffoldKey.currentState?.closeDrawer();
    _scaffoldKey.currentState?.openEndDrawer();
  }

  void _openConnections() {
    _scaffoldKey.currentState?.closeDrawer();
    _scaffoldKey.currentState?.closeEndDrawer();
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => InstanceConnectionsPage(
            store: widget.store,
            current: widget.session,
            allowService: widget.onSwitch != null,
            onActivate: widget.onActivateProfile!)));
  }

  final ServerOnlineTracker _serverTracker = ServerOnlineTracker();
  Timer? _serverMonitorTimer;
  bool _serverOnlineReminderEnabled = false;
  bool? _serverReachable;
  bool _checkingServer = false;

  late final HubApi _api;

  @override
  void initState() {
    super.initState();
    _api = widget.apiFactory?.call(widget.session) ??
        HubApi(
          baseUrl: widget.session.baseUrl,
          token: widget.session.token,
        );
    unawaited(_loadServerOnlineReminder());
    unawaited(_refreshExtensions());
    unawaited(_loadCapabilities());
  }

  @override
  void dispose() {
    _serverMonitorTimer?.cancel();
    _api.dispose();
    super.dispose();
  }

  Future<void> _loadServerOnlineReminder() async {
    final enabled = await widget.store.loadServerOnlineReminderEnabled();
    if (!mounted) return;
    setState(() => _serverOnlineReminderEnabled = enabled);
    if (enabled) _startServerMonitor();
  }

  Future<void> _setServerOnlineReminder(bool enabled) async {
    if (enabled) {
      var permitted = false;
      try {
        permitted = await widget.notificationService.requestPermission();
      } on Exception {
        permitted = false;
      }
      if (!permitted) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('未获得系统通知权限，无法开启提醒。')),
          );
        }
        return;
      }
    }

    await widget.store.saveServerOnlineReminderEnabled(enabled);
    if (!mounted) return;
    setState(() {
      _serverOnlineReminderEnabled = enabled;
      if (!enabled) _serverReachable = null;
    });
    if (enabled) {
      _startServerMonitor();
    } else {
      _stopServerMonitor();
    }
  }

  void _startServerMonitor() {
    _serverMonitorTimer?.cancel();
    _serverTracker.reset();
    unawaited(_checkServer());
    _serverMonitorTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => unawaited(_checkServer()),
    );
  }

  void _stopServerMonitor() {
    _serverMonitorTimer?.cancel();
    _serverMonitorTimer = null;
    _serverTracker.reset();
  }

  Future<void> _checkServer() async {
    if (!_serverOnlineReminderEnabled || _checkingServer) return;
    _checkingServer = true;
    var online = false;
    try {
      await _api.checkHealth();
      online = true;
    } on HubApiException {
      online = false;
    } finally {
      _checkingServer = false;
    }

    final shouldNotify = _serverTracker.update(online);
    if (!mounted) return;
    if (mounted && _serverReachable != online) {
      setState(() => _serverReachable = online);
    }
    if (shouldNotify) {
      try {
        await widget.notificationService.showServerOnline(
          baseUrl: widget.session.baseUrl,
        );
      } on Exception {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('服务器已上线，但系统通知发送失败。')),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      CompShareInstancePage(api: _api),
      DashboardPage(
        api: _api,
        serverOnlineReminderEnabled: _serverOnlineReminderEnabled,
        serverReachable: _serverReachable,
        onServerOnlineReminderChanged: _setServerOnlineReminder,
      ),
      PromptLibraryPage(api: _api),
      PresetSections(api: _api, admin: true, presets: PresetsPage(api: _api)),
      LoraLibraryPage(api: _api),
      LiteUsersPage(api: _api),
      LiteJobHistoryPage(api: _api),
      CharacterDictionaryPage(api: _api, adminMode: true),
      PromptReportsPage(api: _api),
      StorageManagementPage(api: _api),
      if (_chatGroupsAvailable) ChatGroupsPage(api: _api),
    ];
    final baseDestinations = const [
      // Keep destination order aligned with pages below.
      NavigationDestination(
        icon: CourtyardIcon(Icons.cloud_outlined),
        selectedIcon: CourtyardIcon(Icons.cloud),
        label: '实例',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.monitor_heart_outlined),
        selectedIcon: CourtyardIcon(Icons.monitor_heart),
        label: '概览',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.library_books_outlined),
        selectedIcon: CourtyardIcon(Icons.library_books),
        label: '提示词',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.auto_awesome_outlined),
        selectedIcon: CourtyardIcon(Icons.auto_awesome),
        label: '预设',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.extension_outlined),
        selectedIcon: CourtyardIcon(Icons.extension),
        label: 'LoRA',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.manage_accounts_outlined),
        selectedIcon: CourtyardIcon(Icons.manage_accounts),
        label: '用户',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.photo_library_outlined),
        selectedIcon: CourtyardIcon(Icons.photo_library),
        label: '记录',
      ),
      NavigationDestination(
        icon: CourtyardIcon(Icons.translate_outlined),
        selectedIcon: CourtyardIcon(Icons.translate),
        label: '角色词典',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 820;
        final destinations = [
          ...baseDestinations,
          const NavigationDestination(
              icon: CourtyardIcon(Icons.warning_amber_rounded), label: '举报'),
          const NavigationDestination(
              icon: CourtyardIcon(Icons.storage_outlined), label: '储存管理'),
          if (_chatGroupsAvailable)
            const NavigationDestination(
                icon: Icon(Icons.groups_outlined), label: '群聊'),
        ];
        final content = IndexedStack(index: _index, children: pages);
        return Scaffold(
          key: _scaffoldKey,
          drawer: wide
              ? null
              : Drawer(
                  child: SafeArea(
                      child: HubNavigation(
                  destinations: destinations,
                  extensionEntries: _extensionEntries(),
                  onRefreshExtensions: () => _refreshExtensions(notify: true),
                  selectedIndex: _index,
                  onSettings: _openSettings,
                  onSelected: (value) {
                    setState(() => _navigation.selectPage(value));
                    Navigator.of(context).pop();
                  },
                ))),
          endDrawer: SettingsDrawer(
              onDisconnect: widget.onDisconnect,
              onSwitch: widget.onSwitch,
              onConnections:
                  widget.onActivateProfile == null ? null : _openConnections,
              onGallery: () {
                Navigator.pop(context);
                Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                        builder: (_) => GalleryPage(api: _api, admin: true)));
              }),
          appBar: AppBar(
            title: Text('Hub · ${destinations[_index].label}'),
            actions: [
              if (widget.onSwitch != null)
                IconButton(
                  tooltip: '切换工作站',
                  onPressed: widget.onSwitch,
                  icon: const Icon(Icons.swap_horiz),
                ),
              Builder(
                  builder: (context) => IconButton(
                      tooltip: '设置',
                      onPressed: () => Scaffold.of(context).openEndDrawer(),
                      icon: const CourtyardIcon(Icons.settings))),
              if (wide)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Center(
                    child: Text(
                      widget.session.baseUrl,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ),
              IconButton(
                tooltip: '断开工作站',
                onPressed: widget.onDisconnect,
                icon: const CourtyardIcon(Icons.logout),
              ),
              const SizedBox(width: 8),
            ],
          ),
          body: wide
              ? Row(
                  children: [
                    SizedBox(
                        width: 220,
                        child: HubNavigation(
                            destinations: destinations,
                            extensionEntries: _extensionEntries(),
                            onRefreshExtensions: () =>
                                _refreshExtensions(notify: true),
                            selectedIndex: _index,
                            onSettings: _openSettings,
                            onSelected: (value) =>
                                setState(() => _navigation.selectPage(value)))),
                    const VerticalDivider(width: 1),
                    Expanded(child: content),
                  ],
                )
              : content,
          bottomNavigationBar: NavigationBar(
            selectedIndex: _navigation.selectedIndex,
            onDestinationSelected: (value) =>
                setState(() => _navigation.selectDestination(value)),
            destinations: [
              for (final index in _navigation.entries)
                if (index >= 0)
                  destinations[index]
                else
                  NavigationDestination(
                    icon: CourtyardIcon(index == -1
                        ? Icons.arrow_back
                        : index == -2
                            ? Icons.folder_outlined
                            : Icons.admin_panel_settings_outlined),
                    label: index == -1
                        ? '返回'
                        : index == -2
                            ? '资源'
                            : '管理',
                  ),
            ],
          ),
        );
      },
    );
  }
}
