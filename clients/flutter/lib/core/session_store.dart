import 'dart:convert';
import 'dart:math';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'connection_profile.dart';

enum HubAccessMode { admin, lite }

enum HubDeploymentMode { remote, local }

enum WindowsWorkspaceMode { local, onlineAdmin, onlineService }

extension WindowsWorkspaceDetails on WindowsWorkspaceMode {
  HubDeploymentMode get deployment => this == WindowsWorkspaceMode.local
      ? HubDeploymentMode.local
      : HubDeploymentMode.remote;

  HubAccessMode get access => this == WindowsWorkspaceMode.onlineService
      ? HubAccessMode.lite
      : HubAccessMode.admin;
}

class HubSession {
  const HubSession({
    required this.baseUrl,
    required this.token,
    this.mode = HubAccessMode.admin,
    this.deployment = HubDeploymentMode.remote,
  });

  final String baseUrl;
  final String token;
  final HubAccessMode mode;
  final HubDeploymentMode deployment;

  bool get isConfigured => baseUrl.isNotEmpty && token.isNotEmpty;
  bool get isAdmin => mode == HubAccessMode.admin;
}

class SessionStore {
  SessionStore({this.persistConnectionMetadata});

  /// Persistence fault injection. Production commits endpoint + credential ID
  /// in a single JSON write, never independently overwriting a token slot.
  final Future<bool> Function(String key, String value)?
      persistConnectionMetadata;
  Future<bool> _persistMetadata(String key, String value) async =>
      persistConnectionMetadata?.call(key, value) ??
      (await SharedPreferences.getInstance()).setString(key, value);
  String _activeKey(String scope) => 'hub_active_v2_$scope';
  Future<HubSession?> _readActive(String scope) async {
    final raw =
        (await SharedPreferences.getInstance()).getString(_activeKey(scope));
    if (raw == null) return null;
    final profile = ConnectionProfile.fromJson(
        Map<String, dynamic>.from(jsonDecode(raw) as Map));
    return profileSession('active_$scope', profile);
  }

  Future<void> _saveActive(String scope, HubSession session) async {
    final prefs = await SharedPreferences.getInstance();
    final before = prefs.getString(_activeKey(scope));
    final profile = ConnectionProfile(
        id: _newProfileId(),
        label: 'active',
        baseUrl: session.baseUrl,
        mode: session.mode,
        deployment: session.deployment);
    await _secureStorage.write(
        key: _profileToken('active_$scope', profile.id), value: session.token);
    final committed =
        await _persistMetadata(_activeKey(scope), jsonEncode(profile.toJson()));
    if (!committed) throw StateError('当前连接写入失败，未切换');
    if (before != null) {
      try {
        final old = ConnectionProfile.fromJson(
            Map<String, dynamic>.from(jsonDecode(before) as Map));
        await _secureStorage.delete(
            key: _profileToken('active_$scope', old.id));
      } catch (_) {/* Old unreferenced secrets never route to a new URL. */}
    }
  }

  Future<void> _clearActive(String scope) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_activeKey(scope));
    if (!await prefs.remove(_activeKey(scope))) throw StateError('无法清除连接');
    if (raw != null) {
      final old = ConnectionProfile.fromJson(
          Map<String, dynamic>.from(jsonDecode(raw) as Map));
      await _secureStorage.delete(key: _profileToken('active_$scope', old.id));
    }
  }

  String _profilesKey(String scope) => 'hub_profiles_v1_$scope';
  String _profileToken(String scope, String id) =>
      'hub_profile_token_${scope}_$id';

  Future<List<ConnectionProfile>> profiles(String scope,
      {HubSession? migrate}) async {
    final prefs = await SharedPreferences.getInstance();
    final key = _profilesKey(scope);
    final raw = prefs.getString(key);
    if (raw != null) {
      final rows = jsonDecode(raw) as List;
      return rows
          .map((row) =>
              ConnectionProfile.fromJson(Map<String, dynamic>.from(row as Map)))
          .toList();
    }
    // Import only the currently selected, already isolated legacy slot.
    // An empty array is a migration tombstone: removed profiles never return.
    final result = <ConnectionProfile>[];
    if (migrate != null && migrate.isConfigured) {
      final id = _newProfileId();
      result.add(ConnectionProfile(
          id: id,
          label: '原有连接',
          baseUrl: migrate.baseUrl,
          mode: migrate.mode,
          deployment: migrate.deployment));
      await _secureStorage.write(
          key: _profileToken(scope, id), value: migrate.token);
    }
    await prefs.setString(
        key, jsonEncode(result.map((e) => e.toJson()).toList()));
    return result;
  }

  String _newProfileId() => List.generate(16,
          (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'))
      .join();

  Future<HubSession> profileSession(
          String scope, ConnectionProfile profile) async =>
      HubSession(
          baseUrl: profile.baseUrl,
          token: await _secureStorage.read(
                  key: _profileToken(scope, profile.id)) ??
              '',
          mode: profile.mode,
          deployment: profile.deployment);

  Future<ConnectionProfile> saveProfile(String scope,
      {String? id, required String label, required HubSession session}) async {
    final endpoint =
        validateProfileEndpoint(session.baseUrl, session.deployment);
    if (label.trim().isEmpty ||
        label.trim().length > 80 ||
        session.token.trim().isEmpty) {
      throw const FormatException('名称须为 1–80 字，且必须填写该实例自己的令牌。');
    }
    final rows = await profiles(scope);
    // Copy-on-write credential identity: if metadata persistence fails/crashes,
    // the old endpoint can NEVER pick up a token intended for the edited one.
    final profile = ConnectionProfile(
        id: _newProfileId(),
        label: label.trim(),
        baseUrl: endpoint,
        mode: session.mode,
        deployment: session.deployment);
    if (id != null && !rows.any((p) => p.id == id)) {
      throw StateError('连接已被移除，请重新添加');
    }
    await _secureStorage.write(
        key: _profileToken(scope, profile.id), value: session.token);
    final next = [...rows.where((p) => p.id != id), profile];
    final committed = await _persistMetadata(
        _profilesKey(scope), jsonEncode(next.map((p) => p.toJson()).toList()));
    if (!committed) throw StateError('连接信息写入失败，旧连接保持不变');
    if (id != null) {
      try {
        await _secureStorage.delete(key: _profileToken(scope, id));
      } catch (_) {/* Unreferenced old secret cannot be used by any profile. */}
    }
    return profile;
  }

  Future<void> removeProfile(String scope, String id) async {
    final rows = await profiles(scope);
    // Persist the deletion before erasing its credential; never restore legacy.
    final committed = await (await SharedPreferences.getInstance()).setString(
        _profilesKey(scope),
        jsonEncode(
            rows.where((p) => p.id != id).map((p) => p.toJson()).toList()));
    if (!committed) throw StateError('未能移除连接，令牌保持不变');
    await _secureStorage.delete(key: _profileToken(scope, id));
  }

  static const _urlKey = 'hub_base_url';
  static const _tokenKey = 'hub_admin_token';
  static const _modeKey = 'hub_access_mode';
  static const _deploymentKey = 'hub_deployment_mode';
  static const _serverOnlineReminderKey = 'server_online_reminder_enabled';
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();

  String _scoped(String key, HubDeploymentMode deployment) =>
      '${key}_${deployment.name}';

  String _workspaceScoped(String key, WindowsWorkspaceMode workspace) =>
      '${key}_win_${workspace.name}';

  String _workspaceMarker(WindowsWorkspaceMode workspace) =>
      'hub_win_workspace_initialized_${workspace.name}';

  Future<HubSession> load() async {
    return loadForDeployment(HubDeploymentMode.remote);
  }

  Future<HubSession> loadForDeployment(HubDeploymentMode deployment) async {
    final active = await _readActive('deployment_${deployment.name}');
    if (active != null) return active;
    final preferences = await SharedPreferences.getInstance();
    final scopedUrl = preferences.getString(_scoped(_urlKey, deployment));
    final scopedToken =
        await _secureStorage.read(key: _scoped(_tokenKey, deployment));
    // Existing installations used a single slot. Migrate it only to the
    // deployment it originally belonged to; never copy a remote token local.
    final legacyMode = preferences.getString(_deploymentKey) == 'local'
        ? HubDeploymentMode.local
        : HubDeploymentMode.remote;
    final useLegacy = legacyMode == deployment && scopedUrl == null;
    return HubSession(
      baseUrl:
          scopedUrl ?? (useLegacy ? preferences.getString(_urlKey) ?? '' : ''),
      token: scopedToken ??
          (useLegacy ? await _secureStorage.read(key: _tokenKey) ?? '' : ''),
      mode: (preferences.getString(_scoped(_modeKey, deployment)) ??
                  (useLegacy ? preferences.getString(_modeKey) : null)) ==
              HubAccessMode.lite.name
          ? HubAccessMode.lite
          : HubAccessMode.admin,
      deployment: deployment,
    );
  }

  Future<void> save(HubSession session) async {
    await _saveActive('deployment_${session.deployment.name}', session);
    final preferences = await SharedPreferences.getInstance();
    final legacyMode = preferences.getString(_deploymentKey) == 'local'
        ? HubDeploymentMode.local
        : HubDeploymentMode.remote;
    if (legacyMode == session.deployment) {
      await preferences.remove(_urlKey);
      await preferences.remove(_modeKey);
      await preferences.remove(_deploymentKey);
      await _secureStorage.delete(key: _tokenKey);
    }
  }

  // Windows admin profiles are separate from the standalone service app's
  // legacy remote slot. Never reuse its user token as an administrator token.
  Future<HubSession> loadForWorkspace(WindowsWorkspaceMode workspace) async {
    final active = await _readActive('workspace_${workspace.name}');
    if (active != null) return active;
    final preferences = await SharedPreferences.getInstance();
    final url = preferences.getString(_workspaceScoped(_urlKey, workspace));
    final token =
        await _secureStorage.read(key: _workspaceScoped(_tokenKey, workspace));
    if (preferences.getBool(_workspaceMarker(workspace)) == true ||
        url != null ||
        token != null) {
      return HubSession(
        baseUrl: url ?? '',
        token: token ?? '',
        mode: workspace.access,
        deployment: workspace.deployment,
      );
    }
    // Migrate only old admin profiles. The standalone service app continues
    // using its original remote keys without being modified by this migration.
    if (workspace != WindowsWorkspaceMode.onlineService) {
      final old = await loadForDeployment(workspace.deployment);
      if (old.mode == HubAccessMode.admin) {
        return HubSession(
          baseUrl: old.baseUrl,
          token: old.token,
          mode: workspace.access,
          deployment: workspace.deployment,
        );
      }
    }
    return HubSession(
        baseUrl: '',
        token: '',
        mode: workspace.access,
        deployment: workspace.deployment);
  }

  Future<void> saveForWorkspace(
      WindowsWorkspaceMode workspace, HubSession session) async {
    if (session.mode != workspace.access ||
        session.deployment != workspace.deployment) {
      throw ArgumentError('连接权限与选择的 Windows 工作模式不一致');
    }
    final preferences = await SharedPreferences.getInstance();
    await _saveActive('workspace_${workspace.name}', session);
    await preferences.setBool(_workspaceMarker(workspace), true);
  }

  Future<void> clearForWorkspace(WindowsWorkspaceMode workspace) async {
    await _clearActive('workspace_${workspace.name}');
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_workspaceScoped(_urlKey, workspace));
    await _secureStorage.delete(key: _workspaceScoped(_tokenKey, workspace));
    // Prevent a cleared profile from silently falling back to an old token.
    await preferences.setBool(_workspaceMarker(workspace), true);
  }

  Future<void> clear() async {
    await clearForDeployment(HubDeploymentMode.remote);
  }

  Future<void> clearForDeployment(HubDeploymentMode deployment) async {
    await _clearActive('deployment_${deployment.name}');
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_scoped(_urlKey, deployment));
    await preferences.remove(_scoped(_modeKey, deployment));
    await _secureStorage.delete(key: _scoped(_tokenKey, deployment));
    if (preferences.getString(_deploymentKey) == deployment.name ||
        (deployment == HubDeploymentMode.remote &&
            preferences.getString(_deploymentKey) == null)) {
      await preferences.remove(_urlKey);
      await preferences.remove(_modeKey);
      await preferences.remove(_deploymentKey);
      await _secureStorage.delete(key: _tokenKey);
    }
  }

  Future<bool> loadServerOnlineReminderEnabled() async {
    final preferences = await SharedPreferences.getInstance();
    return preferences.getBool(_serverOnlineReminderKey) ?? false;
  }

  Future<void> saveServerOnlineReminderEnabled(bool enabled) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_serverOnlineReminderKey, enabled);
  }
}
