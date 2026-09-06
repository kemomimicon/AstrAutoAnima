import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/compshare_api.dart';

class CompShareInstancePage extends StatefulWidget {
  const CompShareInstancePage({super.key});

  @override
  State<CompShareInstancePage> createState() => _CompShareInstancePageState();
}

class _CompShareInstancePageState extends State<CompShareInstancePage> {
  final _store = CompShareConfigStore();
  final _publicKey = TextEditingController();
  final _privateKey = TextEditingController();
  final _region = TextEditingController();
  final _zone = TextEditingController();
  final _uhostId = TextEditingController();
  CompShareConfig _config = const CompShareConfig();
  CompShareInstance? _instance;
  bool _loading = true;
  bool _editing = false;
  bool _working = false;
  bool _showPrivateKey = false;
  String _startMode = '';
  String _error = '';

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _publicKey.dispose();
    _privateKey.dispose();
    _region.dispose();
    _zone.dispose();
    _uhostId.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final config = await _store.load();
    _fill(config);
    if (!mounted) return;
    setState(() {
      _config = config;
      _editing = !config.isConfigured;
      _loading = false;
    });
    if (config.isConfigured) await _refresh();
  }

  void _fill(CompShareConfig config) {
    _publicKey.text = config.publicKey;
    _privateKey.text = config.privateKey;
    _region.text = config.region;
    _zone.text = config.zone;
    _uhostId.text = config.uhostId;
  }

  CompShareConfig _fromFields() => CompShareConfig(
        publicKey: _publicKey.text.trim(),
        privateKey: _privateKey.text.trim(),
        region: _region.text.trim(),
        zone: _zone.text.trim(),
        uhostId: _uhostId.text.trim(),
      );

  Future<void> _save() async {
    final config = _fromFields();
    if (!config.isConfigured) {
      _notice('所有配置项都必须填写。', error: true);
      return;
    }
    await _store.save(config);
    if (!mounted) return;
    setState(() {
      _config = config;
      _editing = false;
      _instance = null;
      _error = '';
    });
    await _refresh();
  }

  Future<void> _refresh() async {
    if (_working || !_config.isConfigured) return;
    setState(() {
      _working = true;
      _error = '';
    });
    try {
      final instance = await CompShareApi(config: _config).describe();
      if (mounted) setState(() => _instance = instance);
    } on CompShareApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<bool> _confirm(String title, String content) async {
    return await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(title),
            content: Text(content),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('确认'),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _start() async {
    final label = switch (_startMode) {
      'A' => '无卡 2 核 4G',
      'B' => '无卡 8 核 16G',
      _ => 'GPU',
    };
    if (!await _confirm(
      '启动优云实例？',
      '实例将以 $label 模式启动，并可能开始产生计算费用。',
    )) {
      return;
    }
    await _operate(() => CompShareApi(config: _config).start(
          withoutGpuSpec: _startMode,
        ));
  }

  Future<void> _stop() async {
    final name =
        _instance?.name.isNotEmpty == true ? _instance!.name : _config.uhostId;
    if (!await _confirm(
      '关闭优云实例？',
      '将关闭 $name。Hub、AstrBot、ComfyUI 和 QQ 服务都会离线，管理端仍可通过优云 API 再次开机。',
    )) {
      return;
    }
    await _operate(() => CompShareApi(config: _config).stop());
  }

  Future<void> _operate(Future<void> Function() action) async {
    setState(() {
      _working = true;
      _error = '';
    });
    try {
      await action();
      _notice('操作已提交，正在刷新实例状态。');
      await Future<void>.delayed(const Duration(seconds: 2));
    } on CompShareApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
    await _refresh();
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

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    final instance = _instance;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('优云实例',
                        style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 4),
                    const Text('直接连接优云智算控制面，Hub 离线时仍可开机。'),
                  ],
                ),
              ),
              IconButton.filledTonal(
                tooltip: '刷新状态',
                onPressed: _working ? null : _refresh,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_error.isNotEmpty)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_error),
              ),
            ),
          if (_working) const LinearProgressIndicator(),
          if (!_editing && instance != null) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          instance.isRunning
                              ? Icons.cloud_done_outlined
                              : Icons.cloud_off_outlined,
                          color: instance.isRunning
                              ? Colors.green
                              : Theme.of(context).colorScheme.outline,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            instance.name.isEmpty ? instance.id : instance.name,
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                        ),
                        Chip(label: Text(instance.state)),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text('${instance.region} / ${instance.zone}'),
                    Text('${instance.gpuType} × ${instance.gpuCount}'),
                    if (instance.pricePerHour > 0)
                      Text(
                          '实例价格：¥${instance.pricePerHour.toStringAsFixed(2)} / 小时'),
                    const SizedBox(height: 16),
                    if (instance.isStopped) ...[
                      DropdownButtonFormField<String>(
                        initialValue: _startMode,
                        decoration: const InputDecoration(labelText: '启动模式'),
                        items: [
                          const DropdownMenuItem(
                              value: '', child: Text('GPU 模式')),
                          if (instance.supportWithoutGpuStart) ...const [
                            DropdownMenuItem(
                                value: 'A', child: Text('无卡 A · 2 核 4G')),
                            DropdownMenuItem(
                                value: 'B', child: Text('无卡 B · 8 核 16G')),
                          ],
                        ],
                        onChanged: (value) =>
                            setState(() => _startMode = value ?? ''),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: _working ? null : _start,
                        icon: const Icon(Icons.power_settings_new),
                        label: const Text('启动实例'),
                      ),
                    ] else if (instance.isRunning)
                      FilledButton.tonalIcon(
                        onPressed: _working ? null : _stop,
                        icon: const Icon(Icons.power_off_outlined),
                        label: const Text('关闭实例'),
                      )
                    else
                      Text('实例正在 ${instance.state}，请稍后刷新。'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
          ],
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('API 配置',
                            style: Theme.of(context).textTheme.titleMedium),
                      ),
                      if (!_editing)
                        TextButton.icon(
                          onPressed: () => setState(() => _editing = true),
                          icon: const Icon(Icons.edit_outlined),
                          label: const Text('修改'),
                        ),
                    ],
                  ),
                  if (_editing) ...[
                    TextField(
                      controller: _publicKey,
                      decoration:
                          const InputDecoration(labelText: 'Public Key'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _privateKey,
                      obscureText: !_showPrivateKey,
                      decoration: InputDecoration(
                        labelText: 'Private Key',
                        suffixIcon: IconButton(
                          onPressed: () => setState(
                              () => _showPrivateKey = !_showPrivateKey),
                          icon: Icon(_showPrivateKey
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _region,
                      decoration: const InputDecoration(
                        labelText: 'Region',
                        hintText: 'cn-wlcb',
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _zone,
                      decoration: const InputDecoration(
                        labelText: 'Zone',
                        hintText: 'cn-wlcb-01',
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _uhostId,
                      decoration: const InputDecoration(
                        labelText: '实例 ID',
                        hintText: 'uhost-xxxx',
                      ),
                    ),
                    const SizedBox(height: 14),
                    FilledButton.icon(
                      onPressed: _working ? null : _save,
                      icon: const Icon(Icons.lock_outline),
                      label: const Text('安全保存并验证'),
                    ),
                  ] else ...[
                    Text('实例：${_config.uhostId}'),
                    Text('区域：${_config.region} / ${_config.zone}'),
                    const Text('公钥与私钥保存在本机系统安全存储中。'),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 40),
        ],
      ),
    );
  }
}
