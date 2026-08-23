import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/command_builder.dart';
import '../../core/hub_api.dart';
import '../../core/job_image_store.dart';
import '../../core/models.dart';
import '../dashboard/dashboard_page.dart';

class LiteGeneratePage extends StatefulWidget {
  const LiteGeneratePage({
    required this.api,
    required this.serverOnlineReminderEnabled,
    required this.onServerOnlineReminderChanged,
    this.serverReachable,
    super.key,
  });

  final HubApi api;
  final bool serverOnlineReminderEnabled;
  final bool? serverReachable;
  final ValueChanged<bool> onServerOnlineReminderChanged;

  @override
  State<LiteGeneratePage> createState() => _LiteGeneratePageState();
}

class _LiteGeneratePageState extends State<LiteGeneratePage> {
  final JobImageStore _imageStore = JobImageStore();
  final Set<String> _autoDownloadedJobs = {};
  late Future<(PresetListResult, DeliveryTargetListResult)> _data = _loadData();
  final TextEditingController _promptController = TextEditingController();
  Timer? _jobTimer;
  ImageCommandKind _kind = ImageCommandKind.direct;
  bool _fiveDraw = false;
  bool _submitting = false;
  String _poolFilter = '';
  String _character = '';
  String _style = '';
  String _ratio = '';
  String _sampler = '';
  String _reversePreset = 'full';
  bool _customReverseCategories = false;
  final Set<String> _reverseCategories = {'scene', 'action'};
  bool _reverseOnly = false;
  String _profile = 'stable';
  String _parentJobId = '';
  double _enhanceScale = 1.25;
  double _enhanceDenoise = 0.28;
  Uint8List? _sourceImage;
  String _sourceImageName = '';
  String _sourceImageMime = '';
  bool _customSamplerParameters = false;
  int _steps = 30;
  double _cfg = 6.0;
  String _safety = 'N';
  String _targetId = '';
  RemoteJobResult? _job;
  bool _autoDownloadEnabled = false;
  String _downloadDirectory = '';
  String _downloadDirectoryUri = '';

  static const _poolFilters = <String, String>{
    '': '来源默认 · 按下方分级',
    'B': 'B · Basic',
    'G': 'G · Generate',
    'D': 'D · Discord',
    'C': 'C · Codex',
    'R': 'R · Reverse',
    'B/N': 'B/N',
    'D/N': 'D/N',
    'C/N': 'C/N',
    'C/H': 'C/H',
    'C/S': 'C/S（仅私聊）',
  };
  static const _ratios = [
    '',
    '1:1',
    '2:3',
    '3:2',
    '3:4',
    '4:3',
    '9:16',
    '16:9',
  ];
  static const _reversePresets = <String, String>{
    'full': '完整 · 综合角色、动作、场景与构图',
    'scene': '场景 · 环境与构图',
    'action': '动作 · 姿势与互动',
    'character': '角色 · 外观与服装',
    'safe': '安全 · 去除 NSFW 标签',
    'raw': '原始 · 合并 WD、CL 与 JoyCaption',
  };
  static const _reverseCategoryLabels = <String, String>{
    'scene': '场景',
    'action': '动作',
    'character': '角色',
    'appearance': '外观',
    'clothing': '服装',
    'composition': '构图',
    'other': '其他',
    'safety': '安全过滤',
  };

  @override
  void initState() {
    super.initState();
    unawaited(_loadDownloadSettings());
  }

  Future<void> _loadDownloadSettings() async {
    final settings = await _imageStore.loadSettings();
    if (!mounted) return;
    setState(() {
      _autoDownloadEnabled = settings.autoDownload;
      _downloadDirectory = settings.directory;
      _downloadDirectoryUri = settings.directoryUri;
    });
  }

  Future<void> _setAutoDownload(bool enabled) async {
    var directory = _downloadDirectory;
    if (enabled && directory.trim().isEmpty) {
      directory = await _imageStore.defaultDirectory();
    }
    await _imageStore.saveSettings(
      JobDownloadSettings(
        autoDownload: enabled,
        directory: directory,
        directoryUri: _downloadDirectoryUri,
      ),
    );
    if (!mounted) return;
    setState(() {
      _autoDownloadEnabled = enabled;
      _downloadDirectory = directory;
    });
  }

  Future<void> _chooseDownloadDirectory() async {
    if (_imageStore.usesPublicDownloads) {
      try {
        final selected = await _imageStore.chooseAndroidDirectory(
          autoDownload: _autoDownloadEnabled,
          initialUri: _downloadDirectoryUri,
        );
        if (selected == null || !mounted) return;
        setState(() {
          _downloadDirectory = selected.directory;
          _downloadDirectoryUri = selected.directoryUri;
        });
        _notice('图片保存目录已更新为 ${selected.directory}。');
      } on Exception catch (error) {
        _notice('无法使用所选目录：$error', error: true);
      }
      return;
    }
    final selected = await FilePicker.platform.getDirectoryPath(
      dialogTitle: '选择跑图保存目录',
      initialDirectory: _downloadDirectory.isEmpty ? null : _downloadDirectory,
    );
    if (selected == null || selected.trim().isEmpty) return;
    await _imageStore.saveSettings(
      JobDownloadSettings(
        autoDownload: _autoDownloadEnabled,
        directory: selected,
        directoryUri: _downloadDirectoryUri,
      ),
    );
    if (!mounted) return;
    setState(() => _downloadDirectory = selected);
    _notice('图片保存目录已更新。');
  }

  Future<void> _resetDownloadDirectory() async {
    final settings = await _imageStore.resetAndroidDirectory(
      autoDownload: _autoDownloadEnabled,
    );
    if (!mounted) return;
    setState(() {
      _downloadDirectory = settings.directory;
      _downloadDirectoryUri = '';
    });
    _notice('已恢复默认保存目录 ${settings.directory}。');
  }

  Future<void> _autoDownload(RemoteJobResult job) async {
    if (!_autoDownloadEnabled ||
        job.status != 'succeeded' ||
        job.images.isEmpty ||
        !_autoDownloadedJobs.add(job.id)) {
      return;
    }
    try {
      final directory = _downloadDirectory.trim().isEmpty
          ? await _imageStore.defaultDirectory()
          : _downloadDirectory;
      final paths = await _imageStore.saveAll(
        api: widget.api,
        job: job,
        directory: directory,
      );
      _notice('已自动保存 ${paths.length} 张图片到 $directory');
    } on Exception catch (error) {
      _notice('任务已完成，但自动保存失败：$error', error: true);
    }
  }

  Future<(PresetListResult, DeliveryTargetListResult)> _loadData() async {
    final presets = await widget.api.getLitePresets();
    final targets = await widget.api.getDeliveryTargets();
    return (presets, targets);
  }

  @override
  void dispose() {
    _jobTimer?.cancel();
    _promptController.dispose();
    super.dispose();
  }

  void _refresh() => setState(() => _data = _loadData());

  String _command() => buildImageCommand(
        kind: _kind,
        fiveDraw: _fiveDraw,
        poolFilter: _poolFilter.isEmpty ? _safety : _poolFilter,
        character: _character,
        style: _style,
        ratio: _ratio,
        sampler: _sampler,
        steps: _customSamplerParameters ? _steps : null,
        cfg: _customSamplerParameters ? _cfg : null,
        prompt: _promptController.text,
        reversePreset: _reversePreset,
        reverseCategories:
            _customReverseCategories ? _reverseCategories.toList() : const [],
        reverseOnly: _reverseOnly,
        profile: _profile,
        parentJobId: _parentJobId,
        scale:
            (_kind == ImageCommandKind.hq || _kind == ImageCommandKind.refine)
                ? _enhanceScale
                : null,
        denoise:
            (_kind == ImageCommandKind.hq || _kind == ImageCommandKind.refine)
                ? _enhanceDenoise
                : null,
      );

  String get _kindValue => switch (_kind) {
        ImageCommandKind.direct => 'direct',
        ImageCommandKind.chinese => 'chinese',
        ImageCommandKind.reverse => 'reverse',
        ImageCommandKind.random => 'random',
        ImageCommandKind.chaos => 'chaos',
        ImageCommandKind.hq => 'hq',
        ImageCommandKind.refine => 'refine',
      };

  Future<void> _pickSourceImage() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['jpg', 'jpeg', 'png', 'webp'],
      allowMultiple: false,
      withData: true,
    );
    if (result == null || result.files.isEmpty) return;
    final file = result.files.single;
    final bytes = file.bytes;
    if (bytes == null || bytes.isEmpty) {
      _notice('无法读取所选图片。', error: true);
      return;
    }
    if (bytes.length > 20 * 1024 * 1024) {
      _notice('图片不能超过 20 MiB。', error: true);
      return;
    }
    final extension = (file.extension ?? '').toLowerCase();
    final mime = switch (extension) {
      'jpg' || 'jpeg' => 'image/jpeg',
      'png' => 'image/png',
      'webp' => 'image/webp',
      _ => '',
    };
    if (mime.isEmpty) {
      _notice('仅支持 JPEG、PNG 和 WebP。', error: true);
      return;
    }
    setState(() {
      _sourceImage = bytes;
      _sourceImageName = file.name;
      _sourceImageMime = mime;
    });
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _command()));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          _kind == ImageCommandKind.reverse || _kind == ImageCommandKind.refine
              ? '指令已复制；在 QQ 使用时仍需同时附图或填写历史任务 ID。'
              : '指令已复制，可作为直投失败时的备用方式。',
        ),
      ),
    );
  }

  void _notice(String message, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error ? Theme.of(context).colorScheme.error : null,
      ),
    );
  }

  Future<void> _submit(List<DeliveryTarget> targets) async {
    final target = targets.where((item) => item.id == _targetId).firstOrNull;
    if (target == null) {
      _notice('请先选择投递目标。', error: true);
      return;
    }
    if ((_kind == ImageCommandKind.direct ||
            _kind == ImageCommandKind.chinese ||
            _kind == ImageCommandKind.hq) &&
        _promptController.text.trim().isEmpty) {
      _notice(
        _kind == ImageCommandKind.chinese
            ? '中文生图必须填写中文描述。'
            : '直接/HQ 生图必须填写提示词。',
        error: true,
      );
      return;
    }
    final imageMode =
        _kind == ImageCommandKind.reverse || _kind == ImageCommandKind.refine;
    if (imageMode &&
        _sourceImage == null &&
        !(_kind == ImageCommandKind.refine && _parentJobId.trim().isNotEmpty)) {
      _notice('图片反推/精修必须选择图片，精修也可以填写历史任务 ID。', error: true);
      return;
    }
    if (_kind == ImageCommandKind.reverse && target.isGroup) {
      _notice('反推内容由模型判级，为防止越界只能返图到私聊。', error: true);
      return;
    }
    final explicitSafety = RegExp(r'[NHS]')
        .allMatches(_poolFilter)
        .map((match) => match.group(0))
        .toSet();
    final effectiveSafety =
        explicitSafety.length == 1 ? explicitSafety.first! : _safety;
    if (_kind != ImageCommandKind.reverse &&
        target.isGroup &&
        effectiveSafety == 'S') {
      _notice('S 级内容只能发送到私聊目标。', error: true);
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认提交跑图任务'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('投递目标：${target.label}'),
            Text(
              _kind == ImageCommandKind.reverse
                  ? '内容级别：由反推模型判定（仅私聊）'
                  : '内容级别：$effectiveSafety',
            ),
            if (imageMode && _sourceImage != null)
              Text(
                  '${_kind == ImageCommandKind.refine ? '精修' : '反推'}图片：$_sourceImageName'),
            const SizedBox(height: 12),
            const Text('生成完成后，AstrBot 会主动把结果发送到该会话。'),
            const SizedBox(height: 12),
            SelectableText(_command()),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认提交'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _submitting = true);
    try {
      final job = await widget.api.createRemoteJob({
        'target_id': target.id,
        'kind': _kindValue,
        'five_draw': _fiveDraw,
        'pool_filter': _poolFilter,
        'character': _character,
        'style': _style,
        'ratio': _ratio,
        'sampler': _sampler,
        if (_customSamplerParameters) 'steps': _steps,
        if (_customSamplerParameters) 'cfg': _cfg,
        'prompt': _promptController.text.trim(),
        'safety_code': _safety,
        if (_kind == ImageCommandKind.reverse) ...{
          'reverse_preset': _reversePreset,
          'reverse_categories':
              _customReverseCategories ? _reverseCategories.toList() : [],
          'reverse_only': _reverseOnly,
          'source_image_name': _sourceImageName,
          'source_image_data':
              'data:$_sourceImageMime;base64,${base64Encode(_sourceImage!)}',
        },
        if (_kind == ImageCommandKind.hq ||
            _kind == ImageCommandKind.refine) ...{
          'profile': _profile,
          'scale': _enhanceScale,
          'denoise': _enhanceDenoise,
          if (_kind == ImageCommandKind.refine)
            'parent_job_id': _parentJobId.trim(),
          if (_kind == ImageCommandKind.refine && _sourceImage != null) ...{
            'source_image_name': _sourceImageName,
            'source_image_data':
                'data:$_sourceImageMime;base64,${base64Encode(_sourceImage!)}',
          },
        },
      });
      if (!mounted) return;
      setState(() => _job = job);
      _jobTimer?.cancel();
      _jobTimer = Timer.periodic(
        const Duration(seconds: 2),
        (_) => unawaited(_pollJob(job.id)),
      );
      unawaited(_pollJob(job.id));
    } on HubApiException catch (error) {
      _notice(error.message, error: true);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _pollJob(String id) async {
    try {
      final job = await widget.api.getRemoteJob(id);
      if (!mounted) return;
      setState(() => _job = job);
      if (job.isFinished) {
        _jobTimer?.cancel();
        _jobTimer = null;
        _notice(job.message, error: job.status == 'failed');
        await _autoDownload(job);
      }
    } on HubApiException catch (error) {
      _jobTimer?.cancel();
      _jobTimer = null;
      _notice('任务状态读取失败：${error.message}', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final chaos = _kind == ImageCommandKind.chaos;
    final random =
        _kind == ImageCommandKind.random || _kind == ImageCommandKind.chaos;
    final reverse = _kind == ImageCommandKind.reverse;
    final hq = _kind == ImageCommandKind.hq;
    final refine = _kind == ImageCommandKind.refine;
    final enhance = hq || refine;
    final chinese = _kind == ImageCommandKind.chinese;
    return FutureBuilder<(PresetListResult, DeliveryTargetListResult)>(
      future: _data,
      builder: (context, snapshot) {
        final presets = snapshot.data?.$1;
        final targets = snapshot.data?.$2.targets ?? const <DeliveryTarget>[];
        final characters =
            presets?.characters.map((item) => item.name).toList() ??
                const <String>[];
        final styles = presets?.styles.map((item) => item.name).toList() ??
            const <String>[];
        final selectedTarget =
            targets.where((item) => item.id == _targetId).firstOrNull;
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('快捷跑图',
                          style: Theme.of(context).textTheme.headlineMedium),
                      const SizedBox(height: 4),
                      const Text('一键提交到 Hub，完成后由 AstrBot 主动返图'),
                    ],
                  ),
                ),
                IconButton.filledTonal(
                  tooltip: '更新在线配置',
                  onPressed: snapshot.connectionState == ConnectionState.waiting
                      ? null
                      : _refresh,
                  icon: const Icon(Icons.sync),
                ),
              ],
            ),
            const SizedBox(height: 20),
            ServerReminderCard(
              enabled: widget.serverOnlineReminderEnabled,
              reachable: widget.serverReachable,
              onChanged: widget.onServerOnlineReminderChanged,
            ),
            const SizedBox(height: 12),
            Card(
              child: Column(
                children: [
                  SwitchListTile(
                    value: _autoDownloadEnabled,
                    onChanged: _setAutoDownload,
                    secondary: const Icon(Icons.download_for_offline_outlined),
                    title: const Text('生成完成后自动保存到本地'),
                    subtitle: Text(
                      _downloadDirectory.isEmpty
                          ? '开启后使用系统默认下载目录'
                          : _downloadDirectory,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.only(right: 12, bottom: 10),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        if (_imageStore.usesPublicDownloads &&
                            _downloadDirectoryUri.isNotEmpty)
                          TextButton(
                            onPressed: _resetDownloadDirectory,
                            child: const Text('恢复默认'),
                          ),
                        TextButton.icon(
                          onPressed: _chooseDownloadDirectory,
                          icon: const Icon(Icons.folder_outlined),
                          label: const Text('更改保存目录'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    DropdownButtonFormField<String>(
                      initialValue: _targetId,
                      decoration: const InputDecoration(labelText: '返图目标'),
                      items: [
                        const DropdownMenuItem(value: '', child: Text('请选择')),
                        ...targets.map(
                          (target) => DropdownMenuItem(
                            value: target.id,
                            child: Text(
                                '${target.label} · ${target.isGroup ? '群聊' : '私聊'}'),
                          ),
                        ),
                      ],
                      onChanged: (value) {
                        final next = targets
                            .where((item) => item.id == value)
                            .firstOrNull;
                        setState(() {
                          _targetId = value ?? '';
                          if ((next?.isGroup ?? false) && _safety == 'S') {
                            _safety = 'N';
                          }
                        });
                      },
                    ),
                    if (targets.isEmpty && snapshot.hasData)
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text('管理员尚未配置可投递目标。'),
                      ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<ImageCommandKind>(
                      initialValue: _kind,
                      decoration: const InputDecoration(labelText: '跑图方式'),
                      items: const [
                        DropdownMenuItem(
                            value: ImageCommandKind.direct,
                            child: Text('直接生图 /aimg')),
                        DropdownMenuItem(
                            value: ImageCommandKind.chinese,
                            child: Text('中文生图 /aicn')),
                        DropdownMenuItem(
                            value: ImageCommandKind.reverse,
                            child: Text('图片反推 /aip')),
                        DropdownMenuItem(
                            value: ImageCommandKind.hq,
                            child: Text('HQ 高清生图 /ahq')),
                        DropdownMenuItem(
                            value: ImageCommandKind.refine,
                            child: Text('放大精修 /arefine')),
                        DropdownMenuItem(
                            value: ImageCommandKind.random,
                            child: Text('来张好图')),
                        DropdownMenuItem(
                            value: ImageCommandKind.chaos, child: Text('混沌时刻')),
                      ],
                      onChanged: (value) => setState(() {
                        _kind = value ?? _kind;
                        if (_kind != ImageCommandKind.random &&
                            _kind != ImageCommandKind.chaos) {
                          _fiveDraw = false;
                          _poolFilter = '';
                        }
                        if (_kind == ImageCommandKind.hq) {
                          _profile = 'stable';
                          _enhanceScale = 1.25;
                          _enhanceDenoise = 0.28;
                        } else if (_kind == ImageCommandKind.refine) {
                          _profile = 'light';
                          _enhanceScale = 1.25;
                          _enhanceDenoise = 0.25;
                        }
                      }),
                    ),
                    if (!reverse) ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _safety,
                        decoration: const InputDecoration(labelText: '本次内容级别'),
                        items: const [
                          DropdownMenuItem(
                              value: 'N', child: Text('N · Normal')),
                          DropdownMenuItem(value: 'H', child: Text('H · NSFW')),
                          DropdownMenuItem(
                              value: 'S', child: Text('S · Sexual（仅私聊）')),
                        ],
                        onChanged: (value) {
                          if ((selectedTarget?.isGroup ?? false) &&
                              value == 'S') {
                            _notice('S 级内容只能发送到私聊目标。', error: true);
                            return;
                          }
                          setState(() => _safety = value ?? 'N');
                        },
                      ),
                    ],
                    if (random) ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _poolFilter,
                        decoration:
                            const InputDecoration(labelText: '提示词来源 / 显式分级'),
                        items: _poolFilters.entries
                            .map((entry) => DropdownMenuItem(
                                value: entry.key, child: Text(entry.value)))
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _poolFilter = value ?? ''),
                      ),
                      CheckboxListTile(
                        value: _fiveDraw,
                        onChanged: (value) =>
                            setState(() => _fiveDraw = value ?? false),
                        title: const Text('五连抽'),
                        subtitle: const Text('普通用户有 150 秒冷却'),
                        contentPadding: EdgeInsets.zero,
                      ),
                    ],
                    if (reverse) ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _reversePreset,
                        decoration: const InputDecoration(
                          labelText: '反推模式',
                          helperText: '决定从图片中保留哪些类别的提示词',
                        ),
                        items: _reversePresets.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: _customReverseCategories
                            ? null
                            : (value) => setState(
                                  () => _reversePreset = value ?? 'full',
                                ),
                      ),
                      SwitchListTile(
                        value: _customReverseCategories,
                        onChanged: (value) => setState(() {
                          _customReverseCategories = value;
                          if (value && _reverseCategories.isEmpty) {
                            _reverseCategories.addAll({'scene', 'action'});
                          }
                        }),
                        title: const Text('自定义分类复选'),
                        subtitle: const Text('可同时返回场景、动作、角色、构图等多类结果'),
                        contentPadding: EdgeInsets.zero,
                      ),
                      if (_customReverseCategories) ...[
                        Wrap(
                          spacing: 8,
                          runSpacing: 6,
                          children: _reverseCategoryLabels.entries.map((entry) {
                            final selected =
                                _reverseCategories.contains(entry.key);
                            return FilterChip(
                              label: Text(entry.value),
                              selected: selected,
                              onSelected: (value) => setState(() {
                                if (value) {
                                  _reverseCategories.add(entry.key);
                                } else if (_reverseCategories.length > 1) {
                                  _reverseCategories.remove(entry.key);
                                } else {
                                  _notice('至少保留一个反推分类。', error: true);
                                }
                              }),
                            );
                          }).toList(),
                        ),
                        const SizedBox(height: 6),
                      ],
                      CheckboxListTile(
                        value: _reverseOnly,
                        onChanged: (value) =>
                            setState(() => _reverseOnly = value ?? false),
                        title: const Text('只返回反推提示词，不跑图'),
                        subtitle: const Text('返回分类结果、合并提示词、安全级别和记录 ID'),
                        contentPadding: EdgeInsets.zero,
                      ),
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: _submitting ? null : _pickSourceImage,
                        icon: const Icon(Icons.add_photo_alternate_outlined),
                        label: Text(
                          _sourceImage == null ? '选择反推图片' : '重新选择图片',
                        ),
                      ),
                      if (_sourceImage case final bytes?) ...[
                        const SizedBox(height: 10),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ClipRRect(
                              borderRadius: BorderRadius.circular(12),
                              child: Image.memory(
                                bytes,
                                width: 96,
                                height: 96,
                                fit: BoxFit.cover,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    _sourceImageName,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    '${(bytes.length / 1024 / 1024).toStringAsFixed(2)} MiB',
                                  ),
                                  TextButton.icon(
                                    onPressed: () => setState(() {
                                      _sourceImage = null;
                                      _sourceImageName = '';
                                      _sourceImageMime = '';
                                    }),
                                    icon: const Icon(Icons.close),
                                    label: const Text('移除'),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ],
                      if (selectedTarget?.isGroup ?? false)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            '反推结果可能被判定为 NSFW/S，因此客户端只允许投递到私聊。',
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                        ),
                    ],
                    if (enhance) ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _profile,
                        decoration: InputDecoration(
                          labelText: hq ? 'HQ Profile' : '精修 Profile',
                          helperText: 'Profile 表示参数策略，不会切换到另一份工作流拓扑',
                        ),
                        items: hq
                            ? const [
                                DropdownMenuItem(
                                  value: 'stable',
                                  child: Text('Stable · 稳定保角色/画风'),
                                ),
                                DropdownMenuItem(
                                  value: 'beauty',
                                  child: Text('Beauty · 更强成品观感（Beta）'),
                                ),
                              ]
                            : const [
                                DropdownMenuItem(
                                  value: 'light',
                                  child: Text('Light · 1.25x 低重绘'),
                                ),
                                DropdownMenuItem(
                                  value: 'medium',
                                  child: Text('Medium · 1.5x 中低重绘（Beta）'),
                                ),
                              ],
                        onChanged: (value) => setState(() {
                          _profile = value ?? (hq ? 'stable' : 'light');
                          if (_profile == 'stable') {
                            _enhanceScale = 1.25;
                            _enhanceDenoise = 0.28;
                          } else if (_profile == 'beauty') {
                            _enhanceScale = 1.5;
                            _enhanceDenoise = 0.30;
                          } else if (_profile == 'light') {
                            _enhanceScale = 1.25;
                            _enhanceDenoise = 0.25;
                          } else {
                            _enhanceScale = 1.5;
                            _enhanceDenoise = 0.35;
                          }
                        }),
                      ),
                      const SizedBox(height: 8),
                      Text('放大倍率：${_enhanceScale.toStringAsFixed(2)}x'),
                      Slider(
                        value: _enhanceScale,
                        min: 1.0,
                        max: 2.0,
                        divisions: 20,
                        label: _enhanceScale.toStringAsFixed(2),
                        onChanged: (value) =>
                            setState(() => _enhanceScale = value),
                      ),
                      Text('重绘强度：${_enhanceDenoise.toStringAsFixed(2)}'),
                      Slider(
                        value: _enhanceDenoise,
                        min: 0.0,
                        max: 1.0,
                        divisions: 100,
                        label: _enhanceDenoise.toStringAsFixed(2),
                        onChanged: (value) =>
                            setState(() => _enhanceDenoise = value),
                      ),
                      if (refine) ...[
                        TextField(
                          decoration: const InputDecoration(
                            labelText: '历史任务 ID（可选）',
                            helperText: '填写 job_xxx 可恢复原 Prompt、LoRA 与父子关系',
                          ),
                          onChanged: (value) => _parentJobId = value,
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          onPressed: _submitting ? null : _pickSourceImage,
                          icon: const Icon(Icons.auto_fix_high_outlined),
                          label: Text(
                            _sourceImage == null ? '选择待精修图片' : '重新选择待精修图片',
                          ),
                        ),
                        if (_sourceImage case final bytes?) ...[
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(12),
                                child: Image.memory(
                                  bytes,
                                  width: 96,
                                  height: 96,
                                  fit: BoxFit.cover,
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(child: Text(_sourceImageName)),
                              IconButton(
                                tooltip: '移除',
                                onPressed: () => setState(() {
                                  _sourceImage = null;
                                  _sourceImageName = '';
                                  _sourceImageMime = '';
                                }),
                                icon: const Icon(Icons.close),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ],
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: _character,
                      decoration: InputDecoration(
                          labelText: '角色',
                          helperText: chaos ? '混沌时刻会随机角色' : null),
                      items: [
                        const DropdownMenuItem(value: '', child: Text('不指定')),
                        ...characters.map((name) =>
                            DropdownMenuItem(value: name, child: Text(name))),
                      ],
                      onChanged: chaos
                          ? null
                          : (value) => setState(() => _character = value ?? ''),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: _style,
                      decoration: InputDecoration(
                          labelText: '画风',
                          helperText: chaos ? '混沌时刻会随机画风' : null),
                      items: [
                        const DropdownMenuItem(value: '', child: Text('不指定')),
                        ...styles.map((name) =>
                            DropdownMenuItem(value: name, child: Text(name))),
                      ],
                      onChanged: chaos
                          ? null
                          : (value) => setState(() => _style = value ?? ''),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: _ratio,
                      decoration: InputDecoration(
                          labelText: '画面比例',
                          helperText: chaos ? '混沌时刻会随机比例' : null),
                      items: _ratios
                          .map((ratio) => DropdownMenuItem(
                              value: ratio,
                              child: Text(ratio.isEmpty ? '默认 2:3' : ratio)))
                          .toList(),
                      onChanged: chaos
                          ? null
                          : (value) => setState(() => _ratio = value ?? ''),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: _sampler,
                      decoration: const InputDecoration(
                        labelText: '采样器预设',
                        helperText: 'DPM 预设默认 30 步、CFG 6',
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: '',
                          child: Text('原有 · 沿用工作流采样器'),
                        ),
                        DropdownMenuItem(
                          value: '2m',
                          child: Text('DPM++ 2M · 30 步 · CFG 6'),
                        ),
                        DropdownMenuItem(
                          value: '2m_sde',
                          child: Text('DPM++ 2M SDE · 30 步 · CFG 6'),
                        ),
                        DropdownMenuItem(
                          value: '2m_sde_gpu',
                          child: Text('DPM++ 2M SDE GPU · 30 步 · CFG 6'),
                        ),
                      ],
                      onChanged: (value) => setState(() {
                        _sampler = value ?? '';
                        if (!_customSamplerParameters) {
                          _steps = 30;
                          _cfg = _sampler.isEmpty ? 5.0 : 6.0;
                        }
                      }),
                    ),
                    SwitchListTile(
                      value: _customSamplerParameters,
                      onChanged: (value) => setState(() {
                        _customSamplerParameters = value;
                        if (value) {
                          _steps = 30;
                          _cfg = _sampler.isEmpty ? 5.0 : 6.0;
                        }
                      }),
                      title: const Text('自定义 Steps 与 CFG'),
                      subtitle: const Text('关闭时跟随工作流或采样器预设'),
                      contentPadding: EdgeInsets.zero,
                    ),
                    if (_customSamplerParameters) ...[
                      Text('Steps：$_steps'),
                      Slider(
                        value: _steps.toDouble(),
                        min: 1,
                        max: 200,
                        divisions: 199,
                        label: '$_steps',
                        onChanged: (value) =>
                            setState(() => _steps = value.round()),
                      ),
                      Text('CFG：${_cfg.toStringAsFixed(1)}'),
                      Slider(
                        value: _cfg,
                        min: 0,
                        max: 30,
                        divisions: 60,
                        label: _cfg.toStringAsFixed(1),
                        onChanged: (value) => setState(() => _cfg = value),
                      ),
                    ],
                    const SizedBox(height: 12),
                    TextField(
                      controller: _promptController,
                      minLines: 4,
                      maxLines: 10,
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        labelText: reverse
                            ? _reverseOnly
                                ? '附加提示词（可选，仅追加到返回的合并提示词）'
                                : '额外提示词（可选，会追加到反推结果）'
                            : refine
                                ? '补充/覆盖提示词（历史任务可留空）'
                                : chinese
                                    ? '中文描述'
                                    : random
                                        ? '补充提示词（可选）'
                                        : '提示词',
                        alignLabelWithHint: true,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: SelectableText(_command()),
                    ),
                    if (_job case final job?) ...[
                      const SizedBox(height: 14),
                      _JobStatusCard(job: job),
                    ],
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      onPressed:
                          snapshot.hasData && targets.isNotEmpty && !_submitting
                              ? () => _submit(targets)
                              : null,
                      icon: _submitting
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.send_outlined),
                      label: Text(
                        _submitting
                            ? '正在提交…'
                            : reverse && _reverseOnly
                                ? '发送并仅反推'
                                : '发送并生成',
                      ),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: snapshot.hasError ? null : _copy,
                      icon: const Icon(Icons.copy_all_outlined),
                      label: const Text('仅复制指令（备用）'),
                    ),
                    if (snapshot.connectionState == ConnectionState.waiting)
                      const Padding(
                          padding: EdgeInsets.only(top: 12),
                          child: LinearProgressIndicator()),
                    if (snapshot.hasError)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text('配置同步失败：${snapshot.error}',
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _JobStatusCard extends StatelessWidget {
  const _JobStatusCard({required this.job});

  final RemoteJobResult job;

  @override
  Widget build(BuildContext context) {
    final (icon, color, label) = switch (job.status) {
      'queued' => (Icons.schedule, Colors.orange, '排队中'),
      'running' => (Icons.auto_awesome, Colors.blue, '生成中'),
      'succeeded' => (Icons.check_circle, Colors.green, '已发送'),
      _ => (Icons.error, Colors.red, '失败'),
    };
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 12),
          Expanded(child: Text('$label · ${job.message}')),
        ],
      ),
    );
  }
}
