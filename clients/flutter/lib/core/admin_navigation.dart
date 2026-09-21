/// Stable identities; indices are only an adapter for the existing IndexedStack.
class AdminDestination {
  const AdminDestination(this.id, this.group);
  final String id;
  final String group;
}

const adminDestinations = [
  AdminDestination('instances', 'main'),
  AdminDestination('overview', 'main'),
  AdminDestination('prompts', 'resources'),
  AdminDestination('presets', 'resources'),
  AdminDestination('loras', 'resources'),
  AdminDestination('users', 'management'),
  AdminDestination('records', 'main'),
  AdminDestination('characters', 'resources'),
  AdminDestination('reports', 'management'),
  AdminDestination('storage', 'management'),
];

class AdminNavigation {
  AdminNavigation({this.includeStoragePreview = false});
  final bool includeStoragePreview;
  String selectedId = 'instances';
  String _lastMainId = 'instances';
  String group = 'main';
  int get page => adminDestinations.indexWhere((d) => d.id == selectedId);

  static List<int> indicesFor(String group, {bool includeStorage = true}) => [
        for (var i = 0; i < adminDestinations.length; i++)
          if (adminDestinations[i].group == group &&
              (includeStorage || adminDestinations[i].id != 'storage'))
            i,
      ];

  List<int> get entries => [
        ...indicesFor(group, includeStorage: includeStoragePreview),
        if (group == 'main') ...[-2, -3] else -1,
      ];

  int get selectedIndex => entries.indexOf(page);

  void selectPage(int value) {
    selectId(value >= 0 && value < adminDestinations.length
        ? adminDestinations[value].id
        : 'overview');
  }

  void selectId(String id) {
    final matches = adminDestinations.where((d) => d.id == id);
    final destination = matches.isEmpty ? adminDestinations[1] : matches.first;
    selectedId = destination.id;
    group = destination.group;
    if (group == 'main') _lastMainId = selectedId;
  }

  void selectDestination(int index) {
    final value = entries[index];
    if (value == -1) {
      selectId(_lastMainId);
    } else {
      selectPage(value == -2
          ? 2
          : value == -3
              ? 5
              : value);
    }
  }
}
