import 'package:flutter/material.dart';

import 'app.dart';
import 'core/app_edition.dart';
import 'core/notification_service.dart';
import 'core/session_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = SessionStore();
  final session = await store.load();
  runApp(
    AstrAutoAnimaApp(
      store: store,
      notificationService: NotificationService(),
      initialSession: session,
      edition: AppEdition.admin,
    ),
  );
}
