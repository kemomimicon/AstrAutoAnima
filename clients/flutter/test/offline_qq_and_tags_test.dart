import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/bilingual_tag_dictionary.dart';
import 'package:astr_auto_anima_hub_client/core/qq_command_builder.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('QQ copy mode preserves exact prompt and quotes multiword preset names',
      () {
    expect(
        QqCommandBuilder.build(
          kind: 'direct',
          character: 'My Character',
          style: 'blue bell',
          ratio: '2:3',
          prompt: 'twintails, blue eyes',
        ),
        '/aimg 角色="My Character" 画风="blue bell" 比例=2:3 twintails, blue eyes');
    expect(
        QqCommandBuilder.build(
            kind: 'random', safety: 'N', fiveDraw: true, prompt: ''),
        '来张好图五连抽 N');
  });

  test('current tag replacement range respects Chinese commas', () {
    final token = currentTagToken('1girl， 双马尾, night sky', 9);
    expect(token.text, '双马尾');
    expect(token.start, 6);
    expect(token.end, 10);
  });

  test('bundled dictionary searches Chinese and English offline', () async {
    final dictionary = await BilingualTagDictionary.load();
    expect(dictionary.suggest('twin').any((tag) => tag.english == 'twintails'),
        isTrue);
    expect(dictionary.suggest('双马尾').any((tag) => tag.english == 'twintails'),
        isTrue);
  });
}
