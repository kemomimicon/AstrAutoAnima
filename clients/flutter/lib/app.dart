import 'dart:async';

import 'package:flutter/material.dart';

import 'core/app_edition.dart';
import 'core/character_use_request.dart';
import 'core/hub_api.dart';
import 'core/notification_service.dart';
import 'core/server_online_tracker.dart';
import 'core/session_store.dart';
import 'features/connection/connection_page.dart';
import 'features/characters/character_dictionary_page.dart';
import 'features/cloud/compshare_instance_page.dart';
import 'features/dashboard/dashboard_page.dart';
import 'features/lite/lite_generate_page.dart';
import 'features/lite/lite_job_history_page.dart';
import 'features/lite/lite_prompt_library_page.dart';
import 'features/lite/personal_presets_page.dart';
import 'features/loras/lora_library_page.dart';
import 'features/presets/presets_page.dart';
import 'features/prompts/prompt_library_page.dart';
import 'features/splash/service_splash.dart';
import 'features/users/lite_users_page.dart';

class AstrAutoAnimaApp extends StatefulWidget {
  const AstrAutoAnimaApp({
    required this.store,
    required this.notificationService,
    required this.initialSession,
    this.edition = AppEdition.unified,
    super.key,
  });

  final SessionStore store;
  final NotificationService notificationService;
  final HubSession initialSession;
  final AppEdition edition;

  @override
  State<AstrAutoAnimaApp> createState() => _AstrAutoAnimaAppState();
}

class _AstrAutoAnimaAppState extends State<AstrAutoAnimaApp> {
  late HubSession _session = widget.initialSession;

  Future<void> _connected(HubSession session) async {
    await widget.store.save(session);
    if (mounted) setState(() => _session = session);
  }

  Future<void> _disconnect() async {
    await widget.store.clear();
    if (mounted) {
      setState(() => _session = const HubSession(baseUrl: '', token: ''));
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF5B6CFF),
      brightness: Brightness.light,
    );
    final requiredMode = switch (widget.edition) {
      AppEdition.admin => HubAccessMode.admin,
      AppEdition.service => HubAccessMode.lite,
      AppEdition.unified => null,
    };
    final sessionAllowed = _session.isConfigured &&
        (requiredMode == null || _session.mode == requiredMode);
    final home = sessionAllowed
        ? _session.isAdmin
            ? HubShell(
                session: _session,
                store: widget.store,
                notificationService: widget.notificationService,
                onDisconnect: _disconnect,
              )
            : LiteShell(
                session: _session,
                store: widget.store,
                notificationService: widget.notificationService,
                onDisconnect: _disconnect,
              )
        : ConnectionPage(
            onConnected: _connected,
            fixedMode: requiredMode,
            offlineTool:
                widget.edition.isAdmin ? const CompShareInstancePage() : null,
          );
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: widget.edition.title,
      theme: ThemeData(
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
      darkTheme: ThemeData(
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
    super.key,
  });

  final HubSession session;
  final SessionStore store;
  final NotificationService notificationService;
  final Future<void> Function() onDisconnect;

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
    _api = HubApi(baseUrl: widget.session.baseUrl, token: widget.session.token);
    unawaited(_loadServerOnlineReminder());
  }

  @override
  void dispose() {
    _serverMonitorTimer?.cancel();
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
      LiteGeneratePage(
        api: _api,
        characterRequest: _characterRequest,
        serverOnlineReminderEnabled: _serverOnlineReminderEnabled,
        serverReachable: _serverReachable,
        onServerOnlineReminderChanged: _setServerOnlineReminder,
      ),
      LiteJobHistoryPage(api: _api),
      PersonalPresetsPage(api: _api),
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
    const destinations = [
      NavigationDestination(
        icon: Icon(Icons.auto_awesome_outlined),
        selectedIcon: Icon(Icons.auto_awesome),
        label: '跑图',
      ),
      NavigationDestination(
        icon: Icon(Icons.photo_library_outlined),
        selectedIcon: Icon(Icons.photo_library),
        label: '记录',
      ),
      NavigationDestination(
        icon: Icon(Icons.tune_outlined),
        selectedIcon: Icon(Icons.tune),
        label: '预设',
      ),
      NavigationDestination(
        icon: Icon(Icons.library_books_outlined),
        selectedIcon: Icon(Icons.library_books),
        label: '提示词',
      ),
      NavigationDestination(
        icon: Icon(Icons.translate_outlined),
        selectedIcon: Icon(Icons.translate),
        label: '角色词典',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 820;
        final content = IndexedStack(index: _index, children: pages);
        return Scaffold(
          appBar: AppBar(
            title: const Text('AstrAutoAnima Lite'),
            actions: [
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
                icon: const Icon(Icons.logout),
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
    super.key,
  });

  final HubSession session;
  final SessionStore store;
  final NotificationService notificationService;
  final Future<void> Function() onDisconnect;

  @override
  State<HubShell> createState() => _HubShellState();
}

class _HubShellState extends State<HubShell> {
  int _index = 0;
  final ServerOnlineTracker _serverTracker = ServerOnlineTracker();
  Timer? _serverMonitorTimer;
  bool _serverOnlineReminderEnabled = false;
  bool? _serverReachable;
  bool _checkingServer = false;

  late final HubApi _api;

  @override
  void initState() {
    super.initState();
    _api = HubApi(
      baseUrl: widget.session.baseUrl,
      token: widget.session.token,
    );
    unawaited(_loadServerOnlineReminder());
  }

  @override
  void dispose() {
    _serverMonitorTimer?.cancel();
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
      const CompShareInstancePage(),
      DashboardPage(
        api: _api,
        serverOnlineReminderEnabled: _serverOnlineReminderEnabled,
        serverReachable: _serverReachable,
        onServerOnlineReminderChanged: _setServerOnlineReminder,
      ),
      PromptLibraryPage(api: _api),
      PresetsPage(api: _api),
      LoraLibraryPage(api: _api),
      LiteUsersPage(api: _api),
      LiteJobHistoryPage(api: _api),
      CharacterDictionaryPage(api: _api, adminMode: true),
    ];
    final destinations = const [
      NavigationDestination(
        icon: Icon(Icons.cloud_outlined),
        selectedIcon: Icon(Icons.cloud),
        label: '实例',
      ),
      NavigationDestination(
        icon: Icon(Icons.monitor_heart_outlined),
        selectedIcon: Icon(Icons.monitor_heart),
        label: '概览',
      ),
      NavigationDestination(
        icon: Icon(Icons.library_books_outlined),
        selectedIcon: Icon(Icons.library_books),
        label: '提示词',
      ),
      NavigationDestination(
        icon: Icon(Icons.auto_awesome_outlined),
        selectedIcon: Icon(Icons.auto_awesome),
        label: '预设',
      ),
      NavigationDestination(
        icon: Icon(Icons.extension_outlined),
        selectedIcon: Icon(Icons.extension),
        label: 'LoRA',
      ),
      NavigationDestination(
        icon: Icon(Icons.manage_accounts_outlined),
        selectedIcon: Icon(Icons.manage_accounts),
        label: '用户',
      ),
      NavigationDestination(
        icon: Icon(Icons.photo_library_outlined),
        selectedIcon: Icon(Icons.photo_library),
        label: '记录',
      ),
      NavigationDestination(
        icon: Icon(Icons.translate_outlined),
        selectedIcon: Icon(Icons.translate),
        label: '角色词典',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 820;
        final content = IndexedStack(index: _index, children: pages);
        return Scaffold(
          appBar: AppBar(
            title: const Text('AstrAutoAnima Hub'),
            actions: [
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
                icon: const Icon(Icons.logout),
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
