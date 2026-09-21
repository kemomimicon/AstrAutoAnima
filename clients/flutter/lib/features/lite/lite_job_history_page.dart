import '../../core/courtyard_theme.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/job_image_store.dart';
import '../../core/models.dart';
import '../settings/settings_drawer.dart';
import 'remake_options_dialog.dart';

class LiteJobHistoryPage extends StatefulWidget {
  const LiteJobHistoryPage({required this.api, super.key});

  final HubApi api;

  @override
  State<LiteJobHistoryPage> createState() => _LiteJobHistoryPageState();
}

class _LiteJobHistoryPageState extends State<LiteJobHistoryPage> {
  final JobImageStore _imageStore = JobImageStore();
  late Future<RemoteJobPageResult> _jobs = _load();
  String _kind = '';
  String _status = '';
  int _page = 1;
  String _downloadDirectory = '';
  String _downloadDirectoryUri = '';
  bool _downloading = false;
  final Set<String> _liking = {};

  static const _kindLabels = <String, String>{
    '': '全部类型',
    'direct': '直接生图',
    'chinese': '中文生图',
    'reverse': '图片反推',
    'random': '来张好图',
    'chaos': '混沌时刻',
    'hq': 'HQ 高清',
    'refine': '放大精修',
    'remake': '重跑一张',
    'multi': '裸模多人图',
  };

  static const _statusLabels = <String, String>{
    '': '全部状态',
    'queued': '排队中',
    'running': '生成中',
    'succeeded': '已完成',
    'failed': '失败',
  };

  @override
  void initState() {
    super.initState();
    _loadDownloadDirectory();
  }

  Future<void> _loadDownloadDirectory() async {
    final settings = await _imageStore.loadSettings();
    if (!mounted) return;
    setState(() {
      _downloadDirectory = settings.directory;
      _downloadDirectoryUri = settings.directoryUri;
    });
  }

  Future<RemoteJobPageResult> _load() {
    return widget.api.getRemoteJobs(
      kind: _kind,
      status: _status,
      page: _page,
      pageSize: 20,
    );
  }

  void _refresh({bool resetPage = false}) {
    setState(() {
      if (resetPage) _page = 1;
      _jobs = _load();
    });
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

  Future<String> _resolveDirectory() async {
    if (_downloadDirectory.trim().isNotEmpty) return _downloadDirectory;
    final value = await _imageStore.defaultDirectory();
    final settings = await _imageStore.loadSettings();
    await _imageStore.saveSettings(
      JobDownloadSettings(
        autoDownload: settings.autoDownload,
        directory: value,
        directoryUri: settings.directoryUri,
      ),
    );
    if (mounted) setState(() => _downloadDirectory = value);
    return value;
  }

  Future<void> _chooseDirectory() async {
    if (!_imageStore.supportsDirectorySelection) {
      _notice('Web App 会使用 Safari 的下载目录，保存位置由浏览器管理。');
      return;
    }
    if (_imageStore.usesPublicDownloads) {
      try {
        final current = await _imageStore.loadSettings();
        final selected = await _imageStore.chooseAndroidDirectory(
          autoDownload: current.autoDownload,
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
    final settings = await _imageStore.loadSettings();
    await _imageStore.saveSettings(
      JobDownloadSettings(
        autoDownload: settings.autoDownload,
        directory: selected,
        directoryUri: settings.directoryUri,
      ),
    );
    if (!mounted) return;
    setState(() => _downloadDirectory = selected);
    _notice('图片保存目录已更新。');
  }

  Future<void> _resetDirectory() async {
    final current = await _imageStore.loadSettings();
    final settings = await _imageStore.resetAndroidDirectory(
      autoDownload: current.autoDownload,
    );
    if (!mounted) return;
    setState(() {
      _downloadDirectory = settings.directory;
      _downloadDirectoryUri = '';
    });
    _notice('已恢复默认保存目录 ${settings.directory}。');
  }

  Future<void> _download(RemoteJobResult job) async {
    if (job.images.isEmpty || _downloading) return;
    setState(() => _downloading = true);
    try {
      final directory = await _resolveDirectory();
      final paths = await _imageStore.saveAll(
        api: widget.api,
        job: job,
        directory: directory,
      );
      _notice(
        _imageStore.usesBrowserDownloads
            ? '已向浏览器提交 ${paths.length} 张图片下载'
            : '已保存 ${paths.length} 张图片到 $directory',
      );
    } on Exception catch (error) {
      _notice('保存图片失败：$error', error: true);
    } finally {
      if (mounted) setState(() => _downloading = false);
    }
  }

  Future<void> _like(RemoteJobResult job, String promptId) async {
    final key = '${job.id}:$promptId';
    if (!_liking.add(key)) return;
    setState(() {});
    try {
      if (job.likedPromptIds.contains(promptId)) {
        await widget.api.unfavoritePrompt(promptId);
        _notice('已取消收藏');
        _refresh();
        return;
      }
      final result =
          await widget.api.likeJobPrompt(jobId: job.id, promptId: promptId);
      _notice(
          result.action == 'already_liked' ? '这条模板已经收藏在 P 组。' : '已点赞并保存到 P 组。');
      _refresh();
    } on HubApiException catch (error) {
      _notice(error.message, error: true);
    } finally {
      _liking.remove(key);
      if (mounted) setState(() {});
    }
  }

  String _time(DateTime value) {
    final local = value.toLocal();
    String two(int number) => number.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  Color _statusColor(BuildContext context, String status) {
    return switch (status) {
      'succeeded' => Colors.green,
      'failed' => Theme.of(context).colorScheme.error,
      'running' => Colors.blue,
      _ => Colors.orange,
    };
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<RemoteJobPageResult>(
      future: _jobs,
      builder: (context, snapshot) {
        final data = snapshot.data;
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '跑图记录',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                      const SizedBox(height: 4),
                      Text('按类型和状态查看任务及图片 · 共 ${data?.total ?? 0} 条'),
                    ],
                  ),
                ),
                IconButton.filledTonal(
                  tooltip: '刷新记录',
                  onPressed: snapshot.connectionState == ConnectionState.waiting
                      ? null
                      : () => _refresh(),
                  icon: const CourtyardIcon(Icons.refresh),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    SizedBox(
                      width: 190,
                      child: DropdownButtonFormField<String>(
                        initialValue: _kind,
                        decoration: const InputDecoration(labelText: '任务分类'),
                        items: _kindLabels.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: (value) {
                          _kind = value ?? '';
                          _refresh(resetPage: true);
                        },
                      ),
                    ),
                    SizedBox(
                      width: 170,
                      child: DropdownButtonFormField<String>(
                        initialValue: _status,
                        decoration: const InputDecoration(labelText: '任务状态'),
                        items: _statusLabels.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: (value) {
                          _status = value ?? '';
                          _refresh(resetPage: true);
                        },
                      ),
                    ),
                    if (_imageStore.supportsDirectorySelection)
                      OutlinedButton.icon(
                        onPressed: _chooseDirectory,
                        icon: const CourtyardIcon(Icons.folder_outlined),
                        label: Text(
                          _imageStore.usesPublicDownloads ? '更改保存目录' : '保存目录',
                        ),
                      ),
                    if (_imageStore.usesPublicDownloads &&
                        _downloadDirectoryUri.isNotEmpty)
                      TextButton(
                        onPressed: _resetDirectory,
                        child: const Text('恢复默认'),
                      ),
                    if (_imageStore.usesBrowserDownloads)
                      const Text('图片会保存到 Safari 下载目录')
                    else if (_downloadDirectory.isNotEmpty)
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 360),
                        child: Text(
                          _downloadDirectory,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            if (snapshot.connectionState == ConnectionState.waiting)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(40),
                  child: CircularProgressIndicator(),
                ),
              )
            else if (snapshot.hasError)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text('读取跑图记录失败：${snapshot.error}'),
                ),
              )
            else if (data == null || data.items.isEmpty)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: Text('当前分类下还没有跑图记录。')),
                ),
              )
            else
              ...data.items.map(_jobCard),
            if (data != null && data.pages > 1)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    IconButton(
                      tooltip: '上一页',
                      onPressed: data.page <= 1
                          ? null
                          : () {
                              _page -= 1;
                              _refresh();
                            },
                      icon: const CourtyardIcon(Icons.chevron_left),
                    ),
                    Text('${data.page} / ${data.pages}'),
                    IconButton(
                      tooltip: '下一页',
                      onPressed: data.page >= data.pages
                          ? null
                          : () {
                              _page += 1;
                              _refresh();
                            },
                      icon: const CourtyardIcon(Icons.chevron_right),
                    ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _jobCard(RemoteJobResult job) {
    final statusColor = _statusColor(context, job.status);
    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  _kindLabels[job.kind] ?? job.kind,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Chip(
                  label: Text(_statusLabels[job.status] ?? job.status),
                  side: BorderSide(color: statusColor),
                ),
                Chip(label: Text(job.safetyCode)),
                if (job.profile.isNotEmpty) Chip(label: Text(job.profile)),
                Text(_time(job.createdAt)),
              ],
            ),
            const SizedBox(height: 8),
            SelectableText(job.commandPreview),
            const SizedBox(height: 6),
            Text('${job.targetLabel} · ${job.message}'),
            if (job.taskSuiteId.isNotEmpty) ...[
              for (final row in job.taskSuiteRows)
                Text(
                    '${row['index']}. ${row['character']} / ${row['style']} · ${row['status']}'),
              if (!job.isFinished)
                TextButton.icon(
                    icon: const Icon(Icons.stop_circle_outlined),
                    label: const Text('取消套组未执行项'),
                    onPressed: () async {
                      final yes = await showDialog<bool>(
                          context: context,
                          builder: (context) => AlertDialog(
                                  title: const Text('取消后续套组任务？'),
                                  content:
                                      const Text('正在生成的单项会完成，其余尚未提交的行不再执行。'),
                                  actions: [
                                    TextButton(
                                        onPressed: () =>
                                            Navigator.pop(context, false),
                                        child: const Text('返回')),
                                    FilledButton(
                                        onPressed: () =>
                                            Navigator.pop(context, true),
                                        child: const Text('确认取消'))
                                  ]));
                      if (yes != true) return;
                      try {
                        await widget.api.cancelTaskSuite(job.id);
                        if (mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('已请求取消未执行项')));
                        }
                      } catch (e) {
                        if (mounted) {
                          ScaffoldMessenger.of(context)
                              .showSnackBar(SnackBar(content: Text('$e')));
                        }
                      }
                    }),
            ],
            if (job.promptIds.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: job.promptIds.map((promptId) {
                  final liked = job.likedPromptIds.contains(promptId);
                  return Chip(
                      label:
                          SelectableText(liked ? '$promptId · 已收藏' : promptId));
                }).toList(),
              ),
            ],
            if (job.images.isNotEmpty) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: job.images
                    .map(
                      (image) =>
                          Column(mainAxisSize: MainAxisSize.min, children: [
                        if (image.taskSuiteIndex > 0)
                          Text('套组第 ${image.taskSuiteIndex} 项'),
                        InkWell(
                          onTap: () => _previewImage(image),
                          borderRadius: BorderRadius.circular(10),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(10),
                            child: Image.network(
                              widget.api.resolveUrl(image.downloadUrl),
                              headers: widget.api.authorizationHeaders,
                              width: 180,
                              height: 180,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => Container(
                                width: 180,
                                height: 180,
                                color: Theme.of(context)
                                    .colorScheme
                                    .surfaceContainerHighest,
                                alignment: Alignment.center,
                                child: const CourtyardIcon(
                                    Icons.broken_image_outlined),
                              ),
                            ),
                          ),
                        ),
                        Row(mainAxisSize: MainAxisSize.min, children: [
                          IconButton(
                              icon: const CourtyardIcon(Icons.refresh),
                              tooltip: '重跑一张',
                              onPressed: () async {
                                Map<String, dynamic> options = {};
                                if (showRemakeOptions.value) {
                                  final selected = await showDialog<
                                          Map<String, dynamic>>(
                                      context: context,
                                      builder: (context) =>
                                          RemakeOptionsDialog(api: widget.api));
                                  if (selected == null) return;
                                  options = selected;
                                }
                                try {
                                  await widget.api.remakeImage(job.id, image.id,
                                      options: options);
                                  if (mounted) _refresh();
                                } catch (error) {
                                  if (mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text('$error')));
                                  }
                                }
                              }),
                          if (image.promptId.isNotEmpty)
                            Text('词库编号：${image.promptId}'),
                          if (image.promptId.isNotEmpty ||
                              job.promptIds.length == 1)
                            IconButton(
                                tooltip: '点赞 / 取消收藏',
                                icon: CourtyardIcon(job.likedPromptIds.contains(
                                        image.promptId.isNotEmpty
                                            ? image.promptId
                                            : job.promptIds.first)
                                    ? Icons.thumb_up
                                    : Icons.thumb_up_outlined),
                                onPressed: () => _like(
                                    job,
                                    image.promptId.isNotEmpty
                                        ? image.promptId
                                        : job.promptIds.first)),
                          IconButton(
                              tooltip: '举报图片',
                              icon: const CourtyardIcon(
                                  Icons.warning_amber_rounded),
                              onPressed: () async {
                                final yes = await showDialog<bool>(
                                    context: context,
                                    builder: (context) => AlertDialog(
                                            title: const Text('举报这张图？'),
                                            content: const Text(
                                                '图片和关联提示词将发给管理员审核，不会自动删除词条。'),
                                            actions: [
                                              TextButton(
                                                  onPressed: () =>
                                                      Navigator.pop(
                                                          context, false),
                                                  child: const Text('取消')),
                                              FilledButton(
                                                  onPressed: () =>
                                                      Navigator.pop(
                                                          context, true),
                                                  child: const Text('举报'))
                                            ]));
                                if (yes != true) return;
                                try {
                                  await widget.api
                                      .reportImage(job.id, image.id);
                                  _notice('举报已提交');
                                } catch (error) {
                                  _notice('$error', error: true);
                                }
                              }),
                        ])
                      ]),
                    )
                    .toList(),
              ),
              const SizedBox(height: 12),
              FilledButton.tonalIcon(
                onPressed: _downloading ? null : () => _download(job),
                icon: const CourtyardIcon(Icons.download),
                label: Text('下载 ${job.images.length} 张图片'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _previewImage(RemoteJobImage image) {
    return showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        insetPadding: const EdgeInsets.all(16),
        child: Stack(
          children: [
            SizedBox(
              width: 900,
              height: MediaQuery.sizeOf(context).height * 0.82,
              child: InteractiveViewer(
                minScale: 0.5,
                maxScale: 5,
                child: Center(
                  child: Image.network(
                    widget.api.resolveUrl(image.downloadUrl),
                    headers: widget.api.authorizationHeaders,
                    fit: BoxFit.contain,
                    errorBuilder: (_, __, ___) => const Center(
                      child: Text('图片加载失败，请检查 Hub 连接。'),
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              top: 8,
              right: 8,
              child: IconButton.filled(
                tooltip: '关闭',
                onPressed: () => Navigator.pop(context),
                icon: const CourtyardIcon(Icons.close),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
