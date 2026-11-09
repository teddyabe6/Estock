import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/models/stock.dart';
import 'package:estock_mobile/screens/stock_request_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _main = 'b-main';
const _bole = 'b-bole';
const _kality = 'b-kality';

/// Berbere is short at the main branch, plentiful at Kality and nearly
/// gone at Bole — so there is a right answer to "who should I ask?".
Map<String, dynamic> _overview() => {
      'branches': [
        {'branch_id': _main, 'name': 'Merkato Main', 'is_default': true,
          'total': '7.000'},
        {'branch_id': _bole, 'name': 'Bole Branch', 'is_default': false,
          'total': '3.000'},
        {'branch_id': _kality, 'name': 'Kality Branch', 'is_default': false,
          'total': '40.000'},
      ],
      'rows': [
        {
          'product_id': 'p-berbere',
          'variant_id': 'v-berbere',
          'name': 'Berbere 1kg',
          'unit': 'kg',
          'min_stock': '10',
          'reorder_level': '25',
          'quantities': {_main: '7.000', _bole: '3.000', _kality: '40.000'},
          'stocked_at': [_main, _bole, _kality],
          'total': '50.000',
          'status': 'ok',
        },
      ],
      'grand_total': '50.000',
      'total': 1,
      'limit': 200,
      'offset': 0,
    };

final _catalogue = [
  {
    'id': 'p-berbere',
    'name': 'Berbere 1kg',
    'unit_of_measure': 'kg',
    'track_stock': true,
    'quantity_on_hand': '50.000',
    'stock_status': 'ok',
    'variants': [
      {'id': 'v-berbere', 'name': null, 'selling_price': '450'}
    ],
  },
];

Future<(AppState, List<Map<String, dynamic>>)> signedIn({
  bool withBranchPicture = true,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <Map<String, dynamic>>[];
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (path.endsWith('/stock/branches')) {
      body = [
        {'branch_id': _main, 'branch_name': 'Merkato Main',
          'location_id': 'l-main', 'is_mine': true},
        {'branch_id': _bole, 'branch_name': 'Bole Branch',
          'location_id': 'l-bole', 'is_mine': false},
        {'branch_id': _kality, 'branch_name': 'Kality Branch',
          'location_id': 'l-kality', 'is_mine': false},
      ];
    } else if (path.endsWith('/stock/requests')) {
      posted.add(Map<String, dynamic>.from(jsonDecode(request.body) as Map));
      body = {'id': 'r-1'};
    } else {
      body = <String, dynamic>{};
    }
    return http.Response(jsonEncode(body), 200,
        headers: {'content-type': 'application/json'});
  });

  final state = AppState(
    api: ApiClient(baseUrl: 'http://test/api/v1', httpClient: client),
    outbox: Outbox(preferences: prefs),
    catalogue: CatalogueCache(preferences: prefs),
  );
  state.loading = false;
  state.session = UserSession(
    userId: 'u1',
    fullName: 'Tigist Bekele',
    email: 'tigist@merkato-demo.et',
    tenantId: 't1',
    tenantName: 'Merkato Wholesale',
    currency: 'ETB',
    role: 'owner',
    permissions: const ['stock:view', 'stock:transfer'],
    branches: const [
      Branch(id: _main, name: 'Merkato Main', isDefault: true),
      Branch(id: _bole, name: 'Bole Branch'),
      Branch(id: _kality, name: 'Kality Branch'),
    ],
  );
  state.products = _catalogue
      .map((p) => Product.fromJson(Map<String, dynamic>.from(p)))
      .toList();
  if (withBranchPicture) {
    state.branchStock =
        StockByBranch.fromJson(Map<String, dynamic>.from(_overview()));
  }
  return (state, posted);
}

Future<void> openAsk(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(AppScope(
    state: state,
    child: const MaterialApp(
      home: StockRequestScreen(productId: 'p-berbere'),
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

/// What the quantity box holds — the narrow one on a product's row, not
/// the search box or the note.
String typed(WidgetTester tester) => tester
    .widget<TextField>(find.descendant(
      of: find.byWidgetPredicate((w) => w is SizedBox && w.width == 96),
      matching: find.byType(TextField),
    ))
    .controller!
    .text;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('asking another branch', () {
    testWidgets('it asks the branch with the most of it', (tester) async {
      // Bole is first in the list and has three kilos; Kality has forty.
      final (state, _) = await signedIn();
      await openAsk(tester, state);

      expect(find.textContaining('Kality Branch'), findsOneWidget);
      expect(find.textContaining('Bole Branch'), findsNothing);
    });

    testWidgets('and says what each branch has, so the ask is informed',
        (tester) async {
      final (state, _) = await signedIn();
      await openAsk(tester, state);

      expect(find.text('Kality Branch — 40 kg'), findsOneWidget);
    });

    testWidgets('the amount is the gap up to the reorder level',
        (tester) async {
      // Seven kilos on a shelf that should hold twenty-five.
      final (state, _) = await signedIn();
      await openAsk(tester, state);

      expect(typed(tester), '18');
      expect(find.text('You have 7 kg here'), findsOneWidget);
    });

    testWidgets('and that is what is sent', (tester) async {
      final (state, posted) = await signedIn();
      await openAsk(tester, state);

      await tester.tap(find.text('Send the request'));
      await tester.pumpAndSettle();

      expect(posted, hasLength(1));
      expect(posted.first['from_location_id'], 'l-kality');
      expect(posted.first['to_location_id'], 'l-main');
      expect(posted.first['lines'], [
        {'variant_id': 'v-berbere', 'quantity': '18'},
      ]);
    });

    testWidgets('a phone that cannot see other shelves still works',
        (tester) async {
      // Somebody without cross-branch sight gets names and nothing else —
      // no figures invented, no figures leaked.
      final (state, _) = await signedIn(withBranchPicture: false);
      await openAsk(tester, state);

      expect(find.text('Bole Branch'), findsOneWidget);
      expect(find.textContaining('Bole Branch —'), findsNothing);
      expect(find.textContaining('You have'), findsNothing);
      expect(typed(tester), '1');
    });
  });
}
