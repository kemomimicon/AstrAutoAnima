import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'oc_wave_motion.dart';

/// Deterministic scene shared by the startup player and the art preview.
class OcSplashScene extends StatelessWidget {
  const OcSplashScene({required this.atlas, required this.seconds, super.key});
  final ui.Image atlas;
  final double seconds;
  static const duration = Duration(milliseconds: 2600);
  static const asset = 'assets/splash/oc_greeting_layered_atlas.png';

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: const Color(0xFFF4F8FF),
        child: LayoutBuilder(builder: (context, constraints) {
          final extent = math.min(
              320.0,
              math.min(
                  constraints.maxWidth * .88, constraints.maxHeight * .62));
          return Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
            SizedBox.square(
                dimension: extent,
                child: _OcCanvas(atlas: atlas, seconds: seconds)),
            const SizedBox(height: 18),
            const Text('AstrAutoAnima',
                style: TextStyle(
                    color: Color(0xFF354B70),
                    fontSize: 21,
                    fontWeight: FontWeight.w600,
                    letterSpacing: .7,
                    decoration: TextDecoration.none)),
            const SizedBox(height: 9),
            const Text('让灵感，轻轻跃入画面',
                style: TextStyle(
                    color: Color(0xFF8495AE),
                    fontSize: 12,
                    fontWeight: FontWeight.w400,
                    letterSpacing: 2,
                    decoration: TextDecoration.none)),
          ]));
        }),
      );
}

class _OcCanvas extends StatefulWidget {
  const _OcCanvas({required this.atlas, required this.seconds});
  final ui.Image atlas;
  final double seconds;
  @override
  State<_OcCanvas> createState() => _OcCanvasState();
}

class _OcCanvasState extends State<_OcCanvas> {
  late OcWaveRig _rig = OcWaveRig(widget.atlas);
  @override
  void didUpdateWidget(_OcCanvas oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.atlas != widget.atlas) {
      _rig.dispose();
      _rig = OcWaveRig(widget.atlas);
    }
  }

  @override
  void dispose() {
    _rig.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      CustomPaint(painter: _OcPainter(widget.atlas, widget.seconds, _rig));
}

class _OcPainter extends CustomPainter {
  _OcPainter(this.atlas, this.seconds, this.waveRig);
  final OcWaveRig waveRig;
  final ui.Image atlas;
  final double seconds;
  double ease(double start, double end) => Curves.easeOutCubic
      .transform(((seconds - start) / (end - start)).clamp(0, 1));

  @override
  void paint(Canvas canvas, Size size) {
    final t = seconds;
    canvas.save();
    canvas.scale(size.width / 320);
    final paint = Paint()..isAntiAlias = true;
    final reveal = ease(0, .25);
    canvas.drawCircle(
        const Offset(160, 161), 119, paint..color = const Color(0xFFE8F1FD));
    canvas.drawCircle(
        const Offset(160, 161), 106, paint..color = const Color(0xFFEDF5FE));
    canvas.drawArc(
        const Rect.fromLTWH(29, 30, 262, 262),
        -.7,
        1.3,
        false,
        paint
          ..color = const Color(0xFFD5E5F9)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.4);
    paint.style = PaintingStyle.fill;
    final hop = t >= .4 && t < .78 ? math.sin((t - .4) / .38 * math.pi) : 0.0;
    canvas.drawOval(
        Rect.fromCenter(
            center: const Offset(148, 294),
            width: (47 - hop * 12) * 2,
            height: 10 - hop * 3),
        paint..color = Color.fromRGBO(94, 126, 173, .13 * reveal));
    final sparkle = ease(.78, 1.03) * (1 - ease(2.05, 2.4));
    for (var i = 0; i < 4; i++) {
      final center = [
        const Offset(43, 127),
        const Offset(279, 109),
        const Offset(277, 231),
        const Offset(59, 244)
      ][i];
      final r =
          (i.isEven ? 6.0 : 4.0) * sparkle * (1 + .15 * math.sin(t * 5 + i));
      final path = Path()
        ..moveTo(center.dx, center.dy - r)
        ..quadraticBezierTo(
            center.dx + r * .22, center.dy - r * .22, center.dx + r, center.dy)
        ..quadraticBezierTo(
            center.dx + r * .22, center.dy + r * .22, center.dx, center.dy + r)
        ..quadraticBezierTo(
            center.dx - r * .22, center.dy + r * .22, center.dx - r, center.dy)
        ..quadraticBezierTo(
            center.dx - r * .22, center.dy - r * .22, center.dx, center.dy - r)
        ..close();
      canvas.drawPath(
          path,
          paint
            ..color =
                i.isEven ? const Color(0xFF8ABCE9) : const Color(0xFFE6BD86));
    }
    var frame = 0;
    if (t >= .24) frame = 1;
    if (t >= .40) frame = 2;
    if (t >= .78) frame = 3;
    if (t >= .92) frame = 4;
    if (t >= 2.02) frame = 7;
    final landing =
        t >= .78 && t < .92 ? math.sin((t - .78) / .14 * math.pi) : 0.0;
    final bob = t > .92 ? math.sin((t - .92) * math.pi * 3) * 1.5 : 0.0;
    final y = (1 - reveal) * 26 - hop * 27 + landing * 4 + bob;
    final scale = .92 + .08 * reveal;
    canvas.save();
    canvas.translate(160, 294 + y);
    canvas.scale(scale * (1 + landing * .04), scale * (1 - landing * .04));
    canvas.translate(-160, -294);
    final cw = atlas.width / 4;
    final ch = atlas.height / 3;
    // The jump has clear space below its feet; exclude the next row's ear tip.
    final sourceHeight = frame == 2 ? ch - 12 : ch;
    paint
      ..color = Color.fromRGBO(255, 255, 255, reveal)
      // White matte artwork composes cleanly with the ice-blue palette.
      // Avoids fragile cutout fringes while retaining the drawn outline.
      ..blendMode = BlendMode.multiply
      // Normalize the paper white so no rectangular matte is visible.
      ..colorFilter = const ColorFilter.matrix([
        1.06,
        0,
        0,
        0,
        0,
        0,
        1.06,
        0,
        0,
        0,
        0,
        0,
        1.06,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
      ])
      ..filterQuality = FilterQuality.high;
    if (t >= OcWaveMotion.start && t < OcWaveMotion.end) {
      waveRig.paint(canvas, paint, t);
    } else {
      canvas.drawImageRect(
          atlas,
          Rect.fromLTWH((frame % 4) * cw, (frame ~/ 4) * ch, cw, sourceHeight),
          Rect.fromLTWH(16, 9, 288, 288 * sourceHeight / ch),
          paint);
    }
    canvas.restore();
    canvas.restore();
  }

  @override
  bool shouldRepaint(_OcPainter oldDelegate) =>
      atlas != oldDelegate.atlas || seconds != oldDelegate.seconds;
}
