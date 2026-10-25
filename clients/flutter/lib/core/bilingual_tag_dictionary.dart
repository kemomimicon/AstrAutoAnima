import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class BilingualTag {
  const BilingualTag(this.english, this.chinese);
  final String english;
  final String chinese;
}

class BilingualTagDictionary {
  BilingualTagDictionary._(this._tags)
      : _english = _tags.map((tag) => _compact(tag.english)).toList(),
        _chinese = _tags.map((tag) => tag.chinese.toLowerCase()).toList();

  final List<BilingualTag> _tags;
  final List<String> _english;
  final List<String> _chinese;
  static Future<BilingualTagDictionary>? _loading;

  static Future<BilingualTagDictionary> load() => _loading ??= _read();

  static Future<BilingualTagDictionary> _read() async {
    final source =
        await rootBundle.loadString('assets/tag_dict/zh_en_top50000.json');
    final decoded = await compute(_parseEntries, source);
    return BilingualTagDictionary._(decoded);
  }

  static List<BilingualTag> _parseEntries(String source) {
    final raw = jsonDecode(source) as List;
    return raw
        .whereType<List>()
        .where((item) => item.length >= 2)
        .map((item) => BilingualTag(item[0] as String, item[1] as String))
        .toList(growable: false);
  }

  static String _compact(String text) =>
      text.toLowerCase().replaceAll(RegExp(r'[ _]'), '');

  List<BilingualTag> suggest(String input, {int limit = 8}) {
    final term = input.trim().toLowerCase();
    if (term.isEmpty) return const [];
    final compact = _compact(term);
    final chinese = RegExp(r'[\u3400-\u9fff]').hasMatch(term);
    final found = <BilingualTag>[];
    final seen = <String>{};
    for (var pass = 0; pass < 2 && found.length < limit; pass++) {
      for (var i = 0; i < _tags.length && found.length < limit; i++) {
        final key = chinese ? _chinese[i] : _english[i];
        final needle = chinese ? term : compact;
        final matched =
            pass == 0 ? key.startsWith(needle) : key.contains(needle);
        if (matched && seen.add(_tags[i].english)) found.add(_tags[i]);
      }
    }
    return found;
  }
}

class TagToken {
  const TagToken(this.text, this.start, this.end);
  final String text;
  final int start;
  final int end;
}

TagToken currentTagToken(String value, int cursor) {
  final at = cursor.clamp(0, value.length);
  var start = at;
  var end = at;
  bool separator(String char) => char == ',' || char == '，' || char == '\n';
  while (start > 0 && !separator(value[start - 1])) {
    start--;
  }
  while (end < value.length && !separator(value[end])) {
    end++;
  }
  return TagToken(value.substring(start, end).trim(), start, end);
}
