import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import 'home.dart';

class WatchlistPage extends StatelessWidget {
  const WatchlistPage({super.key, required this.api});
  final EngineApi api;

  @override
  Widget build(BuildContext context) {
    return Loader<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from((await api.get('/watchlist') as Map?) ?? {}),
      refreshEvery: const Duration(seconds: 30),
      builder: (context, w, refresh) {
        final picks = (w['picks'] as List? ?? []).cast<Map>();
        final rejected = (w['rejected'] as List? ?? []).cast<Map>();
        final t = Theme.of(context).textTheme;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(w['note']?.toString() ?? 'No research yet.', style: t.titleMedium),
            if (w['generated_at'] != null)
              Text('Researched ${w['generated_at'].toString().replaceFirst('T', ' ').substring(0, 16)} '
                  '(${w['kind'] ?? 'nightly'}) for capital ${rupees(asDouble(w['capital']))}',
                  style: t.bodySmall),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                icon: const Icon(Icons.refresh),
                label: const Text('Research now'),
                onPressed: () async {
                  final m = ScaffoldMessenger.of(context);
                  try {
                    await api.post('/research');
                    m.showSnackBar(const SnackBar(content: Text('Research started. This can take a few minutes.')));
                  } catch (e) {
                    m.showSnackBar(SnackBar(content: Text(e.toString())));
                  }
                },
              ),
            ),
            for (final p in picks) _PickCard(p: Map<String, dynamic>.from(p)),
            if (rejected.isNotEmpty)
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('Skipped (${rejected.length})'),
                children: [
                  for (final r in rejected)
                    ListTile(dense: true, title: Text(r['symbol'].toString()), subtitle: Text(r['reason'].toString())),
                ],
              ),
          ],
        );
      },
    );
  }
}

class _PickCard extends StatelessWidget {
  const _PickCard({required this.p});
  final Map<String, dynamic> p;

  @override
  Widget build(BuildContext context) {
    final ctx = Map<String, dynamic>.from(p['context'] as Map? ?? {});
    final test = Map<String, dynamic>.from(p['test'] as Map? ?? {});
    final reasons = (p['reasons'] as List? ?? []).map((e) => e.toString()).toList();
    final t = Theme.of(context).textTheme;
    final trend = ctx['trend']?.toString();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(p['symbol'].toString(), style: t.titleLarge),
            const SizedBox(width: 8),
            if (ctx['last_price'] != null) Text(rupees(asDouble(ctx['last_price']))),
            const Spacer(),
            if (trend != null)
              Icon(
                trend == 'up' ? Icons.trending_up : (trend == 'down' ? Icons.trending_down : Icons.trending_flat),
                color: trend == 'up' ? AppColors.profit : (trend == 'down' ? AppColors.loss : null),
              ),
          ]),
          if (test.isNotEmpty)
            Text('Unseen-data test: ${rupees(asDouble(test['net']), sign: true)} over ${test['trades']} trades, '
                'win rate ${(asDouble(test['win_rate']) * 100).round()}%'),
          const SizedBox(height: 8),
          for (final r in reasons)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('•  '),
                Expanded(child: Text(r, style: t.bodySmall)),
              ]),
            ),
        ]),
      ),
    );
  }
}
