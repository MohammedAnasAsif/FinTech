import 'package:flutter/material.dart';

import '../api.dart';
import 'log.dart';
import 'reviews.dart';
import 'today.dart';
import 'trades.dart';
import 'watchlist.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.api, required this.onDisconnect});
  final EngineApi api;
  final VoidCallback onDisconnect;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int tab = 0;

  static const titles = ['Today', 'Watchlist', 'Trades', 'Reviews', 'Activity'];

  @override
  Widget build(BuildContext context) {
    final pages = [
      TodayPage(api: widget.api),
      WatchlistPage(api: widget.api),
      TradesPage(api: widget.api),
      ReviewsPage(api: widget.api),
      LogPage(api: widget.api),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(titles[tab]),
        actions: [
          PopupMenuButton<String>(
            onSelected: (v) {
              if (v == 'disconnect') widget.onDisconnect();
            },
            itemBuilder: (_) => [
              PopupMenuItem(value: 'info', enabled: false, child: Text(widget.api.baseUrl)),
              const PopupMenuItem(value: 'disconnect', child: Text('Disconnect')),
            ],
          ),
        ],
      ),
      body: SafeArea(child: IndexedStack(index: tab, children: pages)),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.speed), label: 'Today'),
          NavigationDestination(icon: Icon(Icons.travel_explore), label: 'Watchlist'),
          NavigationDestination(icon: Icon(Icons.receipt_long), label: 'Trades'),
          NavigationDestination(icon: Icon(Icons.school), label: 'Reviews'),
          NavigationDestination(icon: Icon(Icons.list_alt), label: 'Activity'),
        ],
      ),
    );
  }
}

/// Shared helper: fetches on open and on pull-to-refresh, shows errors inline.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder, this.refreshEvery});
  final Future<T> Function() load;
  final Widget Function(BuildContext, T, Future<void> Function()) builder;
  final Duration? refreshEvery;

  @override
  State<Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<Loader<T>> {
  T? data;
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
    final every = widget.refreshEvery;
    if (every != null) _loop(every);
  }

  Future<void> _loop(Duration every) async {
    while (mounted) {
      await Future.delayed(every);
      if (mounted) await _refresh(quiet: true);
    }
  }

  Future<void> _refresh({bool quiet = false}) async {
    if (!quiet && mounted) setState(() => loading = true);
    try {
      final d = await widget.load();
      if (mounted) {
        setState(() {
          data = d;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = data;
    if (d == null) {
      if (loading) return const Center(child: CircularProgressIndicator());
      return ErrorView(message: error ?? 'No data', onRetry: _refresh);
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: Column(
        children: [
          if (error != null)
            MaterialBanner(
              content: Text(error!),
              leading: const Icon(Icons.wifi_off),
              actions: [TextButton(onPressed: _refresh, child: const Text('Retry'))],
            ),
          Expanded(child: widget.builder(context, d, _refresh)),
        ],
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, required this.onRetry});
  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 40),
          const SizedBox(height: 12),
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
        ]),
      ),
    );
  }
}

class EmptyNote extends StatelessWidget {
  const EmptyNote(this.text, {super.key, this.icon = Icons.inbox});
  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      const SizedBox(height: 80),
      Icon(icon, size: 40, color: Theme.of(context).colorScheme.outline),
      const SizedBox(height: 12),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Text(text, textAlign: TextAlign.center),
      ),
    ]);
  }
}
