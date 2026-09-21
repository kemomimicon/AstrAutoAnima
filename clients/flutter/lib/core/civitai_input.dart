import 'dart:convert';

/// Extract identifiers only. Credentials and downloads still go to civitai.com.
({int? modelId, int? versionId}) parseCivitaiInput(String value) {
  final text = value.trim();
  if (text.runes.length > 8192) {
    throw const FormatException('模型链接最多 8192 个字符，与保存目录长度无关');
  }
  final number = int.tryParse(text);
  if (number != null && number > 0) return (modelId: null, versionId: number);
  final uri = Uri.tryParse(text);
  if (uri == null ||
      uri.scheme != 'https' ||
      !{'civitai.com', 'www.civitai.com', 'civitai.red', 'www.civitai.red'}
          .contains(uri.host.toLowerCase()) ||
      uri.userInfo.isNotEmpty ||
      (uri.hasPort && uri.port != 443)) {
    throw const FormatException('请输入 HTTPS Civitai 模型链接或版本 ID');
  }
  final model = RegExp(r'^/models/(\d+)(?:/|$)').firstMatch(uri.path);
  final download =
      RegExp(r'^/api/download/models/(\d+)/?$').firstMatch(uri.path);
  if (model == null && download == null) {
    throw const FormatException('链接必须为模型主页或模型下载链接');
  }
  final versionText =
      uri.queryParameters['modelVersionId'] ?? download?.group(1);
  final version = int.tryParse(versionText ?? '');
  if (versionText != null && (version == null || version <= 0)) {
    throw const FormatException('modelVersionId 必须是正整数');
  }
  final modelId = int.tryParse(model?.group(1) ?? '');
  if (version == null && (modelId == null || modelId <= 0)) {
    throw const FormatException('模型 ID 必须是正整数');
  }
  return (modelId: modelId, versionId: version);
}

String? civitaiDirectoryError(String value) {
  final text = value.trim().replaceAll('\\', '/');
  if (text.runes.length > 200) return '相对目录总长最多 200 个字符';
  // Match Python Unicode \w, rather than Dart's ASCII-only \w.
  final allowed = RegExp(r'^[\p{L}\p{N}_ -]+$', unicode: true);
  for (final part in text.split('/')) {
    if (part.isEmpty || part.runes.length > 80 || !allowed.hasMatch(part)) {
      return '每层目录 1–80 个字母、数字、汉字、空格、下划线或短横线；不能填写网址、绝对路径或 ..';
    }
    if (utf8.encode(part).length > 240) return '每层目录最多 240 个 UTF-8 字节';
  }
  return null;
}
