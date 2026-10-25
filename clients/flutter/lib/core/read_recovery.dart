import 'dart:async';

import 'hub_api.dart';

/// Retry failed read-only page loads; never retries a mutation or bad credentials.
class ReadRecovery {
  ReadRecovery(this.onRetry);

  final void Function() onRetry;
  Timer? _timer;
  int _failures = 0;
  bool _disposed = false;

  void begin() {
    _timer?.cancel();
    _timer = null;
  }

  void succeeded() {
    begin();
    _failures = 0;
  }

  void failed(Object error) {
    begin();
    if (_disposed || error is! HubApiException) return;
    final status = error.statusCode;
    if (status != null && !{408, 429, 502, 503, 504}.contains(status)) return;
    const delays = [2, 4, 8, 15, 30];
    final index = _failures < delays.length ? _failures : delays.length - 1;
    _failures++;
    _timer = Timer(Duration(seconds: delays[index]), () {
      _timer = null;
      if (!_disposed) onRetry();
    });
  }

  void dispose() {
    _disposed = true;
    begin();
  }
}
