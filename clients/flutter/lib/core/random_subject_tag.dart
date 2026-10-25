import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

const randomSubjectChoices = <String, String>{
  '': '原样（1girl）',
  '1boy': '1boy',
  '1woman': '1woman',
  '1man': '1man',
  'none': '不指定人物 Tag',
};

final randomSubjectTag = ValueNotifier<String>('');
final randomSubjectTagLocked = ValueNotifier<bool>(false);

const _tagKey = 'aaa_random_subject_tag';
const _lockKey = 'aaa_random_subject_tag_locked';

Future<void> loadRandomSubjectTag() async {
  final prefs = await SharedPreferences.getInstance();
  final saved = prefs.getString(_tagKey) ?? '';
  randomSubjectTag.value = randomSubjectChoices.containsKey(saved) ? saved : '';
  randomSubjectTagLocked.value = prefs.getBool(_lockKey) ?? false;
}

Future<void> saveRandomSubjectTag(String tag) async {
  if (!randomSubjectChoices.containsKey(tag)) {
    throw ArgumentError.value(tag, 'tag', '不支持的随机串起手 Tag');
  }
  if (randomSubjectTagLocked.value) return;
  randomSubjectTag.value = tag;
  await (await SharedPreferences.getInstance()).setString(_tagKey, tag);
}

Future<void> saveRandomSubjectTagLocked(bool locked) async {
  randomSubjectTagLocked.value = locked;
  await (await SharedPreferences.getInstance()).setBool(_lockKey, locked);
}
