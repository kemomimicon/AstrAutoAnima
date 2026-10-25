import 'dart:convert';

/// Personal deployment transport: produce text only. Never contacts a Hub,
/// stores a QQ token, or sends messages on behalf of the user.
class QqCommandBuilder {
  static String _argument(String label, String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return '';
    final encoded = RegExp(r'''\s|["']''').hasMatch(trimmed)
        ? jsonEncode(trimmed)
        : trimmed;
    return '$label=$encoded';
  }

  static String build({
    required String kind,
    required String prompt,
    String character = '',
    String style = '',
    String ratio = '',
    String safety = 'N',
    bool fiveDraw = false,
  }) {
    if (!{'direct', 'chinese', 'random', 'hq'}.contains(kind)) {
      throw const FormatException('不支持的指令类型');
    }
    if (!{'N', 'H', 'S'}.contains(safety)) {
      throw const FormatException('安全级别应为 N/H/S');
    }
    if ({'direct', 'chinese', 'hq'}.contains(kind) && prompt.trim().isEmpty) {
      throw const FormatException('当前指令必须填写提示词');
    }
    final prefix = switch (kind) {
      'direct' => '/aimg',
      'chinese' => '/aicn',
      'hq' => '/ahq stable',
      _ => fiveDraw ? '来张好图五连抽' : '来张好图抽一抽',
    };
    final parts = <String>[
      prefix,
      if (kind == 'random') safety,
      _argument('角色', character),
      _argument('画风', style),
      _argument('比例', ratio),
      prompt.trim(),
    ];
    return parts.where((part) => part.isNotEmpty).join(' ');
  }
}
