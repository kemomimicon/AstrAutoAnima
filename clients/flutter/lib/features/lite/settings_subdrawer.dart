import 'package:flutter/material.dart';

/// A compact entry with a separate, live-updating secondary settings drawer.
class SettingsSubdrawer extends StatelessWidget {
  const SettingsSubdrawer(
      {super.key,
      required this.title,
      required this.revision,
      required this.children});
  final String title;
  final ValueNotifier<int> revision;
  final List<Widget> Function() children;

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          useSafeArea: true,
          builder: (context) => FractionallySizedBox(
            heightFactor: .85,
            child: ValueListenableBuilder<int>(
              valueListenable: revision,
              builder: (context, value, child) => SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                    20, 12, 20, 24 + MediaQuery.viewInsetsOf(context).bottom),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(children: [
                        Expanded(
                            child: Text(title,
                                style: Theme.of(context).textTheme.titleLarge)),
                        IconButton(
                            onPressed: () => Navigator.pop(context),
                            icon: const Icon(Icons.close),
                            tooltip: '关闭')
                      ]),
                      ...children(),
                    ]),
              ),
            ),
          ),
        ),
      );
}
