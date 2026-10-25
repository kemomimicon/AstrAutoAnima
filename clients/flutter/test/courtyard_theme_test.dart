import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:astr_auto_anima_hub_client/core/courtyard_theme.dart';
import 'package:astr_auto_anima_hub_client/features/settings/settings_drawer.dart';
import 'package:astr_auto_anima_hub_client/features/connection/connection_page.dart';

void main() {
  setUpAll(() async {
    final icons = FontLoader('MaterialIcons');
    icons.addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
    // Local QA font only; never packaged or redistributed with the client.
    final font = File('C:/Windows/Fonts/msyh.ttc');
    if (font.existsSync()) {
      final loader = FontLoader('CourtyardQA');
      loader
          .addFont(Future.value(ByteData.sublistView(font.readAsBytesSync())));
      await loader.load();
    }
  });
  test('mapped production assets exist in both themes', () {
    for (final theme in ['light', 'dark']) {
      for (final name in CourtyardIcon.names.values) {
        expect(File('assets/courtyard/$theme/$name.png').existsSync(), isTrue,
            reason: name);
      }
    }
  });
  test('skin and brightness restore independently', () async {
    SharedPreferences.setMockInitialValues(
        {'aaa_skin': 'classic', 'aaa_theme_mode': 'dark'});
    await loadAppTheme();
    expect(appSkin.value, 'classic');
    expect(appThemeMode.value, ThemeMode.dark);
  });
  for (final mode in Brightness.values) {
    testWidgets('connection ${mode.name} small-screen render', (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final theme = courtyardTheme(mode);
      await tester.pumpWidget(MaterialApp(
          theme: theme.copyWith(
              textTheme: theme.textTheme.apply(fontFamily: 'CourtyardQA')),
          home: RepaintBoundary(
              key: const Key('shot'),
              child: ConnectionPage(onConnected: (_) async {}))));
      await tester.pumpAndSettle();
      await tester.runAsync(() => precacheImage(
          const AssetImage('assets/courtyard/illustrations/welcome_480.webp'),
          tester.element(find.byType(ConnectionPage))));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(find.byKey(const Key('shot')),
          matchesGoldenFile('goldens/courtyard_connection_${mode.name}.png'));
    });
  }
  testWidgets('drawer at 200 percent is scrollable without overflow',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        theme: courtyardTheme(Brightness.dark),
        home: MediaQuery(
            data: const MediaQueryData(
                size: Size(360, 800), textScaler: TextScaler.linear(2)),
            child: Scaffold(body: SettingsDrawer(onDisconnect: () async {})))));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(find.text('版本信息'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(tester.takeException(), isNull);
  });
  testWidgets('administrator navigation retains all nine destinations',
      (tester) async {
    final destinations = List.generate(
        9,
        (i) => NavigationDestination(
            icon: const Icon(Icons.settings), label: 'Page $i'));
    int selected = -1;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SizedBox(
                width: 220,
                child: HubNavigation(
                    destinations: destinations,
                    selectedIndex: 0,
                    onSelected: (i) => selected = i)))));
    await tester.scrollUntilVisible(find.text('Page 8'), 150);
    await tester.tap(find.text('Page 8'));
    expect(selected, 8);
    expect(tester.takeException(), isNull);
  });
}
