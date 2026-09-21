import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/presets/presets_page.dart';

class PresetApi extends HubApi {
  PresetApi() : super(baseUrl: 'http://unused.invalid', token: 'test');
  String revision = 'old';
  bool race = false;
  int writes = 0;
  final rows = <PresetSummary>[];

  @override
  Future<PresetListResult> getPresets() async => PresetListResult(
      styles: const [], characters: List.of(rows), revision: revision);

  @override
  Future<MutationResult> createPreset({required String kind,
      required String revision, required Map<String, dynamic> value}) async {
    writes++;
    if (race) {
      race = false;
      this.revision = 'raced';
    }
    if (revision != this.revision) {
      throw const HubApiException('resource changed since it was loaded', statusCode: 409);
    }
    if (rows.any((r) => r.name == value['name'])) {
      throw const HubApiException('preset already exists', statusCode: 409);
    }
    rows.add(PresetSummary.fromJson({...value, 'kind': kind}));
    this.revision = 'saved';
    return const MutationResult(action: 'created', resource: 'character',
        revision: 'saved', count: 1);
  }
}

Future<void> openEditor(WidgetTester tester, PresetApi api) async {
  await tester.binding.setSurfaceSize(const Size(1000, 1600));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: PresetsPage(api: api))));
  await tester.pumpAndSettle();
  await tester.tap(find.text('角色'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('新增角色'));
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextFormField).at(0), '梅娅');
  await tester.enterText(find.byType(TextFormField).at(1), 'test_character');
}

void main() {
  testWidgets('create refreshes revision after dialog was opened', (tester) async {
    final api = PresetApi();
    await openEditor(tester, api);
    api.revision = 'external-change';
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 1);
    expect(api.rows.single.name, '梅娅');
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('梅娅'), findsOneWidget);
  });

  testWidgets('race retains input; explicit retry obtains new revision', (tester) async {
    final api = PresetApi();
    await openEditor(tester, api);
    api.race = true;
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.rows, isEmpty);
    expect(api.writes, 1); // Never silently retries a write.
    expect(find.textContaining('resource changed'), findsOneWidget);
    expect(find.text('梅娅'), findsOneWidget);
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 2);
    expect(api.rows.single.name, '梅娅');
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('duplicate created elsewhere is not overwritten', (tester) async {
    final api = PresetApi();
    await openEditor(tester, api);
    api.rows.add(PresetSummary.fromJson({
      'name': '梅娅', 'kind': 'character', 'prompt': 'original',
    }));
    api.revision = 'external-change';
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 0);
    expect(api.rows.single.prompt, 'original');
    expect(find.textContaining('同名预设已存在'), findsOneWidget);
    expect(find.byType(AlertDialog), findsOneWidget);
  });
}
