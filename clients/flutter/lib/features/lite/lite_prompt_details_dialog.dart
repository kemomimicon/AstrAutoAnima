import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/models.dart';

Future<void> showLitePromptDetailsDialog(
  BuildContext context,
  PromptRecord item,
) {
  return showDialog<void>(
    context: context,
    builder: (context) => LitePromptDetailsDialog(item: item),
  );
}

class LitePromptDetailsDialog extends StatelessWidget {
  const LitePromptDetailsDialog({required this.item, super.key});

  final PromptRecord item;

  Future<void> _copy(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: item.prompt));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('完整提示词已复制到剪贴板')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final title = item.name.isEmpty ? item.id : '${item.id} · ${item.name}';
    final screenHeight = MediaQuery.sizeOf(context).height;

    return AlertDialog(
      title: Text(title),
      content: SizedBox(
        width: 720,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: screenHeight * 0.62),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  Chip(label: Text('来源 ${item.sourceCode}')),
                  Chip(label: Text('分级 ${item.safetyCode}')),
                  if (item.categories.isNotEmpty)
                    ...item.categories.map((value) => Chip(label: Text(value))),
                ],
              ),
              const SizedBox(height: 12),
              Text('完整提示词', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Flexible(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surfaceContainerLow,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Scrollbar(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(16),
                      child: SelectableText(
                        item.prompt,
                        key: const Key('lite-prompt-full-text'),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        OutlinedButton.icon(
          key: const Key('lite-prompt-copy-button'),
          onPressed: () => _copy(context),
          icon: const Icon(Icons.copy_outlined),
          label: const Text('复制提示词'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('关闭'),
        ),
      ],
    );
  }
}
