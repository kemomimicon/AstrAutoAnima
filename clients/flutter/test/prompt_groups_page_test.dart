import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_groups_page.dart';

class GroupsApi extends HubApi {
  GroupsApi() : super(baseUrl: 'http://unused.invalid', token: 'test');
  final groups = <Map<String, dynamic>>[];
  var revision = 'missing';

  @override
  Future<Map<String, dynamic>> getPromptGroups() async =>
      {'groups': List<Map<String, dynamic>>.from(groups), 'revision': revision};

  @override
  Future<Map<String, dynamic>> savePromptGroups({
    required String revision,
    required List<Map<String, dynamic>> groups,
  }) async {
    if (revision != this.revision) {
      throw const HubApiException('changed', statusCode: 409);
    }
    this.groups
      ..clear()
      ..addAll(groups);
    this.revision = 'saved';
    return {'groups': groups, 'revision': this.revision};
  }
}

void main() {
  testWidgets('admin can save group name and private permission manually',
      (tester) async {
    final api = GroupsApi();
    await tester.pumpWidget(MaterialApp(home: PromptGroupsPage(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新增分组'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(0), 'night_scene');
    await tester.enterText(find.byType(TextField).at(1), '夜景');
    await tester.tap(find.text('允许 QQ 私聊抽取'));
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.groups.single['id'], 'night_scene');
    expect(api.groups.single['name'], '夜景');
    expect(api.groups.single['allow_private'], true);
    expect(find.text('夜景 · @night_scene'), findsOneWidget);
  });
}
