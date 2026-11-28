import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/hub_api.dart';

class CharacterGalleryPage extends StatefulWidget {
  const CharacterGalleryPage({
    super.key,
    required this.api,
    required this.admin,
  });
  final HubApi api;
  final bool admin;
  @override
  State<CharacterGalleryPage> createState() => _CharacterGalleryPageState();
}

class _CharacterGalleryPageState extends State<CharacterGalleryPage> {
  Map<String, dynamic>? data;
  String? error;
  final selected = <String>[];
  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    try {
      final next = await widget.api.characterGallery();
      if (mounted) {
        setState(() {
          data = next;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  Future<void> edit([Map? card]) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _CardEditor(
        api: widget.api,
        revision: '${data!['revision']}',
        card: card,
      ),
    );
    if (result != null && mounted) {
      setState(() {
        data = result;
        error = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final cards = (data?['items'] as List? ?? []).whereType<Map>().toList();
    final chosen = selected
        .map((id) => cards.where((c) => c['id'] == id).firstOrNull)
        .whereType<Map>()
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('角色画廊'),
        actions: [
          IconButton(
            onPressed: refresh,
            tooltip: '刷新',
            icon: const Icon(Icons.refresh),
          ),
          if (widget.admin && data != null)
            IconButton(
              onPressed: () => edit(),
              tooltip: '添加角色卡',
              icon: const Icon(Icons.add),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('选择两个角色，复制多人预览指令。管理员可导入独立特征档案，并从已完成任务保存封面。'),
          if (error != null)
            SelectableText(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (data == null && error == null) const LinearProgressIndicator(),
          FilledButton(
            onPressed: chosen.length == 2
                ? () async {
                    String role(Map c) =>
                        '${c['character']}${c['variant'] == 'default' ? '' : '::${c['variant']}'}';
                    final command =
                        '/amulti 预览\n人物1：${role(chosen[0])} | | on the left\n人物2：${role(chosen[1])} | | on the right\n场景：a quiet garden';
                    await Clipboard.setData(ClipboardData(text: command));
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('预览指令已复制；确认后将“预览”换成“预设”即可生图'),
                        ),
                      );
                    }
                  }
                : null,
            child: Text('复制双人预览指令（${chosen.length}/2）'),
          ),
          for (final card in cards)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    CheckboxListTile(
                      value: selected.contains(card['id']),
                      title: Text('${card['character']} · ${card['variant']}'),
                      subtitle: Text(
                        card['published'] == true ? '已展示' : '管理员草稿',
                      ),
                      onChanged: (v) => setState(() {
                        if (v == true && selected.length < 2) {
                          selected.add('${card['id']}');
                        } else {
                          selected.remove(card['id']);
                        }
                      }),
                    ),
                    if ('${card['cover_url'] ?? ''}'.isNotEmpty)
                      Image.network(
                        widget.api.resolveImageUrl(card['cover_url']),
                        headers: widget.api.authorizationHeaders,
                        height: 250,
                        fit: BoxFit.contain,
                        errorBuilder: (_, e, st) =>
                            const Text('封面暂不可用，请刷新或检查任务审核状态'),
                      ),
                    Text((card['features'] as Map? ?? {}).values.join(' · ')),
                    if (widget.admin) ...[
                      Text('${card['source_state']}'),
                      TextButton(
                        onPressed: () => edit(card),
                        child: const Text('编辑卡片／导入特征／保存封面'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _CardEditor extends StatefulWidget {
  const _CardEditor({required this.api, required this.revision, this.card});
  final HubApi api;
  final String revision;
  final Map? card;
  @override
  State<_CardEditor> createState() => _CardEditorState();
}

class _CardEditorState extends State<_CardEditor> {
  late final name = TextEditingController(
    text: widget.card?['character'] ?? '',
  );
  late final variant = TextEditingController(
    text: widget.card?['variant'] ?? 'default',
  );
  final job = TextEditingController(), image = TextEditingController();
  late Map<String, dynamic>? profile = widget.card?['profile'] == null
      ? null
      : Map<String, dynamic>.from(widget.card!['profile']);
  late bool published = widget.card?['published'] == true;
  bool busy = false;
  String? error;
  @override
  void dispose() {
    for (final c in [name, variant, job, image]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> importProfile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['json'],
        withData: true,
      );
      if (result == null) return;
      final bytes = result.files.single.bytes;
      if (bytes == null || bytes.length > 1000000) {
        throw const FormatException('请选择小于 1MB 的独立人物档案 JSON');
      }
      final value = jsonDecode(utf8.decode(bytes).replaceFirst('\uFEFF', ''));
      if (value is! Map || value['source'] is! Map || value['features'] is! Map) {
        throw const FormatException('需要双人实验室 profiles 目录内的单个人物档案');
      }
      if (!mounted) return;
      setState(() {
        profile = Map<String, dynamic>.from(value);
        name.text = '${value['source']['name']}';
        variant.text = '${value['source']['variant_id']}';
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.saveCharacterCard({
        'revision': widget.revision,
        'character': name.text.trim(),
        'variant': variant.text.trim(),
        'published': published,
        'profile': profile,
        'cover_job': job.text.trim(),
        'cover_image': image.text.trim(),
      });
      if (mounted) Navigator.pop(context, result);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = '$e';
          busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('角色卡片'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  decoration:
                      const InputDecoration(labelText: '现有角色预设名称（完整名称）'),
                ),
                TextField(
                  controller: variant,
                  decoration:
                      const InputDecoration(labelText: '造型 ID；默认填 default'),
                ),
                TextButton(
                  onPressed: busy ? null : importProfile,
                  child: const Text('导入双人实验室特征档案 JSON'),
                ),
                Text(profile == null
                    ? '未导入特征：读取当前预设建立角色卡'
                    : '已载入独立特征档案；保存时核对当前预设'),
                TextField(
                  controller: job,
                  decoration: const InputDecoration(
                    labelText: '封面来源：已完成的 Hub 任务 ID（可留空）',
                  ),
                ),
                TextField(
                  controller: image,
                  decoration: const InputDecoration(
                    labelText: '该任务的图片 ID（与任务 ID 一起填写）',
                  ),
                ),
                CheckboxListTile(
                  value: published,
                  onChanged: busy
                      ? null
                      : (v) => setState(() => published = v == true),
                  title: const Text('向已登录用户展示此卡片'),
                ),
                if (error != null)
                  SelectableText(
                    error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: busy ? null : () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: busy ? null : save,
            child: Text(busy ? '保存中…' : '保存'),
          ),
        ],
      );
}
