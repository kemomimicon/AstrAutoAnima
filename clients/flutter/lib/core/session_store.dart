import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum HubAccessMode { admin, lite }

class HubSession {
  const HubSession({
    required this.baseUrl,
    required this.token,
    this.mode = HubAccessMode.admin,
  });

  final String baseUrl;
  final String token;
  final HubAccessMode mode;

  bool get isConfigured => baseUrl.isNotEmpty && token.isNotEmpty;
  bool get isAdmin => mode == HubAccessMode.admin;
}

class SessionStore {
  static const _urlKey = 'hub_base_url';
  static const _tokenKey = 'hub_admin_token';
  static const _modeKey = 'hub_access_mode';
  static const _serverOnlineReminderKey = 'server_online_reminder_enabled';
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();

  Future<HubSession> load() async {
    final preferences = await SharedPreferences.getInstance();
    final token = await _secureStorage.read(key: _tokenKey) ?? '';
    return HubSession(
      baseUrl: preferences.getString(_urlKey) ?? '',
      token: token,
      mode: preferences.getString(_modeKey) == HubAccessMode.lite.name
          ? HubAccessMode.lite
          : HubAccessMode.admin,
    );
  }

  Future<void> save(HubSession session) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_urlKey, session.baseUrl);
    await preferences.setString(_modeKey, session.mode.name);
    await _secureStorage.write(key: _tokenKey, value: session.token);
  }

  Future<void> clear() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_urlKey);
    await preferences.remove(_modeKey);
    await _secureStorage.delete(key: _tokenKey);
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
