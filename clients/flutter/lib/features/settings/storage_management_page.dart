import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import '../../core/hub_api.dart';

class StorageManagementPage extends StatefulWidget {
  const StorageManagementPage({super.key, required this.api});
  final HubApi api;
  @override
  State<StorageManagementPage> createState() => _StorageManagementPageState();
}

class _StorageManagementPageState extends State<StorageManagementPage> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;
  final destination = TextEditingController(text: '/workspace/backups');
  final jobId = TextEditingController();
  final imageId = TextEditingController();
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    destination.dispose();
    jobId.dispose();
    imageId.dispose();
    super.dispose();
  }

  void message(String text) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
    }
  }

  Future<void> load() async {
    try {
      final result = await widget.api.imageStorage();
      if (mounted) {
        setState(() {
          data = result;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  Future<bool> confirm(String title, String body) async {
    if (!mounted) return false;
    return await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
                    title: Text(title),
                    content: SingleChildScrollView(child: Text(body)),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(context, false),
                          child: const Text('取消')),
                      FilledButton(
                          onPressed: () => Navigator.pop(context, true),
                          child: const Text('确认')),
                    ])) ??
        false;
  }

  Future<void> action(String area, bool archive) async {
    final areas = (data?['areas'] as List?) ?? [];
    final matches = areas.where((row) => row['id'] == area);
    final folders = matches.isEmpty
        ? <dynamic>[]
        : (matches.first['folders'] as List?) ?? <dynamic>[];
    final selected = folders.map((row) => row['name'] as String).toSet();
    if (folders.isNotEmpty) {
      final accepted = await showDialog<bool>(
          context: context,
          builder: (context) => StatefulBuilder(builder: (context, update) {
                return AlertDialog(
                    title: Text(archive ? '选择打包目录' : '选择清理目录'),
                    content: SizedBox(
                        width: 440,
                        child: SingleChildScrollView(
                            child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                              const Text('每项只包含该目录直属图片；子目录单独选择。打包保留目录结构。'),
                              Wrap(children: [
                                TextButton(
                                    onPressed: () => update(() =>
                                        selected.addAll(folders
                                            .map((r) => r['name'] as String))),
                                    child: const Text('全选')),
                                TextButton(
                                    onPressed: () => update(selected.clear),
                                    child: const Text('取消全选')),
                              ]),
                              for (final folder in folders)
                                CheckboxListTile(
                                    title: Text(folder['name'] == '.'
                                        ? '根目录直属图片'
                                        : '${folder['name']}'),
                                    subtitle: Text('${folder['count']} 张'),
                                    value: selected.contains(folder['name']),
                                    onChanged: (value) => update(() {
                                          if (value == true) {
                                            selected
                                                .add(folder['name'] as String);
                                          } else {
                                            selected.remove(folder['name']);
                                          }
                                        })),
                            ]))),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(context, false),
                          child: const Text('取消')),
                      FilledButton(
                          onPressed: selected.isEmpty
                              ? null
                              : () => Navigator.pop(context, true),
                          child: const Text('预览选定范围')),
                    ]);
              }));
      if (accepted != true || !mounted) return;
    }
    setState(() => busy = true);
    try {
      final preview = await widget.api.storageAction('preview', {
        'area': area,
        'include_recent': archive,
        if (folders.isNotEmpty) 'folders': selected.toList(),
      });
      if (preview['count'] == 0) {
        message('没有可操作图片（最近五分钟的文件受保护）');
        return;
      }
      if (!await confirm(archive ? '确认打包范围' : '清理风险警告',
          '${preview['warning']}\n\n${preview['count']} 张，${preview['bytes']} 字节\n${(preview['files'] as List).take(20).join('\n')}')) {
        return;
      }
      if (!archive &&
          !await confirm(
              '建议先打包', '本次尚未打包。仍继续将永久删除选定图片，可能使历史图片无法查看。建议取消后先打包。是否仍继续？')) {
        return;
      }
      if (!archive &&
          !await confirm(
              '最终确认删除', '永久删除本次清单中的 ${preview['count']} 张图片？不会删除模型、目录或任务记录。')) {
        return;
      }
      final result =
          await widget.api.storageAction(archive ? 'archive' : 'cleanup', {
        'area': area,
        'snapshot': preview['snapshot'],
        'confirmed': true,
        'acknowledge_unarchived': !archive,
        'destination': destination.text.trim(),
      });
      message(archive
          ? '校验完成，压缩包：${result['path']}'
          : '已清理 ${result['deleted']} 张图片');
      await load();
    } catch (e) {
      message('$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (data == null) {
      return Center(
          child: error == null
              ? const CircularProgressIndicator()
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(error!),
                  TextButton(onPressed: load, child: const Text('重试'))
                ]));
    }
    final config = Map<String, dynamic>.from(data!['config'] as Map);
    void change(String key, dynamic value) => setState(() {
          config[key] = value;
          data!['config'] = config;
        });
    const names = {
      'cache': '插件缓存图片',
      'random_style': '随机画风 · AAA-RandomStyle',
      'output': 'ComfyUI 普通输出',
      'author': '签名图片 · Author Pictures'
    };
    return ListView(padding: const EdgeInsets.all(16), children: [
      Row(children: [
        Text('储存管理', style: Theme.of(context).textTheme.headlineSmall),
        const Spacer(),
        IconButton(
            onPressed: busy ? null : load, icon: const Icon(Icons.refresh))
      ]),
      const Text('只处理明确列出的图片。随机画风目录独立统计，不纳入普通输出清理。画廊、模型、训练数据和配置不在清理范围内。'),
      DropdownButtonFormField<String>(
          initialValue: config['grouping'] as String,
          decoration: const InputDecoration(labelText: '新图片存储分组'),
          items: const [
            DropdownMenuItem(value: 'original', child: Text('沿用工作流')),
            DropdownMenuItem(value: 'style', child: Text('按画风')),
            DropdownMenuItem(value: 'character', child: Text('按角色')),
            DropdownMenuItem(value: 'user', child: Text('按用户'))
          ],
          onChanged: busy ? null : (v) => change('grouping', v)),
      SwitchListTile(
          title: const Text('清除新生成 PNG 内嵌元数据'),
          subtitle: const Text('保留像素和独立任务记录；不是删除图片。非 PNG 暂不支持。'),
          value: config['strip_metadata'] == true,
          onChanged: busy ? null : (v) => change('strip_metadata', v)),
      SwitchListTile(
          title: const Text('定期清理插件缓存'),
          subtitle:
              const Text('仅插件 outputs；不自动清理 ComfyUI 或随机画风。启用后按服务器时间执行，无需每次确认。'),
          value: config['scheduled'] == true,
          onChanged: busy
              ? null
              : (v) async {
                  if (!v ||
                      await confirm(
                          '启用自动永久清理？', '超过保留天数的插件缓存将自动删除，不保留副本；历史图片可能失效。')) {
                    change('scheduled', v);
                  }
                }),
      TextFormField(
          initialValue: '${config['retention_days']}',
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: '保留天数（1–3650）'),
          onChanged: (v) => change('retention_days', int.tryParse(v) ?? 0)),
      TextFormField(
          initialValue: '${config['cleanup_hour']}',
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: '执行小时（服务器时间 0–23）'),
          onChanged: (v) => change('cleanup_hour', int.tryParse(v) ?? -1)),
      FilledButton(
          onPressed: busy
              ? null
              : () async {
                  try {
                    await widget.api.storageAction('config', config);
                    message('设置已保存，新任务生效');
                  } catch (e) {
                    message('$e');
                  }
                },
          child: const Text('保存设置')),
      Text('最近自动清理状态：${data!['last_cleanup']}'),
      const Divider(),
      Text('签名水印', style: Theme.of(context).textTheme.titleLarge),
      OutlinedButton(
          onPressed: busy
              ? null
              : () async {
                  try {
                    final selected = await FilePicker.platform.pickFiles(
                        type: FileType.custom,
                        allowedExtensions: ['png'],
                        withData: true);
                    if (selected == null) return;
                    final bytes = selected.files.single.bytes;
                    if (bytes == null || bytes.length > 4000000) {
                      message('请选小于4MB的透明PNG');
                      return;
                    }
                    await widget.api.storageAction(
                        'signature', {'data': base64Encode(bytes)});
                    message('签名已上传，原有签名已替换');
                  } catch (e) {
                    message('$e');
                  }
                },
          child: const Text('上传透明签名 PNG')),
      SwitchListTile(
          title: const Text('管理员图片自动加签名'),
          subtitle: const Text('原图保留，签名副本独立保存；普通用户不自动添加。'),
          value: config['watermark'] == true,
          onChanged: (v) => change('watermark', v)),
      DropdownButtonFormField<String>(
          initialValue:
              (config['watermark_corner'] ?? 'bottom-right') as String,
          decoration: const InputDecoration(labelText: '水印位置'),
          items: const [
            DropdownMenuItem(value: 'top-left', child: Text('左上')),
            DropdownMenuItem(value: 'top-right', child: Text('右上')),
            DropdownMenuItem(value: 'bottom-left', child: Text('左下')),
            DropdownMenuItem(value: 'bottom-right', child: Text('右下'))
          ],
          onChanged: (v) => change('watermark_corner', v)),
      TextFormField(
          initialValue:
              (config['watermark_folder'] ?? 'Author Pictures') as String,
          decoration: const InputDecoration(
              labelText: '签名副本文件夹（ComfyUI output 下的单层名称）'),
          onChanged: (v) => change('watermark_folder', v)),
      FilledButton(
          onPressed: busy
              ? null
              : () async {
                  try {
                    await widget.api.storageAction('config', config);
                    message('设置已保存');
                    await load();
                  } catch (e) {
                    message('$e');
                  }
                },
          child: const Text('保存水印设置')),
      TextField(
          controller: jobId,
          decoration: const InputDecoration(labelText: '手动水印：Hub 任务 ID')),
      TextField(
          controller: imageId,
          decoration: const InputDecoration(labelText: '任务中的图片 ID')),
      OutlinedButton(
          onPressed: busy
              ? null
              : () async {
                  try {
                    final result = await widget.api.storageAction('watermark', {
                      'job_id': jobId.text.trim(),
                      'image_id': imageId.text.trim()
                    });
                    message('${result['message']}');
                    await load();
                  } catch (e) {
                    message('$e');
                  }
                },
          child: const Text('创建签名副本')),
      const Divider(),
      TextField(
          controller: destination,
          decoration: const InputDecoration(labelText: '服务器打包目标目录（必须已存在）')),
      for (final raw in data!['areas'] as List)
        Card(
            child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(names[raw['id']] ?? '${raw['id']}',
                          style: Theme.of(context).textTheme.titleMedium),
                      SelectableText('${raw['path']}'),
                      Text(
                          '${raw['count']} 张 · ${(raw['bytes'] / 1048576).toStringAsFixed(1)} MiB'),
                      Wrap(spacing: 12, children: [
                        OutlinedButton(
                            onPressed: busy
                                ? null
                                : () => action(raw['id'] as String, true),
                            child: const Text('打包')),
                        TextButton(
                            onPressed: busy
                                ? null
                                : () => action(raw['id'] as String, false),
                            child: const Text('清理'))
                      ]),
                    ]))),
      if (busy) const LinearProgressIndicator(),
    ]);
  }
}
