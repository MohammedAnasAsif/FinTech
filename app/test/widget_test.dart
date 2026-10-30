import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:tradebot_app/api.dart';
import 'package:tradebot_app/main.dart';

void main() {
  testWidgets('first launch asks to connect to the engine', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const TradeBotApp());
    await tester.pumpAndSettle();
    expect(find.text('Connect to your engine'), findsOneWidget);
    expect(find.text('Connect'), findsOneWidget);
  });

  test('money formatting', () {
    expect(rupees(12.5), '₹12.50');
    expect(rupees(-3), '-₹3.00');
    expect(rupees(4, sign: true), '+₹4.00');
    expect(rupees(null), '—');
  });

  test('engine address is normalised', () {
    expect(EngineApi('192.168.1.5:8765/', 't').baseUrl, 'http://192.168.1.5:8765');
  });
}
