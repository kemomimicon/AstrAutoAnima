enum ImageCommandKind { direct, chinese, reverse, random, chaos, hq, refine }

String _numberText(num value) => value == value.roundToDouble()
    ? value.toInt().toString()
    : value.toString();

String buildImageCommand({
  required ImageCommandKind kind,
  bool fiveDraw = false,
  String poolFilter = '',
  String character = '',
  String style = '',
  String ratio = '',
  String sampler = '',
  int? steps,
  double? cfg,
  String prompt = '',
  String reversePreset = 'full',
  List<String> reverseCategories = const [],
  bool reverseOnly = false,
  String profile = '',
  String parentJobId = '',
  double? scale,
  double? denoise,
}) {
  final prefix = switch (kind) {
    ImageCommandKind.direct => '/aimg',
    ImageCommandKind.chinese => '/aicn',
    ImageCommandKind.reverse => '/aip',
    ImageCommandKind.random => fiveDraw ? '来张好图五连抽' : '来张好图抄一抄',
    ImageCommandKind.chaos => fiveDraw ? '来张好图混沌五连抽' : '来张好图混沌时刻',
    ImageCommandKind.hq => '/ahq',
    ImageCommandKind.refine => '/arefine',
  };
  final parts = <String>[prefix];
  if (kind == ImageCommandKind.hq) {
    parts.add(profile.isEmpty ? 'stable' : profile);
  }
  if (kind == ImageCommandKind.refine) {
    parts.add(profile.isEmpty ? 'light' : profile);
  }
  if (kind == ImageCommandKind.reverse) {
    if (reverseOnly) parts.add('仅反推');
    final labels = <String, String>{
      'scene': '场景',
      'action': '动作',
      'character': '角色',
      'appearance': '外观',
      'clothing': '服装',
      'composition': '构图',
      'other': '其他',
      'safety': '安全',
    };
    final categories = reverseCategories
        .where(labels.containsKey)
        .map((value) => labels[value]!)
        .toSet()
        .toList();
    if (categories.isEmpty) {
      parts.add('模式=$reversePreset');
    } else {
      parts.add('分类=${categories.join(',')}');
    }
  }
  if ((kind == ImageCommandKind.random || kind == ImageCommandKind.chaos) &&
      poolFilter.trim().isNotEmpty) {
    parts.add(poolFilter.trim());
  }
  if (kind != ImageCommandKind.chaos) {
    if (character.trim().isNotEmpty) parts.add('角色=${character.trim()}');
    if (style.trim().isNotEmpty) parts.add('画风=${style.trim()}');
    if (ratio.trim().isNotEmpty) parts.add('比例=${ratio.trim()}');
  }
  if (sampler.trim().isNotEmpty) parts.add('采样器=${sampler.trim()}');
  if (steps != null) parts.add('步数=$steps');
  if (cfg != null) parts.add('CFG=${_numberText(cfg)}');
  if (scale != null) parts.add('放大=${_numberText(scale)}');
  if (denoise != null) parts.add('重绘=${_numberText(denoise)}');
  if (kind == ImageCommandKind.refine && parentJobId.trim().isNotEmpty) {
    parts.add('任务=${parentJobId.trim()}');
  }
  if (prompt.trim().isNotEmpty) parts.add(prompt.trim());
  return parts.join(' ');
}
