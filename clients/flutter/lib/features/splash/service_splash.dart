import 'dart:async';
import 'package:flutter/material.dart';
import 'oc_splash_scene.dart';

class ServiceSplash extends StatefulWidget {
  const ServiceSplash({required this.child, super.key});
  final Widget child;
  @override
  State<ServiceSplash> createState() => _ServiceSplashState();
}

class _ServiceSplashState extends State<ServiceSplash>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: OcSplashScene.duration)
        ..addStatusListener((status) {
          if (status == AnimationStatus.completed && mounted) _finish();
        });
  ImageStream? _stream;
  ImageStreamListener? _listener;
  ImageInfo? _imageInfo;
  Timer? _loadDeadline;
  bool _started = false;
  bool _finished = false;

  void _finish() {
    _loadDeadline?.cancel();
    _detachListener();
    if (!_finished) setState(() => _finished = true);
  }

  void _detachListener() {
    if (_listener != null) _stream?.removeListener(_listener!);
    _listener = null;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
      _loadDeadline?.cancel();
      _detachListener();
      _finished = true;
      return;
    }
    if (_started || _finished) return;
    _started = true;
    // Fail open if a missing or slow asset cannot be decoded promptly.
    _loadDeadline = Timer(const Duration(milliseconds: 1500), () {
      if (mounted) _finish();
    });
    _stream = const AssetImage(OcSplashScene.asset)
        .resolve(createLocalImageConfiguration(context));
    _listener = ImageStreamListener((info, synchronousCall) {
      if (!mounted || _finished) {
        info.dispose();
        return;
      }
      _loadDeadline?.cancel();
      _imageInfo?.dispose();
      _imageInfo = info;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || _finished) return;
        _detachListener();
        setState(() {});
        _controller.forward();
      });
    }, onError: (Object error, StackTrace? stack) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _finish();
      });
    });
    _stream!.addListener(_listener!);
  }

  @override
  void dispose() {
    _loadDeadline?.cancel();
    _detachListener();
    _imageInfo?.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final atlas = _imageInfo?.image;
    return AnimatedBuilder(
        animation: _controller,
        child: widget.child,
        builder: (context, child) => Stack(fit: StackFit.expand, children: [
              ExcludeSemantics(
                  excluding: !_finished,
                  child: ExcludeFocus(
                      excluding: !_finished,
                      child:
                          IgnorePointer(ignoring: !_finished, child: child))),
              if (!_finished)
                Positioned.fill(
                    child: Semantics(
                        label: 'AstrAutoAnima，欢迎回来',
                        child: BlockSemantics(
                            child: AbsorbPointer(
                                child: Opacity(
                          opacity: 1 -
                              const Interval(.86, 1, curve: Curves.easeInOut)
                                  .transform(_controller.value),
                          child: atlas == null
                              ? const ColoredBox(color: Color(0xFFF4F8FF))
                              : ExcludeSemantics(
                                  child: OcSplashScene(
                                      atlas: atlas,
                                      seconds: _controller.value * 2.6)),
                        ))))),
            ]));
  }
}
