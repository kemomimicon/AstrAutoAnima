import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/users/chat_groups_page.dart';

class GroupsApi extends HubApi {
  GroupsApi() : super(baseUrl: 'http://unused.invalid', token: 'test');
  bool available = true, denied = false;
  int reads = 0;
  final writes = <Map<String, dynamic>>[];
  @override
  Future<Map<String, dynamic>> chatGroups() async {
    reads++;
    if (denied) throw const HubApiException('forbidden', statusCode: 403);
    return {
      'available': available,
      'enabled': false,
      'groups': [
        {
          'key': 'qq:bot:123',
          'name': '测试群',
          'platform': 'qq',
          'bot_id': 'bot',
          'group_id': '123',
          'enabled': true,
          'level_system_enabled': false,
          'safety_mode': null,
          'daily_limit': 20,
          'cooldown_seconds': 60
        }
      ],
      'users': []
    };
  }

  @override
  Future<Map<String, dynamic>> saveChatGroup(Map<String, dynamic> value) async {
    if (denied) {
      throw const HubApiException('permission denied', statusCode: 403);
    }
    writes.add(value);
    return {};
  }
}

void main() {
  testWidgets('local capability hides writes and does not continuously poll',
      (tester) async {
    final api = GroupsApi()..available = false;
    await tester.pumpWidget(MaterialApp(home: ChatGroupsPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('新增群聊'), findsNothing);
    expect(find.textContaining('本机模式不经过 Bot'), findsOneWidget);
    await tester.pump(const Duration(minutes: 5));
    expect(api.reads, 1);
  });
  testWidgets('403 exposes no editing controls', (tester) async {
    final api = GroupsApi()..denied = true;
    await tester.pumpWidget(MaterialApp(home: ChatGroupsPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('forbidden'), findsOneWidget);
    expect(find.text('新增群聊'), findsNothing);
  });
  testWidgets(
      'group failed save keeps draft; retry writes selected entity only',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1000, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = GroupsApi();
    await tester.pumpWidget(MaterialApp(home: ChatGroupsPage(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('测试群'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑群设置'));
    await tester.pumpAndSettle();
    final name = find.byWidgetPredicate(
        (w) => w is TextField && w.decoration?.labelText == '群名称');
    await tester.enterText(name, '新群名称');
    api.denied = true;
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.textContaining('填写内容保留'), findsOneWidget);
    expect(find.text('新群名称'), findsOneWidget);
    api.denied = false;
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes.single['key'], 'qq:bot:123');
    expect(api.writes.single['name'], '新群名称');
    expect(api.writes.single['platform'], 'qq');
    expect(api.writes.single['safety_mode'], null);
    expect(api.writes.single.containsKey('users'), false);
    expect(find.textContaining('填写内容保留'), findsNothing);
  });
}
