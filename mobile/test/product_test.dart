import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/product_form_screen.dart';
import 'package:estock_mobile/screens/stock_product_screen.dart';
import 'package:estock_mobile/screens/stock_receive_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _berbere() => {
      'id': 'p-berbere',
      'name': 'Berbere 1kg',
      'category_name': 'Spices',
      'unit_of_measure': 'kg',
      'track_stock': true,
      'is_published': false,
      'quantity_on_hand': '33',
      'stock_status': 'ok',
      'variants': [
        <String, dynamic>{
          'id': 'v-berbere',
          'name': null,
          'selling_price': '450.00',
          'purchase_price': '320.00',
          'reorder_level': '10',
        }
      ],
    };

/// The catalogue's side of the server, holding what the phone changes.
class CatalogueServer {
  final products = <Map<String, dynamic>>[_berbere()];
  bool offline = false;

  /// Everything the phone asked to have done, in order.
  final done = <(String, String, Object?)>[];

  Map<String, dynamic> _product(String id) =>
      products.firstWhere((product) => product['id'] == id);

  Future<http.Response> handle(http.Request request) async {
    if (offline) throw http.ClientException('offline');
    final path = request.url.path.replaceFirst('/api/v1', '');
    final method = request.method;
    final Object? sent =
        request.body.isEmpty ? null : jsonDecode(request.body);
    if (method != 'GET') done.add((method, path, sent));
    final parts = path.split('/').where((part) => part.isNotEmpty).toList();

    dynamic body;
    var status = 200;
    if (path == '/products' && method == 'POST') {
      final given = sent! as Map;
      final created = {
        'id': 'p-new',
        'name': given['name'],
        'category_name': given['category_name'],
        'unit_of_measure': given['unit_of_measure'] ?? 'pcs',
        'track_stock': true,
        'is_published': given['is_published'] ?? false,
        'quantity_on_hand': given['opening_stock'] ?? '0',
        'stock_status': 'ok',
        'variants': [
          {
            'id': 'v-new',
            'name': null,
            'selling_price': given['selling_price'],
            'purchase_price': given['purchase_price'],
          }
        ],
      };
      products.add(created);
      body = created;
      status = 201;
    } else if (parts.length == 2 && parts[0] == 'products') {
      final product = _product(parts[1]);
      if (method == 'PATCH') {
        final given = sent! as Map;
        for (final key in ['name', 'unit_of_measure', 'category_name']) {
          if (given.containsKey(key)) product[key] = given[key];
        }
      }
      body = product;
    } else if (parts.length == 2 && parts[0] == 'variants') {
      final product = products.firstWhere((p) =>
          (p['variants'] as List).any((v) => (v as Map)['id'] == parts[1]));
      final variant = (product['variants'] as List)
          .cast<Map<String, dynamic>>()
          .firstWhere((v) => v['id'] == parts[1]);
      variant.addAll(Map<String, dynamic>.from(sent! as Map));
      body = variant;
    } else if (path == '/stock/movements') {
      body = {'items': <dynamic>[], 'total': 0, 'limit': 20, 'offset': 0};
    } else if (path == '/stock/branches') {
      body = [
        {
          'branch_id': 'b1',
          'branch_name': 'Merkato Main',
          'location_id': 'l1',
          'is_mine': true,
        },
      ];
    } else if (path == '/suppliers') {
      body = {'items': <dynamic>[], 'total': 0, 'limit': 200, 'offset': 0};
    } else {
      throw http.ClientException('not mocked: $path');
    }
    return http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json'},
    );
  }
}

const _manager = [
  'stock:view',
  'stock:adjust',
  'stock:receive',
  'purchase:create',
  'supplier:view',
  'product:view',
  'product:manage',
  'cost:view',
];

Future<AppState> signedIn(
  CatalogueServer server, {
  List<String> permissions = _manager,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final state = AppState(
    api: ApiClient(
      baseUrl: 'http://test/api/v1',
      httpClient: MockClient(server.handle),
    ),
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
    branches: const [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
  );
  state.products = server.products
      .map((p) => Product.fromJson(Map<String, dynamic>.from(p)))
      .toList();
  return state;
}

void phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(390 * 3, 844 * 3);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
}

Future<void> settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

Future<void> open(WidgetTester tester, AppState state, Widget screen) async {
  phone(tester);
  await tester.pumpWidget(
    AppScope(state: state, child: MaterialApp(home: screen)),
  );
  await settle(tester);
}

String buttonLabel(WidgetTester tester) => tester
    .widget<Text>(find.descendant(
      of: find.byKey(const Key('productSave')),
      matching: find.byType(Text),
    ))
    .data!;

bool enabled(WidgetTester tester, Key key) =>
    tester.widget<ButtonStyleButton>(find.byKey(key)).enabled;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('adding a product', () {
    testWidgets('not finding something offers to add it, name and all',
        (tester) async {
      final state = await signedIn(CatalogueServer());
      phone(tester);
      await tester.pumpWidget(EstockApp(state: state));
      await tester.pump();
      await tester.tap(find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('Stock'),
      ));
      await settle(tester);

      await tester.enterText(find.byType(TextField).first, 'Teff flour');
      await settle(tester);
      expect(find.text('Add “Teff flour” as a new product'), findsOneWidget);

      await tester.tap(find.byKey(const Key('addFromSearch')));
      await tester.pumpAndSettle();
      expect(find.text('A new product'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('productName')))
            .controller!
            .text,
        'Teff flour',
      );
    });

    testWidgets('somebody who may not add products is not offered it',
        (tester) async {
      final state = await signedIn(
        CatalogueServer(),
        permissions: _manager.where((p) => p != 'product:manage').toList(),
      );
      phone(tester);
      await tester.pumpWidget(EstockApp(state: state));
      await tester.pump();
      await tester.tap(find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('Stock'),
      ));
      await settle(tester);

      await tester.enterText(find.byType(TextField).first, 'Teff flour');
      await settle(tester);
      expect(find.byKey(const Key('addFromSearch')), findsNothing);
    });

    testWidgets('only the name is needed, and the button says what happens',
        (tester) async {
      final server = CatalogueServer();
      await open(
        tester,
        await signedIn(server),
        const ProductFormScreen(name: 'Teff flour 25kg'),
      );

      expect(buttonLabel(tester), 'Add it without a price');
      expect(enabled(tester, const Key('productSave')), isTrue);

      await tester.enterText(find.byKey(const Key('productName')), ' ');
      await tester.pump();
      expect(buttonLabel(tester), 'Give it a name first');
      expect(enabled(tester, const Key('productSave')), isFalse);

      await tester.enterText(
          find.byKey(const Key('productName')), 'Teff flour 25kg');
      await tester.enterText(find.byKey(const Key('productPrice')), '2800');
      await tester.pump();
      expect(buttonLabel(tester), 'Add it');

      await tester.tap(find.byKey(const Key('unit-bag')));
      await tester.enterText(find.byKey(const Key('productCost')), '2400');
      await tester.enterText(find.byKey(const Key('productStock')), '12');
      await tester.pump();
      expect(find.text('You make 400.00 ETB on each bag.'), findsOneWidget);
      expect(buttonLabel(tester), 'Add it · 12 bag here');

      await tester.tap(find.byKey(const Key('productSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (method, path, body) = server.done.single;
      expect((method, path), ('POST', '/products'));
      expect(body, {
        'name': 'Teff flour 25kg',
        'unit_of_measure': 'bag',
        'selling_price': '2800',
        'purchase_price': '2400',
        'opening_stock': '12',
        'branch_id': 'b1',
      });
      // Straight to its own page, where the rest of what can be done to
      // it starts.
      expect(find.byType(StockProductScreen), findsOneWidget);
      expect(find.textContaining('Sells for 2,800.00 ETB a bag'),
          findsOneWidget);
    });

    testWidgets('a new kind of thing needs its name before it is saved',
        (tester) async {
      final server = CatalogueServer();
      await open(
        tester,
        await signedIn(server),
        const ProductFormScreen(name: 'Teff flour 25kg'),
      );

      await tester.tap(find.byKey(const Key('productCategory')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('A new kind…').last);
      await tester.pumpAndSettle();
      expect(buttonLabel(tester), 'Name the new kind');
      expect(enabled(tester, const Key('productSave')), isFalse);

      await tester.enterText(find.byKey(const Key('categoryName')), 'Flour');
      await tester.pump();
      await tester.tap(find.byKey(const Key('productSave')));
      await settle(tester);

      expect((server.done.single.$3! as Map)['category_name'], 'Flour');
    });

    testWidgets('with no connection it says so, and keeps what was typed',
        (tester) async {
      final server = CatalogueServer();
      final state = await signedIn(server);
      server.offline = true;
      await open(tester, state, const ProductFormScreen(name: 'Teff'));

      await tester.tap(find.byKey(const Key('productSave')));
      await settle(tester);

      expect(find.textContaining('No connection'), findsOneWidget);
      expect(find.text('A new product'), findsOneWidget);
    });

    testWidgets('what is new on a delivery goes onto it, and is not counted '
        'twice', (tester) async {
      final server = CatalogueServer();
      await open(tester, await signedIn(server), const StockReceiveScreen());

      await tester.enterText(
          find.byKey(const Key('receiveSearch')), 'Teff flour 25kg');
      await tester.pump();
      await tester.tap(find.byKey(const Key('receiveNewProduct')));
      await tester.pumpAndSettle();

      // The delivery says how many came; the form does not ask again.
      expect(find.byKey(const Key('productStock')), findsNothing);
      await tester.enterText(find.byKey(const Key('productPrice')), '2800');
      await tester.pump();
      await tester.tap(find.byKey(const Key('productSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final created = server.done.single.$3! as Map;
      expect(created.containsKey('opening_stock'), isFalse);
      // Back on the delivery, with the new product as a line on it.
      expect(find.byType(StockReceiveScreen), findsOneWidget);
      expect(find.text('Teff flour 25kg'), findsOneWidget);
    });
  });

  group('changing a price', () {
    testWidgets('is one field and one button, from the product page',
        (tester) async {
      final server = CatalogueServer();
      await open(
        tester,
        await signedIn(server),
        const StockProductScreen(productId: 'p-berbere'),
      );
      expect(find.textContaining('Sells for 450.00 ETB a kg'), findsOneWidget);

      await tester.tap(find.byKey(const Key('changePrice')));
      await tester.pumpAndSettle();
      expect(find.textContaining('was 450.00 ETB'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('priceNew')), '480');
      await tester.pump();
      expect(find.text('You make 160.00 ETB on each kg.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('priceSave')));
      await settle(tester);

      final (method, path, body) = server.done.single;
      expect((method, path), ('PATCH', '/variants/v-berbere'));
      expect(body, {'selling_price': '480'});
      expect(find.text('Berbere 1kg now sells for 480.00 ETB.'), findsOneWidget);
      expect(find.textContaining('Sells for 480.00 ETB a kg'), findsOneWidget);
    });

    testWidgets('a price below what it costs is said out loud',
        (tester) async {
      await open(
        tester,
        await signedIn(CatalogueServer()),
        const StockProductScreen(productId: 'p-berbere'),
      );
      await tester.tap(find.byKey(const Key('changePrice')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('priceNew')), '300');
      await tester.pump();

      expect(
        find.text('That is less than it costs you: you lose 20.00 ETB on '
            'each kg.'),
        findsOneWidget,
      );
      // Said, not forbidden: a clearance sale is a decision, not a typo.
      expect(enabled(tester, const Key('priceSave')), isTrue);
    });

    testWidgets('somebody who may not change products is not offered to',
        (tester) async {
      await open(
        tester,
        await signedIn(
          CatalogueServer(),
          permissions: _manager.where((p) => p != 'product:manage').toList(),
        ),
        const StockProductScreen(productId: 'p-berbere'),
      );

      expect(find.byKey(const Key('changePrice')), findsNothing);
      expect(find.byKey(const Key('editProduct')), findsNothing);
    });

    testWidgets('changing the details sends only what changed',
        (tester) async {
      final server = CatalogueServer();
      final state = await signedIn(server);
      await open(
        tester,
        state,
        ProductFormScreen(product: state.products.single),
      );
      expect(buttonLabel(tester), 'Nothing has changed');
      expect(enabled(tester, const Key('productSave')), isFalse);

      await tester.enterText(find.byKey(const Key('productName')), 'Berbere 1 kg');
      await tester.pump();
      expect(buttonLabel(tester), 'Save the changes');
      await tester.tap(find.byKey(const Key('productSave')));
      await settle(tester);

      final (method, path, body) = server.done.single;
      expect((method, path), ('PATCH', '/products/p-berbere'));
      expect(body, {'name': 'Berbere 1 kg'});
      expect(state.products.single.name, 'Berbere 1 kg');
    });
  });
}
