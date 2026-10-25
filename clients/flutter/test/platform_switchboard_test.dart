import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/platforms/platform_switchboard_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class BoardApi extends HubApi {
  BoardApi() : super(baseUrl: 'http://unused.invalid', token: 'test');
  var revision = 'missing';
  final switches = <String, bool>{
    'qq': true,
    'telegram': false,
    'discord': false
  };

  @override
  Future<Map<String, dynamic>> getPlatformSwitchboard() async => {
        'revision': revision,
        'accept_new': Map<String, bool>.from(switches),
        'adapter_configuration': {
          'qq': 'configured_enabled',
          'telegram': 'not_configured',
          'discord': 'not_configured',
        },
      };

  @override
  Future<Map<String, dynamic>> savePlatformSwitchboard({
    required String revision,
    required Map<String, bool> acceptNew,
  }) async {
    if (revision != this.revision) {
      throw const HubApiException('changed', statusCode: 409);
    }
    switches
      ..clear()
      ..addAll(acceptNew);
    this.revision = 'saved';
    return getPlatformSwitchboard();
  }
}

void main() {
  testWidgets(
      'enabling Telegram preserves QQ and Discord and warns about AstrBot',
      (tester) async {
    final api = BoardApi();
    await tester
        .pumpWidget(MaterialApp(home: PlatformSwitchboardPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('AstrBot 尚未配置'), findsNWidgets(2));
    await tester.tap(find.byKey(const ValueKey('platform.telegram')));
    await tester.pumpAndSettle();
    expect(find.text('确认开始接单'), findsOneWidget);
    await tester.tap(find.text('确认开启'));
    await tester.pumpAndSettle();
    expect(api.switches, {'qq': true, 'telegram': true, 'discord': false});
  });
}
