import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/qq_command_builder.dart';
import 'bilingual_prompt_field.dart';

class QqCommandComposerPage extends StatefulWidget {
  const QqCommandComposerPage({super.key});

  @override
  State<QqCommandComposerPage> createState() => _QqCommandComposerPageState();
}

class _QqCommandComposerPageState extends State<QqCommandComposerPage> {
  static const _key = 'aaa_qq_command_templates_v1';
  final _prompt = TextEditingController();
  final _character = TextEditingController();
  final _style = TextEditingController();
  final _ratio = TextEditingController();
  String _kind = 'direct';
  String _safety = 'N';
  bool _fiveDraw = false;
  Map<String, dynamic> _templates = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final controller in [_prompt, _character, _style, _ratio]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    try {
      final value = jsonDecode(prefs.getString(_key) ?? '{}');
      if (value is Map && mounted) {
        setState(() => _templates = Map<String, dynamic>.from(value));
      }
    } on FormatException {
      // Invalid local templates never block copying a fresh command.
    }
  }

  Map<String, dynamic> _snapshot() => {
        'kind': _kind,
        'prompt': _prompt.text,
        'character': _character.text,
        'style': _style.text,
        'ratio': _ratio.text,
        'safety': _safety,
        'five_draw': _fiveDraw,
      };

  void _restore(Map<String, dynamic> value) => setState(() {
        _kind = value['kind'] as String? ?? 'direct';
        _prompt.text = value['prompt'] as String? ?? '';
        _character.text = value['character'] as String? ?? '';
        _style.text = value['style'] as String? ?? '';
        _ratio.text = value['ratio'] as String? ?? '';
        _safety = value['safety'] as String? ?? 'N';
        _fiveDraw = value['five_draw'] == true;
      });

  Future<void> _saveTemplate() async {
    final controller = TextEditingController();
    final name = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
              title: const Text('保存本机常用模板'),
              content: TextField(
                  controller: controller,
                  decoration: const InputDecoration(labelText: '模板名称')),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () =>
                        Navigator.pop(context, controller.text.trim()),
                    child: const Text('保存')),
              ],
            ));
    controller.dispose();
    if (name == null || name.isEmpty || name.length > 50) return;
    _templates[name] = _snapshot();
    await (await SharedPreferences.getInstance())
        .setString(_key, jsonEncode(_templates));
    if (mounted) setState(() {});
  }

  Future<void> _copy() async {
    try {
      final command = QqCommandBuilder.build(
        kind: _kind,
        prompt: _prompt.text,
        character: _character.text,
        style: _style.text,
        ratio: _ratio.text,
        safety: _safety,
        fiveDraw: _fiveDraw,
      );
      await Clipboard.setData(ClipboardData(text: command));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('指令已复制。打开 QQ，粘贴并发送给自己的 Bot。')));
      }
    } on FormatException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('个人部署 · QQ 指令')),
        body: ListView(padding: const EdgeInsets.all(18), children: [
          const Text('本页离线工作：只生成并复制文字，不连接 Hub、不保存令牌、不自动发送 QQ。'),
          const SizedBox(height: 14),
          DropdownButtonFormField<String>(
            initialValue: _kind,
            decoration: const InputDecoration(labelText: '任务类型'),
            items: const [
              DropdownMenuItem(value: 'direct', child: Text('直接生图 /aimg')),
              DropdownMenuItem(value: 'chinese', child: Text('中文生图 /aicn')),
              DropdownMenuItem(value: 'random', child: Text('来张好图')),
              DropdownMenuItem(value: 'hq', child: Text('HQ 高清 /ahq')),
            ],
            onChanged: (value) => setState(() => _kind = value ?? 'direct'),
          ),
          if (_kind == 'random') ...[
            DropdownButtonFormField<String>(
              initialValue: _safety,
              decoration: const InputDecoration(labelText: '抽取安全级别'),
              items: const ['N', 'H', 'S']
                  .map((value) =>
                      DropdownMenuItem(value: value, child: Text(value)))
                  .toList(),
              onChanged: (value) => setState(() => _safety = value ?? 'N'),
            ),
            SwitchListTile(
                title: const Text('五连抽'),
                value: _fiveDraw,
                onChanged: (value) => setState(() => _fiveDraw = value)),
          ],
          TextField(
              controller: _character,
              decoration: const InputDecoration(labelText: '角色预设（可选）')),
          TextField(
              controller: _style,
              decoration: const InputDecoration(labelText: '画风预设（可选）')),
          TextField(
              controller: _ratio,
              decoration: const InputDecoration(labelText: '比例（如 2:3，可选）')),
          const SizedBox(height: 12),
          BilingualPromptField(
              controller: _prompt,
              label: _kind == 'random' ? '补充提示词（可选）' : '提示词'),
          const SizedBox(height: 16),
          FilledButton.icon(
              onPressed: _copy,
              icon: const Icon(Icons.copy),
              label: const Text('复制 QQ 指令')),
          OutlinedButton(
              onPressed: _saveTemplate, child: const Text('保存为本机常用模板')),
          if (_templates.isNotEmpty)
            DropdownButtonFormField<String>(
              decoration: const InputDecoration(labelText: '载入本机模板'),
              items: _templates.keys
                  .map((name) =>
                      DropdownMenuItem(value: name, child: Text(name)))
                  .toList(),
              onChanged: (name) {
                final value = _templates[name];
                if (value is Map) _restore(Map<String, dynamic>.from(value));
              },
            ),
        ]),
      );
}
