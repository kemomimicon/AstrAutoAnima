import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

class StudioView extends StatefulWidget {
  const StudioView({required this.uri, super.key});
  final Uri uri;
  @override
  State<StudioView> createState() => _StudioViewState();
}

class _StudioViewState extends State<StudioView> {
  WebViewController? _controller;
  String? _error;
  @override
  void initState() {
    super.initState();
    _setup().catchError((Object _) {
      if (mounted) {
        setState(() => _error = '无法启动工作台，请检查系统 WebView 或改用 Web App。');
      }
    });
  }

  Future<void> _setup() async {
    if (!Platform.isAndroid && !Platform.isIOS && !Platform.isMacOS) return;
    final controller = WebViewController();
    await controller.setJavaScriptMode(JavaScriptMode.unrestricted);
    await controller.enableZoom(true);
    await controller.setNavigationDelegate(NavigationDelegate(
      onNavigationRequest: (request) {
        final url = Uri.tryParse(request.url);
        if (request.url == 'about:blank') return NavigationDecision.navigate;
        return url != null &&
                (url.scheme == 'http' || url.scheme == 'https') &&
                url.origin == widget.uri.origin &&
                url.path.startsWith('/extensions/anima-lora-studio/')
            ? NavigationDecision.navigate
            : NavigationDecision.prevent;
      },
      onWebResourceError: (error) {
        if (error.isForMainFrame == true && mounted) {
          setState(() => _error = '页面连接中断，请返回后重新连接。');
        }
      },
    ));
    if (controller.platform is AndroidWebViewController) {
      await (controller.platform as AndroidWebViewController)
          .setOnShowFileSelector((params) async {
        final files = await FilePicker.platform.pickFiles(
            allowMultiple: params.mode == FileSelectorMode.openMultiple);
        return files?.files
                .where((f) => f.path != null)
                .map((f) => Uri.file(f.path!).toString())
                .toList() ??
            [];
      });
    }
    if (!mounted) return;
    setState(() => _controller = controller);
    await controller.loadRequest(widget.uri);
  }

  @override
  void dispose() {
    _controller?.loadRequest(Uri.parse('about:blank'));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (Platform.isWindows || Platform.isLinux) {
      return const Center(child: Text('此平台请使用 Hub 的 Web App 打开炼丹炉工作台。'));
    }
    if (_error != null) return Center(child: Text(_error!));
    if (_controller == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return WebViewWidget(controller: _controller!);
  }
}
