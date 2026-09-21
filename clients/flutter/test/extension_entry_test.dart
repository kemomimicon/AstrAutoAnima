import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/courtyard_theme.dart';

void main() {
  testWidgets(
      'independent extension is sidebar-only and does not select a base page',
      (tester) async {
    var baseSelected = false;
    var extensionOpened = false;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SizedBox(
                width: 240,
                child: HubNavigation(
                  destinations: List.generate(
                      10,
                      (i) => NavigationDestination(
                          icon: const Icon(Icons.circle), label: 'Page $i')),
                  selectedIndex: 0,
                  onSelected: (_) => baseSelected = true,
                  extensionEntries: [
                    ListTile(
                        title: const Text('炼丹炉'),
                        onTap: () => extensionOpened = true)
                  ],
                )))));
    await tester.scrollUntilVisible(find.text('炼丹炉'), 180);
    await tester.tap(find.text('炼丹炉'));
    expect(extensionOpened, true);
    expect(baseSelected, false);
    expect(find.byType(NavigationBar), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
