import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/sale_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _catalogue = [
  {
    'id': 'p-coffee',
    'name': 'Coffee beans 1kg',
    'unit_of_measure': 'kg',
    'track_stock': true,
    'quantity_on_hand': '50.000',
    'stock_status': 'ok',
    'variants': [
      {'id': 'v-coffee', 'name': null, 'selling_price': '720.00'}
    ],
  },
];

/// A till on a signed-in phone, recording what it posts.
///
/// [refuse] makes the server answer the way it really does when the books
/// would not balance.
Future<(AppState, List<Map<String, dynamic>>)> signedIn({
  String? refuse,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <Map<String, dynamic>>[];
  final client = MockClient((request) async {
    final path = request.url.path;
    if (request.method == 'POST' && path.endsWith('/sales')) {
      final body = Map<String, dynamic>.from(
        jsonDecode(request.body) as Map,
      );
      posted.add(body);
      if (refuse != null) {
        return http.Response(
          jsonEncode({'code': 'overpayment', 'message': refuse}),
          422,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(
        jsonEncode({
          'sale': {'id': 's1', 'number': 'S-2026-000012'},
          'warnings': <String>[],
        }),
        201,
        headers: {'content-type': 'application/json'},
      );
    }
    // Everything else is off the air, so the refresh after a sale falls
    // back to the cache rather than inventing a session.
    throw http.ClientException('not mocked: $path');
  });

  final state = AppState(
    api: ApiClient(baseUrl: 'http://test/api/v1', httpClient: client),
    outbox: Outbox(preferences: prefs),
    catalogue: CatalogueCache(preferences: prefs),
  );
  state.loading = false;
  state.session = const UserSession(
    userId: 'u1',
    fullName: 'Tigist Bekele',
    email: 'tigist@merkato-demo.et',
    tenantId: 't1',
    tenantName: 'Merkato Wholesale',
    currency: 'ETB',
    role: 'owner',
    permissions: ['sale:view', 'sale:create'],
    branches: [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
  );
  state.products = _catalogue
      .map((p) => Product.fromJson(Map<String, dynamic>.from(p)))
      .toList();
  return (state, posted);
}

Future<void> openTill(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(AppScope(
    state: state,
    child: const MaterialApp(home: Scaffold(body: SaleScreen())),
  ));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

/// Put one coffee in the basket.
Future<void> addCoffee(WidgetTester tester) async {
  await tester.enterText(find.byKey(const Key('productSearch')), 'coffee');
  await tester.pump();
  await tester.tap(find.text('Coffee beans 1kg').last);
  await tester.pump();
}

Future<void> received(WidgetTester tester, String amount) async {
  await tester.enterText(find.byKey(const Key('amountPaid')), amount);
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('taking the money', () {
    testWidgets('a note bigger than the sale is change, not a failed sale',
        (tester) async {
      // The one transaction every shop does all day: 720 to pay, a
      // thousand-birr note handed over.  Typing it used to post 1,000
      // against a 720 sale, which the server refuses outright — the
      // basket vanished and the counter was told it had been "saved".
      final (state, posted) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);
      await received(tester, '1000');

      expect(find.text('Change'), findsOneWidget);
      expect(find.text('280.00 ETB'), findsOneWidget);
      expect(find.textContaining('280.00 ETB change'), findsOneWidget);

      await tester.tap(find.byKey(const Key('completeSale')));
      await tester.pumpAndSettle();

      // The books take the sale's worth; the customer takes the change.
      expect(posted.single['payments'], [
        {'method': 'cash', 'amount': '720.00'},
      ]);
    });

    testWidgets('the exact money is still the exact money', (tester) async {
      final (state, posted) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);

      expect(find.text('Change'), findsNothing);

      await tester.tap(find.byKey(const Key('completeSale')));
      await tester.pumpAndSettle();

      expect(posted.single['payments'], [
        {'method': 'cash', 'amount': '720.00'},
      ]);
    });

    testWidgets('less than the total is still credit', (tester) async {
      final (state, _) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);
      await received(tester, '500');

      expect(find.text('On credit'), findsOneWidget);
      expect(find.text('Change'), findsNothing);
    });

    testWidgets('the notes somebody might hand over are one tap',
        (tester) async {
      final (state, _) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);

      // 720 to pay: the next round amounts up are 750, 800 and 1,000.
      expect(find.text('750.00'), findsOneWidget);
      expect(find.text('800.00'), findsOneWidget);
      expect(find.text('1,000.00'), findsOneWidget);

      await tester.tap(find.text('1,000.00'));
      await tester.pump();

      expect(find.text('280.00 ETB'), findsOneWidget);
    });
  });

  group('when the server says no', () {
    testWidgets('the basket stays, and the reason is said out loud',
        (tester) async {
      final (state, _) = await signedIn(
        refuse: 'Payments of 1000.00 exceed the sale total of 720.00',
      );
      await openTill(tester, state);
      await addCoffee(tester);

      await tester.tap(find.byKey(const Key('completeSale')));
      await tester.pumpAndSettle();

      // Not "saved on this phone": it was not saved anywhere.
      expect(find.textContaining('exceed the sale total'), findsOneWidget);
      expect(find.textContaining('Saved on this phone'), findsNothing);
      // And the work is still here, so nobody rings it up twice.
      expect(find.text('Coffee beans 1kg'), findsWidgets);
      expect(find.byKey(const Key('completeSale')), findsOneWidget);
    });

    testWidgets('and the refused copy does not linger in the outbox',
        (tester) async {
      final (state, _) = await signedIn(refuse: 'No.');
      await openTill(tester, state);
      await addCoffee(tester);

      await tester.tap(find.byKey(const Key('completeSale')));
      await tester.pumpAndSettle();

      expect(await state.outbox.all(), isEmpty);
    });
  });

  group('the basket', () {
    testWidgets('shows its own arithmetic once there is more than one',
        (tester) async {
      final (state, _) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);

      // One of something needs no sum; the only other 720.00 on screen
      // is the total.
      expect(find.text('720.00 ETB'), findsNWidgets(2));

      await tester.tap(find.byIcon(Icons.add_circle_outline));
      await tester.pump();
      await tester.tap(find.byIcon(Icons.add_circle_outline));
      await tester.pump();

      expect(find.text('3 × 720.00 = 2,160.00 ETB'), findsOneWidget);
    });

    testWidgets('a quantity can be typed instead of tapped up to',
        (tester) async {
      final (state, posted) = await signedIn();
      await openTill(tester, state);
      await addCoffee(tester);

      await tester.tap(find.text('1'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('howMany')), '12');
      await tester.tap(find.text('Set'));
      await tester.pumpAndSettle();

      expect(find.text('12 × 720.00 = 8,640.00 ETB'), findsOneWidget);

      await tester.tap(find.byKey(const Key('completeSale')));
      await tester.pumpAndSettle();

      expect((posted.single['lines'] as List).single,
          {'variant_id': 'v-coffee', 'quantity': '12.0'});
    });
  });
}
