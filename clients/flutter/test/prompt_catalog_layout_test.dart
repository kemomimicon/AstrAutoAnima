import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_editor_dialog.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_library_page.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_catalog_page.dart';

Map<String, dynamic> fixtureCatalog(String name) => {
      'schema_version': 1,
      'revision': name,
      'sources': [
        {
          'id': 'G',
          'name': name,
          'safety_codes': ['N'],
          'default_safety': 'N',
          'modes': ['random', 'chaos'],
          'allow_group': true,
          'allow_private': true,
          'enabled': true,
          'browseable': true
        }
      ],
      'editable_sources': [
        {
          'id': 'G',
          'name': name,
          'safety_codes': ['N', 'H', 'S']
        }
      ],
      'configuration': {'revision': 'missing', 'sources': []},
    };

class CatalogUiApi extends HubApi {
  CatalogUiApi(this.name)
      : super(baseUrl: 'http://test.invalid/$name', token: name);
  final String name;
  bool saveFails = true;
  int writes = 0;
  @override
  Future<Map<String, dynamic>> getPromptCatalog() async => fixtureCatalog(name);
  @override
  Future<Map<String, dynamic>> getPromptGroups() async =>
      {'groups': [], 'revision': 'missing'};
  @override
  Future<PromptPageResult> getPrompts(
          {String source = '',
          String safety = '',
          String query = '',
          List<String> customGroups = const [],
          bool? enabled,
          int page = 1,
          int pageSize = 30}) async =>
      PromptPageResult.fromJson({
        'items': [
          {
            'id': 'garden-001',
            'name': '初夏庭院',
            'prompt': 'garden, soft daylight, flowers',
            'source_code': 'G',
            'safety_code': 'N',
            'weight': 1,
            'enabled': true
          }
        ],
        'page': page,
        'pages': 4,
        'total': 120,
        'revision': 'r1'
      });
}

void main() {
  const capture = bool.fromEnvironment('AAA_CAPTURE_UI');
  setUpAll(() async {
    if (capture) {
      final font = FontLoader('UiCjk');
      font.addFont(File('C:/Windows/Fonts/msyh.ttc')
          .readAsBytes()
          .then(ByteData.sublistView));
      await font.load();
      final icons = FontLoader('MaterialIcons');
      icons.addFont(File(
              'D:/dev/flutter/bin/cache/artifacts/material_fonts/materialicons-regular.otf')
          .readAsBytes()
          .then(ByteData.sublistView));
      await icons.load();
    }
  });

  test('catalog uses conditional reads and caches only per connection/token',
      () async {
    var calls = 0;
    final api = HubApi(
        baseUrl: 'http://one.invalid',
        token: 'one',
        client: MockClient((req) async {
          expect(req.headers['authorization'], 'Bearer one');
          calls++;
          if (calls == 1) {
            return http.Response(jsonEncode(fixtureCatalog('Garden')), 200,
                headers: {'etag': '"r1"'});
          }
          expect(req.headers['if-none-match'], '"r1"');
          return http.Response('', 304);
        }));
    expect((await api.getPromptCatalog())['revision'], 'Garden');
    expect((await api.getPromptCatalog())['revision'], 'Garden');
    expect(calls, 2);
    final other = HubApi(
        baseUrl: 'http://two.invalid',
        token: 'two',
        client: MockClient((req) async {
          expect(req.headers.containsKey('if-none-match'), false);
          return http.Response(jsonEncode(fixtureCatalog('City')), 200);
        }));
    expect((await other.getPromptCatalog())['revision'], 'City');
    api.dispose();
    other.dispose();
  });

  test(
      'old server has no invented private libraries; errors do not become an empty success',
      () async {
    final old = HubApi(
        baseUrl: 'http://old.invalid',
        token: 'x',
        client: MockClient((_) async => http.Response('', 404)));
    expect((await old.getPromptCatalog())['sources'], isEmpty);
    final bad = HubApi(
        baseUrl: 'http://bad.invalid',
        token: 'x',
        client: MockClient((_) async => http.Response('', 403)));
    await expectLater(bad.getPromptCatalog(), throwsA(isA<HubApiException>()));
    old.dispose();
    bad.dispose();
  });

  Future<void> page(WidgetTester tester, CatalogUiApi api, Size size) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = size;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
            useMaterial3: true,
            fontFamily: capture ? 'UiCjk' : null,
            scaffoldBackgroundColor: const Color(0xFFF6F7FB),
            cardTheme: const CardThemeData(
                elevation: 0,
                margin: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.all(Radius.circular(18)))),
            inputDecorationTheme: const InputDecorationTheme(
                filled: true,
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.all(Radius.circular(14)),
                    borderSide: BorderSide.none)),
            colorScheme:
                ColorScheme.fromSeed(seedColor: const Color(0xff42648a))),
        home: Scaffold(
            appBar: AppBar(title: const Text('管理工作站')),
            body: PromptLibraryPage(api: api))));
    await tester.pumpAndSettle();
  }

  testWidgets(
      'phone shows records above fold, collapsed filters, preserves typed search',
      (tester) async {
    final api = CatalogUiApi('我的风景词库');
    await page(tester, api, const Size(390, 844));
    expect(tester.getTopLeft(find.text('garden-001')).dy, lessThan(400));
    expect(find.text('来源组'), findsNothing);
    expect(find.text('导出并复制'), findsNothing);
    await tester.enterText(find.byType(TextField).first, 'garden');
    await tester.pumpAndSettle();
    if (capture) {
      await expectLater(find.byType(MaterialApp),
          matchesGoldenFile('goldens/prompt-library-phone.png'));
    }
    await tester.tap(find.text('筛选'));
    await tester.pumpAndSettle();
    expect(find.text('来源组'), findsOneWidget);
    expect(find.text('我的风景词库'), findsNothing); // dropdown default is "all"
    await tester.tap(find.text('查询'));
    await tester.pumpAndSettle();
    expect(find.text('garden'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'desktop expands filters and instance switch drops previous names',
      (tester) async {
    final first = CatalogUiApi('朋友的图库');
    await page(tester, first, const Size(1280, 900));
    expect(find.text('来源组'), findsOneWidget);
    if (capture) {
      await expectLater(find.byType(MaterialApp),
          matchesGoldenFile('goldens/prompt-library-desktop.png'));
    }
    final second = CatalogUiApi('另一台服务器');
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: PromptLibraryPage(api: second))));
    await tester.pumpAndSettle();
    expect(find.text('朋友的图库'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'editor compact title, scrolls with keyboard and retains failed draft',
      (tester) async {
    await page(tester, CatalogUiApi('我的风景词库'), const Size(390, 844));
    final context = tester.element(find.byType(PromptLibraryPage));
    var attempts = 0;
    showPromptEditor(context, catalog: fixtureCatalog('我的风景词库'),
        onSave: (value) async {
      attempts++;
      expect(value['prompt'], 'garden, edited');
      if (attempts == 1) throw const HubApiException('冲突', statusCode: 409);
    });
    await tester.pumpAndSettle();
    expect(find.text('权重'), findsNothing);
    final prompt = find.byWidgetPredicate(
        (w) => w is TextFormField && w.controller?.text == '');
    await tester.enterText(prompt.at(1), 'garden, edited');
    await tester.pumpAndSettle();
    if (capture) {
      await expectLater(find.byType(MaterialApp),
          matchesGoldenFile('goldens/prompt-editor-phone.png'));
    }
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.text('garden, edited'), findsOneWidget);
    expect(find.textContaining('填写内容已保留'), findsOneWidget);
    tester.view.viewInsets = const FakeViewPadding(bottom: 290);
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpAndSettle();
    expect(tester.getBottomRight(find.text('保存')).dy, lessThan(554));
    expect(tester.takeException(), isNull);
    tester.view.resetViewInsets();
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('新增提示词'), findsNothing);
  });

  testWidgets('source manager shows current server only', (tester) async {
    await tester.pumpWidget(
        MaterialApp(home: PromptCatalogPage(api: CatalogUiApi('自建健康库'))));
    await tester.pumpAndSettle();
    expect(find.text('自建健康库 · G'), findsOneWidget);
    expect(find.textContaining('国风古韵'), findsNothing);
    await tester.tap(find.text('自建健康库 · G'));
    await tester.pumpAndSettle();
    expect(find.text('显示名称'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
