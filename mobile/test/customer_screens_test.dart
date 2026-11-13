import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/customer.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/customer_form_screen.dart';
import 'package:estock_mobile/screens/customers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _yonas() => <String, dynamic>{
      'id': 'cust-yonas',
      'name': 'Yonas Alemu',
      'phone': '+251912000222',
      'company': null,
      'address': 'Merkato, near Anwar mosque',
      'notes': 'Pays on Fridays',
      'telegram_username': null,
      'email': null,
      'credit_limit': null,
      'credit_limit_behaviour': null,
      'outstanding_balance': '8200.00',
    };

Map<String, dynamic> _almaz() => <String, dynamic>{
      'id': 'cust-almaz',
      'name': 'Almaz Tadesse',
      'phone': '+251911000111',
      'company': 'Almaz Shop',
      'address': null,
      'notes': null,
      'telegram_username': null,
      'email': null,
      'credit_limit': null,
      'credit_limit_behaviour': null,
      'outstanding_balance': '0.00',
    };

/// The customers' side of the server, holding what the phone changes.
class CustomerServer {
  final customers = <Map<String, dynamic>>[_almaz(), _yonas()];
  bool offline = false;

  /// Everything the phone asked to have done, in order.
  final done = <(String, String, Object?)>[];

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
    if (path == '/customers' && method == 'GET') {
      final q = (request.url.queryParameters['q'] ?? '').toLowerCase();
      final rows = customers
          .where((c) =>
              q.isEmpty ||
              '${c['name']}'.toLowerCase().contains(q) ||
              '${c['phone']}'.contains(q))
          .toList();
      body = {'items': rows, 'total': rows.length, 'limit': 200, 'offset': 0};
    } else if (path == '/customers' && method == 'POST') {
      final given = Map<String, dynamic>.from(sent! as Map);
      final created = <String, dynamic>{
        ..._almaz().map((key, _) => MapEntry(key, null)),
        ...given,
        'id': 'cust-new',
        'outstanding_balance': '0.00',
      };
      customers.add(created);
      body = created;
      status = 201;
    } else if (parts.length == 2 && parts[0] == 'customers') {
      final customer = customers.firstWhere((c) => c['id'] == parts[1]);
      if (method == 'PATCH') {
        customer.addAll(Map<String, dynamic>.from(sent! as Map));
      }
      body = customer;
    } else if (parts.length == 3 && parts[2] == 'history') {
      final customer = customers.firstWhere((c) => c['id'] == parts[1]);
      final isYonas = customer['id'] == 'cust-yonas';
      body = {
        'customer': customer,
        'outstanding_balance': customer['outstanding_balance'],
        'sales': isYonas
            ? [
                {
                  'id': 'sale-1',
                  'number': 'S-2026-000003',
                  'sold_at': '2026-10-04T09:00:00Z',
                  'total_amount': '8200.00',
                  'balance_due': '8200.00',
                },
              ]
            : <dynamic>[],
        'credit_transactions': isYonas
            ? [
                {
                  'id': 'c1',
                  'reference': 'CR-2026-000003',
                  'balance': '8200.00',
                  'due_date': '2026-10-18',
                  'is_overdue': true,
                  'days_overdue': 26,
                  'status': 'overdue',
                },
              ]
            : <dynamic>[],
      };
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

const _seller = [
  'customer:view',
  'customer:manage',
  'credit:view',
  'sale:view',
];

Future<AppState> signedIn(
  CustomerServer server, {
  List<String> permissions = _seller,
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
  state.customers = server.customers
      .map((c) => Customer.fromJson(Map<String, dynamic>.from(c)))
      .toList();
  return state;
}

Future<void> settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

Future<void> open(WidgetTester tester, AppState state, Widget screen) async {
  tester.view.physicalSize = const Size(390 * 3, 844 * 3);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    AppScope(state: state, child: MaterialApp(home: screen)),
  );
  await settle(tester);
}

String saveLabel(WidgetTester tester) => tester
    .widget<Text>(find.descendant(
      of: find.byKey(const Key('customerSave')),
      matching: find.byType(Text),
    ))
    .data!;

bool saveEnabled(WidgetTester tester) => tester
    .widget<ButtonStyleButton>(find.byKey(const Key('customerSave')))
    .enabled;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('the list', () {
    testWidgets('is on the More tab', (tester) async {
      final state = await signedIn(CustomerServer());
      tester.view.physicalSize = const Size(390 * 3, 844 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(EstockApp(state: state));
      await tester.pump();
      await tester.tap(find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('More'),
      ));
      await settle(tester);

      await tester.tap(find.byKey(const Key('moreCustomers')));
      await settle(tester);
      expect(find.byType(CustomersScreen), findsOneWidget);
      expect(find.text('Yonas Alemu'), findsOneWidget);
    });

    testWidgets('says who owes what, and finds people by name or number',
        (tester) async {
      await open(tester, await signedIn(CustomerServer()),
          const CustomersScreen());

      expect(find.text('owes 8,200.00 ETB'), findsOneWidget);
      expect(find.text('+251911000111 · Almaz Shop'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('customersSearch')), '0111');
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(find.text('Almaz Tadesse'), findsOneWidget);
      expect(find.text('Yonas Alemu'), findsNothing);
    });

    testWidgets('offers to add whoever a search does not find',
        (tester) async {
      await open(tester, await signedIn(CustomerServer()),
          const CustomersScreen());

      await tester.enterText(
          find.byKey(const Key('customersSearch')), 'Hana Tesfaye');
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      await tester.tap(find.byKey(const Key('addCustomerFromSearch')));
      await tester.pumpAndSettle();

      expect(find.text('A new customer'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('customerName')))
            .controller!
            .text,
        'Hana Tesfaye',
      );
    });

    testWidgets('with no connection shows the people on this phone',
        (tester) async {
      final server = CustomerServer();
      final state = await signedIn(server);
      server.offline = true;
      await open(tester, state, const CustomersScreen());

      expect(find.textContaining('No connection'), findsOneWidget);
      expect(find.text('Yonas Alemu'), findsOneWidget);
    });

    testWidgets('has no way to add for somebody who may only look',
        (tester) async {
      await open(
        tester,
        await signedIn(CustomerServer(), permissions: ['customer:view']),
        const CustomersScreen(),
      );
      expect(find.byKey(const Key('addCustomer')), findsNothing);
    });
  });

  group('a customer', () {
    testWidgets('shows how to reach them, what they owe and what they bought',
        (tester) async {
      await open(tester, await signedIn(CustomerServer()),
          const CustomerScreen(customerId: 'cust-yonas'));

      expect(find.text('Owes 8,200.00 ETB'), findsOneWidget);
      expect(find.text('Call +251912000222'), findsOneWidget);
      expect(find.text('Merkato, near Anwar mosque'), findsOneWidget);
      expect(find.text('“Pays on Fridays”'), findsOneWidget);
      expect(find.text('CR-2026-000003'), findsOneWidget);
      expect(find.text('26 days overdue'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const Key('sale-sale-1')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.textContaining('S-2026-000003'), findsOneWidget);
    });

    testWidgets('can be changed, and only what changed is sent',
        (tester) async {
      final server = CustomerServer();
      final state = await signedIn(server);
      await open(tester, state, const CustomerScreen(customerId: 'cust-yonas'));

      await tester.tap(find.byKey(const Key('editCustomer')));
      await tester.pumpAndSettle();
      expect(saveLabel(tester), 'Nothing has changed');
      expect(saveEnabled(tester), isFalse);

      await tester.enterText(
          find.byKey(const Key('customerAddress')), 'Bole, near Edna Mall');
      await tester.enterText(find.byKey(const Key('customerNotes')), '');
      await tester.pump();
      expect(saveLabel(tester), 'Save the changes');
      await tester.tap(find.byKey(const Key('customerSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (method, path, body) = server.done.single;
      expect((method, path), ('PATCH', '/customers/cust-yonas'));
      // An emptied field is sent as nothing, so it is cleared.
      expect(body, {'address': 'Bole, near Edna Mall', 'notes': null});
      expect(find.text('Bole, near Edna Mall'), findsOneWidget);
      expect(
        state.customers.firstWhere((c) => c.id == 'cust-yonas').address,
        'Bole, near Edna Mall',
      );
    });

    testWidgets('cannot be changed by somebody who may only look',
        (tester) async {
      await open(
        tester,
        await signedIn(CustomerServer(),
            permissions: ['customer:view', 'credit:view']),
        const CustomerScreen(customerId: 'cust-yonas'),
      );
      expect(find.byKey(const Key('editCustomer')), findsNothing);
    });
  });

  group('adding a customer', () {
    testWidgets('needs only a name, and asks for a phone number gently',
        (tester) async {
      final server = CustomerServer();
      final state = await signedIn(server);
      await open(tester, state, const CustomerFormScreen(name: 'Hana Tesfaye'));

      expect(saveLabel(tester), 'Add them without a phone number');
      await tester.enterText(find.byKey(const Key('customerName')), ' ');
      await tester.pump();
      expect(saveLabel(tester), 'Give them a name first');
      expect(saveEnabled(tester), isFalse);

      await tester.enterText(
          find.byKey(const Key('customerName')), 'Hana Tesfaye');
      await tester.enterText(
          find.byKey(const Key('customerPhone')), '0911 22 33 66');
      await tester.enterText(
          find.byKey(const Key('customerAddress')), 'Kazanchis');
      await tester.pump();
      expect(saveLabel(tester), 'Add this customer');

      await tester.tap(find.byKey(const Key('customerSave')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (method, path, body) = server.done.single;
      expect((method, path), ('POST', '/customers'));
      expect(body, {
        'name': 'Hana Tesfaye',
        'phone': '0911 22 33 66',
        'address': 'Kazanchis',
      });
      // Straight to their page — and into the till's list.
      expect(find.byType(CustomerScreen), findsOneWidget);
      expect(state.customers.any((c) => c.name == 'Hana Tesfaye'), isTrue);
    });

    testWidgets('points out a number somebody already has', (tester) async {
      await open(tester, await signedIn(CustomerServer()),
          const CustomerFormScreen());

      await tester.enterText(find.byKey(const Key('customerName')), 'Yonas');
      await tester.enterText(
          find.byKey(const Key('customerPhone')), '0912 000 222');
      await tester.pump();

      expect(find.text('Yonas Alemu already has this number.'), findsOneWidget);
      // Said, not forbidden: two people can share a phone.
      expect(saveEnabled(tester), isTrue);
    });

    testWidgets('lets only somebody allowed to set the most they may owe',
        (tester) async {
      final server = CustomerServer();
      await open(tester, await signedIn(server), const CustomerFormScreen());
      await tester.tap(find.byKey(const Key('customerMore')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('customerLimit')), findsNothing);

      // A fresh screen for somebody who is allowed.
      await tester.pumpWidget(const SizedBox());
      final allowed = CustomerServer();
      await open(
        tester,
        await signedIn(allowed,
            permissions: [..._seller, 'credit:limit_override']),
        const CustomerFormScreen(name: 'Dawit Bekele'),
      );
      await tester.tap(find.byKey(const Key('customerMore')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('customerLimit')), '5000');
      await tester.ensureVisible(find.byKey(const Key('customerLimitRule')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('customerLimitRule')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Do not allow it').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('customerSave')));
      await settle(tester);

      final body = allowed.done.single.$3! as Map;
      expect(body['credit_limit'], '5000');
      expect(body['credit_limit_behaviour'], 'block');
    });

    testWidgets('with no connection says so, and keeps what was typed',
        (tester) async {
      final server = CustomerServer();
      final state = await signedIn(server);
      server.offline = true;
      await open(tester, state, const CustomerFormScreen(name: 'Hana'));

      await tester.tap(find.byKey(const Key('customerSave')));
      await settle(tester);

      expect(find.textContaining('No connection'), findsOneWidget);
      expect(find.text('A new customer'), findsOneWidget);
    });
  });

  test('a phone number is the same however it was typed', () {
    expect(phoneKey('0912 000 222'), phoneKey('+251912000222'));
    expect(phoneKey('912-000-222'), phoneKey('+251 912 000 222'));
    expect(phoneKey('0911 000 111') == phoneKey('0912 000 222'), isFalse);
  });
}
