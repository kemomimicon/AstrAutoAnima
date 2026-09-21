import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';
import 'napcat_login_dialog.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({
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
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  late Future<WorkstationStatus> _future = widget.api.getWorkstationStatus();
  WorkstationMetrics? _metrics;
  Object? _metricsError;
  bool _metricsLoading = false;
  Timer? _metricsTimer;

  @override
  void initState() {
    super.initState();
    _loadMetrics();
    _metricsTimer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => _loadMetrics(),
    );
  }

  @override
  void didUpdateWidget(covariant DashboardPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) {
      _metrics = null;
      _metricsError = null;
      _loadMetrics();
    }
  }

  @override
  void dispose() {
    _metricsTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadMetrics() async {
    if (_metricsLoading) return;
    _metricsLoading = true;
    try {
      final value = await widget.api.getWorkstationMetrics();
      if (!mounted) return;
      setState(() {
        _metrics = value;
        _metricsError = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _metricsError = error);
    } finally {
      if (mounted) {
        setState(() => _metricsLoading = false);
      } else {
        _metricsLoading = false;
      }
    }
  }

  void _refresh() {
    setState(() => _future = widget.api.getWorkstationStatus());
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<WorkstationStatus>(
      future: _future,
      builder: (context, snapshot) {
        return RefreshIndicator(
          onRefresh: () async {
            _refresh();
            await _future;
          },
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '工作站概览',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'AstrBot、ComfyUI 与资源状态',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                  IconButton.filledTonal(
                    tooltip: '刷新',
                    onPressed:
                        snapshot.connectionState == ConnectionState.waiting
                            ? null
                            : _refresh,
                    icon: const Icon(Icons.refresh),
                  ),
                  IconButton(
                      tooltip: 'NapCat 登录助手',
                      icon: const Icon(Icons.login),
                      onPressed: () => showDialog<void>(
                          context: context,
                          builder: (_) => NapcatLoginDialog(api: widget.api))),
                ],
              ),
              const SizedBox(height: 24),
              ServerReminderCard(
                enabled: widget.serverOnlineReminderEnabled,
                reachable: widget.serverReachable,
                onChanged: widget.onServerOnlineReminderChanged,
              ),
              const SizedBox(height: 18),
              _LiveMetricsPanel(
                metrics: _metrics,
                error: _metricsError,
                loading: _metricsLoading,
                onRefresh: _loadMetrics,
              ),
              const SizedBox(height: 18),
              if (snapshot.connectionState == ConnectionState.waiting)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(48),
                    child: CircularProgressIndicator(),
                  ),
                )
              else if (snapshot.hasError)
                _ErrorCard(error: snapshot.error, onRetry: _refresh)
              else if (snapshot.data case final data?) ...[
                _OverviewBanner(status: data),
                const SizedBox(height: 18),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 1100
                        ? 3
                        : constraints.maxWidth >= 650
                            ? 2
                            : 1;
                    final width =
                        (constraints.maxWidth - (columns - 1) * 14) / columns;
                    return Wrap(
                      spacing: 14,
                      runSpacing: 14,
                      children: data.probes
                          .map(
                            (probe) => SizedBox(
                              width: width,
                              child: _ProbeCard(probe: probe),
                            ),
                          )
                          .toList(),
                    );
                  },
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _LiveMetricsPanel extends StatelessWidget {
  const _LiveMetricsPanel({
    required this.metrics,
    required this.error,
    required this.loading,
    required this.onRefresh,
  });

  final WorkstationMetrics? metrics;
  final Object? error;
  final bool loading;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final data = metrics;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.monitor_heart_outlined,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '实时资源仪表',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      Text(
                        data == null
                            ? '正在读取工作站资源'
                            : '每 2 秒刷新 · ${_timeLabel(data.collectedAt)}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                if (loading)
                  const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                else
                  IconButton(
                    tooltip: '立即刷新资源数据',
                    onPressed: onRefresh,
                    icon: const Icon(Icons.refresh),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            if (data == null && error == null)
              const SizedBox(
                height: 118,
                child: Center(child: CircularProgressIndicator()),
              )
            else if (data == null)
              _MetricsUnavailable(error: error, onRetry: onRefresh)
            else ...[
              LayoutBuilder(
                builder: (context, constraints) {
                  final cards = <Widget>[
                    _MetricGaugeCard(
                      label: 'CPU',
                      percent: data.cpuPercent,
                      valueText: '${data.cpuPercent.toStringAsFixed(1)}%',
                      detail: _cpuDetail(data),
                      icon: Icons.memory,
                      color: Colors.blue,
                    ),
                    _MetricGaugeCard(
                      label: '系统内存',
                      percent: data.memory.utilizationPercent,
                      valueText:
                          '${data.memory.utilizationPercent.toStringAsFixed(1)}%',
                      detail:
                          '${_bytes(data.memory.usedBytes)} / ${_bytes(data.memory.totalBytes)}',
                      icon: Icons.storage_outlined,
                      color: Colors.teal,
                    ),
                    for (final gpu in data.gpus) ...[
                      _MetricGaugeCard(
                        label: data.gpus.length == 1
                            ? 'GPU 核心'
                            : 'GPU ${gpu.index} 核心',
                        percent: gpu.utilizationPercent ?? 0,
                        valueText: gpu.utilizationPercent == null
                            ? '不可用'
                            : '${gpu.utilizationPercent!.toStringAsFixed(0)}%',
                        detail: _gpuDetail(gpu),
                        icon: Icons.developer_board_outlined,
                        color: Colors.deepPurple,
                      ),
                      _MetricGaugeCard(
                        label: data.gpus.length == 1
                            ? '显存'
                            : 'GPU ${gpu.index} 显存',
                        percent: gpu.memoryUtilizationPercent,
                        valueText:
                            '${gpu.memoryUtilizationPercent.toStringAsFixed(1)}%',
                        detail:
                            '${_mib(gpu.memoryUsedMib)} / ${_mib(gpu.memoryTotalMib)}',
                        icon: Icons.video_settings_outlined,
                        color: Colors.orange,
                      ),
                    ],
                  ];
                  if (data.gpus.isEmpty) {
                    cards.add(const _NoGpuCard());
                  }
                  final columns = constraints.maxWidth >= 1050
                      ? 4
                      : constraints.maxWidth >= 620
                          ? 2
                          : 1;
                  final width =
                      (constraints.maxWidth - (columns - 1) * 12) / columns;
                  return Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: cards
                        .map((card) => SizedBox(width: width, child: card))
                        .toList(growable: false),
                  );
                },
              ),
              if (error != null) ...[
                const SizedBox(height: 10),
                Text(
                  '本次刷新失败，继续显示上次数据：$error',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }

  static String _timeLabel(DateTime value) {
    final local = value.toLocal();
    String two(int number) => number.toString().padLeft(2, '0');
    return '${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
  }

  static String _bytes(int value) {
    if (value <= 0) return '0 B';
    const gib = 1024 * 1024 * 1024;
    return '${(value / gib).toStringAsFixed(1)} GiB';
  }

  static String _mib(int value) {
    if (value >= 1024) return '${(value / 1024).toStringAsFixed(1)} GiB';
    return '$value MiB';
  }

  static String _cpuDetail(WorkstationMetrics data) {
    final load = data.loadAverage1m;
    return load == null
        ? '${data.cpuLogicalCount} 个逻辑核心'
        : '${data.cpuLogicalCount} 个逻辑核心 · Load ${load.toStringAsFixed(2)}';
  }

  static String _gpuDetail(GpuMetrics gpu) {
    final temperature = gpu.temperatureC;
    return temperature == null
        ? gpu.name
        : '${gpu.name} · ${temperature.toStringAsFixed(0)}°C';
  }
}

class _MetricGaugeCard extends StatelessWidget {
  const _MetricGaugeCard({
    required this.label,
    required this.percent,
    required this.valueText,
    required this.detail,
    required this.icon,
    required this.color,
  });

  final String label;
  final double percent;
  final String valueText;
  final String detail;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final target = (percent.clamp(0, 100) / 100).toDouble();
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            SizedBox(
              width: 74,
              height: 74,
              child: TweenAnimationBuilder<double>(
                tween: Tween<double>(end: target),
                duration: const Duration(milliseconds: 480),
                curve: Curves.easeOutCubic,
                builder: (context, value, _) => Stack(
                  fit: StackFit.expand,
                  children: [
                    CircularProgressIndicator(
                      value: value,
                      strokeWidth: 9,
                      strokeCap: StrokeCap.round,
                      color: color,
                      backgroundColor: color.withValues(alpha: 0.14),
                    ),
                    Center(child: Icon(icon, color: color, size: 26)),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(label, style: Theme.of(context).textTheme.titleMedium),
                  Text(
                    valueText,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          color: color,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  Text(
                    detail,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NoGpuCard extends StatelessWidget {
  const _NoGpuCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 106),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Theme.of(context).dividerColor),
      ),
      child: const Row(
        children: [
          Icon(Icons.videocam_off_outlined),
          SizedBox(width: 12),
          Expanded(child: Text('未检测到 NVIDIA GPU，显存仪表暂不可用')),
        ],
      ),
    );
  }
}

class _MetricsUnavailable extends StatelessWidget {
  const _MetricsUnavailable({required this.error, required this.onRetry});

  final Object? error;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(Icons.monitor_heart_outlined,
            color: Theme.of(context).colorScheme.error),
        const SizedBox(width: 12),
        Expanded(child: Text('资源数据暂不可用：$error')),
        TextButton(onPressed: onRetry, child: const Text('重试')),
      ],
    );
  }
}

class ServerReminderCard extends StatelessWidget {
  const ServerReminderCard({
    required this.enabled,
    required this.reachable,
    required this.onChanged,
    super.key,
  });

  final bool enabled;
  final bool? reachable;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final stateLabel = !enabled
        ? '未开启'
        : reachable == null
            ? '正在检测'
            : reachable!
                ? '服务器在线'
                : '服务器离线，等待恢复';
    return Card(
      child: CheckboxListTile(
        value: enabled,
        onChanged: (value) => onChanged(value ?? false),
        secondary: Icon(
          enabled ? Icons.notifications_active : Icons.notifications_none,
          color: enabled ? Theme.of(context).colorScheme.primary : null,
        ),
        title: const Text('服务器开启提醒'),
        subtitle: Text(
          '$stateLabel · 每 30 秒检测，仅在离线恢复后提醒一次',
        ),
        controlAffinity: ListTileControlAffinity.trailing,
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
      ),
    );
  }
}

class _OverviewBanner extends StatelessWidget {
  const _OverviewBanner({required this.status});

  final WorkstationStatus status;

  @override
  Widget build(BuildContext context) {
    final ready = status.status == 'ready';
    final offline = status.status == 'offline';
    final color = ready
        ? Colors.green
        : offline
            ? Colors.red
            : Colors.orange;
    final label = ready
        ? '工作站已就绪'
        : offline
            ? '核心服务离线'
            : '工作站部分可用';
    return Card(
      color: color.withValues(alpha: 0.09),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Container(
              width: 12,
              height: 52,
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(20),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 4),
                  Text('检查时间：${status.checkedAt.toLocal()}'),
                ],
              ),
            ),
            Icon(
              ready ? Icons.check_circle : Icons.warning_amber_rounded,
              color: color,
              size: 34,
            ),
          ],
        ),
      ),
    );
  }
}

class _ProbeCard extends StatelessWidget {
  const _ProbeCard({required this.probe});

  final ProbeStatus probe;

  static const labels = {
    'astrbot': 'AstrBot',
    'comfyui': 'ComfyUI',
    'comfy_bridge_plugin': '桥接插件',
    'prompt_pool': '提示词库',
    'presets': '角色与画风',
    'comfyui_disk': 'ComfyUI 磁盘',
    'output_disk': 'Output 磁盘',
    'nvidia_gpu': 'NVIDIA GPU',
  };

  @override
  Widget build(BuildContext context) {
    final color = probe.isOnline ? Colors.green : Colors.orange;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    labels[probe.name] ?? probe.name,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (probe.latencyMs != null)
                  Text(
                    '${probe.latencyMs} ms',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(probe.detail, maxLines: 3, overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.error, required this.onRetry});

  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(Icons.cloud_off, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 12),
            Text('$error', textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
