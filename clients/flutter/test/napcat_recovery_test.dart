import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/compshare_api.dart';
import 'package:astr_auto_anima_hub_client/features/dashboard/napcat_login_dialog.dart';

class NapcatTestApi extends HubApi {
  NapcatTestApi() : super(baseUrl: 'http://localhost', token: 'test');
  @override
  Future<Map<String, dynamic>> napcatAccounts(String code) async => {
        'accounts': ['123456'],
        'is_login': false,
        'qr_code': 'https://qq.example/test'
      };
}

void main() {
  testWidgets(
      'NapCat reads account and displays local QR without opening external site',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: NapcatLoginDialog(api: NapcatTestApi()))));
    await tester.pumpAndSettle();
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text('123456'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '快捷登录'))
            .onPressed,
        isNotNull);
  });
  test('reboot uses cloud control plane without a Hub request', () async {
    final api = CompShareApi(
        config: const CompShareConfig(
            publicKey: 'p',
            privateKey: 's',
            region: 'r',
            zone: 'z',
            uhostId: 'uhost-test'),
        client: MockClient((request) async {
          expect(request.url.host, 'api.compshare.cn');
          final body = Uri.splitQueryString(request.body);
          expect(body['Action'], 'RebootCompShareInstance');
          expect(body['UHostId'], 'uhost-test');
          expect(body.containsKey('Signature'), isTrue);
          return http.Response(jsonEncode({'RetCode': 0}), 200);
        }));
    await api.reboot();
  });
}
