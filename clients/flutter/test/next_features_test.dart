import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:astr_auto_anima_hub_client/core/command_builder.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/gallery/character_gallery_page.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_generate_page.dart';
import 'generation_combinations_test.dart' show CombinationApi, choose;

class CardApi extends HubApi {
  CardApi() : super(baseUrl: 'http://test.invalid', token: 'test');
  Map<String, dynamic>? saved;
  bool fail = false;
  @override
  Future<Map<String, dynamic>> characterGallery() async => {'revision':'r1', 'items': [
    for (final name in ['Alice', 'Bob']) {
      'id': name, 'character': name, 'variant':'default', 'published':true,
      'features': {'hair':'long hair'}, 'source_state':'current', 'cover_url':'',
    },
  ]};
  @override
  Future<Map<String, dynamic>> saveCharacterCard(Map<String, dynamic> value) async {
    saved = value;
    if (fail) throw const HubApiException('画廊已更新，请刷新');
    return characterGallery();
  }
}

class ReferenceApi extends CombinationApi {
  @override
  Future<PresetListResult> getLitePresets() async => PresetListResult.fromJson({
    'styles':[{'name':'Ink style','prompt':'ink painting','loras':[]}],
    'characters':[], 'revision':'r1',
  });
}

void main() {
  test('new commands retain mode and exact multi lines', () {
    expect(buildImageCommand(kind: ImageCommandKind.turbo, prompt:'a garden'), '/aturbo a garden');
    expect(buildImageCommand(kind: ImageCommandKind.reference, prompt:'a garden'), '/aref cs a garden');
    expect(buildImageCommand(kind: ImageCommandKind.reference, prompt:'a garden', style:'Ink style'), '/aref char 画风="Ink style" a garden');
    expect(buildImageCommand(kind: ImageCommandKind.reference, referenceMode:'cs', prompt:'a garden', character:'ignored', style:'ignored', ratio:'3:2'), '/aref cs 比例=3:2 a garden');
    const text = '预设\n人物1：Alice | | left\n人物2：Bob | | right';
    expect(buildImageCommand(kind: ImageCommandKind.multi, prompt:text, ratio:'3:2'), '/amulti 比例=3:2 $text');
  });

  testWidgets('reader selects two cards and has no editor', (tester) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = call.arguments['text'] as String;
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    await tester.pumpWidget(MaterialApp(home: CharacterGalleryPage(api: CardApi(), admin:false)));
    await tester.pumpAndSettle();
    expect(find.byTooltip('添加角色卡'), findsNothing);
    for (final name in ['Alice', 'Bob']) {
      await tester.tap(find.text('$name · default'));
      await tester.pumpAndSettle();
    }
    expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed, isNotNull);
    await tester.tap(find.byType(FilledButton));
    await tester.pumpAndSettle();
    expect(copied, contains('/amulti 预览\n人物1：Alice | | on the left\n人物2：Bob | | on the right'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed card save preserves input; successful save closes editor', (tester) async {
    final api = CardApi()..fail = true;
    await tester.pumpWidget(MaterialApp(home: CharacterGalleryPage(api:api, admin:true)));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('添加角色卡'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Alice');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.textContaining('画廊已更新'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField).first).controller!.text, 'Alice');
    api.fail = false;
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.saved!['character'], 'Alice');
    expect(api.saved!['revision'], 'r1');
    expect(find.byType(AlertDialog), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('remote generation offers Turbo and reference modes', (tester) async {
    tester.view.physicalSize = const Size(1400, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(MaterialApp(home: LiteGeneratePage(api: ReferenceApi(),
      serverOnlineReminderEnabled: false, onServerOnlineReminderChanged: (_) {})));
    await tester.pumpAndSettle();
    await choose(tester, '跑图方式', 'Anima Turbo /aturbo');
    expect(find.textContaining('默认 10 步'), findsOneWidget);
    await choose(tester, '跑图方式', '参考生图 SnapRef /aref');
    expect(find.text('选择参考图片'), findsOneWidget);
    expect(find.text('预设角色'), findsNothing);
    expect(find.text('画风'), findsOneWidget);
    expect(find.text('我的画风预设'), findsOneWidget);
    await choose(tester, '画风', 'Ink style');
    expect(find.byKey(const ValueKey('global-style-Ink style')), findsOneWidget);
    await choose(tester, '参考模式', '角色与画风 cs');
    expect(find.text('画风'), findsNothing);
    expect(find.text('我的画风预设'), findsNothing);
    await choose(tester, '参考模式', '角色 char');
    expect(find.text('画风'), findsOneWidget);
    expect(find.byKey(const ValueKey('global-style-')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
