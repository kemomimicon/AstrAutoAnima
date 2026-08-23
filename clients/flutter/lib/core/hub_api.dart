import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'models.dart';

class HubApiException implements Exception {
  const HubApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class HubApi {
  HubApi({required String baseUrl, required this.token})
      : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), '');

  final String baseUrl;
  final String token;

  Map<String, String> get authorizationHeaders => Map.unmodifiable(_headers);

  String resolveUrl(String path) {
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    return '$baseUrl${path.startsWith('/') ? path : '/$path'}';
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        if (token.isNotEmpty) 'Authorization': 'Bearer $token',
      };

  Future<Map<String, dynamic>> _get(
    String path, {
    Map<String, String>? query,
    bool authenticated = true,
  }) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    late final http.Response response;
    try {
      response = await http
          .get(uri, headers: authenticated ? _headers : const {})
          .timeout(const Duration(seconds: 8));
    } on Exception catch (error) {
      throw HubApiException('无法连接工作站：$error');
    }
    dynamic payload;
    try {
      payload = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw HubApiException(
        '工作站返回了无效数据（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = payload is Map ? payload['detail'] : null;
      throw HubApiException(
        detail?.toString() ?? '请求失败（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    if (payload is! Map) {
      throw const HubApiException('工作站返回的数据结构不正确');
    }
    return Map<String, dynamic>.from(payload);
  }

  Future<Map<String, dynamic>> _write(
    String method,
    String path, {
    required String revision,
    Map<String, dynamic>? body,
  }) async {
    final request = http.Request(method, Uri.parse('$baseUrl$path'));
    request.headers.addAll({
      ..._headers,
      'Content-Type': 'application/json; charset=utf-8',
      'If-Match': revision,
      'X-Device-Name': 'AstrAutoAnima Flutter',
    });
    if (body != null) request.body = jsonEncode(body);
    late final http.Response response;
    try {
      response = await http.Response.fromStream(
        await request.send().timeout(const Duration(seconds: 30)),
      );
    } on Exception catch (error) {
      throw HubApiException('无法连接工作站：$error');
    }
    dynamic payload;
    try {
      payload = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw HubApiException(
        '工作站返回了无效数据（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = payload is Map ? payload['detail'] : null;
      final message =
          detail is Map ? detail['message']?.toString() : detail?.toString();
      throw HubApiException(
        message ?? '请求失败（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    return Map<String, dynamic>.from(payload as Map);
  }

  Future<Map<String, dynamic>> _post(
    String path, {
    required Map<String, dynamic> body,
  }) async {
    late final http.Response response;
    try {
      response = await http
          .post(
            Uri.parse('$baseUrl$path'),
            headers: {
              ..._headers,
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 120));
    } on Exception catch (error) {
      throw HubApiException('无法连接工作站：$error');
    }
    dynamic payload;
    try {
      payload = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw HubApiException(
        '工作站返回了无效数据（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = payload is Map ? payload['detail'] : null;
      throw HubApiException(
        detail?.toString() ?? '请求失败（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    return Map<String, dynamic>.from(payload as Map);
  }

  Future<void> checkHealth() async {
    await _get('/api/v1/health', authenticated: false);
  }

  Future<WorkstationStatus> getWorkstationStatus() async {
    return WorkstationStatus.fromJson(
      await _get('/api/v1/workstation/status'),
    );
  }

  Future<PromptPageResult> getPrompts({
    String source = '',
    String safety = '',
    String query = '',
    bool? enabled,
    int page = 1,
    int pageSize = 30,
  }) async {
    return PromptPageResult.fromJson(
      await _get(
        '/api/v1/prompts',
        query: {
          if (source.isNotEmpty) 'source': source,
          if (safety.isNotEmpty) 'safety': safety,
          if (query.isNotEmpty) 'query': query,
          if (enabled != null) 'enabled': '$enabled',
          'page': '$page',
          'page_size': '$pageSize',
        },
      ),
    );
  }

  Future<PresetListResult> getPresets() async {
    return PresetListResult.fromJson(await _get('/api/v1/presets'));
  }

  Future<PresetListResult> getLitePresets() async {
    return PresetListResult.fromJson(await _get('/api/v1/lite/presets'));
  }

  Future<PromptPageResult> getLitePrompts({
    String source = '',
    String safety = '',
    String query = '',
    int page = 1,
    int pageSize = 30,
  }) async {
    return PromptPageResult.fromJson(
      await _get(
        '/api/v1/lite/prompts',
        query: {
          if (source.isNotEmpty) 'source': source,
          if (safety.isNotEmpty) 'safety': safety,
          if (query.isNotEmpty) 'query': query,
          'page': '$page',
          'page_size': '$pageSize',
        },
      ),
    );
  }

  Future<DeliveryTargetListResult> getDeliveryTargets() async {
    return DeliveryTargetListResult.fromJson(
      await _get('/api/v1/lite/delivery-targets'),
    );
  }

  Future<RemoteJobResult> createRemoteJob(
    Map<String, dynamic> value,
  ) async {
    return RemoteJobResult.fromJson(
      await _post('/api/v1/lite/jobs', body: value),
    );
  }

  Future<RemoteJobResult> getRemoteJob(String id) async {
    return RemoteJobResult.fromJson(
      await _get('/api/v1/lite/jobs/${Uri.encodeComponent(id)}'),
    );
  }

  Future<RemoteJobPageResult> getRemoteJobs({
    String kind = '',
    String status = '',
    int page = 1,
    int pageSize = 30,
  }) async {
    return RemoteJobPageResult.fromJson(
      await _get(
        '/api/v1/lite/jobs',
        query: {
          if (kind.isNotEmpty) 'kind': kind,
          if (status.isNotEmpty) 'status': status,
          'page': '$page',
          'page_size': '$pageSize',
        },
      ),
    );
  }

  Future<Uint8List> downloadJobImage(RemoteJobImage image) async {
    if (!image.downloadUrl.startsWith('/api/v1/lite/jobs/')) {
      throw const HubApiException('工作站返回了不安全的图片下载地址');
    }
    late final http.Response response;
    try {
      response = await http
          .get(Uri.parse(resolveUrl(image.downloadUrl)), headers: _headers)
          .timeout(const Duration(minutes: 3));
    } on Exception catch (error) {
      throw HubApiException('图片下载失败：$error');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HubApiException(
        '图片下载失败（HTTP ${response.statusCode}）',
        statusCode: response.statusCode,
      );
    }
    return response.bodyBytes;
  }

  Future<MutationResult> createPrompt({
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return MutationResult.fromJson(
      await _write('POST', '/api/v1/prompts', revision: revision, body: value),
    );
  }

  Future<MutationResult> updatePrompt({
    required String id,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'PATCH',
        '/api/v1/prompts/${Uri.encodeComponent(id)}',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<MutationResult> deletePrompt({
    required String id,
    required String revision,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/prompts/${Uri.encodeComponent(id)}',
        revision: revision,
      ),
    );
  }

  Future<MutationResult> importPrompts({
    required String revision,
    required List<Map<String, dynamic>> prompts,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'POST',
        '/api/v1/prompts/import',
        revision: revision,
        body: {'prompts': prompts},
      ),
    );
  }

  Future<String> exportPrompts({
    String source = '',
    String safety = '',
    String query = '',
  }) async {
    final payload = await _get(
      '/api/v1/prompts/export',
      query: {
        if (source.isNotEmpty) 'source': source,
        if (safety.isNotEmpty) 'safety': safety,
        if (query.isNotEmpty) 'query': query,
      },
    );
    return const JsonEncoder.withIndent('  ').convert(payload);
  }

  Future<MutationResult> createPreset({
    required String kind,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'POST',
        '/api/v1/presets/$kind',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<MutationResult> updatePreset({
    required String kind,
    required String originalName,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'PUT',
        '/api/v1/presets/$kind/${Uri.encodeComponent(originalName)}',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<MutationResult> deletePreset({
    required String kind,
    required String name,
    required String revision,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/presets/$kind/${Uri.encodeComponent(name)}',
        revision: revision,
      ),
    );
  }
}
