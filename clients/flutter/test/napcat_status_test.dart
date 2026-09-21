import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/dashboard/napcat_status_card.dart';

class StatusApi extends HubApi {
  StatusApi() : super(baseUrl: 'http://localhost', token: 'test');
  int count = 0;
  bool fail = false;
  @override
  Future<Map<String, dynamic>> napcatStatus() async {
    count++;
    if (fail) throw Exception('network');
    return {'state': count == 1 ? 'online' : 'offline',
      'message': count == 1 ? 'QQ 在线' : 'QQ 已掉线，请重新登录'};
  }
}
void main() {
  testWidgets('polls offline and treats network failure as unknown', (tester) async {
    final api = StatusApi();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: NapcatStatusCard(api: api))));
    await tester.pumpAndSettle();
    expect(find.text('QQ 在线'), findsOneWidget);
    await tester.pump(const Duration(seconds: 30));
    await tester.pumpAndSettle();
    expect(find.text('QQ 已掉线，请重新登录'), findsOneWidget);
    api.fail = true;
    await tester.tap(find.byTooltip('刷新 QQ 状态'));
    await tester.pumpAndSettle();
    expect(find.textContaining('暂时无法查询'), findsOneWidget);
    expect(find.text('QQ 已掉线，请重新登录'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    final count = api.count;
    await tester.pump(const Duration(seconds: 60));
    expect(api.count, count);
  });
}
