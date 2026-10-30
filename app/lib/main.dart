import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/connect.dart';
import 'screens/home.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const TradeBotApp());
}

class AppColors {
  static const profit = Color(0xFF2EBD85);
  static const loss = Color(0xFFF6465D);
  static const warn = Color(0xFFF0B90B);
  static const seed = Color(0xFF3D7BFD);
}

class TradeBotApp extends StatelessWidget {
  const TradeBotApp({super.key});

  ThemeData _theme(Brightness b) {
    final scheme = ColorScheme.fromSeed(seedColor: AppColors.seed, brightness: b);
    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      cardTheme: const CardThemeData(margin: EdgeInsets.symmetric(vertical: 6), elevation: 0),
      inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TradeBot',
      debugShowCheckedModeBanner: false,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      themeMode: ThemeMode.dark,
      home: const Root(),
    );
  }
}

class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  EngineApi? api;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    EngineApi.load().then((a) => setState(() {
          api = a;
          loading = false;
        }));
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (api == null) {
      return ConnectScreen(onConnected: (a) => setState(() => api = a));
    }
    return HomeScreen(
      api: api!,
      onDisconnect: () async {
        await EngineApi.forget();
        setState(() => api = null);
      },
    );
  }
}
