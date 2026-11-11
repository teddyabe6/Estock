import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/models/stock.dart';
import 'package:estock_mobile/screens/stock_adjust_screen.dart';
import 'package:estock_mobile/screens/stock_receive_screen.dart';
import 'package:estock_mobile/screens/stock_request_screen.dart';
import 'package:estock_mobile/screens/stock_transfers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _main = 'b-main';
const _bole = 'b-bole';

const _everything = [
  'stock:view',
  'stock:adjust',
  'stock:receive',
  'stock:transfer',
  'stock:transfer_approve',
  'purchase:create',
  'supplier:view',
  'cost:view',
];

Map<String, dynamic> _overview() => {
      'branches': [
        {'branch_id': _main, 'name': 'Merkato Main', 'is_default': true,
          'total': '60.000'},
        {'branch_id': _bole, 'name': 'Bole Branch', 'is_default': false,
          'total': '4.000'},
      ],
      'rows': [
        {
          'product_id': 'p-teff',
          'variant_id': 'v-teff',
          'name': 'Teff flour 25kg',
          'unit': 'sack',
          'min_stock': '5',
          'reorder_level': '20',
          'quantities': {_main: '60.000', _bole: '4.000'},
          'stocked_at': [_main, _bole],
          'total': '64.000',
          'status': 'ok',
        },
      ],
      'grand_total': '64.000',
      'total': 1,
      'limit': 200,
      'offset': 0,
    };

final _catalogue = [
  {
    'id': 'p-teff',
    'name': 'Teff flour 25kg',
    'unit_of_measure': 'sack',
    'track_stock': true,
    'quantity_on_hand': '64.000',
    'stock_status': 'ok',
    'variants': [
      {
        'id': 'v-teff',
        'name': null,
        'selling_price': '2800',
        'purchase_price': '2400.00',
      }
    ],
  },
];

Map<String, dynamic> _transfer({
  String id = 't1',
  String status = 'dispatched',
  String from = _main,
  String to = _bole,
}) =>
    {
      'id': id,
      'reference': 'TR-2026-000009',
      'status': status,
      'from_branch_id': from,
      'from_branch_name': from == _main ? 'Merkato Main' : 'Bole Branch',
      'to_branch_id': to,
      'to_branch_name': to == _main ? 'Merkato Main' : 'Bole Branch',
      'lines': [
        {'name': 'Teff flour 25kg', 'quantity_sent': '10.000'}
      ],
    };

/// A signed-in phone, recording what it posts.
Future<(AppState, List<(String, Object?)>)> signedIn({
  List<String> permissions = _everything,
  List<Map<String, dynamic>> transfers = const [],
  List<Branch> branches = const [
    Branch(id: _main, name: 'Merkato Main', isDefault: true),
    Branch(id: _bole, name: 'Bole Branch'),
  ],
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <(String, Object?)>[];
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (request.method == 'POST') {
      posted.add((path, jsonDecode(request.body)));
      if (path.endsWith('/purchases')) {
        body = {
          'purchase': {'id': 'pu1', 'number': 'P-2026-000003'},
        };
      } else if (path.contains('/stock/transfers')) {
        body = _transfer(status: 'received');
      } else {
        body = {'id': 'm1'};
      }
    } else if (path.endsWith('/stock/branches')) {
      body = [
        {'branch_id': _main, 'branch_name': 'Merkato Main',
          'location_id': 'l-main', 'is_mine': true},
        {'branch_id': _bole, 'branch_name': 'Bole Branch',
          'location_id': 'l-bole', 'is_mine': true},
      ];
    } else if (path.endsWith('/suppliers')) {
      body = {
        'items': [
          {'id': 'sup-1', 'name': 'Highland Grain Suppliers'},
        ],
        'total': 1,
        'limit': 200,
        'offset': 0,
      };
    } else if (path.endsWith('/stock/transfers')) {
      body = transfers;
    } else {
      // Everything else is off the air, so a refresh falls back to the
      // copy on the phone.
      throw http.ClientException('not mocked: $path');
    }
    return http.Response(
      jsonEncode(body),
      request.method == 'POST' ? 201 : 200,
      headers: {'content-type': 'application/json'},
    );
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
    permissions: permissions,
    branches: branches,
  );
  state.products = _catalogue
      .map((p) => Product.fromJson(Map<String, dynamic>.from(p)))
      .toList();
  state.branchStock =
      StockByBranch.fromJson(Map<String, dynamic>.from(_overview()));
  return (state, posted);
}

Future<void> open(WidgetTester tester, AppState state, Widget screen) async {
  await tester.pumpWidget(
    AppScope(state: state, child: MaterialApp(home: screen)),
  );
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

/// The app itself, on the Stock tab.
Future<void> openStockTab(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(EstockApp(state: state));
  await tester.pump();
  await tester.tap(find.descendant(
    of: find.byType(NavigationBar),
    matching: find.text('Stock'),
  ));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('the way in', () {
    testWidgets('one button with a word on it, not two icons to guess at',
        (tester) async {
      final (state, _) = await signedIn();
      await openStockTab(tester, state);

      expect(find.text('Update stock'), findsOneWidget);

      await tester.tap(find.byKey(const Key('updateStock')));
      await tester.pumpAndSettle();

      // Each job in the words somebody would use for it.
      expect(find.text('What happened?'), findsOneWidget);
      expect(find.text('A delivery arrived'), findsOneWidget);
      expect(find.text('Count a shelf'), findsOneWidget);
      expect(find.text('Something broke or went missing'), findsOneWidget);
      expect(find.text('Move between branches'), findsOneWidget);
    });

    testWidgets('only the jobs this person may do are offered',
        (tester) async {
      final (state, _) = await signedIn(
        permissions: const ['stock:view', 'stock:adjust'],
      );
      await openStockTab(tester, state);

      await tester.tap(find.byKey(const Key('updateStock')));
      await tester.pumpAndSettle();

      expect(find.text('Count a shelf'), findsOneWidget);
      expect(find.text('A delivery arrived'), findsNothing);
      expect(find.text('Move between branches'), findsNothing);
    });

    testWidgets('somebody who may only look is not shown a button at all',
        (tester) async {
      final (state, _) = await signedIn(permissions: const ['stock:view']);
      await openStockTab(tester, state);

      expect(find.text('Update stock'), findsNothing);
    });
  });

  group('a delivery arriving', () {
    Future<void> addTeff(WidgetTester tester) async {
      await tester.enterText(find.byKey(const Key('receiveSearch')), 'teff');
      await tester.pump();
      await tester.tap(find.text('Teff flour 25kg').last);
      await tester.pump();
    }

    testWidgets('the cost starts at what it cost last time', (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const StockReceiveScreen());
      await addTeff(tester);

      // A price that has not moved is then nothing to type.
      expect(find.text('2400'), findsOneWidget);
      expect(find.text('Type how many arrived'), findsOneWidget);
    });

    testWidgets('it says the sum before it is asked to save it',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const StockReceiveScreen());
      await addTeff(tester);

      await tester.enterText(find.widgetWithText(TextField, 'How many'), '30');
      await tester.pump();

      expect(find.text('30 × 2,400.00 = 72,000.00 ETB'), findsOneWidget);
      expect(find.text('72,000.00 ETB'), findsOneWidget);
      expect(find.text('Add to the shelves'), findsOneWidget);
    });

    testWidgets('it reads the delivery back, and only then writes it',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const StockReceiveScreen());
      await addTeff(tester);
      await tester.enterText(find.widgetWithText(TextField, 'How many'), '30');
      await tester.pump();

      await tester.tap(find.byKey(const Key('receiveSave')));
      await tester.pumpAndSettle();

      // A slipped nought here is thirty sacks nobody has.
      expect(find.text('Add this to the shelves?'), findsOneWidget);
      expect(find.text('+30 sack'), findsOneWidget);
      expect(posted, isEmpty);

      await tester.tap(find.byKey(const Key('receiveConfirm')));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/purchases'));
      final body = posted.single.$2! as Map;
      expect(body['branch_id'], _main);
      expect(body['lines'], [
        {'variant_id': 'v-teff', 'quantity': '30', 'unit_cost': '2400'},
      ]);
      // Paid in full unless somebody says otherwise.
      expect(body['amount_paid'], '72000.00');
      expect(body['idempotency_key'], isNotNull);
    });

    testWidgets('paying part of it says what is still owed', (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const StockReceiveScreen());
      await addTeff(tester);
      await tester.enterText(find.widgetWithText(TextField, 'How many'), '30');
      await tester.pump();

      await tester.enterText(find.byKey(const Key('receivePaid')), '50000');
      await tester.pump();

      expect(find.textContaining('22,000.00 ETB still to pay'), findsOneWidget);
      // Below the fold on a short screen, so it is scrolled to like a
      // person would.
      await tester.scrollUntilVisible(
        find.text('Pay the rest by'),
        120,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Pay the rest by'), findsOneWidget);

      await tester.tap(find.byKey(const Key('receiveSave')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('receiveConfirm')));
      await tester.pumpAndSettle();

      expect((posted.single.$2! as Map)['amount_paid'], '50000.00');
    });

    testWidgets('more than it cost cannot be paid for it', (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const StockReceiveScreen());
      await addTeff(tester);
      await tester.enterText(find.widgetWithText(TextField, 'How many'), '1');
      await tester.pump();

      await tester.enterText(find.byKey(const Key('receivePaid')), '9000');
      await tester.pump();

      expect(find.text('Paid is more than the delivery cost'), findsOneWidget);
      await tester.tap(find.byKey(const Key('receiveSave')));
      await tester.pumpAndSettle();
      expect(posted, isEmpty);
    });
  });

  group('something broke or went missing', () {
    Future<void> openFor(WidgetTester tester, AppState state) => open(
          tester,
          state,
          const StockAdjustScreen(productId: 'p-teff', branchId: _bole),
        );

    testWidgets('it starts from what happened, and what is on the shelf',
        (tester) async {
      final (state, _) = await signedIn();
      await openFor(tester, state);

      expect(find.text('Broke or went off'), findsOneWidget);
      expect(find.text('Lost or stolen'), findsOneWidget);
      expect(find.text('Found more'), findsOneWidget);
      expect(find.text('On record here: 4 sack'), findsOneWidget);
    });

    testWidgets('it shows the shelf before and after, then says the words',
        (tester) async {
      final (state, posted) = await signedIn();
      await openFor(tester, state);

      await tester.enterText(find.byKey(const Key('adjustQuantity')), '3');
      await tester.pump();

      expect(find.text('4 → 1 sack'), findsOneWidget);
      expect(find.text('Take 3 sack off the books'), findsOneWidget);

      await tester.tap(find.byKey(const Key('adjustSave')));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/stock/adjust'));
      final body = posted.single.$2! as Map;
      expect(body['variant_id'], 'v-teff');
      expect(body['location_id'], 'l-bole');
      // The ledger carries the sign; the shopkeeper never types a minus.
      expect(body['quantity'], '-3');
      expect(body['reason'], 'damage');
      // Choosing what happened is already a reason in words.
      expect(body['note'], 'Broke or went off');
    });

    testWidgets('more than is there cannot break', (tester) async {
      final (state, posted) = await signedIn();
      await openFor(tester, state);

      await tester.enterText(find.byKey(const Key('adjustQuantity')), '9');
      await tester.pump();

      expect(find.textContaining('Only 4 sack on record here'), findsOneWidget);
      expect(find.text('That is more than is there'), findsOneWidget);

      await tester.tap(find.byKey(const Key('adjustSave')));
      await tester.pumpAndSettle();
      expect(posted, isEmpty);
    });

    testWidgets('finding more adds, and may be any amount', (tester) async {
      final (state, posted) = await signedIn();
      await openFor(tester, state);

      await tester.tap(find.text('Found more'));
      await tester.pump();
      await tester.enterText(find.byKey(const Key('adjustQuantity')), '9');
      await tester.pump();

      expect(find.text('4 → 13 sack'), findsOneWidget);
      await tester.tap(find.byKey(const Key('adjustSave')));
      await tester.pumpAndSettle();

      final body = posted.single.$2! as Map;
      expect(body['quantity'], '9');
      expect(body['reason'], 'adjustment');
    });
  });

  group('between branches', () {
    testWidgets('stock on its way can be said to have arrived',
        (tester) async {
      // Sent from the web by the main branch.  Until the other end
      // answers, it has left one shelf and is on nobody's — and a branch
      // that works from phones had no way to answer.
      final (state, posted) = await signedIn(transfers: [_transfer()]);
      await open(tester, state, const StockTransfersScreen());

      expect(find.text('On its way to you (1)'), findsOneWidget);
      expect(find.text('on its way'), findsWidgets);

      await tester.tap(find.text('It arrived').first);
      await tester.pumpAndSettle();
      expect(find.text('Did all of it arrive?'), findsOneWidget);
      expect(posted, isEmpty);

      await tester.tap(find.text('It arrived').last);
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/stock/transfers/t1/receive'));
    });

    testWidgets('stock can be sent as well as asked for', (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const StockTransfersScreen());

      expect(find.byKey(const Key('sendStock')), findsOneWidget);
      expect(find.byKey(const Key('askForStock')), findsOneWidget);
    });

    testWidgets('sending leaves at once, as one request', (tester) async {
      final (state, posted) = await signedIn();
      await open(
        tester,
        state,
        const StockRequestScreen(productId: 'p-teff', sending: true),
      );

      expect(find.text('Send stock'), findsOneWidget);
      // From the shelf that has it, to the one that is short of it; and
      // enough to bring that one back up to its reorder level.
      expect(find.text('Merkato Main — 60 sack'), findsOneWidget);
      expect(find.text('Bole Branch has 4 sack'), findsOneWidget);

      await tester.tap(find.text('Send it now'));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/stock/transfers'));
      final body = posted.single.$2! as Map;
      expect(body['from_location_id'], 'l-main');
      expect(body['to_location_id'], 'l-bole');
      expect(body['dispatch_now'], isTrue);
      expect(body['lines'], [
        {'variant_id': 'v-teff', 'quantity': '16'},
      ]);
    });

    testWidgets('more than the shelf holds cannot be sent from it',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(
        tester,
        state,
        const StockRequestScreen(productId: 'p-teff', sending: true),
      );

      await tester.enterText(
        find.descendant(
          of: find.byWidgetPredicate((w) => w is SizedBox && w.width == 96),
          matching: find.byType(TextField),
        ),
        '500',
      );
      await tester.pump();

      expect(find.text('Only 60 sack at Merkato Main'), findsOneWidget);
      expect(find.text('That is more than is there'), findsOneWidget);
      await tester.tap(find.text('That is more than is there'));
      await tester.pumpAndSettle();
      expect(posted, isEmpty);
    });
  });
}
