import 'dart:convert';

import 'package:flutter/material.dart';

class PromptProvenanceDetails extends StatelessWidget {
  const PromptProvenanceDetails(
      {required this.jobId, required this.provenance, super.key});

  final String jobId;
  final Map<String, dynamic> provenance;

  @override
  Widget build(BuildContext context) => provenance.isEmpty
      ? const SizedBox.shrink()
      : Material(
          type: MaterialType.transparency,
          child: ExpansionTile(
            key: PageStorageKey('prompt-provenance-$jobId'),
            title: const Text('离线提示词出处'),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: SelectionArea(
                  child: Text(
                    const JsonEncoder.withIndent('  ').convert(provenance),
                  ),
                ),
              ),
            ],
          ),
        );
}
