import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:astr_auto_anima_hub_client/app.dart';
import 'package:astr_auto_anima_hub_client/core/session_store.dart';
import 'package:astr_auto_anima_hub_client/core/connection_profile.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/core/notification_service.dart';
import 'package:astr_auto_anima_hub_client/core/compshare_api.dart';
import 'package:astr_auto_anima_hub_client/features/connection/instance_connections_page.dart';

const a = HubSession(baseUrl: 'https://a.example', token: 'secret-a');
const b = HubSession(baseUrl: 'https://b.example', token: 'secret-b');
const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

void main() {
  late Map<String, String> secrets;
  bool failSecretWrite = false;
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    secrets = {};
    failSecretWrite = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      final key = args['key'] as String?;
      switch (call.method) {
        case 'read':
          return secrets[key];
        case 'readAll':
          return secrets;
        case 'write':
          if (failSecretWrite) throw PlatformException(code: 'denied');
          secrets[key!] = args['value'] as String;
          return null;
        case 'delete':
          secrets.remove(key);
          return null;
      }
      throw MissingPluginException(call.method);
    });
  });
  tearDown(() => TestDefaultBinaryMessengerBinding
      .instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, null));

  test('profile credentials stay secure and immutable across endpoint edits',
      () async {
    final store = SessionStore();
    final original = await store.profiles('manager', migrate: a);
    final edited = await store.saveProfile('manager',
        id: original.single.id, label: 'B', session: b);
    expect(edited.id, isNot(original.single.id));
    expect((await store.profileSession('manager', edited)).token, 'secret-b');
    expect((await store.profileSession('manager', original.single)).token,
        isEmpty);
    final prefs = await SharedPreferences.getInstance();
    expect(
        prefs.getString('hub_profiles_v1_manager'), isNot(contains('secret')));
    await store.removeProfile('manager', edited.id);
    expect(await store.profiles('manager', migrate: a), isEmpty);
    expect(secrets, isEmpty);
  });
  test('secure persistence failure leaves old endpoint and credential paired',
      () async {
    final store = SessionStore();
    final original = (await store.profiles('manager', migrate: a)).single;
    failSecretWrite = true;
    await expectLater(
        store.saveProfile('manager', id: original.id, label: 'B', session: b),
        throwsA(isA<PlatformException>()));
    final current = (await store.profiles('manager')).single;
    expect(current.baseUrl, a.baseUrl);
    expect((await store.profileSession('manager', current)).token, a.token);
  });
  test('new active slots use immutable credentials; modes remain isolated',
      () async {
    final store = SessionStore();
    await store.save(a);
    failSecretWrite = true;
    await expectLater(store.save(b), throwsA(isA<PlatformException>()));
    expect((await store.load()).baseUrl, a.baseUrl);
    expect((await store.load()).token, a.token);
    failSecretWrite = false;
    await store.saveForWorkspace(
        WindowsWorkspaceMode.onlineService,
        const HubSession(
            baseUrl: 'https://service.example',
            token: 'user-secret',
            mode: HubAccessMode.lite));
    expect((await store.load()).token, a.token);
    expect((await store.loadForWorkspace(WindowsWorkspaceMode.local)).token,
        isEmpty);
  });
  test('metadata failure after secret write cannot swap token on old endpoint',
      () async {
    final normal = SessionStore();
    final old = (await normal.profiles('manager', migrate: a)).single;
    await normal.save(a);
    final failing =
        SessionStore(persistConnectionMetadata: (key, value) async => false);
    await expectLater(
        failing.saveProfile('manager', id: old.id, label: 'B', session: b),
        throwsStateError);
    await expectLater(failing.save(b), throwsStateError);
    expect((await normal.profiles('manager')).single.baseUrl, a.baseUrl);
    expect((await normal.profileSession('manager', old)).token, a.token);
    expect((await normal.load()).baseUrl, a.baseUrl);
    expect((await normal.load()).token, a.token);
  });
  test('cloud credentials never migrate implicitly into another Hub identity',
      () async {
    final legacy = CompShareConfigStore();
    await legacy.save(const CompShareConfig(
        publicKey: 'pub',
        privateKey: 'priv',
        region: 'r',
        zone: 'z',
        uhostId: 'old'));
    final first = CompShareConfigStore(scope: '${a.baseUrl}|${a.token}');
    final second = CompShareConfigStore(scope: '${b.baseUrl}|${b.token}');
    expect((await first.load()).isConfigured, false);
    await first.save(const CompShareConfig(
        publicKey: 'pa',
        privateKey: 'sa',
        region: 'r',
        zone: 'z',
        uhostId: 'instance-a'));
    expect((await second.load()).isConfigured, false);
    expect((await first.load()).uhostId, 'instance-a');
    expect((await legacy.load()).uhostId, 'old');
  });
  test('invalid/local remote endpoints are rejected before credentials sent',
      () {
    expect(
        () => validateProfileEndpoint(
            'https://user:secret@host', HubDeploymentMode.remote),
        throwsFormatException);
    expect(
        () => validateProfileEndpoint(
            'http://example.com', HubDeploymentMode.local),
        throwsFormatException);
    expect(
        validateProfileEndpoint(
            'http://127.0.0.1:6278/', HubDeploymentMode.local),
        'http://127.0.0.1:6278');
  });
  test('late responses and future requests from disposed API are rejected',
      () async {
    final response = Completer<http.Response>();
    var requests = 0;
    final api = HubApi(
        baseUrl: a.baseUrl,
        token: a.token,
        client: MockClient((request) {
          requests++;
          expect(request.headers['Authorization'], 'Bearer secret-a');
          return response.future;
        }));
    final future = api.capabilities();
    final assertion = expectLater(future, throwsA(isA<HubApiException>()));
    await Future<void>.delayed(Duration.zero);
    api.dispose();
    response.complete(http.Response('{}', 200));
    await assertion;
    await expectLater(api.capabilities(), throwsA(isA<HubApiException>()));
    expect(requests, 1);
  });
  test(
      'network image cache is isolated even for same server and different account',
      () {
    final first = HubApi(baseUrl: a.baseUrl, token: 'admin-secret');
    final second = HubApi(baseUrl: a.baseUrl, token: 'lite-secret');
    final one =
        first.resolveImageUrl('/api/v1/lite/jobs/job/images/img?width=180');
    final two =
        second.resolveImageUrl('/api/v1/lite/jobs/job/images/img?width=180');
    expect(one, isNot(two));
    expect(one, isNot(contains('secret')));
    expect(Uri.parse(one).queryParameters['width'], '180');
    expect(() => first.resolveImageUrl('https://outside.example/img'),
        throwsA(isA<HubApiException>()));
    first.dispose();
    second.dispose();
  });
  test(
      'byte download rejects external URL before HTTP and preserves local save bytes',
      () async {
    var requests = 0;
    final api = HubApi(
        baseUrl: a.baseUrl,
        token: a.token,
        client: MockClient((request) async {
          requests++;
          expect(request.url.host, 'a.example');
          expect(request.headers['Authorization'], 'Bearer secret-a');
          return http.Response.bytes([1, 2, 3], 200);
        }));
    await expectLater(
        api.downloadJobImage(RemoteJobImage.fromJson(
            {'id': 'bad', 'download_url': 'https://outside.example/steal'})),
        throwsA(isA<HubApiException>()));
    expect(requests, 0);
    final bytes = await api.downloadJobImage(RemoteJobImage.fromJson(
        {'id': 'ok', 'download_url': '/api/v1/lite/jobs/job/images/ok'}));
    expect(bytes, [1, 2, 3]);
    expect(requests, 1);
    api.dispose();
  });

  testWidgets('failed activation keeps original; no polling inactive profiles',
      (tester) async {
    final store = SessionStore();
    final target = await store.saveProfile('manager', label: 'B', session: b);
    var active = a;
    var checks = 0;
    await tester.pumpWidget(MaterialApp(
        home: InstanceConnectionsPage(
            store: store,
            current: a,
            preflight: (session) async {
              checks++;
              expect(session.token, b.token);
              throw const HubApiException('forbidden', statusCode: 403);
            },
            onActivate: (session) async {
              active = session;
            })));
    await tester.pumpAndSettle();
    expect(checks, 0);
    await tester.tap(find.byKey(ValueKey('profile.${target.id}')));
    await tester.pumpAndSettle();
    expect(active, a);
    expect(checks, 1);
    expect(find.text('forbidden'), findsOneWidget);
    await tester.pump(const Duration(minutes: 2));
    expect(checks, 1);
  });

  testWidgets('successful activation receives only chosen profile token',
      (tester) async {
    final store = SessionStore();
    final target = await store.saveProfile('manager', label: 'B', session: b);
    HubSession? active;
    await tester.pumpWidget(MaterialApp(
        home: InstanceConnectionsPage(
            store: store,
            current: a,
            preflight: (session) async {
              expect(session.token, b.token);
            },
            onActivate: (session) async {
              active = session;
            })));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(ValueKey('profile.${target.id}')));
    await tester.pumpAndSettle();
    expect(active?.baseUrl, b.baseUrl);
    expect(active?.token, b.token);
  });
  testWidgets('cancel plaintext HTTP warning sends no token or preflight',
      (tester) async {
    final store = SessionStore();
    final target = await store.saveProfile('manager',
        label: 'LAN',
        session: const HubSession(
            baseUrl: 'http://192.168.1.10:6278', token: 'lan-secret'));
    var checks = 0, switches = 0;
    await tester.pumpWidget(MaterialApp(
        home: InstanceConnectionsPage(
            store: store,
            current: a,
            preflight: (session) async {
              checks++;
            },
            onActivate: (session) async {
              switches++;
            })));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(ValueKey('profile.${target.id}')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('确认明文 HTTP 连接风险'), findsOneWidget);
    expect(checks, 0);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(checks, 0);
    expect(switches, 0);
  });

  testWidgets('root activation destroys old shell navigator and HTTP lifetime',
      (tester) async {
    final apis = <HubApi>[];
    final received = <String>[];
    HubApi factory(HubSession session) {
      final api = HubApi(
          baseUrl: session.baseUrl,
          token: session.token,
          client: MockClient((request) async {
            received
                .add('${request.url.host}:${request.headers['Authorization']}');
            return http.Response(
                jsonEncode({
                  'execution_mode': 'remote',
                  'features': {},
                  'items': [],
                  'characters': [],
                  'styles': [],
                  'targets': [],
                  'extensions': [],
                  'available': false,
                  'groups': [],
                  'config': {
                    'grouping': 'original',
                    'strip_metadata': false,
                    'scheduled': false,
                    'retention_days': 7,
                    'cleanup_hour': 4
                  },
                  'areas': [],
                  'revision': 'r',
                  'page': 1,
                  'pages': 1,
                  'page_size': 30,
                  'total': 0
                }),
                200);
          }));
      apis.add(api);
      return api;
    }

    await tester.pumpWidget(AstrAutoAnimaApp(
        store: SessionStore(),
        notificationService: NotificationService(),
        initialSession: a,
        apiFactory: factory));
    await tester.pump(const Duration(milliseconds: 100));
    final oldShell = tester.widget<HubShell>(find.byType(HubShell));
    final oldState = tester.state(find.byType(HubShell));
    final nav = Navigator.of(tester.element(find.byType(HubShell)));
    nav.push(MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('OLD SERVER DIALOG'))));
    await tester.pumpAndSettle();
    await oldShell.onActivateProfile!(b);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('OLD SERVER DIALOG'), findsNothing);
    expect(oldState.mounted, false);
    expect(apis.first.isDisposed, true);
    expect(tester.widget<HubShell>(find.byType(HubShell)).session.baseUrl,
        b.baseUrl);
    expect(
        received
            .where((line) => line.startsWith('b.example:'))
            .every((line) => line.endsWith('secret-b')),
        true);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  });
}
