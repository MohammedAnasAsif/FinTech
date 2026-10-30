import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import 'home.dart';

class TradesPage extends StatelessWidget {
  const TradesPage({super.key, required this.api});
  final EngineApi api;

  @override
  Widget build(BuildContext context) {
    return Loader<List<Map<String, dynamic>>>(
      load: () async => ((await api.get('/trades?limit=300')) as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList(),
      refreshEvery: const Duration(seconds: 15),
      builder: (context, trades, refresh) {
        if (trades.isEmpty) return const EmptyNote('No trades yet.', icon: Icons.receipt_long);
        final byDay = <String, List<Map<String, dynamic>>>{};
        for (final t in trades) {
          byDay.putIfAbsent(t['day'].toString(), () => []).add(t);
        }
        final days = byDay.keys.toList()..sort((a, b) => b.compareTo(a));
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final d in days) ...[
              _DayHeader(day: d, trades: byDay[d]!),
              for (final t in byDay[d]!) _TradeTile(t: t),
              const SizedBox(height: 12),
            ],
          ],
        );
      },
    );
  }
}

class _DayHeader extends StatelessWidget {
  const _DayHeader({required this.day, required this.trades});
  final String day;
  final List<Map<String, dynamic>> trades;

  @override
  Widget build(BuildContext context) {
    final net = trades.fold<double>(0, (a, t) => a + asDouble(t['net']));
    final costs = trades.fold<double>(0, (a, t) => a + asDouble(t['costs']));
    final mode = trades.first['mode'];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Text('$day · $mode', style: Theme.of(context).textTheme.titleMedium),
        const Spacer(),
        Text('${rupees(net, sign: true)}  (charges ${rupees(costs)})',
            style: TextStyle(color: net >= 0 ? AppColors.profit : AppColors.loss)),
      ]),
    );
  }
}

class _TradeTile extends StatelessWidget {
  const _TradeTile({required this.t});
  final Map<String, dynamic> t;

  @override
  Widget build(BuildContext context) {
    final net = asDouble(t['net']);
    final long = (t['direction'] as num) > 0;
    String hm(dynamic iso) => iso.toString().length >= 16 ? iso.toString().substring(11, 16) : iso.toString();
    return Card(
      child: ExpansionTile(
        leading: Icon(long ? Icons.north_east : Icons.south_east, color: long ? AppColors.profit : AppColors.loss),
        title: Text('${t['symbol']} · ${long ? 'long' : 'short'} ${t['qty']}'),
        subtitle: Text('${hm(t['entry_ts'])} ${rupees(asDouble(t['entry_price']))} → '
            '${hm(t['exit_ts'])} ${rupees(asDouble(t['exit_price']))} · ${t['exit_reason']}'),
        trailing: Text(rupees(net, sign: true),
            style: TextStyle(color: net >= 0 ? AppColors.profit : AppColors.loss, fontWeight: FontWeight.w600)),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Why it entered: ${t['entry_reason']}'),
          Text('Gross ${rupees(asDouble(t['gross']), sign: true)}, charges ${rupees(asDouble(t['costs']))}, '
              'cycle ${t['cycle']}'),
        ],
      ),
    );
  }
}
