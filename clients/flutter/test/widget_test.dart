// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/core/command_builder.dart';
import 'package:astr_auto_anima_hub_client/core/server_online_tracker.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_prompt_details_dialog.dart';
import 'package:flutter/material.dart';

void main() {
  test('parses a prompt record returned by Hub Service', () {
    final record = PromptRecord.fromJson({
      'id': 'discord-0001',
      'name': 'Rain scene',
      'prompt': '1girl, solo, rainy street',
      'source_code': 'D',
      'safety_code': 'N',
      'enabled': true,
      'weight': 2,
      'categories': ['rain', 'night'],
    });

    expect(record.id, 'discord-0001');
    expect(record.sourceCode, 'D');
    expect(record.weight, 2);
    expect(record.categories, ['rain', 'night']);
  });

  testWidgets(
      'Lite prompt details show complete selectable content and copy action',
      (tester) async {
    const fullPrompt =
        '1girl, solo, rainy street, transparent umbrella, detailed background';
    const record = PromptRecord(
      id: 'discord-0001',
      name: 'Rain scene',
      prompt: fullPrompt,
      sourceCode: 'D',
      safetyCode: 'N',
      enabled: true,
      weight: 1,
      categories: ['rain'],
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: LitePromptDetailsDialog(item: record)),
      ),
    );

    expect(find.text(fullPrompt), findsOneWidget);
    expect(find.byKey(const Key('lite-prompt-full-text')), findsOneWidget);
    expect(find.byKey(const Key('lite-prompt-copy-button')), findsOneWidget);
    expect(find.text('复制提示词'), findsOneWidget);
  });

  test('server online tracker only notifies after an offline transition', () {
    final tracker = ServerOnlineTracker();

    expect(tracker.update(true), isFalse);
    expect(tracker.update(true), isFalse);
    expect(tracker.update(false), isFalse);
    expect(tracker.update(false), isFalse);
    expect(tracker.update(true), isTrue);
    expect(tracker.update(true), isFalse);
  });

  test('reset clears previous server state', () {
    final tracker = ServerOnlineTracker();

    expect(tracker.update(false), isFalse);
    tracker.reset();
    expect(tracker.update(true), isFalse);
  });

  test('builds direct and random commands in plugin parameter order', () {
    expect(
      buildImageCommand(
        kind: ImageCommandKind.direct,
        character: 'demo_character',
        style: 'demo_style',
        ratio: '2:3',
        sampler: '2m',
        steps: 36,
        cfg: 5.5,
        prompt: 'rainy street',
      ),
      '/aimg 角色=demo_character 画风=demo_style 比例=2:3 采样器=2m 步数=36 CFG=5.5 rainy street',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.random,
        fiveDraw: true,
        poolFilter: 'C/H',
        style: 'demo_style',
      ),
      '来张好图五连抽 C/H 画风=demo_style',
    );
  });

  test('chaos command ignores selectors that the plugin randomizes', () {
    expect(
      buildImageCommand(
        kind: ImageCommandKind.chaos,
        fiveDraw: true,
        poolFilter: 'D/N',
        character: 'ignored',
        style: 'ignored',
        ratio: '1:1',
        sampler: '2m_sde_gpu',
        prompt: 'rainy night',
      ),
      '来张好图混沌五连抽 D/N 采样器=2m_sde_gpu rainy night',
    );
  });

  test('builds Chinese and reverse commands with existing presets', () {
    expect(
      buildImageCommand(
        kind: ImageCommandKind.chinese,
        character: 'demo_character',
        style: 'demo_style',
        prompt: '雨夜里撑伞',
      ),
      '/aicn 角色=demo_character 画风=demo_style 雨夜里撑伞',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.reverse,
        reversePreset: 'scene',
        character: 'demo_character_2',
        style: 'demo_style',
        prompt: 'transparent umbrella',
      ),
      '/aip 模式=scene 角色=demo_character_2 画风=demo_style transparent umbrella',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.reverse,
        reverseOnly: true,
        reverseCategories: const ['scene', 'action', 'composition'],
      ),
      '/aip 仅反推 分类=场景,动作,构图',
    );
  });

  test('builds HQ and refine beta commands', () {
    expect(
      buildImageCommand(
        kind: ImageCommandKind.hq,
        profile: 'beauty',
        character: 'demo_character',
        style: 'demo_style',
        ratio: '2:3',
        sampler: '2m_sde_gpu',
        steps: 38,
        cfg: 4.5,
        scale: 1.5,
        denoise: 0.3,
        prompt: 'rainy street',
      ),
      '/ahq beauty 角色=demo_character 画风=demo_style 比例=2:3 '
      '采样器=2m_sde_gpu 步数=38 CFG=4.5 放大=1.5 重绘=0.3 rainy street',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.refine,
        profile: 'medium',
        parentJobId: 'job_20260821_test',
        scale: 1.5,
        denoise: 0.35,
      ),
      '/arefine medium 放大=1.5 重绘=0.35 任务=job_20260821_test',
    );
  });

  test('parses delivery target and remote job state', () {
    final target = DeliveryTarget.fromJson({
      'id': 'main-group',
      'label': '主群',
      'kind': 'group',
    });
    final job = RemoteJobResult.fromJson({
      'id': 'job-1',
      'status': 'succeeded',
      'target_id': 'main-group',
      'target_label': '主群',
      'command_preview': '来张好图抄一抄 N',
      'message': '已发送',
      'kind': 'random',
      'safety_code': 'N',
      'profile': '',
      'created_at': '2026-08-22T10:00:00Z',
      'updated_at': '2026-08-22T10:01:00Z',
      'images': [
        {
          'id': 'img_1234',
          'filename': 'result.png',
          'content_type': 'image/png',
          'size_bytes': 1024,
          'sha256':
              'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          'download_url': '/api/v1/lite/jobs/job-1/images/img_1234',
        },
      ],
    });

    expect(target.isGroup, isTrue);
    expect(job.isFinished, isTrue);
    expect(job.targetLabel, '主群');
    expect(job.kind, 'random');
    expect(job.images.single.filename, 'result.png');
  });
}
