import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:astr_auto_anima_hub_client/core/command_builder.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/core/random_subject_tag.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_generate_page.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_job_history_page.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_prompt_library_page.dart';

class LocalRandomApi extends HubApi {
  LocalRandomApi({this.installed = true, this.executionMode = 'local'})
      : super(baseUrl: 'http://test.invalid', token: 'test');

  final bool installed;
  final String executionMode;
  int capabilityReads = 0;
  int groupReads = 0;
  Completer<Map<String, dynamic>>? pendingCapabilities;
  final submissions = <Map<String, dynamic>>[];

  Map<String, dynamic> get capabilityData => {
        'execution_mode': executionMode,
        'random_groups': [
          if (installed) {'id': 'v', 'name': 'V · 国风古韵'},
        ],
      };

  @override
  Future<Map<String, dynamic>> getPromptCatalog() async => {
        'schema_version': 1,
        'revision': 'fixture',
        'sources': [
          {
            'id': 'P',
            'name': '个人收藏',
            'safety_codes': ['N', 'S'],
            'default_safety': 'N',
            'browseable': true,
            'modes': ['random', 'chaos']
          },
          if (installed && executionMode == 'remote')
            {
              'id': 'V',
              'name': '服务器的风景库',
              'safety_codes': ['N'],
              'default_safety': 'N',
              'modes': ['random'],
              'enabled': true,
              'allow_private': true,
              'allow_group': true,
              'supports_custom_groups': false
            },
        ]
      };

  @override
  Future<Map<String, dynamic>> getLocalCapabilities() async {
    capabilityReads++;
    if (pendingCapabilities != null) return pendingCapabilities!.future;
    return capabilityData;
  }

  @override
  Future<PresetListResult> getLitePresets() async => PresetListResult.fromJson({
        'styles': [
          {'name': '水墨'}
        ],
        'characters': [
          {'name': '角色甲'}
        ],
      });

  @override
  Future<DeliveryTargetListResult> getDeliveryTargets() async =>
      const DeliveryTargetListResult(targets: [
        DeliveryTarget(id: 'local', label: '本机', kind: 'local'),
        DeliveryTarget(id: 'group', label: '测试群', kind: 'group'),
        DeliveryTarget(id: 'private', label: '本人', kind: 'private'),
      ]);

  @override
  Future<PersonalStyleListResult> getPersonalStyles() async =>
      const PersonalStyleListResult(items: [], revision: 'r');

  @override
  Future<CharacterFavoriteListResult> getCharacterFavorites() async =>
      const CharacterFavoriteListResult(items: [], revision: 'r');

  @override
  Future<Map<String, dynamic>> getVisualPresets() async =>
      {'available': true, 'lighting': [], 'material': []};

  @override
  Future<Map<String, dynamic>> getTaskSuites() async => {'items': []};

  @override
  Future<Map<String, dynamic>> getLitePromptGroups() async {
    groupReads++;
    return {
      'groups': [
        {'id': 'night', 'name': '夜景', 'allow_private': true}
      ],
    };
  }

  RemoteJobResult finished() => RemoteJobResult.fromJson({
        'id': 'done',
        'status': 'succeeded',
        'kind': 'random',
        'target_id': 'local',
        'source_prompt': 'ancient garden',
        'final_prompt': 'ancient garden, warm light',
        'prompt_provenance': {'group_id': 'v', 'record_id': 'scene-17'},
      });

  @override
  Future<RemoteJobResult> createRemoteJob(Map<String, dynamic> value) async {
    submissions.add(Map<String, dynamic>.from(value));
    return finished();
  }

  @override
  Future<RemoteJobResult> getRemoteJob(String id) async => finished();

  @override
  Future<RemoteJobPageResult> getRemoteJobs(
          {String kind = '',
          String status = '',
          int page = 1,
          int pageSize = 30}) async =>
      RemoteJobPageResult(items: [finished()], total: 1, page: 1, pages: 1);
}

class LocalFavoriteApi extends LocalRandomApi {
  String? queriedSource;
  String? queriedSafety;

  @override
  Future<PromptPageResult> getLitePrompts(
      {String source = '',
      String safety = '',
      String query = '',
      List<String> customGroups = const [],
      int page = 1,
      int pageSize = 30}) async {
    queriedSource = source;
    queriedSafety = safety;
    return PromptPageResult.fromJson({
      'items': [
        {
          'id': 'favorite-17',
          'original_id': 'V:scene-17',
          'prompt': 'ancient garden, warm light',
          'user_addition': 'warm light',
          'source_code': 'P',
          'safety_code': 'S',
        }
      ],
      'page': 1,
      'pages': 1,
      'total': 1,
    });
  }
}

Finder field(String label) => find.byWidgetPredicate(
    (widget) => widget is TextField && widget.decoration?.labelText == label);

Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> choose(WidgetTester tester, String label, String option) async {
  final dropdown = find
      .ancestor(
          of: find.text(label),
          matching: find
              .byWidgetPredicate((widget) => widget is DropdownButtonFormField))
      .first;
  await tap(tester, dropdown);
  await tap(tester, find.text(option).last);
}

Future<void> render(WidgetTester tester, LocalRandomApi api,
    {bool local = true}) async {
  await tester.pumpWidget(MaterialApp(
      home: Scaffold(
          body: LiteGeneratePage(
    api: api,
    localMode: local,
    serverOnlineReminderEnabled: false,
    onServerOnlineReminderChanged: (_) {},
  ))));
  await tester.pumpAndSettle();
}

Future<void> submit(WidgetTester tester) async {
  await tap(tester, find.text('发送并生成'));
  await tap(tester, find.text('确认提交'));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    randomSubjectTag.value = '';
    randomSubjectTagLocked.value = false;
  });

  Future<void> open(WidgetTester tester, LocalRandomApi api,
      {bool local = true}) async {
    tester.view.physicalSize = const Size(1400, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await render(tester, api, local: local);
  }

  test('local capability request uses reader authorization', () async {
    final api = HubApi(
        baseUrl: 'http://test.invalid',
        token: 'reader-token',
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/lite/local-capabilities');
          expect(request.headers['authorization'], 'Bearer reader-token');
          return http.Response(
              jsonEncode({
                'execution_mode': 'local',
                'random_groups': [
                  {'id': 'v', 'name': 'V · 国风古韵'}
                ]
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }));
    final capabilities = await api.getLocalCapabilities();
    expect(capabilities['execution_mode'], 'local');
    api.dispose();
  });

  testWidgets(
      'installed local V sends one fixed offline scene and no remote options',
      (tester) async {
    final api = LocalRandomApi();
    await open(tester, api);
    await choose(tester, '跑图方式', '来张好图');
    expect(find.text('V · 国风古韵'), findsOneWidget);
    expect(find.textContaining('服务器分级：N'), findsOneWidget);
    expect(find.text('随机串开头人物 Tag'), findsOneWidget);
    expect(find.text('默认（1girl）'), findsOneWidget);
    expect(find.textContaining('默认补 1girl, solo'), findsWidgets);
    for (final label in [
      '五连抽',
      '启用任务套组',
      '随机画风预设',
      '提示词来源 / 显式分级',
      '本次内容级别',
      '自定义提示词分组',
      '仅复制指令（备用）'
    ]) {
      expect(find.text(label), findsNothing);
    }
    await choose(tester, '预设角色', '角色甲');
    await choose(tester, '画风', '水墨');
    await choose(tester, '画面比例', '16:9');
    await submit(tester);
    final payload = api.submissions.single;
    expect(payload['target_id'], 'local');
    expect(payload['deliver_to_im'], false);
    expect(payload['kind'], 'random');
    expect(payload['custom_groups'], ['v']);
    expect(payload['pool_filter'], '');
    expect(payload['random_subject_tag'], '');
    expect(payload['prompt'], '');
    expect(payload['character'], '角色甲');
    expect(payload['style'], '水墨');
    expect(payload['ratio'], '16:9');
    for (final key in ['five_draw', 'task_suite_id', 'personal_style_slot']) {
      expect(payload.containsKey(key), false);
    }
    expect(api.groupReads, 0);
    await tap(tester, find.byTooltip('更新在线配置'));
    await tester.pump(const Duration(minutes: 3));
    expect(api.capabilityReads, 2);
    expect(tester.takeException(), isNull);
  });

  for (final tag in ['1boy', '1woman', '1man', 'none']) {
    testWidgets(
        'local V submits selected subject $tag and preserves solo guidance',
        (tester) async {
      final api = LocalRandomApi();
      await open(tester, api);
      await choose(tester, '跑图方式', '来张好图');
      await choose(tester, '随机串开头人物 Tag', randomSubjectChoices[tag]!);
      expect(find.text('默认补 1girl, solo；不指定人物 Tag 时仍保留 solo'), findsOneWidget);
      await tap(tester, find.text('发送并生成'));
      expect(find.textContaining('起手=${tag == 'none' ? '无' : tag}'),
          findsOneWidget);
      await tap(tester, find.text('确认提交'));
      expect(api.submissions.single['random_subject_tag'], tag);
      expect(api.submissions.single['custom_groups'], ['v']);
      expect(api.submissions.single['prompt'], '');
      expect(
          (await SharedPreferences.getInstance())
              .getString('aaa_random_subject_tag'),
          tag);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'locked local V subject stays hidden and uses the saved selection',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'aaa_random_subject_tag': '1man',
      'aaa_random_subject_tag_locked': true,
    });
    await loadRandomSubjectTag();
    final api = LocalRandomApi();
    await open(tester, api);
    await choose(tester, '跑图方式', '来张好图');
    expect(find.text('随机串开头人物 Tag'), findsNothing);
    await saveRandomSubjectTag('1boy');
    await submit(tester);
    expect(api.submissions.single['random_subject_tag'], '1man');
    await saveRandomSubjectTagLocked(false);
    await tester.pumpAndSettle();
    expect(find.text('随机串开头人物 Tag'), findsOneWidget);
    expect(find.text('1man'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final mode in ['direct', 'hq']) {
    testWidgets('local $mode does not send the saved random subject',
        (tester) async {
      randomSubjectTag.value = '1boy';
      final api = LocalRandomApi();
      await open(tester, api);
      if (mode == 'hq') await choose(tester, '跑图方式', '本机 HQ · 二段采样');
      expect(find.text('随机串开头人物 Tag'), findsNothing);
      await tester.enterText(field('提示词'), 'ancient garden');
      await submit(tester);
      expect(api.submissions.single['kind'], mode);
      expect(api.submissions.single.containsKey('random_subject_tag'), false);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'local addition and saved sampling options are preserved without translation',
      (tester) async {
    final api = LocalRandomApi();
    final key =
        'aaa_advanced_${sha256.convert(utf8.encode('${api.baseUrl}|${api.token}'))}';
    SharedPreferences.setMockInitialValues({
      key: jsonEncode({
        'sampler': 'euler',
        'scheduler': 'karras',
        'custom': true,
        'steps': 27,
        'cfg': 5.5,
        'detail_upscale': true,
        'visual': {'lighting_key': 'light'},
      })
    });
    await open(tester, api);
    await choose(tester, '跑图方式', '来张好图');
    await tester.enterText(field('附加英文内容（可选）'), 'warm light');
    await submit(tester);
    final payload = api.submissions.single;
    expect(payload['prompt'], 'warm light');
    expect(payload['sampler'], 'euler');
    expect(payload['scheduler'], 'karras');
    expect(payload['steps'], 27);
    expect(payload['cfg'], 5.5);
    expect(payload.containsKey('lighting_key'), false);
    expect(payload.containsKey('detail_upscale'), false);
    await tap(tester, find.text('离线提示词出处'));
    expect(find.textContaining('scene-17'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing library retains direct Chinese and HQ modes',
      (tester) async {
    final api = LocalRandomApi(installed: false);
    await open(tester, api);
    final dropdown = tester.widget<DropdownButton<ImageCommandKind>>(
        find.byType(DropdownButton<ImageCommandKind>));
    expect(dropdown.items!.map((item) => item.value), [
      ImageCommandKind.direct,
      ImageCommandKind.chinese,
      ImageCommandKind.hq
    ]);
    await tester.enterText(field('提示词'), 'ancient garden');
    await submit(tester);
    expect(api.submissions.single['kind'], 'direct');
    expect(api.submissions.single.containsKey('custom_groups'), false);
    expect(api.capabilityReads, 1);
  });

  testWidgets(
      'local sampler choice preserves workflow defaults and hides remote advanced tools',
      (tester) async {
    final api = LocalRandomApi();
    await open(tester, api);
    await choose(tester, '跑图方式', '来张好图');
    await tap(tester, find.text('高级设置'));
    expect(find.text('光影与材质'), findsNothing);
    expect(find.text('构图与视角'), findsNothing);
    await tap(tester, find.text('调度器、采样器与自定义参数'));
    await choose(tester, '采样器预设', 'DPM++ 2M');
    await choose(tester, '调度器', 'karras');
    await tap(tester, find.byTooltip('关闭'));
    await submit(tester);
    expect(api.submissions.single['sampler'], '2m');
    expect(api.submissions.single['scheduler'], 'karras');
    expect(api.submissions.single.containsKey('steps'), false);
    expect(api.submissions.single.containsKey('cfg'), false);
    expect(tester.takeException(), isNull);
  });

  testWidgets('local UI ignores V capability reported by remote execution mode',
      (tester) async {
    final api = LocalRandomApi(executionMode: 'remote');
    await open(tester, api);
    final dropdown = tester.widget<DropdownButton<ImageCommandKind>>(
        find.byType(DropdownButton<ImageCommandKind>));
    expect(dropdown.items!.any((item) => item.value == ImageCommandKind.random),
        false);
  });

  testWidgets(
      'remote random still supports group filters five draw and subject tag',
      (tester) async {
    final api = LocalRandomApi();
    randomSubjectTag.value = '1boy';
    await open(tester, api, local: false);
    await choose(tester, '返图目标', '测试群 · 群聊');
    await choose(tester, '跑图方式', '来张好图');
    await choose(tester, '自定义提示词分组', '夜景 · @night');
    expect(find.text('仅替换词库串开头的 1girl；solo、K 组不变'), findsOneWidget);
    expect(find.textContaining('默认补 1girl, solo'), findsNothing);
    await tap(tester, find.text('五连抽'));
    await submit(tester);
    expect(api.submissions.single['custom_groups'], ['night']);
    expect(api.submissions.single['five_draw'], true);
    expect(api.submissions.single['random_subject_tag'], '1boy');
    expect(api.capabilityReads, 1);
    expect(find.text('V · 国风古韵'), findsNothing);
  });

  testWidgets(
      'switching local V to remote clears V and reloads connection data',
      (tester) async {
    final localApi = LocalRandomApi();
    final remoteApi = LocalRandomApi();
    await open(tester, localApi);
    await choose(tester, '跑图方式', '来张好图');
    await render(tester, remoteApi, local: false);
    await choose(tester, '返图目标', '测试群 · 群聊');
    await choose(tester, '跑图方式', '来张好图');
    await submit(tester);
    expect(remoteApi.submissions.single.containsKey('custom_groups'), false);
    expect(remoteApi.capabilityReads, 1);
    expect(localApi.submissions, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'installed remote V accepts group normal route and clears custom group',
      (tester) async {
    final api = LocalRandomApi(executionMode: 'remote');
    await open(tester, api, local: false);
    await choose(tester, '返图目标', '测试群 · 群聊');
    await choose(tester, '跑图方式', '来张好图');
    await choose(tester, '自定义提示词分组', '夜景 · @night');
    await choose(tester, '提示词来源 / 显式分级', '服务器的风景库');
    await submit(tester);
    expect(api.submissions.single['pool_filter'], 'V');
    expect(api.submissions.single['safety_code'], 'N');
    expect(api.submissions.single.containsKey('custom_groups'), false);
    expect(api.submissions.single['target_id'], 'group');
    expect(api.capabilityReads, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'switching local connections removes stale installed library selection',
      (tester) async {
    final first = LocalRandomApi();
    final next = LocalRandomApi(installed: false);
    await open(tester, first);
    await choose(tester, '跑图方式', '来张好图');
    await render(tester, next);
    expect(find.text('V · 国风古韵'), findsNothing);
    final dropdown = tester.widget<DropdownButton<ImageCommandKind>>(
        find.byType(DropdownButton<ImageCommandKind>));
    expect(dropdown.value, ImageCommandKind.direct);
    expect(dropdown.items!.any((item) => item.value == ImageCommandKind.random),
        false);
    expect(first.capabilityReads, 1);
    expect(next.capabilityReads, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('late capability response cannot enable V on another connection',
      (tester) async {
    final first = LocalRandomApi()..pendingCapabilities = Completer();
    final next = LocalRandomApi(installed: false);
    await open(tester, first);
    await render(tester, next);
    first.pendingCapabilities!.complete(first.capabilityData);
    await tester.pumpAndSettle();
    final dropdown = tester.widget<DropdownButton<ImageCommandKind>>(
        find.byType(DropdownButton<ImageCommandKind>));
    expect(dropdown.items!.any((item) => item.value == ImageCommandKind.random),
        false);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'history shows provenance and does not label offline V as rated N',
      (tester) async {
    final api = LocalRandomApi();
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: LiteJobHistoryPage(api: api, localMode: true))));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(Chip, 'N'), findsNothing);
    expect(find.widgetWithText(Chip, '未人工逐条审核'), findsOneWidget);
    await tap(tester, find.text('离线提示词出处'));
    expect(find.textContaining('scene-17'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'offline favorites remain visible with default filters and explain conservative safety marker',
      (tester) async {
    final api = LocalFavoriteApi();
    tester.view.physicalSize = const Size(1400, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: LitePromptLibraryPage(api: api))));
    await tester.pumpAndSettle();
    expect(api.queriedSource, '');
    expect(api.queriedSafety, '');
    expect(find.text('P · 未审核'), findsOneWidget);
    await choose(tester, '来源', '个人收藏');
    expect(api.queriedSource, 'P');
    expect(api.queriedSafety, '');
    await tap(tester, find.text('V:scene-17'));
    expect(find.textContaining('S 为保守存储标记'), findsOneWidget);
    expect(find.text('分级 S'), findsNothing);
    expect(find.text('附加内容：warm light'), findsOneWidget);
    expect(find.byKey(const Key('lite-prompt-full-text')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
