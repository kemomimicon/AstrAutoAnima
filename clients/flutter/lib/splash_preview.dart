import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'features/splash/oc_splash_scene.dart';

// Run: flutter run -d chrome -t lib/splash_preview.dart
void main() => runApp(const MaterialApp(
    debugShowCheckedModeBanner: false, home: SplashPreview()));

class SplashPreview extends StatefulWidget {
  const SplashPreview({super.key});
  @override
  State<SplashPreview> createState() => _SplashPreviewState();
}

class _SplashPreviewState extends State<SplashPreview>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: OcSplashScene.duration);
  ui.Image? _atlas;
  String? _error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final bytes = await rootBundle.load(OcSplashScene.asset);
      final codec = await ui.instantiateImageCodec(
          bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes));
      final frame = await codec.getNextFrame();
      codec.dispose();
      if (!mounted) {
        frame.image.dispose();
        return;
      }
      setState(() => _atlas = frame.image);
      _controller.forward();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _atlas?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: const Color(0xFFE5EBF4),
        body: SafeArea(
            child: Center(
                child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(children: [
                const Text('OC · 开屏动画',
                    style: TextStyle(
                        fontSize: 18,
                        color: Color(0xFF354B70),
                        fontWeight: FontWeight.w600)),
                const SizedBox(height: 16),
                Expanded(
                    child: ClipRRect(
                        borderRadius: BorderRadius.circular(28),
                        child: AnimatedBuilder(
                            animation: _controller,
                            builder: (context, _) => _atlas == null
                                ? Center(child: Text(_error ?? '正在载入原画…'))
                                : Stack(fit: StackFit.expand, children: [
                                    const ColoredBox(
                                        color: Color(0xFFF6F7FB),
                                        child: Center(
                                            child: Text('进入 AstrAutoAnima',
                                                style: TextStyle(
                                                    color:
                                                        Color(0xFF354B70))))),
                                    Opacity(
                                        opacity: 1 -
                                            const Interval(.86, 1,
                                                    curve: Curves.easeInOut)
                                                .transform(_controller.value),
                                        child: OcSplashScene(
                                            atlas: _atlas!,
                                            seconds: _controller.value * 2.6)),
                                  ])))),
                const SizedBox(height: 12),
                AnimatedBuilder(
                    animation: _controller,
                    builder: (context, _) => Column(children: [
                          Slider(
                              value: _controller.value,
                              onChanged: (value) {
                                _controller.stop();
                                _controller.value = value;
                              }),
                          Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                    '${(_controller.value * 2.6).toStringAsFixed(2)} s / 2.60 s',
                                    style: const TextStyle(
                                        color: Color(0xFF60748F))),
                                FilledButton.tonal(
                                    onPressed: () =>
                                        _controller.forward(from: 0),
                                    child: const Text('重播动画')),
                              ]),
                        ])),
                const SizedBox(height: 8),
                const Text('探身 · 蓄力 · 轻跳 · 挥手 · 眨眼',
                    style: TextStyle(fontSize: 12, color: Color(0xFF60748F))),
              ])),
        ))),
      );
}
