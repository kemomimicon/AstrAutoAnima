import 'package:flutter/material.dart';
import 'admin_navigation.dart';

/// Art tokens from bluebell_courtyard_ui_1_1art_beta_20260910/tokens.json.
ThemeData courtyardTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final canvas = Color(dark ? 0xFF161D2D : 0xFFF4F7FD);
  final surface = Color(dark ? 0xFF222D42 : 0xFFFFFFFF);
  final tint = Color(dark ? 0xFF2C3C59 : 0xFFEAF2FF);
  final ink = Color(dark ? 0xFFEBF2FF : 0xFF34486B);
  final muted = Color(dark ? 0xFF98AAC5 : 0xFF596B86);
  final line = Color(dark ? 0xFF3C4B64 : 0xFFD9E4F3);
  final primary = Color(dark ? 0xFFB2C9F6 : 0xFF426299);
  final error = Color(dark ? 0xFFEAA0B1 : 0xFFA13E59);
  final focus = Color(dark ? 0xFFA9CEFF : 0xFF2555B5);
  final scheme =
      ColorScheme.fromSeed(seedColor: primary, brightness: brightness).copyWith(
          primary: primary,
          onPrimary: Color(dark ? 0xFF182238 : 0xFFFFFFFF),
          surface: surface,
          onSurface: ink,
          onSurfaceVariant: muted,
          primaryContainer: tint,
          onPrimaryContainer: ink,
          outline: line,
          error: error);
  OutlineInputBorder border(Color color, double width) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: BorderSide(color: color, width: width));
  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  return base.copyWith(
    extensions: const [CourtyardMarker()],
    scaffoldBackgroundColor: canvas,
    textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink).copyWith(
        titleLarge: TextStyle(
            fontSize: 24,
            height: 34 / 24,
            fontWeight: FontWeight.w700,
            color: ink),
        titleMedium: TextStyle(
            fontSize: 18,
            height: 28 / 18,
            fontWeight: FontWeight.w600,
            color: ink),
        bodyLarge: TextStyle(fontSize: 16, height: 25 / 16, color: ink),
        bodyMedium: TextStyle(fontSize: 14, height: 22 / 14, color: ink),
        bodySmall: TextStyle(fontSize: 14, height: 22 / 14, color: muted)),
    appBarTheme: AppBarTheme(
        backgroundColor: surface,
        foregroundColor: ink,
        elevation: 0,
        scrolledUnderElevation: 1),
    drawerTheme: DrawerThemeData(backgroundColor: surface),
    cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
            side: BorderSide(color: line))),
    inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        border: border(line, 1.5),
        enabledBorder: border(line, 1.5),
        focusedBorder: border(focus, 2),
        errorBorder: border(error, 2),
        focusedErrorBorder: border(error, 2),
        disabledBorder: border(line, 1),
        errorMaxLines: 4),
    filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
            minimumSize: const Size(48, 48),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14)))),
    outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
            minimumSize: const Size(48, 48),
            side: BorderSide(color: line),
            foregroundColor: ink,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14)))),
    iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(48, 48))),
    navigationBarTheme:
        NavigationBarThemeData(backgroundColor: surface, indicatorColor: tint),
    navigationRailTheme:
        NavigationRailThemeData(backgroundColor: surface, indicatorColor: tint),
    dialogTheme: DialogThemeData(
        backgroundColor: surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24))),
    expansionTileTheme: ExpansionTileThemeData(
        backgroundColor: surface,
        collapsedBackgroundColor: surface,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: line)),
        collapsedShape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: line))),
  );
}

class CourtyardMarker extends ThemeExtension<CourtyardMarker> {
  const CourtyardMarker();
  @override
  CourtyardMarker copyWith() => this;
  @override
  CourtyardMarker lerp(covariant CourtyardMarker? other, double t) => this;
}

class CourtyardIcon extends StatelessWidget {
  const CourtyardIcon(this.icon,
      {this.size, this.color, this.semanticLabel, super.key});
  final IconData? icon;
  final double? size;
  final Color? color;
  final String? semanticLabel;
  static final names = <IconData, String>{
    Icons.auto_awesome_outlined: 'nav_generate_normal',
    Icons.auto_awesome: 'nav_generate_selected',
    Icons.photo_library_outlined: 'nav_history_normal',
    Icons.photo_library: 'nav_history_selected',
    Icons.tune_outlined: 'nav_presets_normal',
    Icons.tune: 'nav_presets_selected',
    Icons.library_books_outlined: 'nav_prompts_normal',
    Icons.library_books: 'nav_prompts_selected',
    Icons.translate_outlined: 'nav_characters_normal',
    Icons.translate: 'nav_characters_selected',
    Icons.cloud_outlined: 'nav_instances_normal',
    Icons.cloud: 'nav_instances_selected',
    Icons.monitor_heart_outlined: 'nav_overview_normal',
    Icons.monitor_heart: 'nav_overview_selected',
    Icons.extension_outlined: 'nav_lora_normal',
    Icons.extension: 'nav_lora_selected',
    Icons.manage_accounts_outlined: 'nav_users_normal',
    Icons.manage_accounts: 'nav_users_selected',
    Icons.refresh: 'actions_refresh_normal',
    Icons.thumb_up_outlined: 'actions_thumb_up_normal',
    Icons.thumb_up: 'actions_thumb_up_selected',
    Icons.warning_amber_rounded: 'actions_report_normal',
    Icons.star_border: 'actions_star_normal',
    Icons.star: 'actions_star_selected',
    Icons.settings: 'actions_settings_normal',
    Icons.help_outline: 'actions_help_normal',
    Icons.info_outline: 'actions_info_normal',
    Icons.palette_outlined: 'actions_theme_normal',
    Icons.dns_outlined: 'actions_server_normal',
    Icons.delete_outline: 'actions_trash_normal',
    Icons.close: 'actions_close_normal',
    Icons.search: 'actions_search_normal',
    Icons.menu: 'actions_menu_normal',
    Icons.copy: 'actions_copy_normal',
  };
  @override
  Widget build(BuildContext context) {
    final fallback =
        Icon(icon, size: size, color: color, semanticLabel: semanticLabel);
    final name = names[icon];
    if (name == null ||
        Theme.of(context).extension<CourtyardMarker>() == null) {
      return fallback;
    }
    final mode =
        Theme.of(context).brightness == Brightness.dark ? 'dark' : 'light';
    return Image.asset('assets/courtyard/$mode/$name.png',
        width: size ?? 28,
        height: size ?? 28,
        color: color,
        semanticLabel: semanticLabel,
        excludeFromSemantics: semanticLabel == null,
        errorBuilder: (_, __, ___) => fallback);
  }
}

class CourtyardWelcome extends StatelessWidget {
  const CourtyardWelcome({super.key});
  @override
  Widget build(BuildContext context) {
    if (Theme.of(context).extension<CourtyardMarker>() == null) {
      return const Icon(Icons.hub_outlined, size: 48);
    }
    return Center(
        child: Container(
            width: 112,
            height: 112,
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
                color: const Color(0xFFF4F7FD),
                borderRadius: BorderRadius.circular(20)),
            clipBehavior: Clip.antiAlias,
            child: Image.asset(
                'assets/courtyard/illustrations/welcome_480.webp',
                excludeFromSemantics: true,
                errorBuilder: (_, __, ___) =>
                    const Icon(Icons.hub_outlined, size: 48))));
  }
}

/// All existing administrator destinations stay accessible on a narrow screen.
class HubNavigation extends StatelessWidget {
  const HubNavigation(
      {required this.destinations,
      required this.selectedIndex,
      required this.onSelected,
      this.onSettings,
      this.extensionEntries = const [],
      this.onRefreshExtensions,
      super.key});
  final List<NavigationDestination> destinations;
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final VoidCallback? onSettings;
  final List<Widget> extensionEntries;
  final VoidCallback? onRefreshExtensions;
  @override
  Widget build(BuildContext context) => Material(
      color: Theme.of(context).colorScheme.surface,
      child: ListView(
          padding: const EdgeInsets.symmetric(vertical: 16),
          children: [
            for (final group in <String, List<int>>{
              '工作站': AdminNavigation.indicesFor('main'),
              '资源': AdminNavigation.indicesFor('resources'),
              '管理': AdminNavigation.indicesFor('management',
                  includeStorage: destinations.length > 9)
            }.entries) ...[
              Padding(
                  padding: const EdgeInsets.fromLTRB(20, 16, 16, 8),
                  child: Text(group.key,
                      style: Theme.of(context).textTheme.labelLarge)),
              for (final index in group.value)
                Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    child: ListTile(
                        selected: index == selectedIndex,
                        selectedTileColor:
                            Theme.of(context).colorScheme.primaryContainer,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12)),
                        leading: index == selectedIndex
                            ? destinations[index].selectedIcon
                            : destinations[index].icon,
                        title: Text(destinations[index].label),
                        trailing: index == selectedIndex
                            ? const Icon(Icons.check, size: 18)
                            : null,
                        onTap: () => onSelected(index))),
            ],
            if (extensionEntries.isNotEmpty) ...[
              const Divider(),
              ...extensionEntries,
            ],
            if (onRefreshExtensions != null)
              ListTile(
                leading: const Icon(Icons.refresh),
                title: const Text('刷新扩展入口'),
                onTap: onRefreshExtensions,
              ),
            if (onSettings != null) ...[
              const Divider(),
              ListTile(
                leading: const CourtyardIcon(Icons.settings_outlined),
                title: const Text('设置'),
                onTap: onSettings,
              ),
            ],
          ]));
}
