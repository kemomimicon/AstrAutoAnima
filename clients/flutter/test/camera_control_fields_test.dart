import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/features/lite/camera_control_fields.dart';

void main() {
  testWidgets('extreme camera does not enable helper until checked',
      (tester) async {
    Map<String, String> values = {'camera_pitch': 'extreme_high'};
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SingleChildScrollView(
      child: StatefulBuilder(
          builder: (context, setState) => CameraControlFields(
                values: values,
                onChanged: (next) => setState(() => values = next),
              )),
    ))));
    expect(tester.widget<CheckboxListTile>(find.byType(CheckboxListTile)).value,
        false);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    expect(values['camera_extreme_lora'], 'true');
    expect(values['camera_pitch'], 'extreme_high');
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    expect(values['camera_extreme_lora'], 'false');
  });
}
