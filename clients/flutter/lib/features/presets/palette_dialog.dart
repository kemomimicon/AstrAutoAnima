import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/models.dart';

Future<Map<String, dynamic>?> showPalette(
        BuildContext context, HubApi api, Map<String, dynamic> style) =>
    showDialog<Map<String, dynamic>>(
        context: context, builder: (_) => _Palette(api: api, style: style));

class _Palette extends StatefulWidget {
  const _Palette({required this.api, required this.style});
  final HubApi api;
  final Map<String, dynamic> style;
  @override
  State<_Palette> createState() => _PaletteState();
}

class _PaletteState extends State<_Palette> {
  late final _loras = (widget.style['loras'] as List)
      .map((e) => Map<String, dynamic>.from(e as Map))
      .toList();
  late final _future = Future.wait(
      [widget.api.getLitePresets(), widget.api.getDeliveryTargets()]);
  late final _loraText = _loras
      .map((e) => TextEditingController(text: '${e['strength']}'))
      .toList();
  final _prompt = TextEditingController(
      text: '1girl, standing, outdoors, looking at viewer');
  final _strength = TextEditingController(text: '1');
  String _role = '';
  String? _target;
  String _status = '';
  bool _busy = false;
  @override
  void dispose() {
    _prompt.dispose();
    _strength.dispose();
    for (final controller in _loraText) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _run() async {
    if (_target == null || _prompt.text.trim().isEmpty) {
      setState(() => _status = '请选投递目标并填写试图提示词。');
      return;
    }
    final strength = double.tryParse(_strength.text);
    if (strength == null ||
        !strength.isFinite ||
        strength < -5 ||
        strength > 5) {
      setState(() => _status = '角色强度须在 -5 到 5 之间。');
      return;
    }
    if (_loraText.any((controller) {
      final value = double.tryParse(controller.text);
      return value == null || !value.isFinite || value < -5 || value > 5;
    })) {
      setState(() => _status = '画风强度须填写 -5 到 5 之间的有效数字。');
      return;
    }
    setState(() => _busy = true);
    try {
      final job = await widget.api.createRemoteJob({
        'target_id': _target,
        'kind': 'direct',
        'character': _role,
        'character_strength': strength,
        'prompt': _prompt.text.trim(),
        'safety_code': 'N',
        'trial_style': {
          ...widget.style,
          'name': '${widget.style['name'] ?? ''}'.isEmpty
              ? '临时调色盘'
              : widget.style['name'],
          'loras': _loras
        }
      });
      if (mounted) {
        setState(() => _status = '试图已排队：${job.id}；在跑图记录查看。未保存或覆盖任何预设。');
      }
    } catch (error) {
      if (mounted) setState(() => _status = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('调色盘 · 临时试图'),
        content: SizedBox(
            width: 640,
            height: 560,
            child: FutureBuilder<List<dynamic>>(
                future: _future,
                builder: (context, snapshot) {
                  if (!snapshot.hasData) {
                    return Center(
                        child: Text(snapshot.hasError
                            ? '${snapshot.error}'
                            : '读取角色与投递目标…'));
                  }
                  final presets = snapshot.data![0] as PresetListResult;
                  final targets = snapshot.data![1] as DeliveryTargetListResult;
                  return ListView(children: [
                    DropdownButtonFormField<String>(
                        initialValue: _role,
                        decoration: const InputDecoration(labelText: '试图角色'),
                        items: [
                          const DropdownMenuItem(
                              value: '', child: Text('不使用角色预设')),
                          ...presets.characters.map((e) => DropdownMenuItem(
                              value: e.name, child: Text(e.name)))
                        ],
                        onChanged: (value) =>
                            setState(() => _role = value ?? '')),
                    TextField(
                        controller: _strength,
                        decoration: const InputDecoration(
                            labelText: '角色LoRA强度（手填 -5～5）'),
                        onChanged: (_) => setState(() {})),
                    Slider(
                        value: (double.tryParse(_strength.text) ?? 1)
                            .clamp(0, 2.5),
                        min: 0,
                        max: 2.5,
                        onChanged: (v) => setState(
                            () => _strength.text = v.toStringAsFixed(2))),
                    for (var i = 0; i < _loras.length; i++) ...[
                      Text('${_loras[i]['path']}'),
                      TextField(
                          controller: _loraText[i],
                          decoration:
                              const InputDecoration(labelText: '画风强度（手填 -5～5）'),
                          onChanged: (v) {
                            final n = double.tryParse(v);
                            if (n != null && n.isFinite && n >= -5 && n <= 5) {
                              setState(() {
                                _loras[i]['strength'] = n;
                                _loras[i]['strength_clip'] = n;
                              });
                            }
                          }),
                      Slider(
                          value: (_loras[i]['strength'] as num)
                              .toDouble()
                              .clamp(0, 2.5),
                          min: 0,
                          max: 2.5,
                          onChanged: (v) => setState(() {
                                _loras[i]['strength'] = v;
                                _loras[i]['strength_clip'] = v;
                                _loraText[i].text = v.toStringAsFixed(2);
                              })),
                    ],
                    DropdownButtonFormField<String>(
                        decoration: const InputDecoration(labelText: '投递目标'),
                        items: targets.targets
                            .map((e) => DropdownMenuItem(
                                value: e.id, child: Text(e.label)))
                            .toList(),
                        onChanged: (v) => setState(() => _target = v)),
                    TextField(
                        controller: _prompt,
                        minLines: 2,
                        maxLines: 5,
                        decoration:
                            const InputDecoration(labelText: '临时试图提示词')),
                    Text(_status),
                  ]);
                })),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消调配')),
          FilledButton.tonal(
              onPressed: _busy ? null : _run, child: const Text('试跑一张（不保存）')),
          FilledButton(
              onPressed: () =>
                  Navigator.pop(context, {...widget.style, 'loras': _loras}),
              child: const Text('采用调配，返回编辑'))
        ],
      );
}
