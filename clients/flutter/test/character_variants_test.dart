import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/presets/character_variants_editor.dart';
import 'package:astr_auto_anima_hub_client/features/presets/preset_editor_dialog.dart';

void main() {
  test('old preset defaults to no variants', () {
    expect(PresetSummary.fromJson({'name': 'A'}).variants, isEmpty);
  });
  testWidgets(
      'base model character creates outfit without LoRA and keeps identity',
      (tester) async {
    tester.view.physicalSize = const Size(1000, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Map<String, dynamic>? saved;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
      builder: (context) => TextButton(
        onPressed: () =>
            showPresetEditor(context, kind: 'character', onSave: (value) async {
          saved = value;
        }),
        child: const Text('open'),
      ),
    ))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).at(0), '底模角色');
    await tester.enterText(
        find.byType(TextFormField).at(1), 'base_character, uniform');
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('新增服装 / 造型 / 其他'));
    await tester.tap(find.text('新增服装 / 造型 / 其他'));
    await tester.pumpAndSettle();
    final variantFields = find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.byType(TextFormField));
    expect(tester.widget<TextFormField>(variantFields.at(2)).controller!.text,
        'base_character, uniform');
    await tester.enterText(variantFields.at(0), '裙装');
    await tester.enterText(variantFields.at(2), 'base_character, dress');
    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(saved, isNotNull);
    expect(saved!['loras'], isEmpty);
    expect(saved!['prompt'], 'base_character, uniform');
    expect(
        (saved!['variants'] as List).single['prompt'], 'base_character, dress');
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('existing text-only outfits can be saved without adding LoRA',
      (tester) async {
    Map<String, dynamic>? saved;
    final initial = PresetSummary.fromJson({
      'name': 'Base',
      'prompt': 'identity',
      'text_only': true,
      'variants': [
        {
          'id': 'hanfu',
          'name': '汉服',
          'category': 'clothing',
          'prompt': 'identity, hanfu'
        }
      ],
    });
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
      builder: (context) => TextButton(
        onPressed: () => showPresetEditor(context,
            kind: 'character', initial: initial, onSave: (value) async {
          saved = value;
        }),
        child: const Text('open'),
      ),
    ))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(saved!['loras'], isEmpty);
    expect((saved!['variants'] as List).single['id'], 'hanfu');
    expect(find.byType(AlertDialog), findsNothing);
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
