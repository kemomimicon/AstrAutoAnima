/// UI names and policy always come from the currently connected deployment.
List<Map<String, dynamic>> catalogRows(Map<String, dynamic>? catalog,
        [String key = 'sources']) =>
    (catalog?[key] as List? ?? const [])
        .whereType<Map>()
        .map((row) => Map<String, dynamic>.from(row))
        .toList();

List<String> catalogLevels(Map<String, dynamic>? source) =>
    (source?['safety_codes'] as List? ?? const ['N', 'H', 'S'])
        .whereType<String>()
        .toList();

bool catalogAllows(Map<String, dynamic> source, String kind, String level) =>
    source['enabled'] != false &&
    source[kind == 'group' ? 'allow_group' : 'allow_private'] != false &&
    catalogLevels(source).contains(level) &&
    !(kind == 'group' && level == 'S');
