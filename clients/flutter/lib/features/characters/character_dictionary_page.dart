import '../../core/courtyard_theme.dart';
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';

class CharacterDictionaryPage extends StatefulWidget {
  const CharacterDictionaryPage({
    required this.api,
    this.onUseCharacter,
    this.adminMode = false,
    super.key,
  });

  final HubApi api;
  final void Function(CharacterDictionaryItem item, bool strong)?
      onUseCharacter;
  final bool adminMode;

  @override
  State<CharacterDictionaryPage> createState() =>
      _CharacterDictionaryPageState();
}

class _CharacterDictionaryPageState extends State<CharacterDictionaryPage> {
  final TextEditingController _query = TextEditingController();
  Timer? _debounce;
  CharacterDictionaryResult? _result;
  CharacterFavoriteListResult? _favorites;
  bool _loading = false;
  bool _strong = false;
  int _page = 1;
  String _error = '';

  @override
  void initState() {
    super.initState();
    unawaited(_search());
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _changed(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      _page = 1;
      unawaited(_search());
    });
  }

  Future<void> _search() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final result = widget.adminMode
          ? await widget.api.getAdminCharacters(
              query: _query.text,
              page: _page,
            )
          : await widget.api.searchCharacters(
              query: _query.text,
              page: _page,
            );
      CharacterFavoriteListResult? favorites;
      if (!widget.adminMode) {
        favorites = await widget.api.getCharacterFavorites();
      }
      if (mounted) {
        setState(() {
          _result = result;
          _favorites = favorites;
        });
      }
    } on HubApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  CharacterFavorite? _favoriteFor(String tag) {
    for (final item in _favorites?.items ?? const <CharacterFavorite>[]) {
      if (item.tag == tag) return item;
    }
    return null;
  }

  Future<void> _toggleFavorite(CharacterDictionaryItem item) async {
    final current = _favoriteFor(item.tag);
    try {
      final controller = TextEditingController(
        text: current?.name ??
            (item.chineseNames.isNotEmpty ? item.chineseNames.first : item.tag),
      );
      final action = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(current == null ? '收藏角色并起名' : '编辑收藏角色'),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(labelText: '收藏显示名'),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消')),
            if (current != null)
              TextButton(
                onPressed: () => Navigator.pop(context, '__delete__'),
                child: const Text('取消收藏'),
              ),
            FilledButton(
              onPressed: () => Navigator.pop(
                context,
                controller.text.trim().isEmpty
                    ? (current?.name ?? item.tag)
                    : controller.text.trim(),
              ),
              child: Text(current == null ? '收藏' : '保存名称'),
            ),
          ],
        ),
      );
      controller.dispose();
      if (action == null || !mounted) return;
      if (action == '__delete__') {
        final result = await widget.api.deleteCharacterFavorite(
          tag: item.tag,
          revision: _favorites?.revision ?? 'missing',
        );
        if (mounted) setState(() => _favorites = result);
        return;
      }
      final result = await widget.api.saveCharacterFavorite(
        tag: item.tag,
        revision: _favorites?.revision ?? 'missing',
        name: action,
        mode: _strong ? 'strong' : 'weak',
      );
      if (mounted) setState(() => _favorites = result);
    } on HubApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
      }
    }
  }

  Future<void> _editCharacter(CharacterDictionaryItem item) async {
    final aliases = TextEditingController(text: item.aliases.join(', '));
    final copyright = TextEditingController(text: item.copyright.join(', '));
    final gender = TextEditingController(text: item.gender.join(', '));
    final appearance = TextEditingController(text: item.appearance.join(', '));
    final postCount = TextEditingController(text: '${item.postCount}');
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('编辑 ${item.tag}'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
                controller: aliases,
                decoration: const InputDecoration(labelText: '别名（逗号分隔）')),
            TextField(
                controller: copyright,
                decoration: const InputDecoration(labelText: '作品 tag')),
            TextField(
                controller: gender,
                decoration: const InputDecoration(labelText: '性别 tag')),
            TextField(
                controller: appearance,
                maxLines: 3,
                decoration: const InputDecoration(labelText: '强模式外貌 tag')),
            TextField(
              controller: postCount,
              keyboardType: TextInputType.number,
              decoration:
                  const InputDecoration(labelText: 'Danbooru 帖子数 / 有效性参考'),
            ),
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    );
    if (accepted == true) {
      try {
        await widget.api.updateCharacter(
          tag: item.tag,
          revision: _result?.revision ?? 'missing',
          value: {
            'aliases': _split(aliases.text),
            'copyright': _split(copyright.text),
            'gender': _split(gender.text),
            'appearance': _split(appearance.text),
            'post_count': int.tryParse(postCount.text.trim()) ?? item.postCount,
          },
        );
        await _search();
      } on HubApiException catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(error.message)));
        }
      }
    }
    aliases.dispose();
    copyright.dispose();
    gender.dispose();
    appearance.dispose();
    postCount.dispose();
  }

  List<String> _split(String value) => value
      .split(RegExp(r'[,，\n]'))
      .map((part) => part.trim())
      .where((part) => part.isNotEmpty)
      .toList();

  Future<void> _disableCharacter(CharacterDictionaryItem item) async {
    if (!item.disabled) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('停用词条？'),
          content: Text('“${item.tag}”将从用户搜索和收藏列表隐藏，可随时恢复。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('停用')),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    try {
      if (item.disabled) {
        await widget.api.updateCharacter(
          tag: item.tag,
          revision: _result?.revision ?? 'missing',
          value: const {'disabled': false},
        );
      } else {
        await widget.api.deleteCharacter(
          tag: item.tag,
          revision: _result?.revision ?? 'missing',
        );
      }
      await _search();
    } on HubApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> _copy(String text, String label) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已复制$label')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    return RefreshIndicator(
      onRefresh: _search,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(widget.adminMode ? 'Danbooru 角色词表管理器' : '角色中 / 英词典',
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 6),
          Text(
            widget.adminMode
                ? '搜索、修订或停用低有效性词条；改动写入独立覆盖层，重建基础词典也不会丢失。'
                : '输入中文角色名、英文名或 Danbooru tag。可点星收藏并自定义名称。',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _query,
            onChanged: _changed,
            onSubmitted: (_) => unawaited(_search()),
            decoration: InputDecoration(
              labelText: '搜索角色',
              hintText: '例如：初音未来 / hatsune miku',
              prefixIcon: const CourtyardIcon(Icons.search),
              suffixIcon: _query.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: '清空',
                      onPressed: () {
                        _query.clear();
                        _page = 1;
                        unawaited(_search());
                      },
                      icon: const CourtyardIcon(Icons.clear),
                    ),
            ),
          ),
          const SizedBox(height: 12),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('弱模式')),
              ButtonSegment(value: true, label: Text('强模式')),
            ],
            selected: {_strong},
            onSelectionChanged: (value) =>
                setState(() => _strong = value.first),
          ),
          const SizedBox(height: 12),
          if (_loading) const LinearProgressIndicator(),
          if (_error.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_error,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          if (result != null && !result.available)
            Card(
              margin: const EdgeInsets.only(top: 12),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                    result.message.isEmpty ? '工作站尚未安装角色词典。' : result.message),
              ),
            ),
          if (result != null && result.available) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text('匹配 ${result.total} 项，当前显示 ${result.items.length} 项'),
            ),
            if (result.items.isEmpty)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(18),
                  child: Text('没有找到对应角色。可以尝试英文名或缩短关键词。'),
                ),
              ),
            ...result.items.map(_characterCard),
            if (result.pages > 1)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    tooltip: '上一页',
                    onPressed: result.page <= 1 || _loading
                        ? null
                        : () {
                            setState(() => _page = result.page - 1);
                            unawaited(_search());
                          },
                    icon: const CourtyardIcon(Icons.chevron_left),
                  ),
                  Text('${result.page} / ${result.pages}'),
                  IconButton(
                    tooltip: '下一页',
                    onPressed: result.page >= result.pages || _loading
                        ? null
                        : () {
                            setState(() => _page = result.page + 1);
                            unawaited(_search());
                          },
                    icon: const CourtyardIcon(Icons.chevron_right),
                  ),
                ],
              ),
          ],
          const SizedBox(height: 48),
        ],
      ),
    );
  }

  Widget _characterCard(CharacterDictionaryItem item) {
    final prompt = _strong ? item.strongPrompt : item.weakPrompt;
    final chinese =
        item.chineseNames.isEmpty ? '暂无中文别名' : item.chineseNames.join('、');
    final favorite = _favoriteFor(item.tag);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(chinese,
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 3),
                      SelectableText(item.tag),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: '复制标准英文 tag',
                  onPressed: () => _copy(item.tag, '英文 tag'),
                  icon: const CourtyardIcon(Icons.content_copy),
                ),
                if (!widget.adminMode)
                  IconButton(
                    tooltip: favorite == null ? '收藏角色' : '取消收藏',
                    onPressed: () => _toggleFavorite(item),
                    icon: CourtyardIcon(
                        favorite == null ? Icons.star_border : Icons.star),
                  ),
              ],
            ),
            if (item.copyright.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text('作品：${item.copyright.join(', ')}'),
            ],
            if (_strong && item.appearance.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('外貌：${[...item.gender, ...item.appearance].join(', ')}'),
            ],
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
              ),
              child: SelectableText(prompt),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: Wrap(
                alignment: WrapAlignment.end,
                children: [
                  TextButton.icon(
                    onPressed: () =>
                        _copy(prompt, _strong ? '强模式提示词' : '弱模式提示词'),
                    icon: const CourtyardIcon(Icons.copy_all),
                    label: Text(_strong ? '复制强模式' : '复制弱模式'),
                  ),
                  if (widget.onUseCharacter != null)
                    FilledButton.tonalIcon(
                      key: ValueKey('use-character-${item.tag}'),
                      onPressed: () => widget.onUseCharacter!(item, _strong),
                      icon:
                          const CourtyardIcon(Icons.person_add_alt_1_outlined),
                      label: const Text('添加到使用角色'),
                    ),
                  if (widget.adminMode) ...[
                    TextButton.icon(
                      onPressed: () => _editCharacter(item),
                      icon: const CourtyardIcon(Icons.edit_outlined),
                      label: const Text('编辑'),
                    ),
                    TextButton.icon(
                      onPressed: () => _disableCharacter(item),
                      icon: CourtyardIcon(
                          item.disabled ? Icons.restore : Icons.delete_outline),
                      label: Text(item.disabled ? '恢复' : '停用'),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
