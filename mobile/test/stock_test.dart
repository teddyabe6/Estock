import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/models/stock.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _main = 'b-main';
const _bole = 'b-bole';

/// Two branches, one product in both and one only at the main branch.
Map<String, dynamic> _overview() => {
      'branches': [
        {'branch_id': _main, 'name': 'Merkato Main', 'is_default': true, 'total': '120.000'},
        {'branch_id': _bole, 'name': 'Bole Branch', 'is_default': false, 'total': '4.000'},
      ],
      'rows': [
        {
          'product_id': 'p-cement',
          'variant_id': 'v-cement',
          'name': 'Cement bag 50kg',
          'unit': 'bag',
          'min_stock': '5',
          'reorder_level': '20',
          'quantities': {_main: '100.000', _bole: '4.000'},
          'total': '104.000',
          'status': 'ok',
        },
        {
          'product_id': 'p-sugar',
          'variant_id': 'v-sugar-a',
          'name': 'Sugar 50kg — white',
          'unit': 'bag',
          'min_stock': null,
          'reorder_level': null,
          'quantities': {_main: '12.000', _bole: '0.000'},
          'total': '12.000',
          'status': 'ok',
        },
        {
          'product_id': 'p-sugar',
          'variant_id': 'v-sugar-b',
          'name': 'Sugar 50kg — brown',
          'unit': 'bag',
          'min_stock': null,
          'reorder_level': null,
          'quantities': {_main: '8.000', _bole: '0.000'},
          'total': '8.000',
          'status': 'ok',
        },
      ],
      'grand_total': '124.000',
      'total': 3,
      'limit': 200,
      'offset': 0,
    };

final _products = [
  {
    'id': 'p-cement',
    'name': 'Cement bag 50kg',
    'unit_of_measure': 'bag',
    'track_stock': true,
    'quantity_on_hand': '104.000',
    'stock_status': 'ok',
    'variants': [
      {'id': 'v-cement', 'name': null, 'selling_price': '900'}
    ],
  },
];

UserSession _session(List<Branch> branches) => UserSession(
      userId: 'u1',
      fullName: 'Tigist Bekele',
      email: 'tigist@merkato-demo.et',
      tenantId: 't1',
      tenantName: 'Merkato Wholesale',
      currency: 'ETB',
      role: 'owner',
      permissions: const [
        'stock:view',
        'stock:adjust',
        'stock:transfer',
        'stock:transfer_approve',
      ],
      branches: branches,
    );

/// A signed-in device whose server answers with the overview above.
Future<AppState> signedIn({
  List<Branch> branches = const [
    Branch(id: _main, name: 'Merkato Main', isDefault: true),
    Branch(id: _bole, name: 'Bole Branch'),
  ],
}) async {
  final prefs = await SharedPreferences.getInstance();
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (path.endsWith('/stock/overview')) {
      body = _overview();
    } else if (path.endsWith('/stock/setup')) {
      body = <dynamic>[];
    } else if (path.endsWith('/stock/transfers')) {
      body = <dynamic>[];
    } else if (path.endsWith('/products')) {
      body = {'items': _products, 'total': 1, 'limit': 200, 'offset': 0};
    } else if (path.endsWith('/notifications')) {
      body = {'items': <dynamic>[], 'total': 0, 'unread': 0};
    } else {
      throw http.ClientException('not mocked: $path');
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
  state.session = _session(branches);
  state.products =
      _products.map((p) => Product.fromJson(Map<String, dynamic>.from(p))).toList();
  state.branchStock =
      StockByBranch.fromJson(Map<String, dynamic>.from(_overview()));
  return state;
}

/// Tap a branch chip, scrolling the row until it is actually on screen: with
/// several branches the chips run past the edge, exactly as they do on a
/// phone.
Future<void> pickBranch(WidgetTester tester, String name) async {
  final chip = find.widgetWithText(ChoiceChip, name);
  await tester.ensureVisible(chip);
  await tester.pumpAndSettle();
  await tester.tap(chip);
  await tester.pump();
}

Future<void> openStock(WidgetTester tester, AppState state) async {
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

  group('the branch picture', () {
    final stock = StockByBranch.fromJson(Map<String, dynamic>.from(_overview()));

    test('a branch holding none of something still has a figure', () {
      // Nothing recorded is an answer, not a missing row: it is exactly what
      // the branch that has run out opens this to find out.
      expect(stock.forProduct('p-sugar')!.at(_bole), 0);
      expect(stock.forProduct('p-sugar')!.at(_main), 20);
    });

    test('two variants of one product are one line on a phone', () {
      expect(stock.forProduct('p-sugar')!.total, 20);
    });

    test('every branch keeps its own total', () {
      expect(stock.forProduct('p-cement')!.at(_main), 100);
      expect(stock.forProduct('p-cement')!.at(_bole), 4);
      expect(stock.forProduct('p-cement')!.total, 104);
    });

    test('short here is short, however much the business holds', () {
      // 104 bags across the business, 4 of them here and the minimum is 5.
      expect(stock.statusFor('p-cement', null), 'ok');
      expect(stock.statusFor('p-cement', _bole), 'critical');
      expect(stock.statusFor('p-sugar', _bole), 'out_of_stock');
    });

    test('it survives the round trip through the device', () {
      final again = StockByBranch.fromJson(
        Map<String, dynamic>.from(jsonDecode(jsonEncode(stock.toJson())) as Map),
      );
      expect(again.branches.map((b) => b.name), ['Merkato Main', 'Bole Branch']);
      expect(again.forProduct('p-cement')!.at(_bole), 4);
      expect(again.statusFor('p-cement', _bole), 'critical');
    });
  });

  group('whose move it is', () {
    final owner = _session(const [
      Branch(id: _main, name: 'Merkato Main', isDefault: true),
      Branch(id: _bole, name: 'Bole Branch'),
    ]);
    final bole = UserSession(
      userId: 'u2',
      fullName: 'Selam',
      email: 'selam@example.et',
      tenantId: 't1',
      tenantName: 'Merkato Wholesale',
      currency: 'ETB',
      role: 'manager',
      permissions: const ['stock:view', 'stock:transfer'],
      branches: const [Branch(id: _bole, name: 'Bole Branch')],
    );

    StockTransfer transfer(String status) => StockTransfer.fromJson({
          'id': 't1',
          'reference': 'TR-1',
          'status': status,
          'from_branch_id': _main,
          'from_branch_name': 'Merkato Main',
          'to_branch_id': _bole,
          'to_branch_name': 'Bole Branch',
          'requested_at': '2026-10-31T06:00:00Z',
          'lines': [
            {'name': 'Cement bag 50kg', 'quantity_sent': '15.000'}
          ],
        });

    test('a request waits on whoever runs the branch being asked', () {
      expect(transfer('requested').needsAnswerFrom(owner, {_main, _bole}), isTrue);
      // Bole asked; Bole cannot answer for Merkato, nor may it decide at all.
      expect(transfer('requested').needsAnswerFrom(bole, {_bole}), isFalse);
    });

    test('an allowed request waits on the branch that asked', () {
      expect(transfer('approved').needsAnswerFrom(bole, {_bole}), isTrue);
    });

    test('a finished transfer waits on nobody', () {
      expect(transfer('received').needsAnswerFrom(owner, {_main, _bole}), isFalse);
      expect(transfer('rejected').needsAnswerFrom(owner, {_main, _bole}), isFalse);
    });
  });

  group('the stock tab', () {
    testWidgets('one branch means no branch chips at all', (tester) async {
      await openStock(
        tester,
        await signedIn(branches: const [
          Branch(id: _main, name: 'Merkato Main', isDefault: true),
        ]),
      );

      expect(find.text('All branches'), findsNothing);
      expect(find.text('Needs restocking'), findsOneWidget);
    });

    testWidgets('the figure follows the branch you pick', (tester) async {
      await openStock(tester, await signedIn());

      // Everything together first.
      expect(find.text('104 bag', findRichText: true), findsOneWidget);
      expect(find.text('All branches'), findsOneWidget);

      await pickBranch(tester, 'Bole Branch');

      // Bole's own four, and where the rest of it is.
      expect(find.text('4 bag', findRichText: true), findsOneWidget);
      expect(find.text('104 bag', findRichText: true), findsNothing);
      expect(find.textContaining('100 at other branches'), findsOneWidget);
    });

    testWidgets('short at this branch shows up under the filter', (tester) async {
      final state = await signedIn();
      await openStock(tester, state);

      // Across the business there is plenty, so nothing is flagged.
      await tester.tap(find.text('Needs restocking'));
      await tester.pump();
      expect(find.text('Cement bag 50kg'), findsNothing);

      // At Bole there are four bags and the minimum is five.
      await pickBranch(tester, 'Bole Branch');
      expect(find.text('Cement bag 50kg'), findsOneWidget);
      expect(find.text('critical'), findsOneWidget);
    });

    testWidgets('tapping a product says where the rest of it is',
        (tester) async {
      await openStock(tester, await signedIn());

      await tester.tap(find.text('Cement bag 50kg'));
      await tester.pumpAndSettle();

      expect(find.textContaining('104 bag across 2 branches'), findsOneWidget);
      expect(find.text('Merkato Main'), findsWidgets);
      expect(find.text('Ask another branch for some'), findsOneWidget);
    });
  });
}
