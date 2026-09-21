import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/gallery/gallery_page.dart';

class GalleryApi extends HubApi {
  GalleryApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<Map<String, dynamic>> gallery() async => {
        'revision': 'initial',
        'active': false,
        'ready': false,
        'config': {
          'model_kind': 'text',
          'character': '',
          'character_text': '',
          'target_id': '',
          'prompts': ['', '', '', '']
        },
        'items': <Map<String, dynamic>>[],
      };
}

class RedrawApi extends GalleryApi {
  int? chosen;
  @override
  Future<Map<String, dynamic>> gallery() async => {
        'revision': 'one',
        'active': false,
        'ready': true,
        'config': {'model_kind': 'text', 'character_text': 'model'},
        'items': [
          {
            'style': 'ink',
            'slots': [
              for (var n = 0; n < 4; n++) {'index': n, 'status': 'failed'}
            ]
          }
        ],
      };
  @override
  Future<Map<String, dynamic>> generateGallery(
      String revision, List<String> styles,
      {int? slotIndex}) async {
    chosen = slotIndex;
    return gallery();
  }
}

void main() {
  testWidgets('admin can request exactly one redraw slot after confirmation',
      (tester) async {
    final api = RedrawApi();
    await tester
        .pumpWidget(MaterialApp(home: GalleryPage(api: api, admin: true)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重绘此张').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('仅重绘第 1 张'), findsOneWidget);
    expect(api.chosen, isNull);
    await tester.tap(find.text('确认更新'));
    await tester.pumpAndSettle();
    expect(api.chosen, 0);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
      'unconfigured gallery cannot generate; reader has no admin controls',
      (tester) async {
    await tester.pumpWidget(
        MaterialApp(home: GalleryPage(api: GalleryApi(), admin: true)));
    await tester.pumpAndSettle();
    final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '更新全部画风（每个四张）'));
    expect(button.onPressed, isNull);
    expect(find.textContaining('四条固定串暂留空'), findsOneWidget);
    await tester.pumpWidget(MaterialApp(
        home: GalleryPage(key: const ValueKey('reader'), api: GalleryApi())));
    await tester.pumpAndSettle();
    expect(find.text('配置模特与固定串'), findsNothing);
    expect(find.text('更新全部画风（每个四张）'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
