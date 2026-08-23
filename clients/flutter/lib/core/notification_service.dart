import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  Future<void> initialize() async {
    if (_initialized) return;
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      windows: WindowsInitializationSettings(
        appName: 'AstrAutoAnima Hub',
        appUserModelId: 'RelN.AstrAutoAnima.Hub.Client',
        guid: 'DA788710-780E-4F0B-A7A4-A2D7CE2B8735',
      ),
    );
    await _plugin.initialize(settings: settings);
    _initialized = true;
  }

  Future<bool> requestPermission() async {
    await initialize();
    if (defaultTargetPlatform != TargetPlatform.android) return true;
    return await _plugin
            .resolvePlatformSpecificImplementation<
                AndroidFlutterLocalNotificationsPlugin>()
            ?.requestNotificationsPermission() ??
        false;
  }

  Future<void> showServerOnline({required String baseUrl}) async {
    await initialize();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'server_online',
        '服务器上线提醒',
        channelDescription: '工作站从离线恢复为在线时提醒',
        importance: Importance.high,
        priority: Priority.high,
      ),
      windows: WindowsNotificationDetails(),
    );
    await _plugin.show(
      id: 1001,
      title: '工作站已上线',
      body: '$baseUrl 已恢复连接，现在可以开始使用。',
      notificationDetails: details,
      payload: 'server-online',
    );
  }
}
