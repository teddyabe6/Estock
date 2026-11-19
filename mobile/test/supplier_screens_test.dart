import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/models/supplier.dart';
import 'package:estock_mobile/screens/stock_receive_screen.dart';
import 'package:estock_mobile/screens/supplier_form_screen.dart';
import 'package:estock_mobile/screens/suppliers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _highland() => <String, dynamic>{
      'id': 'sup-1',
      'name': 'Highland Grain Suppliers',
      'phone': '+251911445566',
      'email': null,
      'telegram_username': null,
      'contact_person': 'Abebe Girma',
      'address': 'Merkato',
      'tin': '0012345678',
      'notes': 'Delivers on Tuesdays',
      'outstanding_balance': '30000.00',
    };

/// The suppliers' side of the server, holding what the phone changes.
class SupplierServer {
  final suppliers = <Map<String, dynamic>>[_highland()];
  bool offline = false;

  /// Everything the phone asked to have done, in order.
  final done = <(String, String, Object?)>[];

  Future<http.Response> handle(http.Request request) async {
    if (offline) throw http.ClientException('offline');
    final path = request.url.path.replaceFirst('/api/v1', '');
    final method = request.method;
    final query = request.url.queryParameters;
    final Object? sent =
        request.body.isEmpty ? null : jsonDecode(request.body);
    if (method != 'GET') done.add((method, path, sent));
    final parts = path.split('/').where((part) => part.isNotEmpty).toList();

    dynamic body;
    var status = 200;
    if (path == '/suppliers' && method == 'GET') {
      final q = (query['q'] ?? '').toLowerCase();
      final rows = suppliers
          .where((s) =>
              q.isEmpty ||
              '${s['name']}'.toLowerCase().contains(q) ||
              '${s['contact_person']}'.toLowerCase().contains(q))
          .toList();
      body = {'items': rows, 'total': rows.length, 'limit': 200, 'offset': 0};
    } else if (path == '/suppliers' && method == 'POST') {
      final created = <String, dynamic>{
        ..._highland().map((key, _) => MapEntry(key, null)),
        ...Map<String, dynamic>.from(sent! as Map),
        'id': 'sup-new',
        'outstanding_balance': '0.00',
      };
      suppliers.add(created);
      body = created;
      status = 201;
    } else if (parts.length == 2 && parts[0] == 'suppliers') {
      final supplier = suppliers.firstWhere((s) => s['id'] == parts[1]);
      if (method == 'PATCH') {
        supplier.addAll(Map<String, dynamic>.from(sent! as Map));
      }
      body = supplier;
    } else if (path == '/credit/transactions') {
      final mine = query['supplier_id'] == 'sup-1';
      final rows = mine
          ? [
              {
                'id': 'pay-1',
                'reference': 'CR-2026-000001',
                'balance': '30000.00',
                'due_date': '2026-11-24',
                'is_overdue': false,
                'days_overdue': null,
              },
            ]
          : <dynamic>[];
      body = {'items': rows, 'total': rows.length, 'limit': 50, 'offset': 0};
    } else if (path == '/purchases') {
      final mine = query['supplier_id'] == 'sup-1';
      final rows = mine
          ? [
              {
                'id': 'pu-1',
                'number': 'P-2026-000001',
                'received_at': '2026-10-24T09:00:00Z',
                'total_amount': '50000.00',
                'balance_due': '30000.00',
                'lines': [
                  {'description': 'Teff flour 25kg', 'quantity': '20'},
                ],
              },
            ]
          : <dynamic>[];
      body = {'items': rows, 'total': rows.length, 'limit': 30, 'offset': 0};
    } else if (path == '/stock/branches') {
      body = [
        {
          'branch_id': 'b1',
          'branch_name': 'Merkato Main',
          'location_id': 'l1',
          'is_mine': true,
        },
      ];
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
  'supplier:view',
  'supplier:manage',
  'credit:view',
  'credit:payment',
  'purchase:view',
  'purchase:create',
  'stock:receive',
  'stock:view',
  'cost:view',
];

Future<AppState> signedIn(
  SupplierServer server, {
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
  state.products = [
    Product.fromJson(const {
      'id': 'p-teff',
      'name': 'Teff flour 25kg',
      'unit_of_measure': 'sack',
      'track_stock': true,
      'variants': [
        {'id': 'v-teff', 'selling_price': '2800', 'purchase_price': '2400.00'},
      ],
    }),
  ];
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

String saveLabel(WidgetTester tester) => tester
    .widget<Text>(find.descendant(
      of: find.byKey(const Key('supplierSave')),
      matching: find.byType(Text),
    ))
    .data!;

/// Put Teff on the delivery, so the questions about the delivery show.
Future<void> addTeff(WidgetTester tester) async {
  await tester.enterText(find.byKey(const Key('receiveSearch')), 'teff');
  await tester.pump();
  await tester.tap(find.text('Teff flour 25kg').first);
  await tester.pumpAndSettle();
}

Finder supplierChoice() => find.byWidgetPredicate((widget) =>
    widget is DropdownButtonFormField<String?> &&
    (widget.key is ValueKey<String>) &&
    (widget.key! as ValueKey<String>).value.startsWith('receiveSupplier'));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('the list', () {
    testWidgets('is on the More tab', (tester) async {
      final state = await signedIn(SupplierServer());
      phone(tester);
      await tester.pumpWidget(EstockApp(state: state));
      await tester.pump();
      await tester.tap(find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('More'),
      ));
      await settle(tester);

      await tester.scrollUntilVisible(
        find.byKey(const Key('moreSuppliers')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.byKey(const Key('moreSuppliers')));
      await settle(tester);
      expect(find.byType(SuppliersScreen), findsOneWidget);
      expect(find.text('Highland Grain Suppliers'), findsOneWidget);
    });

    testWidgets('says what is owed to whom, and finds them by who you deal '
        'with', (tester) async {
      await open(tester, await signedIn(SupplierServer()),
          const SuppliersScreen());

      expect(find.text('you owe 30,000.00 ETB'), findsOneWidget);
      expect(find.text('+251911445566 · Abebe Girma'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('suppliersSearch')), 'girma');
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(find.text('Highland Grain Suppliers'), findsOneWidget);
    });

    testWidgets('offers to add whoever a search does not find',
        (tester) async {
      await open(tester, await signedIn(SupplierServer()),
          const SuppliersScreen());

      await tester.enterText(
          find.byKey(const Key('suppliersSearch')), 'Kality Traders');
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      await tester.tap(find.byKey(const Key('addSupplierFromSearch')));
      await tester.pumpAndSettle();

      expect(find.text('A new supplier'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('supplierName')))
            .controller!
            .text,
        'Kality Traders',
      );
    });

    testWidgets('with no connection says so', (tester) async {
      final server = SupplierServer();
      final state = await signedIn(server);
      server.offline = true;
      await open(tester, state, const SuppliersScreen());

      expect(find.text('Suppliers need a connection'), findsOneWidget);
    });

    testWidgets('has no way to add for somebody who may only look',
        (tester) async {
      await open(
        tester,
        await signedIn(SupplierServer(), permissions: ['supplier:view']),
        const SuppliersScreen(),
      );
      expect(find.byKey(const Key('addSupplier')), findsNothing);
    });
  });

  group('a supplier', () {
    testWidgets('shows how to reach them, what you owe them, and what they '
        'delivered', (tester) async {
      await open(tester, await signedIn(SupplierServer()),
          const SupplierScreen(supplierId: 'sup-1'));

      expect(find.text('You deal with Abebe Girma'), findsOneWidget);
      expect(find.text('You owe them 30,000.00 ETB'), findsOneWidget);
      expect(find.text('Call +251911445566'), findsOneWidget);
      expect(find.text('TIN 0012345678'), findsOneWidget);
      expect(find.byKey(const Key('deliveryFromSupplier')), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const Key('delivery-pu-1')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('CR-2026-000001'), findsOneWidget);
      expect(find.textContaining('Teff flour 25kg × 20'), findsOneWidget);
      expect(find.textContaining('30,000.00 still owed'), findsOneWidget);
    });

    testWidgets('can be changed, and only what changed is sent',
        (tester) async {
      final server = SupplierServer();
      await open(tester, await signedIn(server),
          const SupplierScreen(supplierId: 'sup-1'));

      await tester.tap(find.byKey(const Key('editSupplier')));
      await tester.pumpAndSettle();
      expect(saveLabel(tester), 'Nothing has changed');

      await tester.enterText(
          find.byKey(const Key('supplierContact')), 'Hirut Girma');
      await tester.enterText(find.byKey(const Key('supplierNotes')), '');
      await tester.pump();
      expect(saveLabel(tester), 'Save the changes');
      await tester.tap(find.byKey(const Key('supplierSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (method, path, body) = server.done.single;
      expect((method, path), ('PATCH', '/suppliers/sup-1'));
      expect(body, {'contact_person': 'Hirut Girma', 'notes': null});
      expect(find.text('You deal with Hirut Girma'), findsOneWidget);
    });

    testWidgets('cannot be changed by somebody who may only look',
        (tester) async {
      await open(
        tester,
        await signedIn(SupplierServer(), permissions: ['supplier:view']),
        const SupplierScreen(supplierId: 'sup-1'),
      );
      expect(find.byKey(const Key('editSupplier')), findsNothing);
      expect(find.byKey(const Key('deliveryFromSupplier')), findsNothing);
      // What is owed is credit information, and so is not said either.
      expect(find.textContaining('You owe them'), findsNothing);
    });
  });

  group('adding a supplier', () {
    testWidgets('needs only a name, and asks for a phone number gently',
        (tester) async {
      final server = SupplierServer();
      await open(tester, await signedIn(server),
          const SupplierFormScreen(name: 'Kality Traders'));

      expect(saveLabel(tester), 'Add them without a phone number');
      await tester.enterText(
          find.byKey(const Key('supplierPhone')), '0911 77 88 99');
      await tester.enterText(
          find.byKey(const Key('supplierContact')), 'Meron');
      await tester.pump();
      expect(saveLabel(tester), 'Add this supplier');

      await tester.tap(find.byKey(const Key('supplierSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (method, path, body) = server.done.single;
      expect((method, path), ('POST', '/suppliers'));
      expect(body, {
        'name': 'Kality Traders',
        'phone': '0911 77 88 99',
        'contact_person': 'Meron',
      });
      expect(find.byType(SupplierScreen), findsOneWidget);
    });

    testWidgets('points out a number another supplier has', (tester) async {
      await open(
        tester,
        await signedIn(SupplierServer()),
        SupplierFormScreen(known: [Supplier.fromJson(_highland())]),
      );
      await tester.enterText(find.byKey(const Key('supplierName')), 'X');
      await tester.enterText(
          find.byKey(const Key('supplierPhone')), '0911 44 55 66');
      await tester.pump();

      expect(find.text('Highland Grain Suppliers already has this number.'),
          findsOneWidget);
    });

    testWidgets('can happen on the delivery screen, and the new supplier is '
        'who it came from', (tester) async {
      final server = SupplierServer();
      await open(tester, await signedIn(server), const StockReceiveScreen());
      await addTeff(tester);

      await tester.ensureVisible(supplierChoice());
      await tester.pumpAndSettle();
      await tester.tap(supplierChoice());
      await tester.pumpAndSettle();
      await tester.tap(find.text('A new supplier…').last);
      await tester.pumpAndSettle();

      expect(find.text('A new supplier'), findsOneWidget);
      await tester.enterText(
          find.byKey(const Key('supplierName')), 'Kality Traders');
      await tester.pump();
      await tester.tap(find.byKey(const Key('supplierSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      expect(find.byType(StockReceiveScreen), findsOneWidget);
      expect(server.done.single.$2, '/suppliers');
      expect(
        tester
            .widget<DropdownButtonFormField<String?>>(supplierChoice())
            .initialValue,
        'sup-new',
      );
      expect(find.text('Kality Traders'), findsOneWidget);
    });

    testWidgets('a delivery opened from a supplier already says who it came '
        'from', (tester) async {
      await open(tester, await signedIn(SupplierServer()),
          const StockReceiveScreen(supplierId: 'sup-1'));

      // Before anything is added, the title already names them.
      expect(find.text('A delivery from Highland Grain Suppliers'),
          findsOneWidget);

      await addTeff(tester);

      await tester.ensureVisible(supplierChoice());
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<DropdownButtonFormField<String?>>(supplierChoice())
            .initialValue,
        'sup-1',
      );
    });
  });
}
