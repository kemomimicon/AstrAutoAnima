import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/courtyard_theme.dart';
import 'package:astr_auto_anima_hub_client/features/splash/service_splash.dart';

void main() {
  testWidgets('public theme uses native icons without private raster assets', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: courtyardTheme(Brightness.light),
      home: const Scaffold(body: Column(children: [CourtyardWelcome(), CourtyardIcon(Icons.home)]))));
    expect(find.byType(Image), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('public splash yields to application', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: ServiceSplash(child: Text('Ready'))));
    await tester.pumpAndSettle();
    expect(find.text('Ready'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
