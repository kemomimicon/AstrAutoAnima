class ProbeStatus {
  const ProbeStatus({
    required this.name,
    required this.status,
    required this.detail,
    required this.data,
    this.latencyMs,
  });

  factory ProbeStatus.fromJson(Map<String, dynamic> json) {
    return ProbeStatus(
      name: json['name'] as String? ?? 'unknown',
      status: json['status'] as String? ?? 'unknown',
      detail: json['detail'] as String? ?? '',
      latencyMs: json['latency_ms'] as int?,
      data: Map<String, dynamic>.from(json['data'] as Map? ?? const {}),
    );
  }

  final String name;
  final String status;
  final String detail;
  final int? latencyMs;
  final Map<String, dynamic> data;

  bool get isOnline => status == 'online';
}

class WorkstationStatus {
  const WorkstationStatus({
    required this.status,
    required this.checkedAt,
    required this.probes,
  });

  factory WorkstationStatus.fromJson(Map<String, dynamic> json) {
    final rawProbes = json['probes'] as List? ?? const [];
    return WorkstationStatus(
      status: json['status'] as String? ?? 'offline',
      checkedAt: DateTime.tryParse(json['checked_at'] as String? ?? '') ??
          DateTime.now(),
      probes: rawProbes
          .whereType<Map>()
          .map((item) => ProbeStatus.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
    );
  }

  final String status;
  final DateTime checkedAt;
  final List<ProbeStatus> probes;
}

class MemoryMetrics {
  const MemoryMetrics({
    required this.totalBytes,
    required this.usedBytes,
    required this.availableBytes,
    required this.utilizationPercent,
  });

  factory MemoryMetrics.fromJson(Map<String, dynamic> json) {
    return MemoryMetrics(
      totalBytes: (json['total_bytes'] as num?)?.toInt() ?? 0,
      usedBytes: (json['used_bytes'] as num?)?.toInt() ?? 0,
      availableBytes: (json['available_bytes'] as num?)?.toInt() ?? 0,
      utilizationPercent:
          (json['utilization_percent'] as num?)?.toDouble() ?? 0,
    );
  }

  final int totalBytes;
  final int usedBytes;
  final int availableBytes;
  final double utilizationPercent;
}

class GpuMetrics {
  const GpuMetrics({
    required this.index,
    required this.name,
    required this.memoryTotalMib,
    required this.memoryUsedMib,
    required this.memoryFreeMib,
    required this.memoryUtilizationPercent,
    this.utilizationPercent,
    this.temperatureC,
  });

  factory GpuMetrics.fromJson(Map<String, dynamic> json) {
    return GpuMetrics(
      index: (json['index'] as num?)?.toInt() ?? 0,
      name: json['name'] as String? ?? 'NVIDIA GPU',
      utilizationPercent: (json['utilization_percent'] as num?)?.toDouble(),
      memoryTotalMib: (json['memory_total_mib'] as num?)?.toInt() ?? 0,
      memoryUsedMib: (json['memory_used_mib'] as num?)?.toInt() ?? 0,
      memoryFreeMib: (json['memory_free_mib'] as num?)?.toInt() ?? 0,
      memoryUtilizationPercent:
          (json['memory_utilization_percent'] as num?)?.toDouble() ?? 0,
      temperatureC: (json['temperature_c'] as num?)?.toDouble(),
    );
  }

  final int index;
  final String name;
  final double? utilizationPercent;
  final int memoryTotalMib;
  final int memoryUsedMib;
  final int memoryFreeMib;
  final double memoryUtilizationPercent;
  final double? temperatureC;
}

class WorkstationMetrics {
  const WorkstationMetrics({
    required this.collectedAt,
    required this.cpuPercent,
    required this.cpuLogicalCount,
    required this.memory,
    required this.gpus,
    this.loadAverage1m,
    this.loadAverage5m,
    this.loadAverage15m,
  });

  factory WorkstationMetrics.fromJson(Map<String, dynamic> json) {
    final rawGpus = json['gpus'] as List? ?? const [];
    return WorkstationMetrics(
      collectedAt: DateTime.tryParse(json['collected_at'] as String? ?? '') ??
          DateTime.now(),
      cpuPercent: (json['cpu_percent'] as num?)?.toDouble() ?? 0,
      cpuLogicalCount: (json['cpu_logical_count'] as num?)?.toInt() ?? 1,
      loadAverage1m: (json['load_average_1m'] as num?)?.toDouble(),
      loadAverage5m: (json['load_average_5m'] as num?)?.toDouble(),
      loadAverage15m: (json['load_average_15m'] as num?)?.toDouble(),
      memory: MemoryMetrics.fromJson(
        Map<String, dynamic>.from(json['memory'] as Map? ?? const {}),
      ),
      gpus: rawGpus
          .whereType<Map>()
          .map((item) => GpuMetrics.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
    );
  }

  final DateTime collectedAt;
  final double cpuPercent;
  final int cpuLogicalCount;
  final double? loadAverage1m;
  final double? loadAverage5m;
  final double? loadAverage15m;
  final MemoryMetrics memory;
  final List<GpuMetrics> gpus;
}

class CharacterDictionaryItem {
  const CharacterDictionaryItem({
    required this.tag,
    required this.chineseNames,
    required this.aliases,
    required this.copyright,
    required this.gender,
    required this.appearance,
    required this.postCount,
    required this.weakPrompt,
    required this.strongPrompt,
    required this.disabled,
    required this.overridden,
  });

  factory CharacterDictionaryItem.fromJson(Map<String, dynamic> json) {
    List<String> strings(dynamic value) => (value as List? ?? const [])
        .map((item) => item.toString())
        .toList(growable: false);
    return CharacterDictionaryItem(
      tag: json['tag'] as String? ?? '',
      chineseNames: strings(json['chinese_names']),
      aliases: strings(json['aliases']),
      copyright: strings(json['copyright']),
      gender: strings(json['gender']),
      appearance: strings(json['appearance']),
      postCount: (json['post_count'] as num?)?.toInt() ?? 0,
      weakPrompt: json['weak_prompt'] as String? ?? '',
      strongPrompt: json['strong_prompt'] as String? ?? '',
      disabled: json['disabled'] as bool? ?? false,
      overridden: json['overridden'] as bool? ?? false,
    );
  }

  final String tag;
  final List<String> chineseNames;
  final List<String> aliases;
  final List<String> copyright;
  final List<String> gender;
  final List<String> appearance;
  final int postCount;
  final String weakPrompt;
  final String strongPrompt;
  final bool disabled;
  final bool overridden;
}

class CharacterDictionaryResult {
  const CharacterDictionaryResult({
    required this.available,
    required this.query,
    required this.total,
    required this.items,
    required this.message,
    required this.page,
    required this.pageSize,
    required this.pages,
    required this.revision,
  });

  factory CharacterDictionaryResult.fromJson(Map<String, dynamic> json) {
    return CharacterDictionaryResult(
      available: json['available'] as bool? ?? false,
      query: json['query'] as String? ?? '',
      total: (json['total'] as num?)?.toInt() ?? 0,
      items: (json['items'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => CharacterDictionaryItem.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(growable: false),
      message: json['message'] as String? ?? '',
      page: (json['page'] as num?)?.toInt() ?? 1,
      pageSize: (json['page_size'] as num?)?.toInt() ?? 20,
      pages: (json['pages'] as num?)?.toInt() ?? 1,
      revision: json['revision'] as String? ?? 'missing',
    );
  }

  final bool available;
  final String query;
  final int total;
  final List<CharacterDictionaryItem> items;
  final String message;
  final int page;
  final int pageSize;
  final int pages;
  final String revision;
}

class CharacterFavorite {
  const CharacterFavorite({
    required this.tag,
    required this.name,
    required this.mode,
    required this.weakPrompt,
    required this.strongPrompt,
  });

  factory CharacterFavorite.fromJson(Map<String, dynamic> json) =>
      CharacterFavorite(
        tag: json['tag'] as String? ?? '',
        name: json['name'] as String? ?? '',
        mode: json['mode'] as String? ?? 'weak',
        weakPrompt: json['weak_prompt'] as String? ?? '',
        strongPrompt: json['strong_prompt'] as String? ?? '',
      );

  final String tag;
  final String name;
  final String mode;
  final String weakPrompt;
  final String strongPrompt;
}

class CharacterFavoriteListResult {
  const CharacterFavoriteListResult({
    required this.items,
    required this.revision,
  });

  factory CharacterFavoriteListResult.fromJson(Map<String, dynamic> json) =>
      CharacterFavoriteListResult(
        items: (json['items'] as List? ?? const [])
            .whereType<Map>()
            .map((item) => CharacterFavorite.fromJson(
                  Map<String, dynamic>.from(item),
                ))
            .toList(growable: false),
        revision: json['revision'] as String? ?? 'missing',
      );

  final List<CharacterFavorite> items;
  final String revision;
}

class PromptRecord {
  const PromptRecord({
    required this.id,
    required this.name,
    required this.prompt,
    required this.sourceCode,
    required this.safetyCode,
    required this.enabled,
    required this.weight,
    required this.categories,
  });

  factory PromptRecord.fromJson(Map<String, dynamic> json) {
    return PromptRecord(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      prompt: json['prompt'] as String? ?? '',
      sourceCode: json['source_code'] as String? ?? '?',
      safetyCode: json['safety_code'] as String? ?? '?',
      enabled: json['enabled'] as bool? ?? true,
      weight: json['weight'] as int? ?? 1,
      categories: (json['categories'] as List? ?? const [])
          .map((value) => '$value')
          .toList(growable: false),
    );
  }

  final String id;
  final String name;
  final String prompt;
  final String sourceCode;
  final String safetyCode;
  final bool enabled;
  final int weight;
  final List<String> categories;
}

class PromptPageResult {
  const PromptPageResult({
    required this.items,
    required this.page,
    required this.pages,
    required this.total,
    required this.revision,
  });

  factory PromptPageResult.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List? ?? const [];
    return PromptPageResult(
      items: rawItems
          .whereType<Map>()
          .map((item) => PromptRecord.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      page: json['page'] as int? ?? 1,
      pages: json['pages'] as int? ?? 1,
      total: json['total'] as int? ?? 0,
      revision: json['revision'] as String? ?? '',
    );
  }

  final List<PromptRecord> items;
  final int page;
  final int pages;
  final int total;
  final String revision;
}

class PresetSummary {
  const PresetSummary({
    required this.name,
    required this.kind,
    required this.prompt,
    required this.match,
    required this.loras,
    required this.textOnly,
    this.variants = const [],
  });

  factory PresetSummary.fromJson(Map<String, dynamic> json) {
    return PresetSummary(
      name: json['name'] as String? ?? '',
      kind: json['kind'] as String? ?? 'character',
      prompt: json['prompt'] as String? ?? '',
      match: (json['match'] as List? ?? const []).map((e) => '$e').toList(),
      loras: (json['loras'] as List? ?? const [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(),
      textOnly: json['text_only'] as bool? ?? false,
      variants: (json['variants'] as List? ?? const [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList(),
    );
  }

  final String name;
  final String kind;
  final String prompt;
  final List<String> match;
  final List<Map<String, dynamic>> loras;
  final bool textOnly;
  final List<Map<String, dynamic>> variants;
}

class PresetListResult {
  const PresetListResult({
    required this.styles,
    required this.characters,
    required this.revision,
  });

  factory PresetListResult.fromJson(Map<String, dynamic> json) {
    List<PresetSummary> parseList(dynamic raw) {
      return (raw as List? ?? const [])
          .whereType<Map>()
          .map((e) => PresetSummary.fromJson(Map<String, dynamic>.from(e)))
          .toList(growable: false);
    }

    return PresetListResult(
      styles: parseList(json['styles']),
      characters: parseList(json['characters']),
      revision: json['revision'] as String? ?? '',
    );
  }

  final List<PresetSummary> styles;
  final List<PresetSummary> characters;
  final String revision;
}

class MutationResult {
  const MutationResult({
    required this.action,
    required this.resource,
    required this.revision,
    required this.count,
  });

  factory MutationResult.fromJson(Map<String, dynamic> json) {
    return MutationResult(
      action: json['action'] as String? ?? '',
      resource: json['resource'] as String? ?? '',
      revision: json['revision'] as String? ?? '',
      count: json['count'] as int? ?? 1,
    );
  }

  final String action;
  final String resource;
  final String revision;
  final int count;
}

class LiteUserRecord {
  const LiteUserRecord({
    required this.id,
    required this.qq,
    required this.label,
    required this.allowGroup,
    required this.enabled,
    this.createdAt,
    this.updatedAt,
  });

  factory LiteUserRecord.fromJson(Map<String, dynamic> json) {
    return LiteUserRecord(
      id: json['id'] as String? ?? '',
      qq: json['qq'] as String? ?? '',
      label: json['label'] as String? ?? '',
      allowGroup: json['allow_group'] as bool? ?? true,
      enabled: json['enabled'] as bool? ?? true,
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? ''),
      updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? ''),
    );
  }

  final String id;
  final String qq;
  final String label;
  final bool allowGroup;
  final bool enabled;
  final DateTime? createdAt;
  final DateTime? updatedAt;
}

class LiteUserListResult {
  const LiteUserListResult({required this.items, required this.revision});

  factory LiteUserListResult.fromJson(Map<String, dynamic> json) {
    return LiteUserListResult(
      items: (json['items'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              LiteUserRecord.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      revision: json['revision'] as String? ?? 'missing',
    );
  }

  final List<LiteUserRecord> items;
  final String revision;
}

class LiteUserIssueResult {
  const LiteUserIssueResult({
    required this.action,
    required this.user,
    required this.token,
    required this.revision,
  });

  factory LiteUserIssueResult.fromJson(Map<String, dynamic> json) {
    return LiteUserIssueResult(
      action: json['action'] as String? ?? '',
      user: LiteUserRecord.fromJson(
        Map<String, dynamic>.from(json['user'] as Map? ?? const {}),
      ),
      token: json['token'] as String? ?? '',
      revision: json['revision'] as String? ?? '',
    );
  }

  final String action;
  final LiteUserRecord user;
  final String token;
  final String revision;
}

class DeliveryTarget {
  const DeliveryTarget({
    required this.id,
    required this.label,
    required this.kind,
  });

  factory DeliveryTarget.fromJson(Map<String, dynamic> json) {
    return DeliveryTarget(
      id: json['id'] as String? ?? '',
      label: json['label'] as String? ?? '',
      kind: json['kind'] as String? ?? 'private',
    );
  }

  final String id;
  final String label;
  final String kind;

  bool get isGroup => kind == 'group';
}

class DeliveryTargetListResult {
  const DeliveryTargetListResult({required this.targets});

  factory DeliveryTargetListResult.fromJson(Map<String, dynamic> json) {
    return DeliveryTargetListResult(
      targets: (json['targets'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              DeliveryTarget.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
    );
  }

  final List<DeliveryTarget> targets;
}

class RemoteJobImage {
  const RemoteJobImage({
    this.taskSuiteIndex = 0,
    this.promptId = '',
    required this.id,
    required this.filename,
    required this.contentType,
    required this.sizeBytes,
    required this.sha256,
    required this.downloadUrl,
  });

  factory RemoteJobImage.fromJson(Map<String, dynamic> json) {
    return RemoteJobImage(
      taskSuiteIndex: json['task_suite_index'] as int? ?? 0,
      promptId: json['prompt_id'] as String? ?? '',
      id: json['id'] as String? ?? '',
      filename: json['filename'] as String? ?? 'generated-image.png',
      contentType: json['content_type'] as String? ?? 'image/png',
      sizeBytes: json['size_bytes'] as int? ?? 0,
      sha256: json['sha256'] as String? ?? '',
      downloadUrl: json['download_url'] as String? ?? '',
    );
  }

  final String id;
  final String filename;
  final String contentType;
  final int sizeBytes;
  final String sha256;
  final String downloadUrl;
  final String promptId;
  final int taskSuiteIndex;
}

class RemoteJobResult {
  const RemoteJobResult({
    this.taskSuiteId = '',
    this.taskSuiteRows = const [],
    required this.id,
    required this.status,
    required this.kind,
    required this.safetyCode,
    required this.profile,
    required this.targetId,
    required this.targetLabel,
    required this.commandPreview,
    required this.message,
    required this.images,
    required this.promptIds,
    required this.likedPromptIds,
    required this.createdAt,
    required this.updatedAt,
  });

  factory RemoteJobResult.fromJson(Map<String, dynamic> json) {
    return RemoteJobResult(
      taskSuiteId: json['task_suite_id'] as String? ?? '',
      taskSuiteRows: (json['task_suite_rows'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e))
          .toList(),
      id: json['id'] as String? ?? '',
      status: json['status'] as String? ?? 'failed',
      kind: json['kind'] as String? ?? 'direct',
      safetyCode: json['safety_code'] as String? ?? 'N',
      profile: json['profile'] as String? ?? '',
      targetId: json['target_id'] as String? ?? '',
      targetLabel: json['target_label'] as String? ?? '',
      commandPreview: json['command_preview'] as String? ?? '',
      message: json['message'] as String? ?? '',
      images: (json['images'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              RemoteJobImage.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      promptIds: (json['prompt_ids'] as List? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
      likedPromptIds: (json['liked_prompt_ids'] as List? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ??
          DateTime.now(),
      updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? '') ??
          DateTime.now(),
    );
  }

  final String id;
  final String status;
  final String kind;
  final String safetyCode;
  final String profile;
  final String targetId;
  final String targetLabel;
  final String commandPreview;
  final String message;
  final List<RemoteJobImage> images;
  final List<String> promptIds;
  final List<String> likedPromptIds;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isFinished => status == 'succeeded' || status == 'failed';
  final String taskSuiteId;
  final List<Map<String, dynamic>> taskSuiteRows;
}

class PromptLikeResult {
  const PromptLikeResult({
    required this.action,
    required this.promptId,
    required this.savedPromptId,
  });

  factory PromptLikeResult.fromJson(Map<String, dynamic> json) {
    return PromptLikeResult(
      action: json['action'] as String? ?? 'liked',
      promptId: json['prompt_id'] as String? ?? '',
      savedPromptId: json['saved_prompt_id'] as String? ?? '',
    );
  }

  final String action;
  final String promptId;
  final String savedPromptId;
}

class LoraCatalogItem {
  const LoraCatalogItem({
    required this.path,
    required this.displayName,
    required this.category,
    required this.recommendedPrompt,
    required this.enabled,
    required this.present,
    required this.sizeBytes,
    this.sourceUrl = '',
  });

  factory LoraCatalogItem.fromJson(Map<String, dynamic> json) {
    return LoraCatalogItem(
      path: json['path'] as String? ?? '',
      displayName: json['display_name'] as String? ?? '',
      category: json['category'] as String? ?? 'unclassified',
      recommendedPrompt: json['recommended_prompt'] as String? ?? '',
      enabled: json['enabled'] as bool? ?? true,
      present: json['present'] as bool? ?? true,
      sizeBytes: json['size_bytes'] as int? ?? 0,
      sourceUrl: json['source_url'] as String? ?? '',
    );
  }

  final String path;
  final String displayName;
  final String category;
  final String recommendedPrompt;
  final bool enabled;
  final bool present;
  final int sizeBytes;
  final String sourceUrl;

  String get shareText =>
      'LoRA：$displayName\n来源：$sourceUrl\n触发词：${recommendedPrompt.isEmpty ? '未提供，请查看作者说明' : recommendedPrompt}';
}

class LoraCatalogResult {
  const LoraCatalogResult({required this.items, required this.revision});

  factory LoraCatalogResult.fromJson(Map<String, dynamic> json) {
    return LoraCatalogResult(
      items: (json['items'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              LoraCatalogItem.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      revision: json['revision'] as String? ?? 'missing',
    );
  }

  final List<LoraCatalogItem> items;
  final String revision;
}

class PersonalStyleLora {
  const PersonalStyleLora({required this.path, required this.strength});

  factory PersonalStyleLora.fromJson(Map<String, dynamic> json) {
    return PersonalStyleLora(
      path: json['path'] as String? ?? '',
      strength: (json['strength'] as num?)?.toDouble() ?? 1,
    );
  }

  final String path;
  final double strength;

  Map<String, dynamic> toJson() => {'path': path, 'strength': strength};
}

class PersonalStyle {
  const PersonalStyle({
    required this.slot,
    required this.name,
    required this.prompt,
    required this.loras,
    required this.styleKey,
  });

  factory PersonalStyle.fromJson(Map<String, dynamic> json) {
    return PersonalStyle(
      slot: json['slot'] as int? ?? 1,
      name: json['name'] as String? ?? '',
      prompt: json['prompt'] as String? ?? '',
      loras: (json['loras'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              PersonalStyleLora.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      styleKey: json['style_key'] as String? ?? '',
    );
  }

  final int slot;
  final String name;
  final String prompt;
  final List<PersonalStyleLora> loras;
  final String styleKey;
}

class PersonalStyleListResult {
  const PersonalStyleListResult({required this.items, required this.revision});

  factory PersonalStyleListResult.fromJson(Map<String, dynamic> json) {
    return PersonalStyleListResult(
      items: (json['items'] as List? ?? const [])
          .whereType<Map>()
          .map(
              (item) => PersonalStyle.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      revision: json['revision'] as String? ?? 'missing',
    );
  }

  final List<PersonalStyle> items;
  final String revision;
}

class RemoteJobPageResult {
  const RemoteJobPageResult({
    required this.items,
    required this.page,
    required this.pages,
    required this.total,
  });

  factory RemoteJobPageResult.fromJson(Map<String, dynamic> json) {
    return RemoteJobPageResult(
      items: (json['items'] as List? ?? const [])
          .whereType<Map>()
          .map((item) =>
              RemoteJobResult.fromJson(Map<String, dynamic>.from(item)))
          .toList(growable: false),
      page: json['page'] as int? ?? 1,
      pages: json['pages'] as int? ?? 1,
      total: json['total'] as int? ?? 0,
    );
  }

  final List<RemoteJobResult> items;
  final int page;
  final int pages;
  final int total;
}
