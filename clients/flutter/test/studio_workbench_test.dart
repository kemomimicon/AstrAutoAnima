import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/extensions/studio_workbench.dart';

class FakeStudioApi extends HubApi {
  FakeStudioApi() : super(baseUrl: 'http://localhost:6278', token: 'never-in-url');
  final request = Completer<Map<String, dynamic>>();
  final closed = <String>[];
  @override
  Future<Map<String, dynamic>> openStudioSession() => request.future;
  @override
  Future<Map<String, dynamic>> closeStudioSession(String id) async {
    closed.add(id);
    return {'revoked': true};
  }
}

void main() {
  testWidgets('closed page revokes a late session instead of loading it', (tester) async {
    final api = FakeStudioApi();
    await tester.pumpWidget(MaterialApp(home: StudioWorkbench(api: api)));
    await tester.pumpWidget(const SizedBox());
    api.request.complete({'session_id': 'late', 'launch_path': '/extensions/anima-lora-studio/launch#one-use'});
    await tester.pump();
    expect(api.closed, ['late']);
    expect(tester.takeException(), isNull);
  });

  testWidgets('connection failure does not expose server exception or token', (tester) async {
    final api = FakeStudioApi();
    await tester.pumpWidget(MaterialApp(home: StudioWorkbench(api: api)));
    api.request.completeError(Exception('never-in-url'));
    await tester.pumpAndSettle();
    expect(find.textContaining('连接失败'), findsOneWidget);
    expect(find.textContaining('never-in-url'), findsNothing);
  });
}
