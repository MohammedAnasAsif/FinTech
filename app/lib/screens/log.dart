import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import 'home.dart';

class LogPage extends StatelessWidget {
  const LogPage({super.key, required this.api});
  final EngineApi api;

  @override
  Widget build(BuildContext context) {
    return Loader<List<Map<String, dynamic>>>(
      load: () async =>
          ((await api.get('/events?limit=300')) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
      refreshEvery: const Duration(seconds: 4),
      builder: (context, events, refresh) {
        if (events.isEmpty) return const EmptyNote('Nothing has happened yet.', icon: Icons.list_alt);
        final items = events.reversed.toList();
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: items.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final e = items[i];
            final level = e['level'];
            final color = level == 'error' ? AppColors.loss : (level == 'warning' ? AppColors.warn : null);
            final ts = e['ts'].toString();
            return ListTile(
              dense: true,
              leading: Text(ts.length >= 19 ? ts.substring(11, 19) : ts,
                  style: const TextStyle(fontFeatures: [FontFeature.tabularFigures()])),
              title: Text(e['message'].toString(), style: TextStyle(color: color)),
            );
          },
        );
      },
    );
  }
}
