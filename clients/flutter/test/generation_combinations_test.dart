import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_generate_page.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_prompt_library_page.dart';
import 'package:astr_auto_anima_hub_client/features/prompts/prompt_group_selector.dart';

class CombinationApi extends HubApi {
  CombinationApi() : super(baseUrl: 'http://test.invalid', token: 'test');
  final submissions = <Map<String, dynamic>>[];
  final queriedGroups = <List<String>>[];
  int groupReads = 0;
  @override
  Future<PresetListResult> getLitePresets() async =>
      const PresetListResult(styles: [], characters: [], revision: 'r');
  @override
  Future<DeliveryTargetListResult> getDeliveryTargets() async =>
      const DeliveryTargetListResult(
          targets: [DeliveryTarget(id: 'group', label: '测试群', kind: 'group')]);
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
  Future<Map<String, dynamic>> getLitePromptGroups() async {
    groupReads++;
    return {
      'groups': [
        {'id': 'night_scene', 'name': '夜景', 'allow_private': true}
      ],
      'revision': 'r'
    };
  }

  @override
  Future<Map<String, dynamic>> getTaskSuites() async => {
        'revision': 'r',
        'items': [
          {
            'id': 'a' * 32,
            'name': '测试套组',
            'rows': [{}, {}],
            'scope': 'personal',
            'editable': true
          }
        ]
      };
  RemoteJobResult finished() =>
      RemoteJobResult.fromJson({'id': 'done', 'status': 'succeeded'});
  @override
  Future<RemoteJobResult> createRemoteJob(Map<String, dynamic> value) async {
    submissions.add(Map<String, dynamic>.from(value));
    return finished();
  }

  @override
  Future<RemoteJobResult> getRemoteJob(String id) async => finished();
  @override
  Future<PromptPageResult> getLitePrompts(
      {String source = '',
      String safety = '',
      String query = '',
      List<String> customGroups = const [],
      int page = 1,
      int pageSize = 30}) async {
    queriedGroups.add(List<String>.from(customGroups));
    return PromptPageResult.fromJson({
      'items': [],
      'total': 0,
      'page': page,
      'pages': 1,
      'page_size': pageSize,
      'revision': 'r'
    });
  }
}

Finder labeled(String label) => find.byWidgetPredicate(
    (widget) => widget is TextField && widget.decoration?.labelText == label);
Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> choose(WidgetTester tester, String label, String option) async {
  final field = find
      .ancestor(
          of: find.text(label),
          matching: find
              .byWidgetPredicate((widget) => widget is DropdownButtonFormField))
      .first;
  await tap(tester, field);
  await tap(tester, find.text(option).last);
}

Future<void> submit(WidgetTester tester) async {
  await tap(tester, find.text('发送并生成'));
  await tap(tester, find.text('确认提交'));
}

void main() {
  Future<void> open(WidgetTester tester, CombinationApi api,
      {bool advanced = false}) async {
    tester.view.physicalSize = const Size(1400, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final key =
        'aaa_advanced_${sha256.convert(utf8.encode('${api.baseUrl}|${api.token}'))}';
    SharedPreferences.setMockInitialValues({
      if (advanced)
        key: jsonEncode({
          'visual': {
            'lighting_key': 'lighting_soft_diffuse',
            'camera_pitch': 'high',
            'camera_extreme_lora': 'true'
          },
          'sampler': 'euler',
          'scheduler': 'normal',
          'custom': true,
          'steps': 27,
          'cfg': 5.0,
          'detail_hands': true,
          'detail_upscale': true,
        })
    });
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: LiteGeneratePage(
                api: api,
                serverOnlineReminderEnabled: false,
                onServerOnlineReminderChanged: (_) {}))));
    await tester.pumpAndSettle();
    await choose(tester, '返图目标', '测试群 · 群聊');
  }

  testWidgets(
      'saved advanced settings are filtered for native/multi and restored for HQ',
      (tester) async {
    final api = CombinationApi();
    await open(tester, api, advanced: true);
    await choose(tester, '跑图方式', '放大精修 /arefine');
    await tester.enterText(labeled('历史任务 ID（可选）'), 'saved-job');
    await submit(tester);
    var payload = api.submissions.last;
    expect(payload['profile'], 'seedvr2');
    expect(payload['lighting_key'], '');
    expect(payload['camera_extreme_lora'], false);
    expect(payload.containsKey('sampler'), false);
    expect(payload.containsKey('steps'), false);
    expect(payload.containsKey('detail_upscale'), false);
    await choose(tester, '跑图方式', '裸模多人图 /amulti');
    await submit(tester);
    payload = api.submissions.last;
    expect(payload['lighting_key'], '');
    expect(payload['sampler'], 'euler');
    await choose(tester, '跑图方式', 'HQ 高清生图 /ahq');
    await submit(tester);
    payload = api.submissions.last;
    expect(payload['lighting_key'], 'lighting_soft_diffuse');
    expect(payload['camera_extreme_lora'], true);
    expect(payload['steps'], 27);
    expect(payload['detail_upscale'], true);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'switching unsupported task modes suspends suite without deleting choice',
      (tester) async {
    final api = CombinationApi();
    await open(tester, api);
    await tester.enterText(labeled('提示词'), 'rainy park');
    await tap(tester, find.text('启用任务套组'));
    await choose(tester, '请选择（在预设页新增）', '测试套组 · 2 项');
    await choose(tester, '跑图方式', 'HQ 高清生图 /ahq');
    expect(find.text('预设角色'), findsOneWidget);
    await submit(tester);
    expect(api.submissions.last.containsKey('task_suite_id'), false);
    await choose(tester, '跑图方式', '来张好图');
    expect(find.text('预设角色'), findsOneWidget);
    await submit(tester);
    expect(api.submissions.last.containsKey('task_suite_id'), false);
    await choose(tester, '跑图方式', '直接生图 /aimg');
    expect(find.text('预设角色'), findsNothing);
    await submit(tester);
    expect(api.submissions.last['task_suite_id'], 'a' * 32);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'custom group uses explicit payload and library filter without polling',
      (tester) async {
    final api = CombinationApi();
    await open(tester, api);
    await choose(tester, '跑图方式', '来张好图');
    await choose(tester, '自定义提示词分组', '夜景 · @night_scene');
    await submit(tester);
    expect(api.submissions.single['custom_groups'], ['night_scene']);
    expect(api.submissions.single['pool_filter'], '');
    expect(api.submissions.single['prompt'], '');
    await tester.pump(const Duration(minutes: 3));
    expect(api.groupReads, 1);
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: LitePromptLibraryPage(api: api))));
    await tester.pumpAndSettle();
    await choose(tester, '自定义提示词分组', '夜景 · @night_scene');
    expect(api.queriedGroups.last, ['night_scene']);
    final reads = api.groupReads;
    await tester.pump(const Duration(minutes: 3));
    expect(api.groupReads, reads);
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing group keeps explicit selection and allows clearing',
      (tester) async {
    final api = CombinationApi();
    String selected = 'removed_group';
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: StatefulBuilder(
                builder: (_, update) => PromptGroupSelector(
                    api: api,
                    value: selected,
                    onChanged: (value) => update(() => selected = value))))));
    await tester.pumpAndSettle();
    expect(find.textContaining('已选组暂不可用'), findsOneWidget);
    await choose(tester, '自定义提示词分组', '不限定自定义分组');
    expect(selected, '');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'private target disables group-only entries without erasing existing selection',
      (tester) async {
    final api = GroupOnlyApi();
    var selected = 'night_scene';
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: StatefulBuilder(
                builder: (_, update) => PromptGroupSelector(
                    api: api,
                    value: selected,
                    forGeneration: true,
                    privateTarget: true,
                    onChanged: (value) => update(() => selected = value))))));
    await tester.pumpAndSettle();
    expect(find.textContaining('已停用或不允许此目标'), findsOneWidget);
    final field = tester.widget<DropdownButtonFormField<String>>(
        find.byType(DropdownButtonFormField<String>));
    expect(field.initialValue, 'night_scene');
    await choose(tester, '自定义提示词分组', '不限定自定义分组');
    expect(selected, '');
    expect(tester.takeException(), isNull);
  });
}

class GroupOnlyApi extends CombinationApi {
  @override
  Future<Map<String, dynamic>> getLitePromptGroups() async => {
        'groups': [
          {'id': 'night_scene', 'name': '夜景', 'allow_private': false}
        ]
      };
}
