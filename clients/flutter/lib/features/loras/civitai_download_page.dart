import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import '../../core/civitai_input.dart';

class CivitaiDownloadPage extends StatefulWidget {
  const CivitaiDownloadPage({required this.api, super.key});
  final HubApi api;
  @override
  State<CivitaiDownloadPage> createState() => _CivitaiDownloadPageState();
}

class _CivitaiDownloadPageState extends State<CivitaiDownloadPage> {
  final _input = TextEditingController();
  final _directory = TextEditingController(text: 'anima_lora');
  final _words = TextEditingController();
  List<dynamic> _versions = [];
  bool _createDirectory = false;
  Map<String, dynamic>? _preview;
  List<dynamic> _jobs = [];
  String _message = '';
  bool _busy = false;
  bool _polling = false;
  Timer? _timer;
  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _input.dispose();
    _directory.dispose();
    _words.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_polling) return;
    _polling = true;
    try {
      final result = await widget.api.civitaiDownloads();
      if (mounted) {
        setState(() {
          _jobs = result['jobs'] as List<dynamic>? ?? [];
          if (result['enabled'] != true) {
            _message = '服务器未开启下载，请管理员设置 AAH_CIVITAI_DOWNLOAD_ENABLED=1。';
          }
        });
      }
    } catch (error) {
      if (mounted) setState(() => _message = '$error');
    } finally {
      _polling = false;
    }
  }

  Future<void> _run(Future<void> Function() work) async {
    setState(() {
      _busy = true;
      _message = '';
    });
    try {
      await work();
    } catch (error) {
      if (mounted) setState(() => _message = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _lookup() => _run(() async {
        setState(() {
          _versions = [];
          _preview = null;
        });
        final selection = parseCivitaiInput(_input.text);
        if (selection.versionId == null) {
          final model = selection.modelId;
          if (model != null) {
            final result = await widget.api.civitaiVersions(model);
            if (mounted) {
              setState(() {
                _versions = result['versions'] as List;
                _preview = null;
              });
            }
            return;
          }
        }
        final id = selection.versionId;
        if (id == null || id <= 0) {
          throw const FormatException(
              '请输入版本ID或带 modelVersionId 的模型链接（不是模型主页ID）。');
        }
        final result = await widget.api.previewCivitai(id);
        if (mounted) {
          setState(() {
            _preview = result;
            _words.text = (result['trained_words'] as List? ?? []).join(', ');
          });
        }
      });
  Future<void> _download(Map file) async {
    final directoryError = civitaiDirectoryError(_directory.text);
    if (directoryError != null) {
      setState(() => _message = directoryError);
      return;
    }
    final preview = _preview!;
    final hash = (file['hashes'] as Map?)?['SHA256']?.toString() ?? '';
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: const Text('确认下载到服务器'),
              content: Text(
                  '${file['name']}\n底模：${preview['base_model']}\n大小：${((file['sizeKB'] as num? ?? 0) / 1024).toStringAsFixed(1)} MiB\n请确认你拥有下载和使用该资源的权限。下载将占用服务器磁盘。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('下载'))
              ],
            ));
    if (confirmed != true || !mounted) return;
    await _run(() async {
      await widget.api.downloadCivitai(
          preview['id'] as int, file['id'] as int, hash,
          directory: _directory.text.trim(),
          createDirectory: _createDirectory,
          words: _words.text
              .split(',')
              .map((word) => word.trim())
              .where((word) => word.isNotEmpty)
              .toList());
      await _refresh();
    });
  }

  Widget _section(String title, IconData icon, List<Widget> children) => Card(
        margin: const EdgeInsets.only(bottom: 20),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Icon(icon, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 12),
              Expanded(
                  child: Text(title,
                      style: Theme.of(context).textTheme.titleMedium)),
            ]),
            const SizedBox(height: 20),
            ...children,
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Civitai LoRA 下载')),
        body: Center(
            child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 960),
                child: ListView(padding: const EdgeInsets.all(16), children: [
                  const Text(
                      '仅管理员可用。Token 只配置在服务器环境变量 AAH_CIVITAI_TOKEN，不要粘贴到这里。仅自动安装 Anima 的 safetensors LoRA。'),
                  const SizedBox(height: 20),
                  _section('1 · 粘贴模型链接', Icons.link, [
                    TextField(
                        key: const Key('civitai-model-link'),
                        controller: _input,
                        minLines: 3,
                        maxLines: 6,
                        keyboardType: TextInputType.multiline,
                        autocorrect: false,
                        enableSuggestions: false,
                        decoration: const InputDecoration(
                            border: OutlineInputBorder(),
                            alignLabelWithHint: true,
                            contentPadding: EdgeInsets.all(16),
                            labelText: '模型版本 ID / Civitai 模型链接',
                            hintText:
                                'https://civitai.com/models/…?modelVersionId=…',
                            helperMaxLines: 3,
                            helperText:
                                '支持 civitai.com / civitai.red 长链接；最多 8192 字符，不受目录限制')),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size.fromHeight(48)),
                        icon: const Icon(Icons.manage_search),
                        onPressed: _busy ? null : _lookup,
                        label: const Text('读取版本')),
                  ]),
                  if (_busy) const LinearProgressIndicator(),
                  if (_message.isNotEmpty)
                    Padding(
                        padding: const EdgeInsets.only(bottom: 20, top: 12),
                        child: SelectableText(_message)),
                  if (_versions.isNotEmpty)
                    _section('2 · 选择版本', Icons.layers_outlined, [
                      for (final version in _versions)
                        ListTile(
                            title: Text(
                                '${version['name']} · ${version['base_model']}'),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: _busy
                                ? null
                                : () => _run(() async {
                                      final result = await widget.api
                                          .previewCivitai(version['id'] as int);
                                      if (mounted) {
                                        setState(() {
                                          _preview = result;
                                          _words.text = (result['trained_words']
                                                      as List? ??
                                                  [])
                                              .join(', ');
                                        });
                                      }
                                    })),
                    ]),
                  if (_preview != null) ...[
                    _section('下载设置', Icons.tune, [
                      Text('${_preview!['name']} · ${_preview!['base_model']}'),
                      SelectableText(
                          '候选触发词：${(_preview!['trained_words'] as List? ?? []).join(', ')}'),
                      const SizedBox(height: 20),
                      TextField(
                          controller: _words,
                          minLines: 2,
                          maxLines: 5,
                          decoration: const InputDecoration(
                              border: OutlineInputBorder(),
                              alignLabelWithHint: true,
                              labelText: '推荐触发词（可编辑，英文逗号分隔）')),
                      const SizedBox(height: 24),
                      TextField(
                          key: const Key('civitai-save-directory'),
                          controller: _directory,
                          minLines: 2,
                          maxLines: 4,
                          onChanged: (_) => setState(() {}),
                          decoration: InputDecoration(
                              border: const OutlineInputBorder(),
                              alignLabelWithHint: true,
                              helperMaxLines: 4,
                              errorMaxLines: 3,
                              labelText: 'LoRA 根目录下的保存目录（不是模型网址）',
                              helperText:
                                  '默认 anima_lora；总长 200 字符，每层 80 字符且最多 240 UTF-8 字节',
                              errorText:
                                  civitaiDirectoryError(_directory.text))),
                      CheckboxListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('目录不存在时新建'),
                          value: _createDirectory,
                          onChanged: (v) =>
                              setState(() => _createDirectory = v ?? false)),
                      const Text(
                          '完成后自动扫描。请返回 LoRA 页设置分类、显示名及触发词，再到预设页建立角色或画风。'),
                    ]),
                    _section('选择文件并下载', Icons.download_outlined, [
                      for (final raw in (_preview!['files'] as List? ?? []))
                        ListTile(
                            title: Text('${raw['name']}'),
                            subtitle: Text(
                                '${raw['virusScanResult']} / ${raw['pickleScanResult']}'),
                            trailing: IconButton(
                                icon: const Icon(Icons.download),
                                onPressed: _busy
                                    ? null
                                    : () => _download(raw as Map))),
                    ]),
                  ],
                  _section('下载记录', Icons.history, [
                    const Text('临时文件不会被当作 LoRA 加载。'),
                    const SizedBox(height: 12),
                    if (_jobs.isEmpty)
                      const Padding(
                          padding: EdgeInsets.symmetric(vertical: 20),
                          child: Text('暂无下载任务，读取模型版本后即可开始。')),
                    for (final job in _jobs.reversed)
                      ListTile(
                          title:
                              Text('${job['model_name']} · ${job['status']}'),
                          subtitle: Text(
                              '${((job['downloaded'] as num? ?? 0) / 1048576).toStringAsFixed(1)} / ${((job['size_bytes'] as num? ?? 0) / 1048576).toStringAsFixed(1)} MiB\n${job['message'] ?? ''}'),
                          trailing: ['queued', 'downloading']
                                  .contains(job['status'])
                              ? IconButton(
                                  icon: const Icon(Icons.cancel),
                                  onPressed: _busy
                                      ? null
                                      : () => _run(() async {
                                            await widget.api
                                                .cancelCivitai('${job['id']}');
                                            await _refresh();
                                          }))
                              : ['failed', 'cancelled', 'interrupted']
                                      .contains(job['status'])
                                  ? IconButton(
                                      tooltip: '续传（重新验证版本哈希）',
                                      icon: const Icon(Icons.play_arrow),
                                      onPressed: _busy
                                          ? null
                                          : () => _run(() async {
                                                await widget.api.resumeCivitai(
                                                    '${job['id']}');
                                                await _refresh();
                                              }))
                                  : null),
                  ]),
                ]))),
      );
}
