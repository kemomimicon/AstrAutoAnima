import 'dart:convert';

String _directiveText(String value) =>
    RegExp(r'''[\s"']''').hasMatch(value) ? jsonEncode(value) : value;

enum ImageCommandKind {
  direct,
  chinese,
  reverse,
  random,
  chaos,
  hq,
  refine,
  multi
}

String _numberText(num value) => value == value.roundToDouble()
    ? value.toInt().toString()
    : value.toString();

String buildImageCommand({
  required ImageCommandKind kind,
  bool fiveDraw = false,
  String poolFilter = '',
  String character = '',
  String characterTagMode = 'weak',
  String characterVariant = '',
  String style = '',
  String ratio = '',
  String sampler = '',
  String scheduler = '',
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
  Map<String, String> visualPresets = const {},
  bool detailHands = false,
  bool detailFeet = false,
  bool detailFace = false,
  bool detailUpscale = false,
}) {
  final prefix = switch (kind) {
    ImageCommandKind.direct => '/aimg',
    ImageCommandKind.chinese => '/aicn',
    ImageCommandKind.reverse => '/aip',
    ImageCommandKind.random => fiveDraw ? '来张好图五连抽' : '来张好图抽一抽',
    ImageCommandKind.chaos => fiveDraw ? '来张好图混沌五连抽' : '来张好图混沌时刻',
    ImageCommandKind.hq => '/ahq',
    ImageCommandKind.refine => '/arefine',
    ImageCommandKind.multi => '/amulti',
  };
  final parts = <String>[prefix];
  if (kind == ImageCommandKind.hq) {
    parts.add(profile.isEmpty ? 'stable' : profile);
    parts.add('修手=${detailHands ? '开启' : '关闭'}');
    parts.add('修脚=${detailFeet ? '开启' : '关闭'}');
    parts.add('修脸=${detailFace ? '开启' : '关闭'}');
    parts.add('修复后放大=${detailUpscale ? '开启' : '关闭'}');
  }
  if (kind == ImageCommandKind.refine) {
    parts.add(profile.isEmpty ? 'seedvr2' : profile);
  }
  if (kind == ImageCommandKind.reverse) {
    if (reverseOnly) parts.add('仅反推');
    final labels = <String, String>{
      'scene': '场景',
      'action': '动作',
      'character': '角色',
      'appearance': '外观',
      'special_features': '特殊特征',
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
  if (kind != ImageCommandKind.chaos && kind != ImageCommandKind.multi) {
    if (character.trim().isNotEmpty) {
      parts.add('角色=${_directiveText(character.trim())}');
      if (characterVariant.isNotEmpty) parts.add('造型=$characterVariant');
      final label = switch (characterTagMode) {
        'strong' => '强',
        'off' => '关闭',
        _ => '弱',
      };
      parts.add('角色模式=$label');
    }
    if (style.trim().isNotEmpty) {
      parts.add('画风=${_directiveText(style.trim())}');
    }
    if (ratio.trim().isNotEmpty) parts.add('比例=${ratio.trim()}');
  }
  if (sampler.trim().isNotEmpty) parts.add('采样器=${sampler.trim()}');
  if (kind == ImageCommandKind.multi && ratio.isNotEmpty) {
    parts.add('比例=$ratio');
  }
  if (scheduler.trim().isNotEmpty) parts.add('调度器=${scheduler.trim()}');
  if (steps != null) parts.add('步数=$steps');
  if (cfg != null) parts.add('CFG=${_numberText(cfg)}');
  if (scale != null && profile != 'seedvr2') {
    parts.add('放大=${_numberText(scale)}');
  }
  if (denoise != null && profile != 'seedvr2') {
    parts.add('重绘=${_numberText(denoise)}');
  }
  if (kind == ImageCommandKind.refine && parentJobId.trim().isNotEmpty) {
    parts.add('任务=${parentJobId.trim()}');
  }
  const visualLabels = {
    'lighting_key': '主光',
    'lighting_effect': '效果光',
    'material_primary': '主材质',
    'material_surface': '表面效果',
    'camera_distance': '镜头距离',
    'camera_yaw': '水平机位',
    'camera_pitch': '俯仰机位',
    'camera_lens': '镜头效果',
    'camera_roll': '画面倾斜',
  };
  for (final entry in visualLabels.entries) {
    final value = visualPresets[entry.key]?.trim() ?? '';
    if (value.isNotEmpty) parts.add('${entry.value}=$value');
  }
  if (visualPresets.containsKey('camera_extreme_lora') ||
      visualPresets.keys.any((key) =>
          key.startsWith('camera_') &&
          (visualPresets[key]?.isNotEmpty ?? false))) {
    parts.add(
        '极限辅助=${visualPresets['camera_extreme_lora'] == 'true' ? '开启' : '关闭'}');
  }
  final details = ['material_detail_1', 'material_detail_2']
      .map((key) => visualPresets[key]?.trim() ?? '')
      .where((value) => value.isNotEmpty)
      .toSet();
  if (details.isNotEmpty) parts.add('细节材质=${details.join(',')}');
  if (prompt.trim().isNotEmpty) parts.add(prompt.trim());
  return parts.join(' ');
}
