class ServerOnlineTracker {
  bool? _wasOnline;

  bool update(bool isOnline) {
    final shouldNotify = _wasOnline == false && isOnline;
    _wasOnline = isOnline;
    return shouldNotify;
  }

  void reset() => _wasOnline = null;
}
