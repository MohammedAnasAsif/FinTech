import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiException implements Exception {
  ApiException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Talks to the TradeBot engine running on your PC.
class EngineApi {
  EngineApi(String baseUrl, this.token) : baseUrl = _normalise(baseUrl);

  final String baseUrl;
  final String token;
  static const _timeout = Duration(seconds: 12);

  static String _normalise(String url) {
    var u = url.trim();
    if (!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://$u';
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    return u;
  }

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  Future<dynamic> get(String path) async {
    final r = await _send(() => http.get(Uri.parse('$baseUrl$path'), headers: _headers));
    return r;
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    return _send(() => http.post(Uri.parse('$baseUrl$path'),
        headers: _headers, body: jsonEncode(body ?? {})));
  }

  Future<dynamic> _send(Future<http.Response> Function() call) async {
    http.Response r;
    try {
      r = await call().timeout(_timeout);
    } on TimeoutException {
      throw ApiException('The engine did not answer. Is it running on your PC?');
    } catch (e) {
      throw ApiException('Cannot reach the engine at $baseUrl ($e)');
    }
    dynamic data;
    try {
      data = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (r.statusCode == 401) throw ApiException('Wrong pairing token.');
    if (r.statusCode >= 400) {
      final detail = (data is Map && data['detail'] != null) ? data['detail'].toString() : 'error ${r.statusCode}';
      throw ApiException(detail);
    }
    return data;
  }

  Future<bool> check() async {
    final h = await _send(() => http.get(Uri.parse('$baseUrl/health')));
    if (h is! Map || h['name'] != 'tradebot') throw ApiException('That address is not a TradeBot engine.');
    await get('/status');
    return true;
  }

  // ---------- saved connection ----------
  static Future<EngineApi?> load() async {
    final p = await SharedPreferences.getInstance();
    final url = p.getString('engine_url');
    final tok = p.getString('engine_token');
    if (url == null || tok == null || url.isEmpty || tok.isEmpty) return null;
    return EngineApi(url, tok);
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('engine_url', baseUrl);
    await p.setString('engine_token', token);
  }

  static Future<void> forget() async {
    final p = await SharedPreferences.getInstance();
    await p.remove('engine_url');
    await p.remove('engine_token');
  }
}

String rupees(num? v, {bool sign = false}) {
  if (v == null) return '—';
  final s = v.abs().toStringAsFixed(2);
  final prefix = v < 0 ? '-' : (sign && v > 0 ? '+' : '');
  return '$prefix₹$s';
}

double asDouble(dynamic v) => v == null ? 0.0 : (v as num).toDouble();
