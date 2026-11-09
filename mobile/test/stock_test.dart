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
          'stocked_at': [_main, _bole],
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
          // Bole has had some and sold out; the nought is real news.
          'quantities': {_main: '12.000', _bole: '0.000'},
          'stocked_at': [_main, _bole],
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
          'stocked_at': [_main, _bole],
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
  {
    'id': 'p-sugar',
    'name': 'Sugar 50kg',
    'unit_of_measure': 'bag',
    'track_stock': true,
    'quantity_on_hand': '20.000',
    'stock_status': 'ok',
    'variants': [
      {'id': 'v-sugar-a', 'name': 'white', 'selling_price': '3200'},
      {'id': 'v-sugar-b', 'name': 'brown', 'selling_price': '3100'},
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

/// A catalogue with categories and quantities worth ordering by, for the
/// tests about ordering and filtering rather than about branches.
final _shelf = [
  {
    'id': 'p-teff',
    'name': 'Teff flour 25kg',
    'category_name': 'Grains',
    'unit_of_measure': 'sack',
    'track_stock': true,
    'quantity_on_hand': '60.000',
    'stock_status': 'ok',
    'variants': [
      {'id': 'v-teff', 'name': null, 'selling_price': '2800'}
    ],
  },
  {
    'id': 'p-sunflower',
    'name': 'Sunflower oil 5L',
    'category_name': 'Cooking',
    'unit_of_measure': 'tin',
    'track_stock': true,
    'quantity_on_hand': '3.000',
    'stock_status': 'critical',
    'variants': [
      {'id': 'v-sunflower', 'name': null, 'selling_price': '950'}
    ],
  },
  {
    'id': 'p-berbere',
    'name': 'Berbere 1kg',
    'category_name': 'Spices',
    'unit_of_measure': 'kg',
    'track_stock': true,
    'quantity_on_hand': '18.000',
    'stock_status': 'warning',
    'variants': [
      {'id': 'v-berbere', 'name': null, 'selling_price': '450'}
    ],
  },
];

/// A signed-in device whose server answers with the overview above.
///
/// [products] replaces the catalogue for tests that care about ordering;
/// with it the branch picture is left empty, so the figures and statuses
/// come from the catalogue itself, as they do before the first sync.
Future<AppState> signedIn({
  List<Branch> branches = const [
    Branch(id: _main, name: 'Merkato Main', isDefault: true),
    Branch(id: _bole, name: 'Bole Branch'),
  ],
  List<Map<String, dynamic>>? products,
  Map<String, dynamic>? overview,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (path.endsWith('/stock/overview')) {
      body = overview ?? _overview();
    } else if (path.endsWith('/stock/setup')) {
      body = <dynamic>[];
    } else if (path.endsWith('/stock/transfers')) {
      body = <dynamic>[];
    } else if (path.endsWith('/products')) {
      final catalogue = products ?? _products;
      body = {
        'items': catalogue,
        'total': catalogue.length,
        'limit': 200,
        'offset': 0,
      };
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
  state.products = (products ?? _products)
      .map((p) => Product.fromJson(Map<String, dynamic>.from(p)))
      .toList();
  if (products == null || overview != null) {
    state.branchStock =
        StockByBranch.fromJson(Map<String, dynamic>.from(overview ?? _overview()));
  }
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
      expect(stock.statusFor('p-cement', _bole), 'critical');
      expect(stock.statusFor('p-sugar', _bole), 'out_of_stock');
    });

    test('short at one branch is short for the business too', () {
      // The old answer here was 'ok', because 104 bags clears a minimum of
      // five — and that is how a shelf with four bags on it stayed hidden
      // from the owner looking at all her branches at once.  With nothing
      // narrowed down, the branch in the worst state is the answer.
      expect(stock.statusFor('p-cement', null), 'critical');
      expect(stock.statusFor('p-sugar', null), 'out_of_stock');
    });

    test('and it names the branch to go and look at', () {
      expect(stock.shortBranches('p-cement').map((b) => b.name),
          ['Bole Branch']);
      expect(stock.shortBranches('p-sugar').map((b) => b.name),
          ['Bole Branch']);

      // And how little is left there, so the row can say it.
      expect(stock.shortBranches('p-cement').single.quantity, 4);
      expect(stock.shortBranches('p-cement').single.isEmpty, isFalse);
      expect(stock.shortBranches('p-sugar').single.isEmpty, isTrue);
    });

    test('a product that is fine everywhere names nobody', () {
      final plenty = StockByBranch.fromJson(Map<String, dynamic>.from({
        ..._overview(),
        'rows': [
          {
            'product_id': 'p-cement',
            'variant_id': 'v-cement',
            'name': 'Cement bag 50kg',
            'unit': 'bag',
            'min_stock': '5',
            'reorder_level': '20',
            'quantities': {_main: '100.000', _bole: '40.000'},
            'total': '140.000',
            'status': 'ok',
          },
        ],
      }));
      expect(plenty.statusFor('p-cement', null), 'ok');
      expect(plenty.shortBranches('p-cement'), isEmpty);
    });

    test('the worst branch wins, and is named first', () {
      final three = StockByBranch.fromJson(Map<String, dynamic>.from({
        'branches': [
          {'branch_id': _main, 'name': 'Merkato Main', 'is_default': true,
            'total': '100.000'},
          {'branch_id': _bole, 'name': 'Bole Branch', 'is_default': false,
            'total': '10.000'},
          {'branch_id': 'b-kality', 'name': 'Kality', 'is_default': false,
            'total': '0.000'},
        ],
        'rows': [
          {
            'product_id': 'p-cement',
            'variant_id': 'v-cement',
            'name': 'Cement bag 50kg',
            'unit': 'bag',
            'min_stock': '5',
            'reorder_level': '20',
            // Plenty here, under the reorder level there, none at all at
            // the third.
            'quantities': {_main: '100.000', _bole: '10.000',
              'b-kality': '0.000'},
            'total': '110.000',
            'status': 'ok',
          },
        ],
        'grand_total': '110.000',
        'total': 1,
        'limit': 200,
        'offset': 0,
      }));
      expect(three.statusFor('p-cement', null), 'out_of_stock');
      expect(three.shortBranches('p-cement').map((b) => b.name),
          ['Kality', 'Bole Branch']);
    });

    test('a branch that does not sell it is not short of it', () {
      // Teff is a main-branch line.  Bole's nought against it says the
      // shop does not sell teff, which is not a reason to send anybody
      // out for a sack of it.
      final narrow = StockByBranch.fromJson(Map<String, dynamic>.from({
        ..._overview(),
        'rows': [
          {
            'product_id': 'p-teff',
            'variant_id': 'v-teff',
            'name': 'Teff flour 25kg',
            'unit': 'sack',
            'min_stock': '10',
            'reorder_level': '20',
            'quantities': {_main: '60.000', _bole: '0.000'},
            'stocked_at': [_main],
            'total': '60.000',
            'status': 'ok',
          },
        ],
      }));

      expect(narrow.statusFor('p-teff', null), 'ok');
      expect(narrow.shortBranches('p-teff'), isEmpty);
      expect(narrow.forProduct('p-teff')!.carriedAt(_bole), isFalse);
      expect(narrow.forProduct('p-teff')!.carriedAt(_main), isTrue);

      // Asked about Bole directly, the honest answer is still nought —
      // somebody standing there with the shelf in front of them is not
      // being told a different story about it.
      expect(narrow.statusFor('p-teff', _bole), 'out_of_stock');
    });

    test('a server that does not say falls back to judging every branch', () {
      // An older server, or a copy cached before this was recorded, must
      // not quietly empty the restocking list.
      final silent = StockByBranch.fromJson(Map<String, dynamic>.from({
        ..._overview(),
        'rows': [
          {
            'product_id': 'p-teff',
            'variant_id': 'v-teff',
            'name': 'Teff flour 25kg',
            'unit': 'sack',
            'min_stock': '10',
            'reorder_level': '20',
            'quantities': {_main: '60.000', _bole: '0.000'},
            'total': '60.000',
            'status': 'ok',
          },
        ],
      }));

      expect(silent.statusFor('p-teff', null), 'out_of_stock');
      expect(silent.shortBranches('p-teff').map((b) => b.name),
          ['Bole Branch']);
    });

    test('it survives the round trip through the device', () {
      final again = StockByBranch.fromJson(
        Map<String, dynamic>.from(jsonDecode(jsonEncode(stock.toJson())) as Map),
      );
      expect(again.branches.map((b) => b.name), ['Merkato Main', 'Bole Branch']);
      expect(again.forProduct('p-cement')!.at(_bole), 4);
      expect(again.statusFor('p-cement', _bole), 'critical');
      // Including which branches sell it, or every cached copy would
      // read as four empty shelves the moment it is loaded again.
      expect(again.forProduct('p-cement')!.stockedAt, {_main, _bole});
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
      expect(find.textContaining('100 bag at other branches'), findsOneWidget);
    });

    testWidgets('short at one branch shows up under the filter',
        (tester) async {
      final state = await signedIn();
      await openStock(tester, state);

      // With every branch in view the four bags at Bole are still four
      // bags, so the filter has to surface them — and say where they are,
      // or there is nothing to act on.
      await tester.tap(find.text('Needs restocking'));
      await tester.pump();
      expect(find.text('Cement bag 50kg'), findsOneWidget);
      expect(find.textContaining('Down to 4 bag at Bole Branch'),
          findsOneWidget);

      // At Bole itself the branch is already the answer, so it is not
      // repeated under the name.
      await pickBranch(tester, 'Bole Branch');
      expect(find.text('Cement bag 50kg'), findsOneWidget);
      expect(find.text('critical'), findsOneWidget);
      expect(find.textContaining('at Bole Branch'), findsNothing);
    });

    testWidgets('an empty shelf is named as empty, not as a small number',
        (tester) async {
      await openStock(tester, await signedIn());

      // Sugar: twelve and eight at the main branch, none at all at Bole.
      expect(find.textContaining('None left at Bole Branch'), findsOneWidget);
    });

    testWidgets('the chip beside a business total counts shelves, not stock',
        (tester) async {
      // "104 bag" and "critical" side by side reads as a broken app.  With
      // every branch in view the figure is the whole business's, so the
      // chip has to be about branches too — but only when there is more
      // than one of them to count.
      final state = await signedIn();
      await openStock(tester, state);

      // Bole is short of both, and it is the only one, so each row counts
      // one branch and names it underneath.
      expect(find.text('critical'), findsNothing);
      expect(find.text('out of stock'), findsNothing);
      expect(find.text('1 branch short'), findsNWidgets(2));
      expect(find.textContaining('Down to 4 bag at Bole Branch'),
          findsOneWidget);

      await pickBranch(tester, 'Bole Branch');

      // Narrowed to one branch, the figure is that branch's own and the
      // plain word is the honest label for it.
      expect(find.text('critical'), findsOneWidget);
      expect(find.text('out of stock'), findsOneWidget);
    });

    testWidgets('nothing short says so without claiming a branch',
        (tester) async {
      // Every product fine at both branches: the empty state must not say
      // "here" when there is no here.
      final state = await signedIn(products: [
        {
          'id': 'p-teff',
          'name': 'Teff flour 25kg',
          'unit_of_measure': 'sack',
          'track_stock': true,
          'quantity_on_hand': '60.000',
          'stock_status': 'ok',
          'variants': [
            {'id': 'v-teff', 'name': null, 'selling_price': '2800'}
          ],
        },
      ]);
      await openStock(tester, state);

      await tester.tap(find.text('Needs restocking'));
      await tester.pumpAndSettle();

      expect(find.text('Nothing needs restocking'), findsOneWidget);
      expect(find.textContaining('at every branch'), findsOneWidget);
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

    testWidgets('and says plainly when a branch does not sell the thing',
        (tester) async {
      // Four satellite branches that each carry two lines would otherwise
      // show a nought against everything else, which reads as an empty
      // shelf and sends somebody out shopping for nothing.
      final state = await signedIn(
        products: [
          {
            'id': 'p-teff',
            'name': 'Teff flour 25kg',
            'unit_of_measure': 'sack',
            'track_stock': true,
            'quantity_on_hand': '60.000',
            'stock_status': 'ok',
            'variants': [
              {'id': 'v-teff', 'name': null, 'selling_price': '2800'}
            ],
          },
        ],
        overview: {
          ..._overview(),
          'rows': [
            {
              'product_id': 'p-teff',
              'variant_id': 'v-teff',
              'name': 'Teff flour 25kg',
              'unit': 'sack',
              'min_stock': '10',
              'reorder_level': '20',
              'quantities': {_main: '60.000', _bole: '0.000'},
              'stocked_at': [_main],
              'total': '60.000',
              'status': 'ok',
            },
          ],
        },
      );
      await openStock(tester, state);

      // Nothing on the row says it is short.
      expect(find.text('1 branch short'), findsNothing);

      await tester.tap(find.text('Teff flour 25kg'));
      await tester.pumpAndSettle();

      expect(find.text('does not stock it'), findsOneWidget);
      expect(find.text('60'), findsOneWidget);
    });

    testWidgets('and marks the shop you are standing in, and the short one',
        (tester) async {
      await openStock(tester, await signedIn());
      await pickBranch(tester, 'Bole Branch');

      await tester.tap(find.text('Cement bag 50kg'));
      await tester.pumpAndSettle();

      // Four bags against a minimum of five, and this is the branch in
      // hand — both worth saying on the row itself.
      expect(find.text('Bole Branch (here)'), findsOneWidget);
      expect(find.text('Merkato Main'), findsWidgets);
      expect(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.text('critical'),
        ),
        findsOneWidget,
      );
    });
  });

  // ---------------------------------------------------------------------- //
  // Finding one thing among many
  // ---------------------------------------------------------------------- //

  group('ordering and filtering', () {
    /// The names on the list, top to bottom.
    List<String> listed(WidgetTester tester) => tester
        .widgetList<ListTile>(find.byType(ListTile))
        .map((tile) => (tile.title! as Text).data!)
        .toList();

    Future<void> openSheet(WidgetTester tester) async {
      await tester.tap(find.byTooltip('Sort and filter'));
      await tester.pumpAndSettle();
    }

    /// Pick an option in the sheet, by name.
    ///
    /// Scoped to the sheet, because a category's name is also printed under
    /// every product of it and a finder that does not say which one it
    /// means will find the wrong one; and scrolled to, because the sheet
    /// builds only the options on screen, as it does on a phone.
    Future<void> choose(WidgetTester tester, String label) async {
      Finder inSheet(String text) => find.descendant(
            of: find.byType(BottomSheet),
            matching: find.text(text),
          );
      final option = inSheet(label);
      if (option.evaluate().isEmpty) {
        await tester.scrollUntilVisible(
          option,
          80,
          scrollable: find
              .descendant(
                of: find.byType(BottomSheet),
                matching: find.byType(Scrollable),
              )
              .first,
        );
      }
      await tester.ensureVisible(option);
      await tester.pumpAndSettle();
      await tester.tap(option);
      await tester.pumpAndSettle();
      await tester.tap(inSheet('Done'));
      await tester.pumpAndSettle();
    }

    testWidgets('it starts alphabetical', (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      expect(listed(tester),
          ['Berbere 1kg', 'Sunflower oil 5L', 'Teff flour 25kg']);
    });

    testWidgets('most urgent first is by urgency, not by the alphabet',
        (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      await openSheet(tester);
      await choose(tester, 'Most urgent');

      // Critical, then warning, then the one that is fine.
      expect(listed(tester),
          ['Sunflower oil 5L', 'Berbere 1kg', 'Teff flour 25kg']);
    });

    testWidgets('fewest and most here are opposite ends of one list',
        (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      await openSheet(tester);
      await choose(tester, 'Fewest here');
      expect(listed(tester).first, 'Sunflower oil 5L');

      await openSheet(tester);
      await choose(tester, 'Most here');
      expect(listed(tester).first, 'Teff flour 25kg');
    });

    testWidgets('by category puts a heading over each run', (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      await openSheet(tester);
      await choose(tester, 'By category');

      expect(find.text('COOKING'), findsOneWidget);
      expect(find.text('GRAINS'), findsOneWidget);
      expect(find.text('SPICES'), findsOneWidget);
      expect(listed(tester),
          ['Sunflower oil 5L', 'Teff flour 25kg', 'Berbere 1kg']);
    });

    testWidgets('one category narrows the list to it', (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      await openSheet(tester);
      await choose(tester, 'Spices');

      expect(listed(tester), ['Berbere 1kg']);
    });

    testWidgets('a narrowed list says which filter emptied it',
        (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      await openSheet(tester);
      await choose(tester, 'Grains');
      await tester.tap(find.text('Needs restocking'));
      await tester.pumpAndSettle();

      expect(find.text('Nothing in Grains'), findsOneWidget);
    });

    testWidgets('the button says when the list is not as it was left',
        (tester) async {
      await openStock(tester, await signedIn(products: _shelf));

      // Plain order, plain icon.
      expect(find.byType(Badge), findsNothing);

      await openSheet(tester);
      await choose(tester, 'Most urgent');

      expect(find.byType(Badge), findsOneWidget);
    });
  });
}
