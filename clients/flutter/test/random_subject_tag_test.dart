import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:astr_auto_anima_hub_client/core/command_builder.dart';
import 'package:astr_auto_anima_hub_client/core/random_subject_tag.dart';
import 'package:astr_auto_anima_hub_client/features/settings/settings_drawer.dart';

void main() {
  test('random subject selection persists and lock prevents edits', () async {
    SharedPreferences.setMockInitialValues({});
    await loadRandomSubjectTag();
    expect(randomSubjectTag.value, '');
    expect(randomSubjectTagLocked.value, false);
    await saveRandomSubjectTag('1boy');
    await saveRandomSubjectTagLocked(true);
    await saveRandomSubjectTag('1man');
    expect(randomSubjectTag.value, '1boy');
    randomSubjectTag.value = '';
    randomSubjectTagLocked.value = false;
    await loadRandomSubjectTag();
    expect(randomSubjectTag.value, '1boy');
    expect(randomSubjectTagLocked.value, true);
    await saveRandomSubjectTagLocked(false);
  });

  test('only random commands include a subject override', () {
    expect(
        buildImageCommand(
            kind: ImageCommandKind.random,
            fiveDraw: true,
            poolFilter: 'D/N',
            randomSubjectTag: '1boy'),
        '来张好图五连抽 D/N 起手=1boy');
    expect(
        buildImageCommand(
            kind: ImageCommandKind.chaos, randomSubjectTag: 'none'),
        '来张好图混沌时刻 起手=无');
    expect(
        buildImageCommand(
            kind: ImageCommandKind.direct,
            randomSubjectTag: '1boy',
            prompt: 'rain'),
        '/aimg rain');
  });

  testWidgets('settings drawer exposes the persistent lock', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await loadRandomSubjectTag();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SettingsDrawer(onDisconnect: () async {}),
      ),
    ));
    expect(find.text('锁定随机串起手选项'), findsOneWidget);
    await tester.tap(find.widgetWithText(SwitchListTile, '锁定随机串起手选项'));
    await tester.pump();
    expect(randomSubjectTagLocked.value, true);
    expect(
        (await SharedPreferences.getInstance())
            .getBool('aaa_random_subject_tag_locked'),
        true);
    await saveRandomSubjectTagLocked(false);
  });
}
