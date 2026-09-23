import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/features/splash/oc_splash_scene.dart';
import 'package:astr_auto_anima_hub_client/features/splash/service_splash.dart';
import 'package:astr_auto_anima_hub_client/features/splash/oc_wave_motion.dart';

class _MissingSplashBundle extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) async => throw StateError('Missing atlas');
}

void main() {
  test('wave uses independent rigid layers and leaves the head unchanged', () {
    final points = [
      const ui.Offset(111, 194),
      const ui.Offset(185, 174),
      const ui.Offset(260, 195),
      const ui.Offset(365, 75)
    ];
    var previous = OcWaveMotion.layers(OcWaveMotion.start);
    for (var frame = 1; frame <= 66; frame++) {
      final layers = OcWaveMotion.layers(OcWaveMotion.start + frame / 60);
      expect(layers.map((layer) => layer.name),
          ['tail', 'body', 'head', 'wave_arm']);
      for (final layer in layers) {
        for (var i = 1; i < points.length; i++) {
          expect((layer.map(points[i]) - layer.map(points[0])).distance,
              closeTo((points[i] - points[0]).distance, 1e-8),
              reason: '${layer.name} must not stretch');
        }
        if (layer.name == 'head' || layer.name == 'body') {
          for (final point in points) {
            expect(layer.map(point), point);
          }
        }
      }
      expect((layers.last.angle - previous.last.angle).abs(), lessThan(.09));
      previous = layers;
    }
    final peak = OcWaveMotion.layers(1.08).last;
    expect(peak.angle.abs(), greaterThan(.15));
    expect(OcWaveMotion.layers(OcWaveMotion.end).last.angle, closeTo(0, 1e-10));
  });
  testWidgets('missing artwork cannot block entry', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
        home: DefaultAssetBundle(
      bundle: _MissingSplashBundle(),
      child: ServiceSplash(
          child:
              TextButton(onPressed: () => taps++, child: const Text('Home'))),
    )));
    await tester.pump(const Duration(milliseconds: 1600));
    await tester.tap(find.text('Home'));
    expect(taps, 1);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('reduced motion opens content immediately', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
        home: MediaQuery(
            data: const MediaQueryData(disableAnimations: true),
            child: ServiceSplash(
                child: TextButton(
                    onPressed: () => taps++, child: const Text('Home'))))));
    await tester.tap(find.text('Home'));
    expect(taps, 1);
    expect(find.byType(OcSplashScene), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('decoded animation blocks taps then yields to the same child',
      (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
        home: ServiceSplash(
            child: TextButton(
                onPressed: () => taps++, child: const Text('Home')))));
    await tester.runAsync(() async {
      await precacheImage(const AssetImage(OcSplashScene.asset),
          tester.element(find.byType(ServiceSplash)));
    });
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(OcSplashScene), findsOneWidget);
    await tester.tap(find.text('Home'), warnIfMissed: false);
    expect(taps, 0);
    await tester.pump(const Duration(milliseconds: 2700));
    await tester.tap(find.text('Home'));
    expect(taps, 1);
    expect(find.byType(OcSplashScene), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('early disposal cancels loading and animation', (tester) async {
    await tester.pumpWidget(
        const MaterialApp(home: ServiceSplash(child: Text('Home'))));
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 4));
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'sprite renders at compact and phone sizes; export actual Flutter frames',
      (tester) async {
    late ui.Image atlas;
    await tester.runAsync(() async {
      final bytes = await rootBundle.load(OcSplashScene.asset);
      final codec = await ui.instantiateImageCodec(
          bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes));
      atlas = (await codec.getNextFrame()).image;
      codec.dispose();
    });
    expect(atlas.width / atlas.height, 4 / 3);
    final boundaryKey = GlobalKey();
    for (final size in [
      const Size(320, 568),
      const Size(390, 844),
      const Size(568, 320)
    ]) {
      await tester.binding.setSurfaceSize(size);
      await tester.pumpWidget(
          MaterialApp(home: OcSplashScene(atlas: atlas, seconds: 1.15)));
      expect(tester.takeException(), isNull);
    }
    if (const bool.fromEnvironment('EXPORT_SPLASH')) {
      // Optional local font for readable exported previews, never shipped.
      final fontFile = File(const String.fromEnvironment('PREVIEW_FONT',
          defaultValue: 'C:/Windows/Fonts/msyh.ttc'));
      if (fontFile.existsSync()) {
        await tester.runAsync(() async {
          final loader = FontLoader('OcPreview');
          loader.addFont(
              Future.value(ByteData.sublistView(await fontFile.readAsBytes())));
          await loader.load();
        });
      }
      await tester.binding.setSurfaceSize(const Size(390, 640));
      final directory = Directory('build/oc_splash_frames_v3')
        ..createSync(recursive: true);
      for (var i = 0; i < 156; i++) {
        final t = i / 60;
        await tester.pumpWidget(MaterialApp(
            theme: ThemeData(fontFamily: 'OcPreview'),
            home: RepaintBoundary(
                key: boundaryKey,
                child: DefaultTextStyle(
                    style: const TextStyle(fontFamily: 'OcPreview'),
                    child: ColoredBox(
                        color: const Color(0xFFF6F7FB),
                        child: Opacity(
                            opacity: 1 -
                                const Interval(.86, 1, curve: Curves.easeInOut)
                                    .transform(t / 2.6),
                            child:
                                OcSplashScene(atlas: atlas, seconds: t)))))));
        await tester.pump();
        final boundary = boundaryKey.currentContext!.findRenderObject()!
            as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image = await boundary.toImage(pixelRatio: 1.5);
          final data = await image.toByteData(format: ui.ImageByteFormat.png);
          File('${directory.path}/frame_${i.toString().padLeft(3, '0')}.png')
              .writeAsBytesSync(data!.buffer.asUint8List());
          image.dispose();
        });
      }
    }
    await tester.pumpWidget(const SizedBox());
    atlas.dispose();
    await tester.binding.setSurfaceSize(null);
  });
}
