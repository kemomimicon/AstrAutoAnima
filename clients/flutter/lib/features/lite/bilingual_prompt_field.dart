import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/bilingual_tag_dictionary.dart';
import '../../core/builtin_features.dart';

/// Local-only tag completion. Selecting a candidate inserts the canonical
/// English tag; free text and Chinese descriptions are never rewritten.
class BilingualPromptField extends StatefulWidget {
  const BilingualPromptField({
    required this.controller,
    required this.label,
    this.onChanged,
    this.minLines = 4,
    this.maxLines = 10,
    super.key,
  });

  final TextEditingController controller;
  final String label;
  final VoidCallback? onChanged;
  final int minLines;
  final int maxLines;

  @override
  State<BilingualPromptField> createState() => _BilingualPromptFieldState();
}

class _BilingualPromptFieldState extends State<BilingualPromptField> {
  BilingualTagDictionary? _dictionary;
  Timer? _debounce;
  List<BilingualTag> _suggestions = const [];
  TagToken? _token;
  bool get _enabled => bilingualTagsEnabled.value;
  bool _committing = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    bilingualTagsEnabled.addListener(_featureChanged);
    BilingualTagDictionary.load().then((value) {
      if (mounted) setState(() => _dictionary = value);
    }).catchError((Object _) {
      // Free-text input still works if the optional local index is missing.
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    widget.controller.removeListener(_changed);
    bilingualTagsEnabled.removeListener(_featureChanged);
    super.dispose();
  }

  void _featureChanged() {
    _debounce?.cancel();
    if (mounted) setState(() => _suggestions = const []);
  }

  void _changed() {
    widget.onChanged?.call();
    if (_committing) {
      _committing = false;
      return;
    }
    _debounce?.cancel();
    final value = widget.controller.value;
    if (!_enabled ||
        _dictionary == null ||
        !value.selection.isValid ||
        (value.composing.isValid && !value.composing.isCollapsed)) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = const []);
      return;
    }
    final token = currentTagToken(value.text, value.selection.baseOffset);
    if (token.text.isEmpty) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = const []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 140), () {
      if (!mounted) return;
      setState(() {
        _token = token;
        _suggestions = _dictionary!.suggest(token.text);
      });
    });
  }

  void _pick(BilingualTag tag) {
    final token = _token;
    if (token == null) return;
    final original = widget.controller.text;
    final left = original.substring(0, token.start);
    final right = original.substring(token.end);
    final replacement = '${left.isNotEmpty ? ' ' : ''}${tag.english}';
    final result = '$left$replacement$right';
    _committing = true;
    widget.controller.value = TextEditingValue(
      text: result,
      selection:
          TextSelection.collapsed(offset: left.length + replacement.length),
    );
    setState(() => _suggestions = const []);
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: widget.controller,
            minLines: widget.minLines,
            maxLines: widget.maxLines,
            decoration: InputDecoration(
              labelText: widget.label,
              alignLabelWithHint: true,
              suffixIcon: IconButton(
                tooltip: _enabled ? '关闭双语候选' : '开启双语候选',
                icon:
                    Icon(_enabled ? Icons.translate : Icons.translate_outlined),
                onPressed: () => saveBuiltinFeature(
                    'bilingual_tags', bilingualTagsEnabled, !_enabled),
              ),
            ),
          ),
          if (_suggestions.isNotEmpty)
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 230),
              child: Material(
                elevation: 3,
                borderRadius: BorderRadius.circular(12),
                clipBehavior: Clip.antiAlias,
                child: ListView.builder(
                  shrinkWrap: true,
                  itemCount: _suggestions.length,
                  itemBuilder: (context, index) {
                    final tag = _suggestions[index];
                    return ListTile(
                      dense: true,
                      title: Text(tag.english),
                      subtitle: Text(tag.chinese),
                      onTap: () => _pick(tag),
                    );
                  },
                ),
              ),
            ),
        ],
      );
}
