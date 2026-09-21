import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/models.dart';

class GalleryPage extends StatefulWidget {
  const GalleryPage({super.key, required this.api, this.admin = false});
  final HubApi api;
  final bool admin;
  @override
  State<GalleryPage> createState() => _GalleryPageState();
}

class _GalleryPageState extends State<GalleryPage> {
  Map<String, dynamic>? _data;
  String? _error;
  bool _busy = false;
  Timer? _timer;
  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (_data?['active'] == true && !_busy) _refresh();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final data = await widget.api.gallery();
      if (mounted) {
        setState(() {
          _data = data;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _configure() async {
    final original = _data!;
    setState(() => _busy = true);
    try {
      final presets = await widget.api.getPresets();
      final targets = await widget.api.getDeliveryTargets();
      if (!mounted) return;
      final config = await showDialog<Map<String, dynamic>>(
          context: context,
          builder: (_) => _GalleryConfigDialog(
                config: Map<String, dynamic>.from(original['config']),
                characters: presets.characters
                    .where((p) => !p.textOnly)
                    .map((p) => p.name)
                    .toList(),
                targets: targets.targets,
              ));
      if (config == null || !mounted) return;
      var confirmed = false;
      if ((original['items'] as List).isNotEmpty) {
        confirmed = await showDialog<bool>(
                context: context,
                builder: (context) => AlertDialog(
                      title: const Text('清理旧画廊并保存配置？'),
                      content: const Text(
                          '旧画廊预览将删除，不能从画廊恢复。普通任务历史、模型和上传图片不受影响；新预览需重新生成。'),
                      actions: [
                        TextButton(
                            onPressed: () => Navigator.pop(context, false),
                            child: const Text('取消')),
                        FilledButton(
                            onPressed: () => Navigator.pop(context, true),
                            child: const Text('确认清理并保存'))
                      ],
                    )) ??
            false;
        if (!confirmed) return;
      }
      final data = await widget.api.saveGallery({
        'revision': original['revision'],
        'config': config,
        'confirm_clear': confirmed
      });
      if (mounted) setState(() => _data = data);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _generate(List<String> styles, {int? slotIndex}) async {
    final revision = _data!['revision'] as String;
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: const Text('更新画廊预览？'),
              content: Text(
                  '${styles.isEmpty ? '全部预设画风' : styles.join('、')}，${slotIndex == null ? '每个画风生成四张' : '仅重绘第 ${slotIndex + 1} 张'}。新图生成并审核成功后替换、删除对应旧预览；失败保留旧图。占用正常生成队列，不发送 QQ。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('确认更新'))
              ],
            ));
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final data = await widget.api
          .generateGallery(revision, styles, slotIndex: slotIndex);
      if (mounted) {
        setState(() {
          _data = data;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = (_data?['items'] as List? ?? []).whereType<Map>();
    final config = _data?['config'] as Map? ?? {};
    final canGenerate =
        !_busy && _data?['ready'] == true && _data?['active'] != true;
    return Scaffold(
        appBar: AppBar(title: const Text('画风画廊'), actions: [
          IconButton(
              tooltip: '刷新画廊',
              onPressed: _busy ? null : _refresh,
              icon: const Icon(Icons.refresh))
        ]),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          if (_error != null)
            Text(_error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (_data == null && _error == null) const LinearProgressIndicator(),
          if (_data != null) ...[
            Text(
                '画廊模特：${config['model_kind'] == 'character' ? config['character'] : config['character_text']}'),
            if (_data!['ready'] != true)
              const Text('画廊尚未配置完整：四条固定串暂留空，不会生成图片。'),
            if (_data!['active'] == true)
              const ListTile(
                  leading: CircularProgressIndicator(),
                  title: Text('正在逐张更新画廊…')),
            if (widget.admin)
              Wrap(spacing: 12, children: [
                OutlinedButton(
                    onPressed: _busy ? null : _configure,
                    child: const Text('配置模特与固定串')),
                FilledButton(
                    onPressed: canGenerate ? () => _generate([]) : null,
                    child: const Text('更新全部画风（每个四张）')),
              ]),
            if (items.isEmpty)
              const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('尚无画风预览，等待管理员配置并生成。')),
            for (final item in items)
              Card(
                  child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ListTile(
                                contentPadding: EdgeInsets.zero,
                                title: Text('${item['style']}'),
                                trailing: widget.admin
                                    ? TextButton(
                                        onPressed: canGenerate
                                            ? () =>
                                                _generate(['${item['style']}'])
                                            : null,
                                        child: const Text('更新四张'))
                                    : null),
                            GridView.count(
                                crossAxisCount: 2,
                                shrinkWrap: true,
                                physics: const NeverScrollableScrollPhysics(),
                                childAspectRatio: 0.85,
                                mainAxisSpacing: 8,
                                crossAxisSpacing: 8,
                                children: [
                                  for (final slot in item['slots'] as List)
                                    _GallerySlot(
                                        key: ValueKey(
                                            '${slot['url']}-${slot['status']}-${slot['index']}'),
                                        api: widget.api,
                                        redraw: widget.admin && canGenerate
                                            ? () => _generate(
                                                ['${item['style']}'],
                                                slotIndex: slot['index'] as int)
                                            : null,
                                        slot: Map<String, dynamic>.from(slot))
                                ]),
                          ]))),
          ],
        ]));
  }
}

class _GallerySlot extends StatefulWidget {
  const _GallerySlot(
      {super.key, required this.api, required this.slot, this.redraw});
  final VoidCallback? redraw;
  final HubApi api;
  final Map<String, dynamic> slot;
  @override
  State<_GallerySlot> createState() => _GallerySlotState();
}

class _GallerySlotState extends State<_GallerySlot> {
  late final _image = widget.slot['url'] == null
      ? null
      : widget.api.galleryImage((widget.slot['url'] as String).split('/').last);
  @override
  Widget build(BuildContext context) => Column(children: [
        Text('固定串 ${(widget.slot['index'] as int) + 1}'),
        if (widget.redraw != null)
          TextButton.icon(
              onPressed: widget.redraw,
              icon: const Icon(Icons.refresh),
              label: const Text('重绘此张')),
        if (widget.slot['message'] != null) Text('${widget.slot['message']}'),
        Expanded(
            child: _image == null
                ? Center(
                    child: Text('${const {
                          'queued': '等待生成',
                          'running': '生成中',
                          'failed': '生成失败',
                          'interrupted': '已中断，请更新'
                        }[widget.slot['status']] ?? widget.slot['status']}\n${widget.slot['message'] ?? ''}'))
                : FutureBuilder(
                    future: _image,
                    builder: (context, snapshot) {
                      if (snapshot.hasError) {
                        return const Center(child: Text('图片不可用，请刷新或重新生成'));
                      }
                      if (!snapshot.hasData) {
                        return const Center(child: CircularProgressIndicator());
                      }
                      return InkWell(
                          onTap: () => showDialog<void>(
                              context: context,
                              builder: (context) => Dialog(
                                      child: Column(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                        Flexible(
                                            child: InteractiveViewer(
                                                child: Image.memory(
                                                    snapshot.data!,
                                                    fit: BoxFit.contain))),
                                        TextButton(
                                            onPressed: () =>
                                                Navigator.pop(context),
                                            child: const Text('关闭')),
                                      ]))),
                          child: Image.memory(snapshot.data!,
                              fit: BoxFit.contain,
                              errorBuilder: (_, error, stack) =>
                                  const Text('图片格式不可读取')));
                    })),
      ]);
}

class _GalleryConfigDialog extends StatefulWidget {
  const _GalleryConfigDialog(
      {required this.config, required this.characters, required this.targets});
  final Map<String, dynamic> config;
  final List<String> characters;
  final List<DeliveryTarget> targets;
  @override
  State<_GalleryConfigDialog> createState() => _GalleryConfigDialogState();
}

class _GalleryConfigDialogState extends State<_GalleryConfigDialog> {
  late String _kind = widget.config['model_kind'] as String;
  late String _character =
      widget.characters.contains(widget.config['character'])
          ? widget.config['character'] as String
          : '';
  late String _target =
      widget.targets.any((t) => t.id == widget.config['target_id'])
          ? widget.config['target_id'] as String
          : '';
  late final _text =
      TextEditingController(text: widget.config['character_text'] as String);
  late final _prompts = (widget.config['prompts'] as List)
      .map((p) => TextEditingController(text: p as String))
      .toList();
  @override
  void dispose() {
    _text.dispose();
    for (final p in _prompts) {
      p.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
          title: const Text('画廊配置'),
          content: SizedBox(
              width: 640,
              child: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Text('四条串可暂留空，配置齐全后才能生成。修改配置会清理旧画廊。'),
                DropdownButtonFormField<String>(
                    initialValue: _kind,
                    decoration: const InputDecoration(labelText: '模特来源'),
                    items: const [
                      DropdownMenuItem(
                          value: 'character', child: Text('角色 LoRA 预设')),
                      DropdownMenuItem(value: 'text', child: Text('角色文本'))
                    ],
                    onChanged: (v) => setState(() => _kind = v!)),
                if (_kind == 'character')
                  DropdownButtonFormField<String>(
                      initialValue: _character,
                      isExpanded: true,
                      decoration:
                          const InputDecoration(labelText: '固定模特（默认造型）'),
                      items: [
                        const DropdownMenuItem(value: '', child: Text('待选择')),
                        ...widget.characters.map(
                            (c) => DropdownMenuItem(value: c, child: Text(c)))
                      ],
                      onChanged: (v) => _character = v ?? ''),
                if (_kind == 'text')
                  TextField(
                      controller: _text,
                      maxLength: 10000,
                      maxLines: 3,
                      decoration: const InputDecoration(labelText: '角色文本提示词')),
                DropdownButtonFormField<String>(
                    initialValue: _target,
                    isExpanded: true,
                    decoration:
                        const InputDecoration(labelText: '任务身份目标（仅排队，不发 QQ）'),
                    items: [
                      const DropdownMenuItem(value: '', child: Text('待选择')),
                      ...widget.targets.map((t) =>
                          DropdownMenuItem(value: t.id, child: Text(t.label)))
                    ],
                    onChanged: (v) => _target = v ?? ''),
                if ((widget.config['default_prompts'] as List?)?.length == 4)
                  TextButton(
                      onPressed: () {
                        setState(() {
                          final defaults =
                              widget.config['default_prompts'] as List;
                          for (var i = 0; i < 4; i++) {
                            _prompts[i].text = defaults[i] as String;
                          }
                        });
                      },
                      child: const Text('填入四场景默认串（保存前可修改或取消）')),
                for (var i = 0; i < 4; i++)
                  Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: TextField(
                          controller: _prompts[i],
                          maxLength: 10000,
                          minLines: 2,
                          maxLines: 5,
                          decoration: InputDecoration(
                              labelText: '固定提示词 ${i + 1}', hintText: '暂留空'))),
              ]))),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, <String, dynamic>{
                      'prompts': _prompts.map((p) => p.text.trim()).toList(),
                      'model_kind': _kind,
                      'character': _kind == 'character' ? _character : '',
                      'character_text':
                          _kind == 'text' ? _text.text.trim() : '',
                      'target_id': _target
                    }),
                child: const Text('保存配置'))
          ]);
}
