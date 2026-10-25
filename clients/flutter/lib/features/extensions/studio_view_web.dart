import 'dart:ui_web' as ui;
import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

class StudioView extends StatefulWidget {
  const StudioView({required this.uri, super.key});
  final Uri uri;
  @override
  State<StudioView> createState() => _StudioViewState();
}

class _StudioViewState extends State<StudioView> {
  static int _count = 0;
  late final String _type = 'aaa-studio-${_count++}';
  late final web.HTMLIFrameElement _frame;
  @override
  void initState() {
    super.initState();
    _frame = web.HTMLIFrameElement()
      ..title = '炼丹炉工作台'
      ..src = widget.uri.toString()
      ..referrerPolicy = 'no-referrer'
      ..style.border = '0'
      ..style.width = '100%'
      ..style.height = '100%';
    ui.platformViewRegistry.registerViewFactory(_type, (_) => _frame);
  }

  @override
  void dispose() {
    _frame.src = 'about:blank';
    _frame.remove();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.uri.origin != web.window.location.origin) {
      return const Center(child: Text('请使用目标 Hub 提供的 Web App 打开炼丹炉；不支持跨站嵌入。'));
    }
    return HtmlElementView(viewType: _type);
  }
}
