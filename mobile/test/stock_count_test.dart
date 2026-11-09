import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/stock_count_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _main = 'b-main';

/// A shelf list as `GET /stock/opening` returns it: two products, one of
/// which the branch is already recorded as holding.
Map<String, dynamic> _sheet({String berbere = '7.000', int recorded = 1}) => {
      'branch_name': 'Merkato Main',
      'location_name': 'Main store',
      'product_count': 2,
      'recorded': recorded,
      'rows': [
        {
          'variant_id': 'v-berbere',
          'product_id': 'p-berbere',
          'name': 'Berbere 1kg',
          'unit': 'kg',
          'quantity': berbere,
        },
        {
          'variant_id': 'v-teff',
          'product_id': 'p-teff',
          'name': 'Teff flour 25kg',
          'unit': 'sack',
          'quantity': '0.000',
        },
      ],
    };

/// A signed-in device whose server serves [sheet] and records what is
/// posted back to it.
Future<(AppState, List<Map<String, dynamic>>)> signedIn({
  Map<String, dynamic>? sheet,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <Map<String, dynamic>>[];
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (path.endsWith('/stock/opening')) {
      if (request.method == 'POST') {
        final sent = Map<String, dynamic>.from(
          jsonDecode(request.body) as Map,
        );
        posted.add(sent);
        body = {'recorded': (sent['lines'] as List<dynamic>).length};
      } else {
        body = sheet ?? _sheet();
      }
    } else if (path.endsWith('/auth/session')) {
      throw http.ClientException('offline');
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
    permissions: const ['stock:view', 'stock:adjust'],
    branches: const [Branch(id: _main, name: 'Merkato Main', isDefault: true)],
  );
  return (state, posted);
}

Future<void> openCount(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(AppScope(
    state: state,
    child: const MaterialApp(home: StockCountScreen(branchId: _main)),
  ));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

/// Type into the quantity box on the row named [product].
Future<void> count(
  WidgetTester tester,
  String product,
  String quantity,
) async {
  final box = find.descendant(
    of: find.ancestor(
      of: find.text(product),
      matching: find.byType(ListTile),
    ),
    matching: find.byType(TextField),
  );
  await tester.enterText(box, quantity);
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('walking the shelves', () {
    testWidgets('an untouched list does not claim to be counted',
        (tester) async {
      // The server's own sentence was "1 of 2 counted", which is about how
      // many products carry a quantity from any source at all.  Standing
      // in front of the shelf with both boxes empty, that reads as a job
      // half done by somebody else.
      final (state, _) = await signedIn();
      await openCount(tester, state);

      expect(find.textContaining('counted'), findsNothing);
      expect(find.text('2 products on this shelf list'), findsOneWidget);
      expect(find.text('Type what you count'), findsOneWidget);
    });

    testWidgets('a branch with nothing recorded says so', (tester) async {
      final (state, _) = await signedIn(
        sheet: _sheet(berbere: '0.000', recorded: 0),
      );
      await openCount(tester, state);

      expect(
        find.text('Nothing recorded here yet · 2 to count'),
        findsOneWidget,
      );
    });

    testWidgets('writing a figure counts towards the walk', (tester) async {
      final (state, _) = await signedIn();
      await openCount(tester, state);

      await count(tester, 'Berbere 1kg', '59');
      expect(find.text('1 of 2 written down'), findsOneWidget);

      await count(tester, 'Teff flour 25kg', '4');
      expect(find.text('All 2 written down'), findsOneWidget);
    });

    testWidgets('the row says how big the change is as it is typed',
        (tester) async {
      final (state, _) = await signedIn();
      await openCount(tester, state);

      // Seven on record, fifty-nine on the shelf.
      await count(tester, 'Berbere 1kg', '59');
      expect(find.text('+52 kg on 7'), findsOneWidget);

      // A missing nought is the slip this is here to catch.
      await count(tester, 'Berbere 1kg', '5');
      expect(find.text('−2 kg on 7'), findsOneWidget);

      // And a figure that was already right is not a change at all.
      await count(tester, 'Berbere 1kg', '7');
      expect(find.text('Same as the record'), findsOneWidget);
      expect(find.text('Type what you count'), findsOneWidget);
    });

    testWidgets('saving reads the changes back before writing them',
        (tester) async {
      final (state, posted) = await signedIn();
      await openCount(tester, state);
      await count(tester, 'Berbere 1kg', '59');

      await tester.tap(find.text('Save 1 quantity'));
      await tester.pumpAndSettle();

      // The ledger is never edited, so this is the last chance to read it.
      expect(find.text('One quantity to change'), findsOneWidget);
      expect(find.textContaining('7 → 59'), findsOneWidget);
      expect(posted, isEmpty);

      await tester.tap(find.text('Keep counting'));
      await tester.pumpAndSettle();

      // Backing out leaves both the typing and the ledger alone.
      expect(posted, isEmpty);
      expect(find.text('+52 kg on 7'), findsOneWidget);
    });

    testWidgets('and writes them once it is confirmed', (tester) async {
      final (state, posted) = await signedIn();
      await openCount(tester, state);
      await count(tester, 'Berbere 1kg', '59');

      await tester.tap(find.text('Save 1 quantity'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save the count'));
      await tester.pumpAndSettle();

      expect(posted, hasLength(1));
      expect(posted.first['branch_id'], _main);
      expect(posted.first['lines'], [
        {'variant_id': 'v-berbere', 'quantity': '59'},
      ]);
    });

    testWidgets('only what was typed is sent, never an empty box',
        (tester) async {
      final (state, posted) = await signedIn();
      await openCount(tester, state);

      await count(tester, 'Teff flour 25kg', '4');
      await tester.tap(find.text('Save 1 quantity'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save the count'));
      await tester.pumpAndSettle();

      // Berbere was left alone: an empty box means "I did not count this
      // one", and must never be read as zero.
      expect(posted.first['lines'], [
        {'variant_id': 'v-teff', 'quantity': '4'},
      ]);
    });
  });
}
