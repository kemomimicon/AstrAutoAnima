import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:astr_auto_anima_hub_client/features/settings/settings_drawer.dart';

void main() {
  testWidgets(
      'settings drawer fits phone and persists theme without exposing token',
      (tester) async {
    SharedPreferences.setMockInitialValues({'aaa_theme_mode': 'dark'});
    await loadAppTheme();
    expect(appThemeMode.value, ThemeMode.dark);
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var disconnected = false;
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: SettingsDrawer(onDisconnect: () async {
      disconnected = true;
    }))));
    await tester.pumpAndSettle();
    expect(find.text('设置'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byType(DropdownButton<ThemeMode>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('浅色').last);
    await tester.pumpAndSettle();
    expect((await SharedPreferences.getInstance()).getString('aaa_theme_mode'),
        'light');
    await tester.tap(find.text('切换服务器 / 令牌'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(disconnected, false);
    expect(tester.takeException(), isNull);
  });
}
