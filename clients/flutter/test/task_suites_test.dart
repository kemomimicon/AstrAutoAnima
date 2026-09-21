import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/presets/task_suites_page.dart';
import 'package:astr_auto_anima_hub_client/features/lite/remake_options_dialog.dart';

class SuiteApi extends HubApi {
  SuiteApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<PresetListResult> getLitePresets() async =>
      const PresetListResult(styles: [], characters: [], revision: 'r');
  @override
  Future<PersonalStyleListResult> getPersonalStyles() async =>
      const PersonalStyleListResult(items: [], revision: 'r');
  @override
  Future<CharacterFavoriteListResult> getCharacterFavorites() async =>
      const CharacterFavoriteListResult(items: [], revision: 'r');
  @override
  Future<Map<String, dynamic>> getTaskSuites() async => {
        'revision': 'r',
        'items': [
          {
            'id': 'a' * 32,
            'name': '测试套组',
            'rows': [{}, {}],
            'scope': 'personal',
            'editable': true
          }
        ]
      };
}

void main() {
  testWidgets('preset tabs exact labels and editor add cancel', (tester) async {
    tester.view.physicalSize = const Size(1000, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: PresetSections(
                api: SuiteApi(), presets: const Text('existing')))));
    expect(find.text('画风预设'), findsOneWidget);
    await tester.tap(find.text('任务套组'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新增套组预设'));
    await tester.pumpAndSettle();
    expect(find.text('第 1 项'), findsOneWidget);
    await tester.tap(find.text('新增一条（最多 20 项）'));
    await tester.pumpAndSettle();
    expect(find.text('第 2 项'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(find.text('第 1 项'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('remake suite hides selectors and requires selection',
      (tester) async {
    tester.view.physicalSize = const Size(1000, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: RemakeOptionsDialog(api: SuiteApi()))));
    await tester.pumpAndSettle();
    expect(find.text('角色'), findsOneWidget);
    await tester.tap(find.text('启用任务套组'));
    await tester.pumpAndSettle();
    expect(find.text('角色'), findsNothing);
    expect(find.text('画风'), findsNothing);
    final submit =
        tester.widget<FilledButton>(find.widgetWithText(FilledButton, '提交重跑'));
    expect(submit.onPressed, isNull);
    await tester.tap(find.text('请选择（在预设页新增）'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('测试套组 · 2 项').last);
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '提交重跑'))
            .onPressed,
        isNotNull);
    expect(tester.takeException(), isNull);
  });
}
