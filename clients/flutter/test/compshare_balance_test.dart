import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:astr_auto_anima_hub_client/core/compshare_api.dart';

void main() {
  test('balance is read only, signed, and needs no instance configuration', () async {
    var calls = 0;
    final api = CompShareApi(config: const CompShareConfig(publicKey: 'public-test', privateKey: 'private-test'),
      client: MockClient((request) async {
        calls++;
        expect(request.url.host, 'api.compshare.cn');
        final fields = Uri.splitQueryString(request.body);
        expect(fields.keys.toSet(), {'Action', 'PublicKey', 'Signature'});
        expect(fields['Action'], 'GetBalance');
        expect(fields['Signature'], CompShareApi.signature({'Action': 'GetBalance', 'PublicKey': 'public-test'}, 'private-test'));
        expect(request.body, isNot(contains('private-test')));
        return http.Response(jsonEncode({'RetCode': 0, 'AccountInfo': {'AmountAvailable': '12.3400', 'Amount': 0}}), 200);
      }));
    final result = await api.balance();
    expect(result['AmountAvailable'], '12.3400');
    expect(result['Amount'], '0');
    expect(result.containsKey('AmountCredit'), isFalse);
    expect(calls, 1);
  });
  test('missing balance and rejected permission are not zero', () async {
    for (final payload in [{'RetCode': 0, 'AccountInfo': {}}, {'RetCode': 1, 'Message': 'denied'}]) {
      final api = CompShareApi(config: const CompShareConfig(publicKey: 'p', privateKey: 's'),
        client: MockClient((_) async => http.Response(jsonEncode(payload), 200)));
      await expectLater(api.balance(), throwsA(isA<CompShareApiException>()));
    }
  });
}
