import 'package:flutter/material.dart';

import '../../core/session_store.dart';

class WorkstationChoicePage extends StatelessWidget {
  const WorkstationChoicePage(
      {required this.onSelect, this.loading = false, super.key});

  final ValueChanged<WindowsWorkspaceMode> onSelect;
  final bool loading;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('选择工作站')),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 800),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('AstrAutoAnima',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 32),
                  if (loading) const LinearProgressIndicator(),
                  Card(
                    child: ListTile(
                      key: const ValueKey('workstation.local'),
                      leading: const Icon(Icons.computer_outlined, size: 36),
                      title: const Text('本机工作站'),
                      subtitle: const Text('本机 ComfyUI 生成；不经过 AstrBot 或 QQ。'),
                      trailing: const Icon(Icons.arrow_forward_ios),
                      onTap: loading
                          ? null
                          : () => onSelect(WindowsWorkspaceMode.local),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Card(
                    child: ListTile(
                      key: const ValueKey('workstation.onlineAdmin'),
                      leading: const Icon(Icons.cloud_outlined, size: 36),
                      title: const Text('在线管理'),
                      subtitle: const Text('管理员令牌连接远程 Hub；使用完整管理功能。'),
                      trailing: const Icon(Icons.arrow_forward_ios),
                      onTap: loading
                          ? null
                          : () => onSelect(WindowsWorkspaceMode.onlineAdmin),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Card(
                    child: ListTile(
                      key: const ValueKey('workstation.onlineService'),
                      leading: const Icon(Icons.person_outline, size: 36),
                      title: const Text('在线服务'),
                      subtitle: const Text('用户令牌连接远程 Hub；使用轻量生图界面。'),
                      trailing: const Icon(Icons.arrow_forward_ios),
                      onTap: loading
                          ? null
                          : () => onSelect(WindowsWorkspaceMode.onlineService),
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text('三种模式的地址与令牌分别保存。切换页面不会停止已提交任务，也不会切换 Hub 进程的运行模式。',
                      textAlign: TextAlign.center),
                ],
              ),
            ),
          ),
        ),
      );
}
