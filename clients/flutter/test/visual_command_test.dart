import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/command_builder.dart';

void main() {
  test('copied command retains visual selections and quoted preset names', () {
    final command = buildImageCommand(
      kind: ImageCommandKind.direct,
      character: '角色 A',
      style: '画风 B',
      prompt: 'solo',
      visualPresets: {
        'lighting_key': 'light_a',
        'material_detail_1': 'detail_a',
        'material_detail_2': 'detail_a',
        'camera_pitch': 'extreme_low',
      },
    );
    expect(command, contains('角色="角色 A"'));
    expect(command, contains('画风="画风 B"'));
    expect(command, contains('主光=light_a'));
    expect(command, contains('俯仰机位=extreme_low'));
    expect(command, contains('极限辅助=关闭'));
    expect(command, endsWith('细节材质=detail_a solo'));
  });

  test('hq command records the repair chain switches', () {
    final command = buildImageCommand(
      kind: ImageCommandKind.hq,
      prompt: 'solo',
      detailHands: true,
      detailFeet: true,
      detailFace: false,
    );
    expect(command, startsWith('/ahq stable 修手=开启 修脚=开启 修脸=关闭'));
    expect(command, contains('修复后放大=关闭'));
  });

  test('optional camera helper and post-repair upscale require explicit enable',
      () {
    final command = buildImageCommand(
      kind: ImageCommandKind.hq,
      detailUpscale: true,
      detailHands: false,
      detailFeet: false,
      detailFace: true,
      visualPresets: {
        'camera_pitch': 'extreme_high',
        'camera_extreme_lora': 'true'
      },
    );
    expect(command, contains('极限辅助=开启'));
    expect(command, contains('修复后放大=开启'));
    expect(command, contains('修手=关闭 修脚=关闭 修脸=开启'));
  });
}
