import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/civitai_input.dart';

void main() {
  test('red long link extracts version without fetching the mirror', () {
    final value = parseCivitaiInput(
        'https://civitai.red/models/2823256/mahira-granblue-fantasy?modelVersionId=3184847');
    expect(value.modelId, 2823256);
    expect(value.versionId, 3184847);
    final slug = List.filled(4000, 'x').join();
    expect(
        parseCivitaiInput('https://civitai.com/models/1/$slug?modelVersionId=2')
            .versionId,
        2);
    expect(parseCivitaiInput('https://civitai.red/models/42/name').modelId, 42);
    expect(
        parseCivitaiInput('https://civitai.com/api/download/models/7')
            .versionId,
        7);
  });
  test('reject forged hosts credentials malformed versions and unrelated URLs',
      () {
    for (final text in [
      'https://civitai.red.evil.com/models/1',
      'http://civitai.red/models/1',
      'https://token@civitai.com/models/1',
      'https://civitai.com/models/1?modelVersionId=no',
      'https://civitai.com/other?modelVersionId=1',
      List.filled(8193, 'x').join()
    ]) {
      expect(() => parseCivitaiInput(text), throwsFormatException);
    }
  });
  test('directory character and UTF8 limits are independent of URL', () {
    expect(civitaiDirectoryError('anima_lora'), isNull);
    expect(civitaiDirectoryError(List.filled(80, '汉').join()), isNull);
    expect(
        civitaiDirectoryError(List.filled(80, '\u{20000}').join()), isNotNull);
    expect(civitaiDirectoryError(List.filled(81, 'a').join()), isNotNull);
    expect(civitaiDirectoryError('../escape'), isNotNull);
    expect(civitaiDirectoryError('/absolute'), isNotNull);
    expect(civitaiDirectoryError('https://civitai.red/models/1'), isNotNull);
  });
}
