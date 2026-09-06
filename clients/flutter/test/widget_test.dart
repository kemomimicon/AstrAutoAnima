// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:astr_auto_anima_hub_client/app.dart';
import 'package:astr_auto_anima_hub_client/core/app_edition.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/core/command_builder.dart';
import 'package:astr_auto_anima_hub_client/core/compshare_api.dart';
import 'package:astr_auto_anima_hub_client/core/notification_service.dart';
import 'package:astr_auto_anima_hub_client/core/server_online_tracker.dart';
import 'package:astr_auto_anima_hub_client/core/session_store.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_prompt_details_dialog.dart';
import 'package:flutter/material.dart';

void main() {
  test('CompShare signing sorts parameters before SHA1', () {
    expect(
      CompShareApi.signature({'B': '2', 'A': '1'}, 'secret'),
      '9f9dc06a555e0a6a59bb6050e16c32ae3b119f72',
    );
  });

  test('parses CompShare instance state and GPU information', () {
    final instance = CompShareInstance.fromJson({
      'UHostId': 'uhost-example',
      'Name': 'Anima Workstation',
      'State': 'Stopped',
      'Region': 'cn-wlcb',
      'Zone': 'cn-wlcb-01',
      'GpuType': 'RTX 5090',
      'GPU': 1,
      'InstancePrice': 3.5,
      'SupportWithoutGpuStart': true,
    });

    expect(instance.isStopped, isTrue);
    expect(instance.gpuType, 'RTX 5090');
    expect(instance.supportWithoutGpuStart, isTrue);
  });

  testWidgets('service edition opens in fixed Lite connection mode',
      (tester) async {
    await tester.pumpWidget(
      AstrAutoAnimaApp(
        store: SessionStore(),
        notificationService: NotificationService(),
        initialSession: const HubSession(baseUrl: '', token: ''),
        edition: AppEdition.service,
      ),
    );

    expect(find.text('使用用户令牌连接轻量跑图端'), findsOneWidget);
    expect(find.text('管理端'), findsNothing);
  });

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

  test('parses live workstation metrics including GPU and VRAM', () {
    final metrics = WorkstationMetrics.fromJson({
      'collected_at': '2026-08-31T12:00:00Z',
      'cpu_percent': 37.5,
      'cpu_logical_count': 32,
      'load_average_1m': 2.25,
      'load_average_5m': 1.75,
      'load_average_15m': 1.5,
      'memory': {
        'total_bytes': 68719476736,
        'used_bytes': 21474836480,
        'available_bytes': 47244640256,
        'utilization_percent': 31.25,
      },
      'gpus': [
        {
          'index': 0,
          'name': 'NVIDIA GeForce RTX 5090',
          'utilization_percent': 82,
          'memory_total_mib': 32607,
          'memory_used_mib': 16384,
          'memory_free_mib': 16223,
          'memory_utilization_percent': 50.25,
          'temperature_c': 61,
        },
      ],
    });

    expect(metrics.cpuPercent, 37.5);
    expect(metrics.memory.utilizationPercent, 31.25);
    expect(metrics.gpus.single.name, 'NVIDIA GeForce RTX 5090');
    expect(metrics.gpus.single.memoryUsedMib, 16384);
  });

  test('parses Chinese and English character dictionary results', () {
    final result = CharacterDictionaryResult.fromJson({
      'available': true,
      'query': '初音未来',
      'total': 1,
      'items': [
        {
          'tag': 'hatsune_miku',
          'chinese_names': ['初音未来'],
          'aliases': ['初音未来', 'hatsune miku'],
          'copyright': ['vocaloid'],
          'gender': ['1girl'],
          'appearance': ['aqua hair', 'twintails'],
          'post_count': 100,
          'weak_prompt': 'hatsune_miku, vocaloid',
          'strong_prompt':
              'hatsune_miku, vocaloid, 1girl, aqua hair, twintails',
        },
      ],
    });

    expect(result.available, isTrue);
    expect(result.items.single.tag, 'hatsune_miku');
    expect(result.items.single.chineseNames, ['初音未来']);
    expect(result.items.single.strongPrompt, contains('twintails'));
  });

  test('parses Lite user list and one-time issued token', () {
    final users = LiteUserListResult.fromJson({
      'revision': 'rev-1',
      'items': [
        {
          'id': 'qq-123456789',
          'qq': '123456789',
          'label': 'Member',
          'allow_group': false,
          'enabled': true,
        },
      ],
    });
    final issued = LiteUserIssueResult.fromJson({
      'action': 'created',
      'revision': 'rev-2',
      'token': 'aah_u_example_one_time_token_1234567890',
      'user': {
        'id': 'qq-123456789',
        'qq': '123456789',
        'label': 'Member',
        'allow_group': false,
        'enabled': true,
      },
    });

    expect(users.items.single.qq, '123456789');
    expect(users.items.single.allowGroup, isFalse);
    expect(users.revision, 'rev-1');
    expect(issued.action, 'created');
    expect(issued.token, startsWith('aah_u_'));
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
        character: 'example_character',
        style: 'example_style',
        ratio: '2:3',
        sampler: '2m',
        scheduler: 'karras',
        steps: 36,
        cfg: 5.5,
        prompt: 'rainy street',
      ),
      '/aimg 角色=example_character 角色模式=弱 画风=example_style 比例=2:3 采样器=2m 调度器=karras 步数=36 CFG=5.5 rainy street',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.random,
        fiveDraw: true,
        poolFilter: 'C/H',
        style: 'soft_style',
      ),
      '来张好图五连抽 C/H 画风=soft_style',
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
        scheduler: 'beta',
        prompt: 'rainy night',
      ),
      '来张好图混沌五连抽 D/N 采样器=2m_sde_gpu 调度器=beta rainy night',
    );
  });

  test('builds Chinese and reverse commands with existing presets', () {
    expect(
      buildImageCommand(
        kind: ImageCommandKind.chinese,
        character: 'example_character',
        style: 'example_style',
        prompt: '雨夜里撑伞',
      ),
      '/aicn 角色=example_character 角色模式=弱 画风=example_style 雨夜里撑伞',
    );
    expect(
      buildImageCommand(
        kind: ImageCommandKind.reverse,
        reversePreset: 'scene',
        character: 'second_character',
        style: 'soft_style',
        prompt: 'transparent umbrella',
      ),
      '/aip 模式=scene 角色=second_character 角色模式=弱 画风=soft_style transparent umbrella',
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
        character: 'example_character',
        style: 'example_style',
        ratio: '2:3',
        sampler: '2m_sde_gpu',
        steps: 38,
        cfg: 4.5,
        scale: 1.5,
        denoise: 0.3,
        prompt: 'rainy street',
      ),
      '/ahq beauty 角色=example_character 角色模式=弱 画风=example_style 比例=2:3 '
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
    expect(
      buildImageCommand(
        kind: ImageCommandKind.refine,
        profile: 'seedvr2',
        parentJobId: 'job_20260821_test',
        scale: 1.75,
        denoise: 0.4,
      ),
      '/arefine seedvr2 任务=job_20260821_test',
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
