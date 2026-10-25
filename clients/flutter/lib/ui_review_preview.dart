// Isolated UI review entry point. Never connects to a real Hub.
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'app.dart';
import 'core/courtyard_theme.dart';
import 'core/notification_service.dart';
import 'core/session_store.dart';

void main() {
  http.runWithClient(() {
    WidgetsFlutterBinding.ensureInitialized();
    runApp(const ReviewPreview());
  },
      () => MockClient((request) async {
            if (request.method != 'GET') {
              return http.Response(
                  jsonEncode({'detail': '本地界面预览：不提交任务、不修改数据。'}), 403,
                  headers: {'content-type': 'application/json; charset=utf-8'});
            }
            final path = request.url.path;
            Map<String, dynamic> data = {
              'items': [],
              'total': 0,
              'page': 1,
              'pages': 1,
              'revision': 'demo'
            };
            if (path.endsWith('/presets')) {
              data = {
                'revision': 'demo',
                'characters': [
                  {
                    'name': '蓝铃（演示）',
                    'kind': 'character',
                    'prompt': 'demo_character',
                    'loras': [],
                    'variants': []
                  }
                ],
                'styles': [
                  for (final name in ['当前画风', '柔光水彩（演示）', '清透赛璐璐（演示）'])
                    {
                      'name': name,
                      'kind': 'style',
                      'prompt': 'demo_style',
                      'loras': []
                    }
                ]
              };
            } else if (path.endsWith('/delivery-targets')) {
              data = {
                'targets': [
                  {'id': 'demo', 'label': '演示目标 · 不会发送', 'kind': 'private'}
                ]
              };
            } else if (path.endsWith('/health')) {
              data = {
                'status': 'ok',
                'version': '本地预览',
                'service': 'astr-auto-anima-hub'
              };
            } else if (path.endsWith('/status')) {
              data = {
                'status': 'online',
                'probes': [
                  for (final name in ['ComfyUI', 'AstrBot', 'Hub'])
                    {'name': name, 'status': 'online', 'detail': '演示状态，非服务器实测'}
                ]
              };
            } else if (path.endsWith('/metrics')) {
              data = {
                'cpu_percent': 18.0,
                'cpu_logical_count': 16,
                'memory': {
                  'total_bytes': 68719476736,
                  'used_bytes': 17179869184,
                  'available_bytes': 51539607552,
                  'utilization_percent': 25.0
                },
                'gpus': []
              };
            } else if (path.endsWith('/prompts')) {
              data['items'] = [
                for (final name in ['林间阅读', '窗边午后', '海边散步'])
                  {
                    'id': 'demo-${name.hashCode}',
                    'name': '$name（演示）',
                    'prompt': 'solo, peaceful scenery, soft lighting',
                    'source_code': 'G',
                    'safety_code': 'N'
                  }
              ];
              data['total'] = 3;
            } else if (path.endsWith('/gallery')) {
              data = {
                'ready': false,
                'active': false,
                'items': [],
                'config': {
                  'model_kind': 'text',
                  'character_text': '',
                  'prompts': ['', '', '', '']
                },
                'revision': 'demo'
              };
            } else if (path.endsWith('/characters')) {
              data['items'] = [
                {
                  'tag': 'hatsune_miku',
                  'chinese_names': ['初音未来（演示）'],
                  'weak_prompt': 'hatsune_miku, vocaloid',
                  'strong_prompt': 'hatsune_miku, vocaloid, twintails',
                  'aliases': [],
                  'appearance': [],
                  'copyright': ['vocaloid']
                }
              ];
              data['total'] = 1;
            }
            return http.Response(jsonEncode(data), 200,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }));
}

class ReviewPreview extends StatefulWidget {
  const ReviewPreview({super.key});
  @override
  State<ReviewPreview> createState() => _ReviewPreviewState();
}

class _ReviewPreviewState extends State<ReviewPreview> {
  bool admin = false;
  bool phone = true;
  @override
  Widget build(BuildContext context) {
    final session = HubSession(
        baseUrl: 'https://preview.invalid',
        token: 'demo-only',
        mode: admin ? HubAccessMode.admin : HubAccessMode.lite);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: courtyardTheme(Brightness.light),
      home: Scaffold(
          body: SafeArea(
              child: Column(children: [
        Material(
            color: const Color(0xffeaf2ff),
            child: Padding(
                padding: const EdgeInsets.all(8),
                child: Wrap(
                    spacing: 12,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      const Text('最新源码 UI 预览 · 演示数据 · 禁止实际操作'),
                      TextButton(
                          onPressed: () => setState(() => admin = !admin),
                          child: Text(admin ? '管理端 → 切换用户端' : '用户端 → 切换管理端')),
                      TextButton(
                          onPressed: () => setState(() => phone = !phone),
                          child: Text(phone ? '手机宽度 → 展开桌面' : '桌面宽度 → 切换手机')),
                    ]))),
        Expanded(
            child: Center(
                child: SizedBox(
                    width: phone ? 430 : double.infinity,
                    child: admin
                        ? HubShell(
                            key: const ValueKey('admin'),
                            session: session,
                            store: SessionStore(),
                            notificationService: NotificationService(),
                            onDisconnect: () async {})
                        : LiteShell(
                            key: const ValueKey('lite'),
                            session: session,
                            store: SessionStore(),
                            notificationService: NotificationService(),
                            onDisconnect: () async {})))),
      ]))),
    );
  }
}
