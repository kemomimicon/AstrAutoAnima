import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/features/presets/preset_editor_dialog.dart';

void main() {
  testWidgets('failed server save keeps editor and entered character', (tester) async {
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: Builder(builder: (context) => TextButton(
      onPressed: () => showPresetEditor(context, kind: 'character', onSave: (_) async { throw Exception('server rejected'); }),
      child: const Text('open'))))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).at(0), '测试角色');
    await tester.enterText(find.byType(TextFormField).at(1), 'test_character');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.textContaining('保存未确认'), findsOneWidget);
    expect(find.text('测试角色'), findsOneWidget);
    expect(find.text('test_character'), findsOneWidget);
    expect(find.byType(AlertDialog), findsOneWidget);
  });
}
