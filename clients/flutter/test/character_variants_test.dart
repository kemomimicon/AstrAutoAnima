import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/presets/character_variants_editor.dart';

void main() {
  test('old preset defaults to no variants', () {
    expect(PresetSummary.fromJson({'name': 'A'}).variants, isEmpty);
  });
  testWidgets('variant edits retain ID and cancel leaves parent untouched',
      (tester) async {
    List<Map<String, dynamic>>? saved;
    final items = <Map<String, dynamic>>[
      {
        'id': 'hanfu',
        'name': '汉服',
        'category': 'clothing',
        'description': '测试说明',
        'prompt': 'identity, hanfu'
      }
    ];
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: CharacterVariantsEditor(
      items: items,
      defaultPrompt: 'identity',
      onChanged: (value) => saved = value,
    ))));
    await tester.tap(find.text('服装 · 汉服'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(saved, isNull);
    await tester.tap(find.text('服装 · 汉服'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).first, '汉服新版');
    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    expect(saved!.single['id'], 'hanfu');
    expect(saved!.single['name'], '汉服新版');
    expect(items.single['name'], '汉服');
  });
}
