import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/loras/lora_library_page.dart';

class LoraEditApi extends HubApi {
  LoraEditApi() : super(baseUrl: 'http://test.invalid', token: 'test-token');
  final Map<String, dynamic> data = {
    'path': 'style.safetensors',
    'display_name': 'Initial LoRA',
    'category': 'unclassified',
    'recommended_prompt': '',
    'source_url': '',
    'enabled': true,
    'present': true
  };
  String revision = 'r1';
  int writes = 0;
  bool race = false;
  @override
  Future<LoraCatalogResult> getLoraCatalog() async =>
      LoraCatalogResult.fromJson({
        'items': [data],
        'revision': revision
      });
  @override
  Future<MutationResult> updateLora(
      {required String path,
      required String revision,
      required Map<String, dynamic> value}) async {
    writes++;
    if (race || revision != this.revision) {
      throw const HubApiException('resource changed since it was loaded',
          statusCode: 409);
    }
    data.addAll(value);
    this.revision = 'r${writes + 1}';
    return MutationResult.fromJson(
        {'resource': path, 'action': 'updated', 'revision': this.revision});
  }
}

Future<void> open(WidgetTester tester, LoraEditApi api) async {
  await tester.binding.setSurfaceSize(const Size(1200, 1100));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester
      .pumpWidget(MaterialApp(home: Scaffold(body: LoraLibraryPage(api: api))));
  await tester.pumpAndSettle();
  await tester.tap(find.byTooltip('编辑 LoRA'));
  await tester.pumpAndSettle();
}

Finder editorName() => find
    .descendant(of: find.byType(AlertDialog), matching: find.byType(TextField))
    .first;

void main() {
  testWidgets(
      'save metadata then reopen and save category without manual refresh',
      (tester) async {
    final api = LoraEditApi();
    await open(tester, api);
    await tester.enterText(editorName(), 'Edited LoRA');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing,
        reason: find
            .descendant(
                of: find.byType(AlertDialog), matching: find.byType(Text))
            .evaluate()
            .map((e) => (e.widget as Text).data)
            .join(' | '));
    expect(api.data['display_name'], 'Edited LoRA');
    await tester.tap(find.byTooltip('编辑 LoRA'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('画风').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 2);
    expect(api.data['category'], 'style');
    expect(find.byType(AlertDialog), findsNothing);
    api.dispose();
  });

  testWidgets(
      'unrelated revision change uses fresh version without overwriting target changes',
      (tester) async {
    final api = LoraEditApi();
    await open(tester, api);
    api.revision = 'unrelated-resource-change';
    await tester.enterText(editorName(), 'Saved draft');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 1);
    expect(api.data['display_name'], 'Saved draft');
    expect(find.byType(AlertDialog), findsNothing);
    api.dispose();
  });

  testWidgets(
      'same LoRA changed elsewhere preserves draft and refuses overwrite',
      (tester) async {
    final api = LoraEditApi();
    await open(tester, api);
    await tester.enterText(editorName(), 'My unsaved draft');
    api.data['display_name'] = 'Other editor';
    api.revision = 'external';
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 0);
    expect(api.data['display_name'], 'Other editor');
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.textContaining('未强行覆盖'), findsOneWidget);
    expect(tester.widget<TextField>(editorName()).controller!.text,
        'My unsaved draft');
    api.dispose();
  });

  testWidgets('racing 409 keeps dialog and draft; never auto-retries mutation',
      (tester) async {
    final api = LoraEditApi()..race = true;
    await open(tester, api);
    await tester.enterText(editorName(), 'Retained draft');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, 1);
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(tester.widget<TextField>(editorName()).controller!.text,
        'Retained draft');
    expect(find.textContaining('未强行覆盖'), findsOneWidget);
    api.dispose();
  });
}
