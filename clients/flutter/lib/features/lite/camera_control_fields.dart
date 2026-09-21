import 'package:flutter/material.dart';

class CameraControlFields extends StatelessWidget {
  const CameraControlFields({
    super.key,
    required this.values,
    required this.onChanged,
  });

  final Map<String, String> values;
  final ValueChanged<Map<String, String>> onChanged;

  static const _fields = <(String, String, String, List<(String, String)>)>[
    (
      'camera_distance',
      '镜头距离 / 构图',
      '控制取景范围；普通选项只写提示词',
      [
        ('', '不指定'),
        ('extreme_close', '极近特写'),
        ('close', '近景'),
        ('portrait', '头像 / 肩部肖像'),
        ('upper_body', '上半身'),
        ('cowboy', '牛仔镜头'),
        ('full_body', '全身'),
        ('wide', '远景'),
        ('very_wide', '大远景'),
      ]
    ),
    (
      'camera_yaw',
      '水平机位',
      '人物相对镜头的水平方向',
      [
        ('', '不指定'),
        ('front', '正面'),
        ('three_quarter', '前侧 3/4'),
        ('side', '侧面'),
        ('rear_three_quarter', '后侧 3/4'),
        ('back', '背面'),
      ]
    ),
    (
      'camera_pitch',
      '俯仰机位',
      '默认只添加提示词；LoRA 辅助需单独勾选',
      [
        ('', '不指定'),
        ('eye', '平视'),
        ('slight_low', '轻微仰视'),
        ('low', '低机位仰视'),
        ('extreme_low', '极限仰视'),
        ('slight_high', '轻微俯视'),
        ('high', '高机位俯视'),
        ('extreme_high', '极限俯视'),
      ]
    ),
    (
      'camera_lens',
      '镜头效果',
      '改变透视感，不改变真实焦距参数',
      [
        ('', '不指定'),
        ('normal', '标准镜头'),
        ('wide', '广角'),
        ('ultra_wide', '超广角'),
        ('telephoto', '长焦压缩'),
        ('fisheye', '鱼眼'),
      ]
    ),
    (
      'camera_roll',
      '画面倾斜',
      '荷兰角会让地平线倾斜',
      [('', '不指定'), ('level', '水平'), ('dutch', '荷兰角')]
    ),
  ];

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('相机控制', style: TextStyle(fontWeight: FontWeight.w600)),
          ),
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('启用极限机位 LoRA 辅助'),
            subtitle: const Text('默认关闭；仅极限俯视/仰视生效，需管理员配置辅助 LoRA'),
            value: values['camera_extreme_lora'] == 'true',
            onChanged: (enabled) => onChanged({
              ...values,
              'camera_extreme_lora': '${enabled == true}',
            }),
          ),
          for (final field in _fields)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: DropdownButtonFormField<String>(
                key: ValueKey('${field.$1}:${values[field.$1] ?? ''}'),
                initialValue: values[field.$1] ?? '',
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: field.$2,
                  helperText: field.$3,
                ),
                items: [
                  for (final item in field.$4)
                    DropdownMenuItem(value: item.$1, child: Text(item.$2)),
                ],
                onChanged: (selected) => onChanged({
                  ...values,
                  field.$1: selected ?? '',
                }),
              ),
            ),
        ],
      );
}
