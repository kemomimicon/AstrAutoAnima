import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/dashboard/napcat_status_card.dart';
import 'package:astr_auto_anima_hub_client/features/dashboard/dashboard_page.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';

class StatusApi extends HubApi {
  StatusApi() : super(baseUrl: 'http://localhost', token: 'test');
  int count = 0;
  bool fail = false;
  @override
  Future<Map<String, dynamic>> napcatStatus() async {
    count++;
    if (fail) throw Exception('network');
    return {
      'state': count == 1 ? 'online' : 'offline',
      'message': count == 1 ? 'QQ 在线' : 'QQ 已掉线，请重新登录'
    };
  }
}

class DashboardNapcatApi extends StatusApi {
  @override
  Future<WorkstationStatus> getWorkstationStatus() async =>
      throw Exception('offline');
  @override
  Future<WorkstationMetrics> getWorkstationMetrics() async =>
      throw Exception('offline');
  @override
  Future<Map<String, dynamic>> napcatAccounts(String code) async => {
        'accounts': ['123456'],
        'is_login': false,
      };
}

void main() {
  testWidgets(
      'actual dashboard keeps a visible NapCat login entry even when probes fail',
      (tester) async {
    tester.view.physicalSize = const Size(390, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: DashboardPage(
      api: DashboardNapcatApi(),
      serverOnlineReminderEnabled: false,
      onServerOnlineReminderChanged: (_) {},
    ))));
    await tester.pumpAndSettle();
    expect(find.text('NapCat · QQ 登录状态'), findsOneWidget);
    expect(find.text('QQ 在线'), findsOneWidget);
    await tester.tap(find.text('NapCat 登录助手'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('123456'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('polls offline and treats network failure as unknown',
      (tester) async {
    final api = StatusApi();
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: NapcatStatusCard(api: api))));
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
