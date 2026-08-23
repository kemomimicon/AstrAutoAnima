import 'package:flutter/material.dart';

import '../../core/hub_api.dart';
import '../../core/models.dart';

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
                ],
              ),
              const SizedBox(height: 24),
              ServerReminderCard(
                enabled: widget.serverOnlineReminderEnabled,
                reachable: widget.serverReachable,
                onChanged: widget.onServerOnlineReminderChanged,
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
