import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/features/settings/storage_management_page.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';

class StorageTestApi extends HubApi {
  StorageTestApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<Map<String, dynamic>> imageStorage() async => {
        'config': {
          'grouping': 'original',
          'strip_metadata': false,
          'scheduled': false,
          'retention_days': 7,
          'cleanup_hour': 4
        },
        'last_cleanup': '尚未执行',
        'areas': [
          {
            'id': 'random_style',
            'path': '/workspace/ComfyUI/output/AAA-RandomStyle',
            'count': 5,
            'bytes': 1048576
          }
        ],
      };
}

class FolderApi extends StorageTestApi {
  Map<String, dynamic>? payload;
  @override
  Future<Map<String, dynamic>> imageStorage() async {
    final value = await super.imageStorage();
    (value['areas'] as List).first['folders'] = [
      {'name': 'one', 'count': 3, 'bytes': 500},
      {'name': 'two', 'count': 2, 'bytes': 500},
    ];
    return value;
  }

  @override
  Future<Map<String, dynamic>> storageAction(
      String action, Map<String, dynamic> value) async {
    payload = value;
    return {'count': 0};
  }
}

void main() {
  testWidgets('directory selection never interprets empty as all',
      (tester) async {
    final api = FolderApi();
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: StorageManagementPage(api: api))));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('打包'), 250,
        scrollable: find.byType(Scrollable).first, maxScrolls: 30);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('打包'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('打包'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消全选'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '预览选定范围'))
            .onPressed,
        isNull);
    await tester.tap(find.text('one'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('预览选定范围'));
    await tester.pumpAndSettle();
    expect(api.payload!['folders'], ['one']);
    expect(tester.takeException(), isNull);
  });
  testWidgets('storage shows real inventory and dedicated random style path',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: StorageManagementPage(api: StorageTestApi()))));
    await tester.pumpAndSettle();
    expect(find.text('储存管理'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('/workspace/ComfyUI/output/AAA-RandomStyle'), 250,
        scrollable: find.byType(Scrollable).first, maxScrolls: 30);
    expect(find.text('5 张 · 1.0 MiB'), findsOneWidget);
    expect(find.text('清理'), findsOneWidget);
  });
}
