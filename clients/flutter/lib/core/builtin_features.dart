import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// UI availability only. These switches never install software, expose ports,
/// change server execution mode, or grant permissions.
final qqComposerEnabled = ValueNotifier<bool>(true);
final bilingualTagsEnabled = ValueNotifier<bool>(true);
final connectionGuidanceEnabled = ValueNotifier<bool>(false);

Future<void> loadBuiltinFeatures() async {
  final prefs = await SharedPreferences.getInstance();
  qqComposerEnabled.value = prefs.getBool('builtin.qq_composer') ?? true;
  bilingualTagsEnabled.value = prefs.getBool('builtin.bilingual_tags') ?? true;
  connectionGuidanceEnabled.value =
      prefs.getBool('builtin.connection_guidance') ?? false;
}

Future<void> saveBuiltinFeature(
    String key, ValueNotifier<bool> feature, bool enabled) async {
  await (await SharedPreferences.getInstance())
      .setBool('builtin.$key', enabled);
  feature.value = enabled;
}
