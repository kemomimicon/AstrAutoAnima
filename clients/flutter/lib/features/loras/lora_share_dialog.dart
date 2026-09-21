import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/models.dart';

Future<void> showLoraShareDialog(
    BuildContext context, LoraCatalogItem item) async {
  if (item.sourceUrl.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('该 LoRA 尚无公开来源链接，请管理员在资产库中补充。')));
    return;
  }
  await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
            title: const Text('分享 LoRA'),
            content:
                SingleChildScrollView(child: SelectableText(item.shareText)),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('关闭')),
              FilledButton(
                  onPressed: () async {
                    try {
                      await Clipboard.setData(
                          ClipboardData(text: item.shareText));
                      if (!dialogContext.mounted) return;
                      Navigator.pop(dialogContext);
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                                content: Text('已复制链接和触发词，可粘贴到 QQ 等应用发送。')));
                      }
                    } catch (_) {
                      if (dialogContext.mounted) {
                        ScaffoldMessenger.of(dialogContext).showSnackBar(
                            const SnackBar(content: Text('复制失败，请长按选择文本复制。')));
                      }
                    }
                  },
                  child: const Text('复制分享内容')),
            ],
          ));
}
