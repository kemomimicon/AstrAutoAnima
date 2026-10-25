import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:astr_auto_anima_hub_client/app.dart';
import 'package:astr_auto_anima_hub_client/core/app_edition.dart';
import 'package:astr_auto_anima_hub_client/core/notification_service.dart';
import 'package:astr_auto_anima_hub_client/core/session_store.dart';
import 'package:astr_auto_anima_hub_client/features/connection/connection_page.dart';
import 'package:astr_auto_anima_hub_client/features/connection/workstation_choice_page.dart';

void main() {
  testWidgets('local and remote retain isolated URLs and tokens',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final secrets = <String, String>{};
    const channel =
        MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel,
        (call) async {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      final key = args['key'] as String;
      switch (call.method) {
        case 'read':
          return secrets[key];
        case 'write':
          secrets[key] = args['value'] as String;
          return null;
        case 'delete':
          secrets.remove(key);
          return null;
      }
      throw MissingPluginException(call.method);
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null));
    final store = SessionStore();
    await store.save(const HubSession(
        baseUrl: 'https://remote.example', token: 'remote-token'));
    await store.save(const HubSession(
        baseUrl: 'http://127.0.0.1:6278',
        token: 'local-token',
        deployment: HubDeploymentMode.local));
    expect((await store.loadForDeployment(HubDeploymentMode.remote)).token,
        'remote-token');
    expect((await store.loadForDeployment(HubDeploymentMode.local)).token,
        'local-token');
    await store.clearForDeployment(HubDeploymentMode.local);
    expect(
        (await store.loadForDeployment(HubDeploymentMode.local)).isConfigured,
        false);
    expect((await store.loadForDeployment(HubDeploymentMode.remote)).baseUrl,
        'https://remote.example');
  });

  testWidgets('Windows admin keeps three profiles separate from service app',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final secrets = <String, String>{};
    const channel =
        MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel,
        (call) async {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      final key = args['key'] as String;
      switch (call.method) {
        case 'read':
          return secrets[key];
        case 'write':
          secrets[key] = args['value'] as String;
          return null;
        case 'delete':
          secrets.remove(key);
          return null;
      }
      throw MissingPluginException(call.method);
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null));
    final store = SessionStore();
    await store.save(const HubSession(
        baseUrl: 'https://service-app.example',
        token: 'standalone-service',
        mode: HubAccessMode.lite));
    await store.saveForWorkspace(
        WindowsWorkspaceMode.local,
        const HubSession(
            baseUrl: 'http://127.0.0.1:6278',
            token: 'local-admin',
            deployment: HubDeploymentMode.local));
    await store.saveForWorkspace(
        WindowsWorkspaceMode.onlineAdmin,
        const HubSession(
            baseUrl: 'https://admin.example', token: 'remote-admin'));
    await store.saveForWorkspace(
        WindowsWorkspaceMode.onlineService,
        const HubSession(
            baseUrl: 'https://user.example',
            token: 'remote-user',
            mode: HubAccessMode.lite));
    expect((await store.loadForWorkspace(WindowsWorkspaceMode.local)).token,
        'local-admin');
    expect(
        (await store.loadForWorkspace(WindowsWorkspaceMode.onlineAdmin)).token,
        'remote-admin');
    final lite =
        await store.loadForWorkspace(WindowsWorkspaceMode.onlineService);
    expect(lite.mode, HubAccessMode.lite);
    expect(lite.token, 'remote-user');
    expect((await store.loadForDeployment(HubDeploymentMode.remote)).token,
        'standalone-service');
    await store.clearForWorkspace(WindowsWorkspaceMode.onlineAdmin);
    expect(
        (await store.loadForWorkspace(WindowsWorkspaceMode.onlineAdmin))
            .isConfigured,
        false);
    expect(
        (await store.loadForWorkspace(WindowsWorkspaceMode.onlineService))
            .token,
        'remote-user');
    expect((await store.loadForDeployment(HubDeploymentMode.remote)).token,
        'standalone-service');
  });

  testWidgets('cleared Windows profile does not restore an old shared token',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final secrets = <String, String>{};
    const channel =
        MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel,
        (call) async {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      final key = args['key'] as String;
      switch (call.method) {
        case 'read':
          return secrets[key];
        case 'write':
          secrets[key] = args['value'] as String;
          return null;
        case 'delete':
          secrets.remove(key);
          return null;
      }
      throw MissingPluginException(call.method);
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null));
    final store = SessionStore();
    await store.save(const HubSession(
        baseUrl: 'https://old-admin.example', token: 'old-admin'));
    expect(
        (await store.loadForWorkspace(WindowsWorkspaceMode.onlineAdmin)).token,
        'old-admin');
    await store.clearForWorkspace(WindowsWorkspaceMode.onlineAdmin);
    expect(
        (await store.loadForWorkspace(WindowsWorkspaceMode.onlineAdmin))
            .isConfigured,
        false);
    expect((await store.loadForDeployment(HubDeploymentMode.remote)).token,
        'old-admin');
  });

  testWidgets('Windows app opens chooser before any saved connection',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    await tester.pumpWidget(AstrAutoAnimaApp(
      store: SessionStore(),
      notificationService: NotificationService(),
      initialSession: const HubSession(baseUrl: '', token: ''),
      edition: AppEdition.admin,
    ));
    expect(find.byType(WorkstationChoicePage), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('Windows admin online service asks for a user token',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    const channel =
        MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel,
        (call) async {
      if (call.method == 'read') return null;
      throw MissingPluginException(call.method);
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null));
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    await tester.pumpWidget(AstrAutoAnimaApp(
      store: SessionStore(),
      notificationService: NotificationService(),
      initialSession: const HubSession(baseUrl: '', token: ''),
      edition: AppEdition.admin,
    ));
    await tester.tap(find.byKey(const ValueKey('workstation.onlineService')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(ConnectionPage), findsOneWidget);
    expect(find.text('用户令牌'), findsOneWidget);
    expect(find.text('管理员令牌'), findsNothing);
    expect(find.text('Hub 离线？管理云实例'), findsNothing);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('standalone Windows service app keeps its original login',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    await tester.pumpWidget(AstrAutoAnimaApp(
      store: SessionStore(),
      notificationService: NotificationService(),
      initialSession: const HubSession(baseUrl: '', token: ''),
      edition: AppEdition.service,
    ));
    expect(find.byType(WorkstationChoicePage), findsNothing);
    expect(find.byType(ConnectionPage), findsOneWidget);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('Windows admin choice exposes three distinct modes',
      (tester) async {
    WindowsWorkspaceMode? selected;
    await tester.pumpWidget(MaterialApp(
        home: WorkstationChoicePage(
      onSelect: (mode) => selected = mode,
    )));
    expect(find.text('本机工作站'), findsOneWidget);
    expect(find.text('在线管理'), findsOneWidget);
    expect(find.text('在线服务'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('workstation.local')));
    expect(selected, WindowsWorkspaceMode.local);
    await tester.tap(find.byKey(const ValueKey('workstation.onlineAdmin')));
    expect(selected, WindowsWorkspaceMode.onlineAdmin);
    await tester.tap(find.byKey(const ValueKey('workstation.onlineService')));
    expect(selected, WindowsWorkspaceMode.onlineService);
  });

  testWidgets('local connection page cannot choose a remote route',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: ConnectionPage(
      fixedDeployment: HubDeploymentMode.local,
      onBack: () {},
      onConnected: (_) async {},
    )));
    expect(find.text('连接本机工作站'), findsOneWidget);
    expect(find.text('连接方式（互斥）'), findsNothing);
    expect(find.text('返回工作站选择'), findsOneWidget);
  });
}
