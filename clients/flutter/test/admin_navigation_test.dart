import 'package:flutter_test/flutter_test.dart';
import 'package:astr_auto_anima_hub_client/core/admin_navigation.dart';

void main() {
  test(
      'stable IDs and groups share a single source; extensions are not bottom tabs',
      () {
    final nav = AdminNavigation(includeStoragePreview: true);
    nav.selectId('storage');
    expect(nav.page, 9);
    expect(nav.selectedId, 'storage');
    expect(adminDestinations.any((d) => d.id.startsWith('extension.')), false);
    nav.selectId('removed-id');
    expect(nav.selectedId, 'overview');
  });
  test('production navigation excludes storage preview', () {
    final nav = AdminNavigation();
    nav.selectDestination(4);
    expect(nav.entries, [5, 8, -1]);
    nav.selectDestination(2);
    expect(nav.page, 0);
  });
  test('main, resources, management and return preserve parent page', () {
    final nav = AdminNavigation(includeStoragePreview: true);
    expect(nav.entries, [0, 1, 6, -2, -3]);
    nav.selectDestination(2);
    expect(nav.page, 6);
    nav.selectDestination(3);
    expect(nav.entries, [2, 3, 4, 7, -1]);
    nav.selectDestination(3);
    expect(nav.page, 7);
    nav.selectDestination(4);
    expect(nav.page, 6);
    nav.selectDestination(4);
    expect(nav.entries, [5, 8, 9, -1]);
    nav.selectDestination(1);
    expect(nav.page, 8);
    nav.selectDestination(3);
    expect(nav.page, 6);
  });
  test('sidebar selection synchronizes bottom navigation', () {
    final nav = AdminNavigation(includeStoragePreview: true);
    nav.selectPage(4);
    expect(nav.group, 'resources');
    expect(nav.selectedIndex, 2);
    nav.selectPage(8);
    expect(nav.group, 'management');
    expect(nav.selectedIndex, 1);
    nav.selectPage(9);
    expect(nav.selectedIndex, 2);
    nav.selectDestination(3);
    expect(nav.page, 0);
    expect(nav.group, 'main');
  });
}
