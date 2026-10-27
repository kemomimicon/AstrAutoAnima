import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_library_page.dart';

class SearchApi extends HubApi {
  SearchApi() : super(baseUrl: 'http://fixture.invalid', token: 'fixture');
  int reads = 0;
  @override
  Future<Map<String, dynamic>> getPromptCatalog() async =>
      {'editable_sources': [], 'revision': 'fixture'};
  @override
  Future<Map<String, dynamic>> getPromptGroups() async =>
      {'groups': [], 'revision': 'fixture'};
  @override
  Future<PromptPageResult> getPrompts(
      {String source = '',
      String safety = '',
      String query = '',
      List<String> customGroups = const [],
      bool? enabled,
      int page = 1,
      int pageSize = 30}) async {
    reads++;
    return PromptPageResult(
        items: List.generate(
            30,
            (i) => PromptRecord(
                id: 'record-$reads-$i',
                name: '旧库测试',
                prompt: 'garden, daylight',
                sourceCode: 'B',
                safetyCode: 'N',
                enabled: true,
                weight: 1,
                categories: const [])),
        page: 1,
        pages: 1,
        total: 30,
        revision: 'r$reads');
  }
}

void main() {
  testWidgets(
      'scrolling then querying does not mix tile bool with scroll double',
      (tester) async {
    final api = SearchApi();
    addTearDown(api.dispose);
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: PromptLibraryPage(api: api))));
    await tester.pumpAndSettle();
    final list = find.byType(ListView).first;
    await tester.drag(list, const Offset(0, -650));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.drag(list, const Offset(0, 1500));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.byTooltip('查询'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(api.reads, 2);
    expect(find.text('record-2-0'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
