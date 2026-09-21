import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/lite/remake_options_dialog.dart';

class FakeApi extends HubApi {
  FakeApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<PresetListResult> getLitePresets() async =>
      const PresetListResult(styles: [], characters: [], revision: 'test');
}

void main() {
  testWidgets('seed between ratio and adjustment; reopening resets edits',
      (tester) async {
    tester.view.physicalSize = const Size(900, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Map<String, dynamic>? result;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
                builder: (context) => TextButton(
                    onPressed: () async {
                      result = await showDialog<Map<String, dynamic>>(
                          context: context,
                          builder: (_) => RemakeOptionsDialog(api: FakeApi()));
                    },
                    child: const Text('open'))))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.text('比例')).dy,
        lessThan(tester.getTopLeft(find.text('固定种子')).dy));
    expect(tester.getTopLeft(find.text('固定种子')).dy,
        lessThan(tester.getTopLeft(find.text('补充调整提示词')).dy));
    await tester.tap(find.byType(CheckboxListTile));
    await tester.enterText(find.byType(TextField), '改成雨夜');
    await tester.tap(find.text('提交重跑'));
    await tester.pumpAndSettle();
    expect(result?['fixed_seed'], true);
    expect(result?['adjustment'], '改成雨夜');
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(tester.widget<CheckboxListTile>(find.byType(CheckboxListTile)).value,
        false);
    expect(find.text('改成雨夜'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
