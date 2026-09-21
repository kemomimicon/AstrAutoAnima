import 'dart:math' as math;
import 'dart:ui' as ui;

/// A rigid layer transform: rotation + translation only, never a deforming mesh.
class OcLayerTransform {
  const OcLayerTransform(this.name, this.cell, this.pivot, this.angle);
  final String name;
  final int cell;
  final ui.Offset pivot;
  final double angle;
  ui.Offset map(ui.Offset point) {
    final p = point - pivot;
    final c = math.cos(angle), s = math.sin(angle);
    return pivot + ui.Offset(p.dx * c - p.dy * s, p.dx * s + p.dy * c);
  }
}

class OcWaveMotion {
  static const start = .92;
  static const end = 2.02;
  static double smooth(double value) {
    final v = value.clamp(0.0, 1.0);
    return v * v * (3 - 2 * v);
  }

  static List<OcLayerTransform> layers(double seconds) {
    final local = (seconds - start).clamp(0.0, end - start);
    final envelope = smooth(local / .14) * smooth((end - start - local) / .17);
    final phase = local * math.pi * 4 / (end - start);
    return [
      OcLayerTransform('tail', 8, const ui.Offset(280, 339),
          .045 * math.sin(phase - .6) * envelope),
      const OcLayerTransform('body', 9, ui.Offset.zero, 0),
      const OcLayerTransform('head', 10, ui.Offset.zero, 0),
      OcLayerTransform('wave_arm', 11, const ui.Offset(126, 266),
          .22 * math.sin(phase) * envelope),
    ];
  }
}

class OcWaveRig {
  OcWaveRig(this.atlas);
  final ui.Image atlas;
  void paint(ui.Canvas canvas, ui.Paint paint, double seconds) {
    canvas.saveLayer(const ui.Rect.fromLTWH(0, 0, 320, 320), paint);
    canvas.save();
    canvas.translate(16, 9);
    canvas.scale(288 / 444);
    final layerPaint = ui.Paint()..filterQuality = ui.FilterQuality.high;
    for (final layer in OcWaveMotion.layers(seconds)) {
      canvas.save();
      canvas.translate(layer.pivot.dx, layer.pivot.dy);
      canvas.rotate(layer.angle);
      canvas.translate(-layer.pivot.dx, -layer.pivot.dy);
      final cw = atlas.width / 4, ch = atlas.height / 3;
      canvas.drawImageRect(
          atlas,
          ui.Rect.fromLTWH(
              (layer.cell % 4) * cw, (layer.cell ~/ 4) * ch, cw, ch),
          const ui.Rect.fromLTWH(0, 0, 444, 444),
          layerPaint);
      canvas.restore();
      if (layer.name == 'head') _paintWink(canvas, seconds);
    }
    canvas.restore();
    canvas.restore();
  }

  void _paintWink(ui.Canvas canvas, double seconds) {
    final local = seconds - OcWaveMotion.start;
    final wink = OcWaveMotion.smooth((local - .42) / .07) *
        (1 - OcWaveMotion.smooth((local - .52) / .1));
    if (wink <= 0) return;
    canvas.save();
    final eye = ui.Path()
      ..moveTo(154, 174)
      ..cubicTo(155, 150, 184, 147, 199, 161)
      ..cubicTo(211, 176, 198, 199, 178, 199)
      ..cubicTo(160, 200, 152, 191, 154, 174)
      ..close();
    canvas.clipPath(eye);
    final skin = ui.Paint()..color = const ui.Color(0xFFFFF1E7);
    canvas.drawRect(ui.Rect.fromLTRB(150, 146, 212, 146 + 31 * wink), skin);
    canvas.drawRect(ui.Rect.fromLTRB(150, 203 - 26 * wink, 212, 204), skin);
    if (wink > .65) {
      final lash = ui.Path()
        ..moveTo(156, 178)
        ..cubicTo(168, 166, 187, 166, 201, 178);
      canvas.drawPath(
          lash,
          ui.Paint()
            ..color =
                ui.Color.fromRGBO(68, 53, 54, ((wink - .65) / .35).clamp(0, 1))
            ..style = ui.PaintingStyle.stroke
            ..strokeWidth = 3.2
            ..strokeCap = ui.StrokeCap.round);
    }

    canvas.restore();
  }

  // The atlas is owned and disposed by the loading widget.
  void dispose() {}
}
