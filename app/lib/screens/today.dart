import 'package:flutter/material.dart';

import '../api.dart';
import '../main.dart';
import 'home.dart';

class TodayPage extends StatelessWidget {
  const TodayPage({super.key, required this.api});
  final EngineApi api;

  @override
  Widget build(BuildContext context) {
    return Loader<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(await api.get('/status') as Map),
      refreshEvery: const Duration(seconds: 3),
      builder: (context, s, refresh) => _TodayView(api: api, s: s, refresh: refresh),
    );
  }
}

String _hhmm(dynamic iso) {
  if (iso == null) return '';
  final s = iso.toString();
  return s.length >= 16 ? s.substring(11, 16) : s;
}

class _TodayView extends StatefulWidget {
  const _TodayView({required this.api, required this.s, required this.refresh});
  final EngineApi api;
  final Map<String, dynamic> s;
  final Future<void> Function() refresh;

  @override
  State<_TodayView> createState() => _TodayViewState();
}

class _TodayViewState extends State<_TodayView> {
  final capital = TextEditingController(text: '2000');
  bool busy = false;

  Future<void> _do(String path, [Map<String, dynamic>? body, String? done]) async {
    setState(() => busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await widget.api.post(path, body);
      if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
      await widget.refresh();
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<bool> _confirm(String title, String body, String action, {bool danger = false}) async {
    final scheme = Theme.of(context).colorScheme;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(
            style: danger ? FilledButton.styleFrom(backgroundColor: scheme.error, foregroundColor: scheme.onError) : null,
            onPressed: () => Navigator.pop(c, true),
            child: Text(action),
          ),
        ],
      ),
    );
    return ok ?? false;
  }

  String _explain(Map<String, dynamic> s, Map<String, dynamic>? r) {
    final sched = Map<String, dynamic>.from(s['schedule'] as Map? ?? {});
    switch (s['state']) {
      case 'IDLE':
        return s['trading_day'] == true
            ? 'Set today\'s capital to begin. Trading runs ${sched['trade_start']}–${sched['square_off']}.'
            : 'Market closed today. Overnight research runs at ${sched['research_at']}.';
      case 'WAITING':
        return 'Ready. First trade allowed at ${sched['trade_start']}.';
      case 'TRADING':
        return 'Watching the market and trading the watchlist.';
      case 'PAUSED':
        return 'On a break you started. No new trades; open trades keep their stop and target.';
      case 'COOLDOWN':
        return 'Short break after a losing streak, until ${_hhmm(r?['cooldown_until'])}.';
      case 'RESEARCHING':
        return 'Hit the cycle loss limit. Everything is closed; re-studying the market. '
            'Back no earlier than ${_hhmm(r?['comeback_after'])}.';
      case 'DONE':
        return 'Finished for today: ${r?['day_over_reason'] ?? ''}. Review runs at ${sched['review_at']}.';
      case 'KILLED':
        return 'Kill switch used. Everything is closed and trading is locked until tomorrow.';
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    final r = s['risk'] == null ? null : Map<String, dynamic>.from(s['risk'] as Map);
    final state = s['state'] as String;
    final scheme = Theme.of(context).colorScheme;
    final pnl = asDouble(s['day_pnl']);
    final positions = (s['positions'] as List? ?? []).cast<Map>();
    final gate = Map<String, dynamic>.from(s['live_gate'] as Map? ?? {});
    final live = s['mode'] == 'live';
    final canAct = !busy;
    final double unreal = asDouble(s['unrealized']);
    final double openLoss = unreal < 0 ? -unreal : 0.0;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(children: [
          Chip(
            label: Text(live ? 'LIVE — REAL MONEY' : 'PAPER — PRACTICE MONEY'),
            backgroundColor: live ? AppColors.loss.withValues(alpha: 0.2) : scheme.secondaryContainer,
          ),
          const SizedBox(width: 8),
          Chip(label: Text(state)),
          const Spacer(),
          Text(_hhmm(s['now']), style: Theme.of(context).textTheme.titleMedium),
        ]),
        if (s['busy'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Row(children: [
              const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
              const SizedBox(width: 8),
              Text('${s['busy']}…'),
            ]),
          ),
        if (s['last_error'] != null)
          Card(
            color: scheme.errorContainer,
            child: ListTile(leading: const Icon(Icons.error_outline), title: Text(s['last_error'].toString())),
          ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Today', style: Theme.of(context).textTheme.labelLarge),
              Text(
                rupees(pnl, sign: true),
                style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    color: pnl > 0 ? AppColors.profit : (pnl < 0 ? AppColors.loss : null),
                    fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              Text(_explain(s, r)),
              if (r != null) ...[
                const SizedBox(height: 16),
                Text('Capital ${rupees(asDouble(r['capital']))} · cycle ${r['cycle']} of ${r['max_cycles']} · '
                    '${r['trades_today']}/${r['max_trades_per_day']} trades'),
                const SizedBox(height: 12),
                _LimitBar(
                  label: 'This cycle',
                  used: -asDouble(r['cycle_realized']) + (state == 'RESEARCHING' ? 0.0 : openLoss),
                  limit: asDouble(r['cycle_loss_limit']),
                ),
                const SizedBox(height: 8),
                _LimitBar(
                  label: 'Whole day',
                  used: -asDouble(r['realized_total']) + openLoss,
                  limit: asDouble(r['daily_loss_limit']),
                ),
              ],
            ]),
          ),
        ),
        if (state == 'IDLE' && s['trading_day'] == true)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                TextField(
                  controller: capital,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Capital for today (₹)', prefixText: '₹ '),
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  icon: const Icon(Icons.play_arrow),
                  label: Text(live ? 'Start with real money' : 'Start paper trading'),
                  onPressed: !canAct
                      ? null
                      : () async {
                          final v = double.tryParse(capital.text.trim());
                          if (v == null || v <= 0) return;
                          if (live &&
                              !await _confirm('Trade real money?',
                                  'The bot will place real orders with up to ${rupees(v)} today. Losses are real.', 'Start',
                                  danger: true)) {
                            return;
                          }
                          await _do('/start', {'capital': v}, 'Started for today');
                        },
                ),
                if (!live && gate.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(gate['message']?.toString() ?? '', style: Theme.of(context).textTheme.bodySmall),
                ],
              ]),
            ),
          ),
        if (positions.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Open positions', style: Theme.of(context).textTheme.titleMedium),
          for (final p in positions) _PositionCard(p: Map<String, dynamic>.from(p)),
        ],
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (state == 'TRADING' || state == 'WAITING' || state == 'COOLDOWN')
            OutlinedButton.icon(
              icon: const Icon(Icons.pause),
              label: const Text('Take a break'),
              onPressed: canAct ? () => _do('/pause', null, 'Paused') : null,
            ),
          if (state == 'PAUSED')
            FilledButton.icon(
              icon: const Icon(Icons.play_arrow),
              label: const Text('Resume'),
              onPressed: canAct ? () => _do('/resume', null, 'Resumed') : null,
            ),
          if (r != null && state != 'DONE' && state != 'KILLED')
            OutlinedButton.icon(
              icon: const Icon(Icons.stop),
              label: const Text('Stop for today'),
              onPressed: !canAct
                  ? null
                  : () async {
                      if (await _confirm('Stop for today?', 'Closes any open trade and stops trading until tomorrow.',
                          'Stop')) {
                        await _do('/stop', null, 'Stopped for today');
                      }
                    },
            ),
        ]),
        const SizedBox(height: 24),
        if (state != 'KILLED')
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: scheme.error,
              foregroundColor: scheme.onError,
              minimumSize: const Size.fromHeight(52),
            ),
            icon: const Icon(Icons.power_settings_new),
            label: const Text('KILL SWITCH'),
            onPressed: !canAct
                ? null
                : () async {
                    if (await _confirm('Kill switch',
                        'Immediately close every open position and lock trading until tomorrow.', 'Close everything',
                        danger: true)) {
                      await _do('/kill', null, 'Everything closed');
                    }
                  },
          ),
        const SizedBox(height: 16),
      ],
    );
  }
}

class _LimitBar extends StatelessWidget {
  const _LimitBar({required this.label, required this.used, required this.limit});
  final String label;
  final double used;
  final double limit;

  @override
  Widget build(BuildContext context) {
    final u = used.clamp(0, limit).toDouble();
    final f = limit <= 0 ? 0.0 : u / limit;
    final color = f > 0.75 ? AppColors.loss : (f > 0.4 ? AppColors.warn : AppColors.profit);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('$label: lost ${rupees(u)} of ${rupees(limit)} allowed', style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 4),
      LinearProgressIndicator(value: f, color: color, minHeight: 6, borderRadius: BorderRadius.circular(3)),
    ]);
  }
}

class _PositionCard extends StatelessWidget {
  const _PositionCard({required this.p});
  final Map<String, dynamic> p;

  @override
  Widget build(BuildContext context) {
    final u = asDouble(p['unrealized']);
    return Card(
      child: ListTile(
        title: Text('${p['symbol']} · ${p['direction']} ${p['qty']} @ ${rupees(asDouble(p['entry']))}'),
        subtitle: Text('now ${rupees(p['ltp'] == null ? null : asDouble(p['ltp']))} · '
            'stop ${rupees(asDouble(p['stop']))} · target ${rupees(asDouble(p['target']))}\n${p['reason'] ?? ''}'),
        isThreeLine: true,
        trailing: Text(rupees(u, sign: true),
            style: TextStyle(color: u >= 0 ? AppColors.profit : AppColors.loss, fontWeight: FontWeight.w600)),
      ),
    );
  }
}
