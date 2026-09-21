import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/features/loras/civitai_download_page.dart';

class LayoutApi extends HubApi {
  LayoutApi() : super(baseUrl: 'http://localhost', token: 'test');
  int? requested;
  @override
  Future<Map<String, dynamic>> civitaiDownloads() async => {'enabled': true, 'jobs': []};
  @override
  Future<Map<String, dynamic>> previewCivitai(int id) async {
    requested = id;
    return {'id': id, 'name': 'Long model name', 'base_model': 'Anima', 'trained_words': ['example'], 'files': []};
  }
}

void main() {
  testWidgets('long link remains intact and narrow layout scrolls without overflow', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = LayoutApi();
    await tester.pumpWidget(MaterialApp(home: CivitaiDownloadPage(api: api)));
    await tester.pumpAndSettle();
    final input = find.byKey(const Key('civitai-model-link'));
    final link = 'https://civitai.red/models/2823256/${'long-name-' * 40}?modelVersionId=3184847';
    await tester.enterText(input, link);
    expect(tester.widget<TextField>(input).controller!.text, link);
    expect(tester.widget<TextField>(input).minLines, 3);
    await tester.ensureVisible(find.text('读取版本'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('读取版本'));
    await tester.pumpAndSettle();
    expect(api.requested, 3184847);
    await tester.scrollUntilVisible(find.byKey(const Key('civitai-save-directory')), 250,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const Key('civitai-save-directory'))).minLines, 2);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
