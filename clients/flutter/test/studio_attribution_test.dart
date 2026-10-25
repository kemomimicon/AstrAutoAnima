import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/extensions/extension_management_page.dart';

class AttributionApi extends HubApi {
  AttributionApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<Map<String, dynamic>> extensionStatus(String id) async => {
    'message': '未安装', 'enabled': false, 'version': '0.1.1',
  };
}

void main() {
  testWidgets('optional Studio names original author and compatible baseline', (tester) async {
    await tester.pumpWidget(MaterialApp(home: ExtensionManagementPage(
        api: AttributionApi(), id: 'anima-lora-studio', name: '炼丹炉')));
    await tester.pumpAndSettle();
    expect(find.text('AnimaLoraStudio · 第三方开源项目'), findsOneWidget);
    expect(find.textContaining('WalkingMeatAxolotl 与贡献者'), findsOneWidget);
    expect(find.textContaining('不代表上游最新版'), findsOneWidget);
    expect(find.text('进入炼丹炉工作台'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
