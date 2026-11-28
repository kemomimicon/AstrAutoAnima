import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:astr_auto_anima_hub_client/core/compshare_api.dart';
import 'package:astr_auto_anima_hub_client/features/cloud/compshare_instance_page.dart';

Future<void> openBalancePage(WidgetTester tester, MockClient client) async {
  tester.view.physicalSize = const Size(700, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel,
      (call) async {
    if (call.method == 'readAll') return <String, String>{};
    throw StateError('Query must not save or rewrite credentials');
  });
  addTearDown(() => tester.binding.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, null));
  await tester.pumpWidget(MaterialApp(
      home: Scaffold(
          body: CompShareInstancePage(
    cloudApiFactory: (config) => CompShareApi(config: config, client: client),
  ))));
  await tester.pumpAndSettle();
}

Finder configField(String label) => find.byWidgetPredicate(
    (w) => w is TextField && w.decoration?.labelText == label);

Future<void> enterKeys(WidgetTester tester) async {
  await tester.enterText(configField('Public Key'), 'p');
  await tester.enterText(configField('Private Key'), 's');
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'instance page queries balance with only keys and no Hub or power calls',
      (tester) async {
    final actions = <String>[];
    await openBalancePage(tester, MockClient((request) async {
      final fields = Uri.splitQueryString(request.body);
      actions.add(fields['Action']!);
      expect(fields.keys.toSet(), {'Action', 'PublicKey', 'Signature'});
      return http.Response(
          jsonEncode({
            'RetCode': 0,
            'AccountInfo': {'AmountAvailable': '12.3400', 'Amount': '0'}
          }),
          200);
    }));
    expect(find.text('优云账户余额'), findsOneWidget);
    await enterKeys(tester);
    await tester.tap(find.text('查询账户余额'));
    await tester.pumpAndSettle();
    expect(actions, ['GetBalance']);
    expect(find.text('可用余额：12.3400'), findsOneWidget);
    expect(find.text('账户余额：0'), findsOneWidget);
    expect(find.textContaining('信用余额：'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('missing keys give setup guidance without a network request',
      (tester) async {
    var calls = 0;
    await openBalancePage(tester, MockClient((_) async {
      calls++;
      return http.Response('{}', 200);
    }));
    await tester.tap(find.text('查询账户余额'));
    await tester.pumpAndSettle();
    expect(calls, 0);
    expect(find.text('请在 API 配置中填写 Public Key 和 Private Key。'), findsOneWidget);
  });
  testWidgets(
      'failed balance refresh clears old amount instead of showing zero',
      (tester) async {
    var calls = 0;
    await openBalancePage(
        tester,
        MockClient((_) async => http.Response(
            jsonEncode(++calls == 1
                ? {
                    'RetCode': 0,
                    'AccountInfo': {'AmountAvailable': '12.34'}
                  }
                : {'RetCode': 1, 'Message': '余额查询权限不足'}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'})));
    await enterKeys(tester);
    await tester.tap(find.text('查询账户余额'));
    await tester.pumpAndSettle();
    expect(find.text('可用余额：12.34'), findsOneWidget);
    await tester.tap(find.text('查询账户余额'));
    await tester.pumpAndSettle();
    expect(find.text('余额查询权限不足'), findsOneWidget);
    expect(find.textContaining('可用余额：'), findsNothing);
  });
  testWidgets('late balance cannot replace data after editing account keys',
      (tester) async {
    final pending = Completer<http.Response>();
    await openBalancePage(tester, MockClient((_) => pending.future));
    await enterKeys(tester);
    await tester.tap(find.text('查询账户余额'));
    await tester.pump();
    await tester.enterText(configField('Public Key'), 'new-account');
    pending.complete(http.Response(
        jsonEncode({
          'RetCode': 0,
          'AccountInfo': {'Amount': '99'}
        }),
        200));
    await tester.pumpAndSettle();
    expect(find.text('账户余额：99'), findsNothing);
    expect(find.text('查询账户余额'), findsOneWidget);
  });
  test('balance is read only, signed, and needs no instance configuration',
      () async {
    var calls = 0;
    final api = CompShareApi(
        config: const CompShareConfig(
            publicKey: 'public-test', privateKey: 'private-test'),
        client: MockClient((request) async {
          calls++;
          expect(request.url.host, 'api.compshare.cn');
          final fields = Uri.splitQueryString(request.body);
          expect(fields.keys.toSet(), {'Action', 'PublicKey', 'Signature'});
          expect(fields['Action'], 'GetBalance');
          expect(
              fields['Signature'],
              CompShareApi.signature(
                  {'Action': 'GetBalance', 'PublicKey': 'public-test'},
                  'private-test'));
          expect(request.body, isNot(contains('private-test')));
          return http.Response(
              jsonEncode({
                'RetCode': 0,
                'AccountInfo': {'AmountAvailable': '12.3400', 'Amount': 0}
              }),
              200);
        }));
    final result = await api.balance();
    expect(result['AmountAvailable'], '12.3400');
    expect(result['Amount'], '0');
    expect(result.containsKey('AmountCredit'), isFalse);
    expect(calls, 1);
  });
  test('missing balance and rejected permission are not zero', () async {
    for (final payload in [
      {'RetCode': 0, 'AccountInfo': {}},
      {'RetCode': 1, 'Message': 'denied'}
    ]) {
      final api = CompShareApi(
          config: const CompShareConfig(publicKey: 'p', privateKey: 's'),
          client:
              MockClient((_) async => http.Response(jsonEncode(payload), 200)));
      await expectLater(api.balance(), throwsA(isA<CompShareApiException>()));
    }
  });
}
