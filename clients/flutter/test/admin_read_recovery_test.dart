import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/core/read_recovery.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_library_page.dart';
import 'package:astr_auto_anima_hub_client/features/characters/character_dictionary_page.dart';

class RecoveringApi extends HubApi {
  RecoveringApi() : super(baseUrl: 'http://test.invalid', token: 'test-token');
  bool online = false;
  int? failureStatus;
  int promptReads = 0, characterReads = 0;
  String lastQuery = '';
  void check() {
    if (!online) throw HubApiException('服务未启动', statusCode: failureStatus);
  }

  @override
  Future<Map<String, dynamic>> getPromptCatalog() async {
    check();
    return {'revision': 'r', 'sources': [], 'editable_sources': []};
  }

  @override
  Future<Map<String, dynamic>> getPromptGroups() async =>
      {'groups': [], 'revision': 'r'};
  @override
  Future<PromptPageResult> getPrompts(
      {String source = '',
      String safety = '',
      String query = '',
      List<String> customGroups = const [],
      bool? enabled,
      int page = 1,
      int pageSize = 30}) async {
    promptReads++;
    lastQuery = query;
    check();
    return PromptPageResult.fromJson({
      'revision': 'r',
      'page': page,
      'pages': 1,
      'total': 1,
      'items': [
        {
          'id': 'test-1',
          'name': '恢复后的提示词',
          'prompt': 'garden',
          'source_code': 'G',
          'safety_code': 'N'
        }
      ]
    });
  }

  @override
  Future<CharacterDictionaryResult> getAdminCharacters(
      {String query = '',
      int page = 1,
      int pageSize = 50,
      bool includeDisabled = true}) async {
    characterReads++;
    lastQuery = query;
    check();
    return CharacterDictionaryResult.fromJson({
      'available': true,
      'revision': 'r',
      'items': [
        {
          'tag': 'recovered_character',
          'chinese_names': ['恢复角色']
        }
      ],
      'total': 1
    });
  }
}

Future<void> mount(WidgetTester tester, Widget page) async {
  await tester.binding.setSurfaceSize(const Size(1200, 1200));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: page)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('prompt page recovers when service starts later without remount',
      (tester) async {
    final api = RecoveringApi();
    await mount(tester, PromptLibraryPage(api: api));
    expect(find.textContaining('服务未启动'), findsWidgets);
    await tester.enterText(find.byType(TextField).first, 'garden search');
    api.online = true;
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(api.promptReads, greaterThanOrEqualTo(2));
    expect(api.lastQuery, 'garden search');
    expect(find.text('test-1'), findsOneWidget);
    expect(find.textContaining('服务未启动'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    api.dispose();
  });

  testWidgets('character dictionary retries transient failure and keeps search',
      (tester) async {
    final api = RecoveringApi()..failureStatus = 503;
    await mount(tester, CharacterDictionaryPage(api: api, adminMode: true));
    await tester.enterText(find.byType(TextField).first, '角色检索');
    await tester.pump(const Duration(milliseconds: 400));
    api.online = true;
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(api.characterReads, greaterThanOrEqualTo(2));
    expect(api.lastQuery, '角色检索');
    expect(find.textContaining('服务未启动'), findsNothing);
    expect(find.textContaining('恢复角色'), findsWidgets);
    await tester.pumpWidget(const SizedBox());
    api.dispose();
  });

  testWidgets('invalid credentials do not produce an automatic retry loop',
      (tester) async {
    final api = RecoveringApi()..failureStatus = 401;
    await mount(tester, CharacterDictionaryPage(api: api, adminMode: true));
    final before = api.characterReads;
    await tester.pump(const Duration(minutes: 2));
    expect(api.characterReads, before);
    expect(find.text('重试连接'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    api.dispose();
  });

  testWidgets('disposing an offline page cancels pending recovery reads',
      (tester) async {
    final api = RecoveringApi();
    await mount(tester, CharacterDictionaryPage(api: api, adminMode: true));
    final before = api.characterReads;
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(minutes: 1));
    expect(api.characterReads, before);
    expect(tester.takeException(), isNull);
    api.dispose();
  });

  testWidgets(
      'read recovery backs off, resets on success and cancels on dispose',
      (tester) async {
    var calls = 0;
    final recovery = ReadRecovery(() => calls++);
    recovery.failed(const HubApiException('offline'));
    await tester.pump(const Duration(seconds: 2));
    expect(calls, 1);
    recovery.failed(const HubApiException('offline'));
    await tester.pump(const Duration(seconds: 2));
    expect(calls, 1);
    await tester.pump(const Duration(seconds: 2));
    expect(calls, 2);
    recovery.succeeded();
    recovery.failed(const HubApiException('offline'));
    await tester.pump(const Duration(seconds: 2));
    expect(calls, 3);
    recovery.failed(const HubApiException('offline'));
    recovery.dispose();
    await tester.pump(const Duration(minutes: 1));
    expect(calls, 3);
  });
}
