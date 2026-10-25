import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/hub_api.dart';
import 'studio_view_native.dart'
    if (dart.library.js_interop) 'studio_view_web.dart';

class StudioWorkbench extends StatefulWidget {
  const StudioWorkbench({required this.api, super.key});
  final HubApi api;
  @override
  State<StudioWorkbench> createState() => _StudioWorkbenchState();
}

class _StudioWorkbenchState extends State<StudioWorkbench> {
  String? _sessionId;
  int _generation = 0;
  late Future<Uri> _launch = _connect();
  Future<Uri> _connect() async {
    final generation = ++_generation;
    final data = await widget.api.openStudioSession();
    final id = data['session_id'] as String;
    if (!mounted || generation != _generation) {
      await widget.api.closeStudioSession(id);
      throw StateError('页面已关闭');
    }
    _sessionId = id;
    final base = Uri.parse(widget.api.baseUrl);
    final uri = base.resolve(data['launch_path'] as String);
    if (uri.origin != base.origin ||
        uri.path != '/extensions/anima-lora-studio/launch') {
      throw StateError('工作台连接地址不符合预期');
    }
    return uri;
  }

  void _close() {
    final id = _sessionId;
    _sessionId = null;
    if (id != null) {
      unawaited(widget.api
          .closeStudioSession(id)
          .then<void>((_) {}, onError: (_) {}));
    }
  }

  @override
  void dispose() {
    _generation++;
    _close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('炼丹炉工作台'), actions: [
          IconButton(
              tooltip: '重新连接（不会停止训练）',
              icon: const Icon(Icons.refresh),
              onPressed: () {
                _close();
                setState(() => _launch = _connect());
              }),
        ]),
        body: FutureBuilder<Uri>(
            future: _launch,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return const Center(
                    child: Text('连接失败或会话失效，请检查 Studio 服务后重新连接。'));
              }
              if (!snapshot.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
              return StudioView(
                  key: ValueKey(snapshot.data.toString()), uri: snapshot.data!);
            }),
      );
}
