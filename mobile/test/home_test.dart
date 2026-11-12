import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _owed(String total, int parties) => {
      'total_outstanding': total,
      'overdue': '0.00',
      'transaction_count': parties,
      'party_count': parties,
    };

/// A phone whose server answers Home's one question and nothing else.
Future<AppState> signedIn({String suppliersOwed = '9000.00'}) async {
  final prefs = await SharedPreferences.getInstance();
  final client = MockClient((request) async {
    final path = request.url.path;
    if (path.endsWith('/dashboard')) {
      return http.Response(
        jsonEncode({
          'today': {
            'net_sales': '0.00',
            'sale_count': 0,
            'items_sold': '0',
          },
          'receivables': _owed('2500.00', 2),
          'payables': _owed(suppliersOwed, 1),
          'low_stock': [
            {
              'product_id': 'p1',
              'variant_id': 'v1',
              'name': 'Berbere 1kg',
              'branch_id': 'b1',
              'branch_name': 'Merkato Main',
              'quantity': '3',
              'severity': 'critical',
            },
          ],
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }
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
    permissions: ['credit:view', 'purchase:view', 'stock:view', 'sale:view'],
    branches: [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
  );
  return state;
}

Future<void> openHome(WidgetTester tester, AppState state) async {
  tester.view.physicalSize = const Size(390 * 3, 844 * 3);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(EstockApp(state: state));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('what the shop owes suppliers is on Home, and opens',
      (tester) async {
    await openHome(tester, await signedIn());

    expect(find.text('YOU OWE SUPPLIERS'), findsOneWidget);
    expect(find.text('9,000.00 ETB'), findsOneWidget);
    expect(find.text('to 1 supplier'), findsOneWidget);

    await tester.tap(find.byKey(const Key('homePayables')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('What you owe suppliers'), findsOneWidget);
  });

  testWidgets('a shop that owes nothing is not told so', (tester) async {
    await openHome(tester, await signedIn(suppliersOwed: '0.00'));

    expect(find.text('YOU OWE SUPPLIERS'), findsNothing);
    expect(find.text('CUSTOMERS OWE YOU'), findsOneWidget);
  });

  testWidgets('a short shelf says how short, not "critical"',
      (tester) async {
    await openHome(tester, await signedIn());

    await tester.scrollUntilVisible(
      find.text('Berbere 1kg'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('very low'), findsOneWidget);
    expect(find.text('critical'), findsNothing);
  });
}
