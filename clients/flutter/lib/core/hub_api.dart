import 'dart:convert';
import 'package:flutter/foundation.dart';

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
  final ValueNotifier<int> catalogChanges = ValueNotifier(0);
  HubApi({required String baseUrl, required this.token})
      : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), '');

  final String baseUrl;
  final String token;
  Future<Map<String, dynamic>> imageStorage() => _get('/api/v1/admin/storage');
  Future<Map<String, dynamic>> storageAction(
          String action, Map<String, dynamic> value) =>
      _post('/api/v1/admin/storage/$action', body: value);
  Future<Map<String, dynamic>> gallery() => _get('/api/v1/gallery');
  Future<Map<String, dynamic>> saveGallery(Map<String, dynamic> value) =>
      _post('/api/v1/admin/gallery/config', body: value);
  Future<Map<String, dynamic>> generateGallery(
          String revision, List<String> styles,
          {int? slotIndex}) =>
      _post('/api/v1/admin/gallery/generate', body: {
        'revision': revision,
        'styles': styles,
        if (slotIndex != null) 'slot_index': slotIndex
      });
  Future<Uint8List> galleryImage(String id) async {
    final response = await http
        .get(Uri.parse('$baseUrl/api/v1/gallery/images/$id'), headers: _headers)
        .timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) throw const HubApiException('预览不可用或审核未通过');
    return response.bodyBytes;
  }

  Future<Map<String, dynamic>> favoritePrompt(String id) =>
      _post('/api/v1/lite/prompt-favorites/${Uri.encodeComponent(id)}',
          body: {});
  Future<Map<String, dynamic>> unfavoritePrompt(String id) => _write(
      'DELETE', '/api/v1/lite/prompt-favorites/${Uri.encodeComponent(id)}',
      revision: '*');
  Future<Map<String, dynamic>> reportImage(String job, String image) =>
      _post('/api/v1/lite/jobs/$job/images/$image/report', body: {});
  Future<Map<String, dynamic>> promptReports() =>
      _get('/api/v1/admin/prompt-reports');
  Future<Map<String, dynamic>> resolvePromptReport(String id, String action) =>
      _post('/api/v1/admin/prompt-reports/$id/$action?confirmed=true',
          body: {});
  Future<Map<String, dynamic>> resumeCivitai(String id) =>
      _post('/api/v1/admin/civitai/downloads/$id/resume', body: {});
  Future<Map<String, dynamic>> napcatAccounts(String code) =>
      _post('/api/v1/admin/napcat/accounts', body: {'totp_code': code});
  Future<Map<String, dynamic>> napcatStatus() =>
      _get('/api/v1/admin/napcat/status');
  Future<Map<String, dynamic>> napcatQr(String code) =>
      _post('/api/v1/admin/napcat/qrcode', body: {'totp_code': code});
  Future<Map<String, dynamic>> serviceRecovery() =>
      _get('/api/v1/admin/services/recovery');
  Future<Map<String, dynamic>> restartServices() =>
      _post('/api/v1/admin/services/restart?confirmed=true', body: {});
  Future<Map<String, dynamic>> napcatLogin(String uin, String code) =>
      _post('/api/v1/admin/napcat/login',
          body: {'uin': uin, 'totp_code': code});

  Future<Map<String, dynamic>> previewCivitai(int versionId) =>
      _get('/api/v1/admin/civitai/versions/$versionId');
  Future<Map<String, dynamic>> civitaiVersions(int modelId) =>
      _get('/api/v1/admin/civitai/models/$modelId');
  Future<Map<String, dynamic>> civitaiDownloads() =>
      _get('/api/v1/admin/civitai/downloads');
  Future<Map<String, dynamic>> downloadCivitai(
          int versionId, int fileId, String sha256,
          {String directory = 'anima_lora',
          bool createDirectory = false,
          List<String>? words}) =>
      _post('/api/v1/admin/civitai/downloads', body: {
        'version_id': versionId,
        'file_id': fileId,
        'expected_sha256': sha256,
        'subdirectory': directory,
        'create_directory': createDirectory,
        if (words != null) 'trained_words': words,
      });
  Future<Map<String, dynamic>> cancelCivitai(String id) =>
      _post('/api/v1/admin/civitai/downloads/$id/cancel', body: {});

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
    if (path.contains('/presets') ||
        path.contains('/personal-styles') ||
        path.contains('/character-favorites')) {
      catalogChanges.value++;
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

  Future<WorkstationMetrics> getWorkstationMetrics() async {
    return WorkstationMetrics.fromJson(
      await _get('/api/v1/workstation/metrics'),
    );
  }

  Future<CharacterDictionaryResult> searchCharacters({
    String query = '',
    int limit = 20,
    int page = 1,
  }) async {
    return CharacterDictionaryResult.fromJson(
      await _get(
        '/api/v1/lite/characters',
        query: {
          if (query.trim().isNotEmpty) 'query': query.trim(),
          'limit': '$limit',
          'page': '$page',
        },
      ),
    );
  }

  Future<CharacterDictionaryResult> getAdminCharacters({
    String query = '',
    int page = 1,
    int pageSize = 50,
    bool includeDisabled = true,
  }) async {
    return CharacterDictionaryResult.fromJson(
      await _get(
        '/api/v1/admin/characters',
        query: {
          if (query.trim().isNotEmpty) 'query': query.trim(),
          'page': '$page',
          'page_size': '$pageSize',
          'include_disabled': '$includeDisabled',
        },
      ),
    );
  }

  Future<MutationResult> updateCharacter({
    required String tag,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'PATCH',
        '/api/v1/admin/characters/${Uri.encodeComponent(tag)}',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<MutationResult> deleteCharacter({
    required String tag,
    required String revision,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/admin/characters/${Uri.encodeComponent(tag)}',
        revision: revision,
      ),
    );
  }

  Future<CharacterFavoriteListResult> getCharacterFavorites() async {
    return CharacterFavoriteListResult.fromJson(
      await _get('/api/v1/lite/character-favorites'),
    );
  }

  Future<CharacterFavoriteListResult> saveCharacterFavorite({
    required String tag,
    required String revision,
    required String name,
    required String mode,
  }) async {
    return CharacterFavoriteListResult.fromJson(
      await _write(
        'PUT',
        '/api/v1/lite/character-favorites/${Uri.encodeComponent(tag)}',
        revision: revision,
        body: {'name': name, 'mode': mode},
      ),
    );
  }

  Future<CharacterFavoriteListResult> deleteCharacterFavorite({
    required String tag,
    required String revision,
  }) async {
    return CharacterFavoriteListResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/lite/character-favorites/${Uri.encodeComponent(tag)}',
        revision: revision,
      ),
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

  Future<LiteUserListResult> getLiteUsers() async {
    return LiteUserListResult.fromJson(
      await _get('/api/v1/admin/lite-users'),
    );
  }

  Future<LiteUserIssueResult> createLiteUser({
    required String revision,
    required String qq,
    required String label,
    required bool allowGroup,
  }) async {
    return LiteUserIssueResult.fromJson(
      await _write(
        'POST',
        '/api/v1/admin/lite-users',
        revision: revision,
        body: {
          'qq': qq,
          'label': label,
          'allow_group': allowGroup,
        },
      ),
    );
  }

  Future<MutationResult> updateLiteUser({
    required String qq,
    required String revision,
    String? label,
    bool? allowGroup,
    bool? enabled,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'PATCH',
        '/api/v1/admin/lite-users/${Uri.encodeComponent(qq)}',
        revision: revision,
        body: {
          if (label != null) 'label': label,
          if (allowGroup != null) 'allow_group': allowGroup,
          if (enabled != null) 'enabled': enabled,
        },
      ),
    );
  }

  Future<LiteUserIssueResult> rotateLiteUserToken({
    required String qq,
    required String revision,
  }) async {
    return LiteUserIssueResult.fromJson(
      await _write(
        'POST',
        '/api/v1/admin/lite-users/${Uri.encodeComponent(qq)}/rotate',
        revision: revision,
      ),
    );
  }

  Future<MutationResult> deleteLiteUser({
    required String qq,
    required String revision,
  }) async {
    return MutationResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/admin/lite-users/${Uri.encodeComponent(qq)}',
        revision: revision,
      ),
    );
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

  Future<RemoteJobResult> remakeImage(String jobId, String imageId,
          {Map<String, dynamic> options = const {}}) async =>
      RemoteJobResult.fromJson(await _post(
          '/api/v1/lite/jobs/$jobId/images/$imageId/remake',
          body: options));

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

  Future<PromptLikeResult> likeJobPrompt({
    required String jobId,
    required String promptId,
  }) async {
    return PromptLikeResult.fromJson(
      await _post(
        '/api/v1/lite/jobs/${Uri.encodeComponent(jobId)}/likes/${Uri.encodeComponent(promptId)}',
        body: const {},
      ),
    );
  }

  Future<LoraCatalogResult> getLoraCatalog() async {
    return LoraCatalogResult.fromJson(await _get('/api/v1/admin/loras'));
  }

  Future<Map<String, dynamic>> getVisualPresets() =>
      _get('/api/v1/visual-presets');

  Future<LoraCatalogResult> getStyleLoras() async {
    return LoraCatalogResult.fromJson(await _get('/api/v1/lite/style-loras'));
  }

  Future<MutationResult> updateLora({
    required String path,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    final encodedPath = path.split('/').map(Uri.encodeComponent).join('/');
    return MutationResult.fromJson(
      await _write(
        'PATCH',
        '/api/v1/admin/loras/$encodedPath',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<PersonalStyleListResult> getPersonalStyles() async {
    return PersonalStyleListResult.fromJson(
      await _get('/api/v1/lite/personal-styles'),
    );
  }

  Future<Map<String, dynamic>> getTaskSuites() =>
      _get('/api/v1/lite/task-suites');
  Future<Map<String, dynamic>> cancelTaskSuite(String id) =>
      _write('POST', '/api/v1/lite/jobs/$id/cancel-suite', revision: '');
  Future<Map<String, dynamic>> saveTaskSuite(
          Map<String, dynamic> value, String revision, {String? id}) =>
      _write(id == null ? 'POST' : 'PUT',
          '/api/v1/lite/task-suites${id == null ? '' : '/$id'}',
          revision: revision, body: value);
  Future<Map<String, dynamic>> deleteTaskSuite(String id, String revision) =>
      _write('DELETE', '/api/v1/lite/task-suites/$id', revision: revision);

  Future<PersonalStyleListResult> savePersonalStyle({
    required int slot,
    required String revision,
    required Map<String, dynamic> value,
  }) async {
    return PersonalStyleListResult.fromJson(
      await _write(
        'PUT',
        '/api/v1/lite/personal-styles/$slot',
        revision: revision,
        body: value,
      ),
    );
  }

  Future<PersonalStyleListResult> deletePersonalStyle({
    required int slot,
    required String revision,
  }) async {
    return PersonalStyleListResult.fromJson(
      await _write(
        'DELETE',
        '/api/v1/lite/personal-styles/$slot',
        revision: revision,
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
