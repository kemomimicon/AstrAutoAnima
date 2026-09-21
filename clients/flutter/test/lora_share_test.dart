import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/loras/lora_share_dialog.dart';

void main() {
  LoraCatalogItem item([String url = 'https://civitai.com/models/42']) =>
      LoraCatalogItem.fromJson({
        'path': 'private/server/path.safetensors',
        'display_name': '画风示例',
        'recommended_prompt': 'ink, soft shading',
        'source_url': url,
      });

  test('share text contains attribution, not local file path', () {
    expect(item().shareText, contains('https://civitai.com/models/42'));
    expect(item().shareText, contains('ink, soft shading'));
    expect(item().shareText, isNot(contains('private/server')));
    expect(LoraCatalogItem.fromJson({}).sourceUrl, '');
  });

  testWidgets('share copies text only', (tester) async {
    String? copied;
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String;
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
      builder: (context) => TextButton(
          onPressed: () => showLoraShareDialog(context, item()),
          child: const Text('分享')),
    ))));
    await tester.tap(find.text('分享'));
    await tester.pumpAndSettle();
    expect(find.text(item().shareText), findsOneWidget);
    await tester.tap(find.text('复制分享内容'));
    await tester.pumpAndSettle();
    expect(copied, item().shareText);
  });

  testWidgets('missing source requires admin metadata, no fabricated link',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
      builder: (context) => TextButton(
          onPressed: () => showLoraShareDialog(context, item('')),
          child: const Text('分享')),
    ))));
    await tester.tap(find.text('分享'));
    await tester.pumpAndSettle();
    expect(find.text('复制分享内容'), findsNothing);
    expect(find.textContaining('请管理员'), findsOneWidget);
  });
}
