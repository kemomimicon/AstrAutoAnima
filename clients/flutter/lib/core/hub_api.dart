import 'dart:convert';
import 'dart:math';
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
  final Map<String, String> _presetSubmissionIds = {};

  Future<MutationResult> submitPreset(
      {required String action,
      required String kind,
      Map<String, dynamic>? value,
      PresetSummary? original}) async {
    final body = <String, dynamic>{
      'action': action,
      'kind': kind,
      'original_name': original?.name ?? '',
      'value': value,
      'expected': original == null
          ? null
          : {
              'name': original.name,
              'kind': original.kind,
              'prompt': original.prompt,
              'match': original.match,
              'loras': original.loras,
              'text_only': original.textOnly,
              'variants': original.variants,
            },
    };
    final key = jsonEncode(body);
    final id = _presetSubmissionIds.putIfAbsent(
        key,
        () => List.generate(
            16,
            (_) => Random.secure()
                .nextInt(256)
                .toRadixString(16)
                .padLeft(2, '0')).join());
    body['request_id'] = id;
    var state = await _post('/api/v1/admin/preset-submissions', body: body);
    for (var attempt = 0; attempt < 30; attempt++) {
      if (state['status'] == 'succeeded') {
        catalogChanges.value++;
        return MutationResult.fromJson(
            Map<String, dynamic>.from(state['result'] as Map));
      }
      if (state['status'] == 'conflict' || state['status'] == 'failed') {
        throw HubApiException('${state['message']}（提交 $id）', statusCode: 409);
      }
      await Future<void>.delayed(const Duration(seconds: 1));
      state = await _get('/api/v1/admin/preset-submissions/$id');
    }
    throw HubApiException('提交已保留在服务器队列（$id），尚未确认完成；不要重写内容，再点保存将查询同一提交。');
  }

  Future<Map<String, dynamic>> openStudioSession() =>
      _post('/api/v1/admin/extensions/anima-lora-studio/session', body: {});
  Future<Map<String, dynamic>> closeStudioSession(String id) => _post(
      '/api/v1/admin/extensions/anima-lora-studio/sessions/${Uri.encodeComponent(id)}/close',
      body: {});
  Future<Map<String, dynamic>> extensions() => _get('/api/v1/admin/extensions');
  Future<Map<String, dynamic>> extensionStatus(String id) =>
      _get('/api/v1/admin/extensions/${Uri.encodeComponent(id)}/status');
  Future<Map<String, dynamic>> autoSleep() => _get('/api/v1/admin/auto-sleep');
  Future<Map<String, dynamic>> setIdleCredentials(
          Map<String, dynamic> values) =>
      _post('/api/v1/admin/auto-sleep/credentials', body: values);
  Future<Map<String, dynamic>> setAutoSleep(bool enabled, String instanceId) =>
      _post('/api/v1/admin/auto-sleep', body: {
        'enabled': enabled,
        'confirmed': true,
        'instance_id': instanceId,
      });
  final ValueNotifier<int> catalogChanges = ValueNotifier(0);
  Map<String, dynamic>? _promptCatalog;
  String? _promptCatalogEtag;
  Future<Map<String, dynamic>>? _promptCatalogPending;

  /// Per connection/token cache. Revalidate on demand; never run a polling timer.
  Future<Map<String, dynamic>> getPromptCatalog() =>
      _promptCatalogPending ??= _readPromptCatalog().whenComplete(() {
        _promptCatalogPending = null;
      });

  Future<Map<String, dynamic>> _readPromptCatalog() async {
    _requireActive();
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/lite/prompt-catalog'),
      headers: {
        ..._headers,
        if (_promptCatalogEtag != null) 'If-None-Match': _promptCatalogEtag!
      },
    ).timeout(const Duration(seconds: 12));
    _requireActive();
    if (response.statusCode == 304 && _promptCatalog != null) {
      return Map<String, dynamic>.from(_promptCatalog!);
    }
    if (response.statusCode == 404) {
      // Old servers can still use their default source. Do not invent private libraries.
      return {
        'legacy': true,
        'sources': <dynamic>[],
        'editable_sources': <dynamic>[]
      };
    }
    if (response.statusCode != 200) {
      throw HubApiException('读取服务器词库配置失败（${response.statusCode}）',
          statusCode: response.statusCode);
    }
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    if (data is! Map ||
        data['schema_version'] != 1 ||
        data['sources'] is! List) {
      throw const HubApiException('词库协议不兼容，请更新客户端；未采用其他实例的配置。');
    }
    _promptCatalog = Map<String, dynamic>.from(data);
    _promptCatalogEtag = response.headers['etag'];
    return Map<String, dynamic>.from(_promptCatalog!);
  }

  Future<Map<String, dynamic>> savePromptCatalog({
    required String revision,
    required List<Map<String, dynamic>> sources,
  }) async {
    final result = await _write('PUT', '/api/v1/admin/prompt-catalog',
        revision: revision, body: {'sources': sources});
    catalogChanges.value++;
    return result;
  }

  HubApi({required String baseUrl, required this.token, http.Client? client})
      : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  final String baseUrl;
  final String token;
  final http.Client _client;
  final String _imageCacheScope = List.generate(16,
          (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'))
      .join();
  bool _disposed = false;
  bool get isDisposed => _disposed;
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _client.close();
    // Existing child widgets remove listeners during their own disposal.
    // Do not notify stale catalog consumers when an old request finishes.
  }

  void _requireActive() {
    if (_disposed) throw const HubApiException('连接已切换，已停止旧实例请求。');
  }

  Future<Map<String, dynamic>> capabilities() => _get('/api/v1/capabilities');
  Future<Map<String, dynamic>> chatGroups() =>
      _get('/api/v1/admin/chat-groups');
  Future<Map<String, dynamic>> setChatGroupsEnabled(bool enabled) =>
      _write('PUT', '/api/v1/admin/chat-groups/config',
          revision: '', body: {'enabled': enabled});
  Future<
      Map<String,
          dynamic>> saveChatGroup(Map<String, dynamic> value) => _write('PUT',
      '/api/v1/admin/chat-groups/groups/${Uri.encodeComponent(value['key'] as String)}',
      revision: '', body: value);
  Future<Map<String, dynamic>> saveChatGroupUser(Map<String, dynamic> value) =>
      _write('PUT', '/api/v1/admin/chat-groups/users',
          revision: '', body: value);
  Future<
      Map<String,
          dynamic>> deleteChatGroupUser(String key, String user) => _write(
      'DELETE',
      '/api/v1/admin/chat-groups/users?group_key=${Uri.encodeComponent(key)}&qq=${Uri.encodeComponent(user)}&confirmed=true',
      revision: '');
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
    _requireActive();
    final response = await _client
        .get(Uri.parse('$baseUrl/api/v1/gallery/images/$id'), headers: _headers)
        .timeout(const Duration(seconds: 30));
    _requireActive();
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

  String resolveImageUrl(String path) {
    _requireActive();
    if (!path.startsWith('/api/v1/')) {
      throw const HubApiException('拒绝向外部图片地址发送当前连接的令牌');
    }
    final uri = Uri.parse(resolveUrl(path));
    // NetworkImage equality omits Authorization headers. Partition its cache
    // by a random, non-secret session ID, even when the Hub URL stays the same.
    return uri.replace(queryParameters: {
      ...uri.queryParameters,
      '_client_image_scope': _imageCacheScope,
    }).toString();
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        if (token.isNotEmpty) 'Authorization': 'Bearer $token',
      };

  Future<Map<String, dynamic>> _get(
    String path, {
    Map<String, String>? query,
    bool authenticated = true,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    _requireActive();
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    late final http.Response response;
    try {
      response = await _client
          .get(uri, headers: authenticated ? _headers : const {})
          .timeout(timeout);
    } on Exception catch (error) {
      throw HubApiException('无法连接工作站：$error');
    }
    _requireActive();
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
    _requireActive();
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
        await _client.send(request).timeout(const Duration(seconds: 30)),
      );
    } on Exception catch (error) {
      throw HubApiException('无法连接工作站：$error');
    }
    _requireActive();
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
        path.contains('/character-favorites') ||
        path == '/api/v1/prompts/groups') {
      catalogChanges.value++;
    }
    return Map<String, dynamic>.from(payload as Map);
  }

  Future<Map<String, dynamic>> _post(
    String path, {
    required Map<String, dynamic> body,
  }) async {
    _requireActive();
    late final http.Response response;
    try {
      response = await _client
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
    _requireActive();
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

  Future<String> getExecutionMode() async {
    final health = await _get('/api/v1/health', authenticated: false);
    return health['execution_mode'] as String? ?? 'remote';
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
    List<String> customGroups = const [],
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
          if (customGroups.isNotEmpty) 'custom_groups': customGroups.join(','),
          if (enabled != null) 'enabled': '$enabled',
          'page': '$page',
          'page_size': '$pageSize',
        },
      ),
    );
  }

  Future<Map<String, dynamic>> getPromptGroups() =>
      _get('/api/v1/prompts/groups');

  Future<Map<String, dynamic>> getLitePromptGroups() =>
      _get('/api/v1/lite/prompt-groups');

  Future<Map<String, dynamic>> getLocalCapabilities() =>
      _get('/api/v1/lite/local-capabilities');

  Future<Map<String, dynamic>> getPlatformSwitchboard() =>
      _get('/api/v1/admin/platform-switchboard');

  Future<Map<String, dynamic>> savePlatformSwitchboard({
    required String revision,
    required Map<String, bool> acceptNew,
  }) =>
      _write('PUT', '/api/v1/admin/platform-switchboard',
          revision: revision, body: acceptNew);

  Future<Map<String, dynamic>> savePromptGroups({
    required String revision,
    required List<Map<String, dynamic>> groups,
  }) =>
      _write('PUT', '/api/v1/prompts/groups',
          revision: revision, body: {'groups': groups});

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
    List<String> customGroups = const [],
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
          if (customGroups.isNotEmpty) 'custom_groups': customGroups.join(','),
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
      await _get('/api/v1/lite/jobs/${Uri.encodeComponent(id)}',
          timeout: const Duration(seconds: 20)),
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
        timeout: const Duration(seconds: 20),
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

  Future<PromptLikeResult> favoriteJobImage({
    required String jobId,
    required String imageId,
  }) async {
    return PromptLikeResult.fromJson(await _post(
      '/api/v1/lite/jobs/${Uri.encodeComponent(jobId)}/images/${Uri.encodeComponent(imageId)}/favorite',
      body: const {},
    ));
  }

  Future<
      Map<String,
          dynamic>> getImagePrompt(String jobId, String imageId) => _get(
      '/api/v1/lite/jobs/${Uri.encodeComponent(jobId)}/images/${Uri.encodeComponent(imageId)}/prompt');

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
    _requireActive();
    if (!image.downloadUrl.startsWith('/api/v1/lite/jobs/')) {
      throw const HubApiException('工作站返回了不安全的图片下载地址');
    }
    late final http.Response response;
    try {
      response = await _client
          .get(Uri.parse(resolveUrl(image.downloadUrl)), headers: _headers)
          .timeout(const Duration(minutes: 3));
    } on Exception catch (error) {
      throw HubApiException('图片下载失败：$error');
    }
    _requireActive();
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
    List<String> customGroups = const [],
  }) async {
    final payload = await _get(
      '/api/v1/prompts/export',
      query: {
        if (source.isNotEmpty) 'source': source,
        if (safety.isNotEmpty) 'safety': safety,
        if (query.isNotEmpty) 'query': query,
        if (customGroups.isNotEmpty) 'custom_groups': customGroups.join(','),
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
