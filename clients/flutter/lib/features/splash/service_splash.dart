import 'dart:math' as math;

import 'package:flutter/material.dart';

class ServiceSplash extends StatefulWidget {
  const ServiceSplash({required this.child, super.key});

  final Widget child;

  @override
  State<ServiceSplash> createState() => _ServiceSplashState();
}

class _ServiceSplashState extends State<ServiceSplash>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2300),
  )..forward();
  late final Animation<double> _characterOpacity = CurvedAnimation(
    parent: _controller,
    curve: const Interval(0.04, 0.40, curve: Curves.easeOut),
  );
  late final Animation<double> _characterScale = Tween<double>(
    begin: 0.82,
    end: 1,
  ).animate(
    CurvedAnimation(
      parent: _controller,
      curve: const Interval(0.04, 0.48, curve: Curves.easeOutBack),
    ),
  );
  late final Animation<double> _lineReveal = CurvedAnimation(
    parent: _controller,
    curve: const Interval(0.02, 0.48, curve: Curves.easeOutCubic),
  );
  late final Animation<double> _contentOpacity = CurvedAnimation(
    parent: _controller,
    curve: const Interval(0.76, 1, curve: Curves.easeIn),
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        final finished = _controller.value >= 1;
        final motionProgress = math.max(0, _controller.value - 0.42);
        final bob = math.sin(motionProgress * math.pi * 5) * 4;
        final tilt = math.sin(motionProgress * math.pi * 3) * 0.018;
        final breathe = 1 + math.sin(motionProgress * math.pi * 4) * 0.018;
        return Stack(
          fit: StackFit.expand,
          children: [
            Opacity(opacity: _contentOpacity.value, child: widget.child),
            if (!finished)
              ColoredBox(
                color: const Color(0xFF075DE8),
                child: Center(
                  child: FadeTransition(
                    opacity: _characterOpacity,
                    child: ScaleTransition(
                      scale: _characterScale,
                      child: Transform.translate(
                        offset: Offset(0, bob),
                        child: Transform.rotate(
                          angle: tilt,
                          child: Transform.scale(
                            scale: breathe,
                            child: ClipRect(
                              child: Align(
                                alignment: Alignment.bottomCenter,
                                heightFactor: _lineReveal.value,
                                child: const Icon(
                                  Icons.auto_awesome,
                                  size: 150,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}
