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
    );
  }

  final String name;
  final String kind;
  final String prompt;
  final List<String> match;
  final List<Map<String, dynamic>> loras;
  final bool textOnly;
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
    required this.id,
    required this.filename,
    required this.contentType,
    required this.sizeBytes,
    required this.sha256,
    required this.downloadUrl,
  });

  factory RemoteJobImage.fromJson(Map<String, dynamic> json) {
    return RemoteJobImage(
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
}

class RemoteJobResult {
  const RemoteJobResult({
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
    required this.createdAt,
    required this.updatedAt,
  });

  factory RemoteJobResult.fromJson(Map<String, dynamic> json) {
    return RemoteJobResult(
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
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isFinished => status == 'succeeded' || status == 'failed';
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
          .map((item) => RemoteJobResult.fromJson(Map<String, dynamic>.from(item)))
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
