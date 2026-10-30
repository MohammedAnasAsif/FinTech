import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import 'home.dart';

class ReviewsPage extends StatelessWidget {
  const ReviewsPage({super.key, required this.api});
  final EngineApi api;

  @override
  Widget build(BuildContext context) {
    return Loader<List<Map<String, dynamic>>>(
      load: () async => ((await api.get('/reviews')) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
      refreshEvery: const Duration(seconds: 60),
      builder: (context, reviews, refresh) {
        if (reviews.isEmpty) {
          return const EmptyNote('The bot reviews each day after the 3 PM square-off. Nothing yet.', icon: Icons.school);
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [for (final r in reviews) _ReviewCard(r: r)],
        );
      },
    );
  }
}

class _ReviewCard extends StatelessWidget {
  const _ReviewCard({required this.r});
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final sum = Map<String, dynamic>.from(r['summary'] as Map? ?? {});
    final findings = (r['findings'] as List? ?? []).cast<Map>();
    final net = asDouble(sum['net']);
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text('${r['day']} · ${r['mode']}', style: t.titleMedium),
            const Spacer(),
            Text(rupees(net, sign: true), style: TextStyle(color: net >= 0 ? AppColors.profit : AppColors.loss)),
          ]),
          Text('${sum['trades'] ?? 0} trades · win rate ${(asDouble(sum['win_rate']) * 100).round()}% · '
              'charges ${rupees(asDouble(sum['costs']))}', style: t.bodySmall),
          const Divider(height: 20),
          for (final f in findings) ...[
            if (f['mistake'] != null) Text(f['mistake'].toString(), style: t.titleSmall),
            Text(f['lesson'].toString()),
            for (final e in (f['evidence'] as List? ?? []))
              Text('   · $e', style: t.bodySmall),
            if (f['change'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.auto_fix_high, size: 16),
                  const SizedBox(width: 6),
                  Expanded(child: Text('Tomorrow: ${f['change']}', style: const TextStyle(fontWeight: FontWeight.w600))),
                ]),
              ),
            const SizedBox(height: 10),
          ],
        ]),
      ),
    );
  }
}
