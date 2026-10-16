import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/models.dart';
import '../presets/task_suites_page.dart';

class RemakeOptionsDialog extends StatefulWidget {
  const RemakeOptionsDialog({required this.api, super.key});
  final HubApi api;
  @override
  State<RemakeOptionsDialog> createState() => _RemakeOptionsDialogState();
}

class _RemakeOptionsDialogState extends State<RemakeOptionsDialog> {
  late final Future<PresetListResult> _presets = _loadPresets();
  bool _ready = false;
  Future<PresetListResult> _loadPresets() async {
    final result = await widget.api.getLitePresets();
    if (mounted) setState(() => _ready = true);
    return result;
  }

  final _adjustment = TextEditingController();
  String _character = '', _style = '', _ratio = '';
  bool _fixed = false;
  bool _suiteEnabled = false;
  String _suiteId = '';
  @override
  void dispose() {
    _adjustment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('重跑一张 · 当次调整'),
        content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
                child: FutureBuilder<PresetListResult>(
                    future: _presets,
                    builder: (context, snapshot) {
                      if (snapshot.hasError) {
                        return const Text('预设加载失败，请返回重试。');
                      }
                      if (!snapshot.hasData) {
                        return const Center(child: CircularProgressIndicator());
                      }
                      Widget select(
                              String label,
                              String value,
                              Iterable<String> names,
                              ValueChanged<String?> changed) =>
                          Padding(
                              padding: const EdgeInsets.only(bottom: 16),
                              child: DropdownButtonFormField<String>(
                                  initialValue: value,
                                  isExpanded: true,
                                  decoration: InputDecoration(labelText: label),
                                  items: [
                                    const DropdownMenuItem(
                                        value: '', child: Text('沿用原任务')),
                                    ...names
                                        .toSet()
                                        .where((n) => n.isNotEmpty)
                                        .map((n) => DropdownMenuItem(
                                            value: n, child: Text(n)))
                                  ],
                                  onChanged: changed));
                      return Column(mainAxisSize: MainAxisSize.min, children: [
                        SwitchListTile(
                            title: const Text('启用任务套组'),
                            value: _suiteEnabled,
                            onChanged: (v) =>
                                setState(() => _suiteEnabled = v)),
                        if (_suiteEnabled)
                          TaskSuiteSelector(
                              api: widget.api,
                              value: _suiteId,
                              onChanged: (v) => setState(() => _suiteId = v)),
                        if (!_suiteEnabled) ...[
                          select(
                              '角色',
                              _character,
                              snapshot.data!.characters.map((p) => p.name),
                              (v) => setState(() => _character = v ?? '')),
                          select(
                              '画风',
                              _style,
                              [
                                '随机模式',
                                ...snapshot.data!.styles.map((p) => p.name)
                              ],
                              (v) => setState(() => _style = v ?? '')),
                        ],
                        select(
                            '比例',
                            _ratio,
                            ['1:1', '2:3', '3:2', '9:16', '16:9'],
                            (v) => setState(() => _ratio = v ?? '')),
                        CheckboxListTile(
                            title: const Text('固定种子'),
                            subtitle: const Text('沿用原图种子；修改参数仍会影响画面'),
                            value: _fixed,
                            onChanged: (v) =>
                                setState(() => _fixed = v ?? false)),
                        TextField(
                            controller: _adjustment,
                            maxLines: 4,
                            maxLength: 4000,
                            decoration: const InputDecoration(
                                labelText: '补充调整提示词',
                                helperText: '文字修改需服务端已配置文本模型')),
                        const Text('以上修改仅本次有效，不保存为个人设置。'),
                      ]);
                    }))),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: !_ready || (_suiteEnabled && _suiteId.isEmpty)
                  ? null
                  : () => Navigator.pop(context, <String, dynamic>{
                        'character': _character,
                        'style': _style,
                        'ratio': _ratio,
                        'fixed_seed': _fixed,
                        'adjustment': _adjustment.text.trim(),
                        if (_suiteEnabled) 'task_suite_id': _suiteId,
                      }),
              child: const Text('提交重跑'))
        ],
      );
}
