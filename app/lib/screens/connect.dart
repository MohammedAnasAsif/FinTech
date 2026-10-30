import 'package:flutter/material.dart';

import '../api.dart';

class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key, required this.onConnected});
  final void Function(EngineApi) onConnected;

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final url = TextEditingController(text: 'http://127.0.0.1:8765');
  final token = TextEditingController();
  bool busy = false;
  String? error;

  Future<void> _connect() async {
    setState(() {
      busy = true;
      error = null;
    });
    final api = EngineApi(url.text, token.text.trim());
    try {
      await api.check();
      await api.save();
      widget.onConnected(api);
    } catch (e) {
      setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Icon(Icons.candlestick_chart, size: 48, color: Theme.of(context).colorScheme.primary),
                  const SizedBox(height: 12),
                  Text('Connect to your engine', style: t.headlineSmall, textAlign: TextAlign.center),
                  const SizedBox(height: 8),
                  Text(
                    'Start the engine on your PC. It prints an address and a pairing token. '
                    'On a phone, use the PC\'s address (not 127.0.0.1) and stay on the same Wi-Fi.',
                    style: t.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    controller: url,
                    keyboardType: TextInputType.url,
                    decoration: const InputDecoration(labelText: 'Engine address', hintText: 'http://192.168.1.20:8765'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: token,
                    decoration: const InputDecoration(labelText: 'Pairing token'),
                    onSubmitted: (_) => _connect(),
                  ),
                  if (error != null) ...[
                    const SizedBox(height: 12),
                    Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: busy ? null : _connect,
                    child: busy
                        ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Connect'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
