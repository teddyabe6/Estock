import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/customer.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/credit_detail_screen.dart';
import 'package:estock_mobile/screens/credit_screen.dart';
import 'package:estock_mobile/screens/home_screen.dart' show owedBy;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _debt({
  String id = 'c1',
  String reference = 'CR-2026-000003',
  String name = 'Yonas Alemu',
  String original = '8200.00',
  String paid = '0.00',
  String balance = '8200.00',
  String status = 'outstanding',
  bool overdue = true,
  int? daysOverdue = 23,
  String? dueDate = '2026-10-18',
  String? customerId = 'cust-1',
  String? note = 'Was due last week; follow up.',
}) =>
    {
      'id': id,
      'reference': reference,
      'kind': 'receivable',
      'status': status,
      'branch_id': 'b1',
      'customer_id': customerId,
      'sale_id': 's1',
      'original_amount': original,
      'amount_paid': paid,
      'balance': balance,
      'currency': 'ETB',
      'issued_on': '2026-10-04',
      'due_date': dueDate,
      'agreement_note': note,
      'counterparty_name': name,
      'is_overdue': overdue,
      'days_overdue': daysOverdue,
    };

const _summary = {
  'kind': 'receivable',
  'currency': 'ETB',
  'total_outstanding': '8200.00',
  'due_today': '0.00',
  'due_within_7_days': '0.00',
  'overdue': '8200.00',
  'no_due_date': '0.00',
  'transaction_count': 1,
  'party_count': 1,
};

/// Every query the credit list has sent, so a search can be checked.
final asked = <Map<String, String>>[];

/// A signed-in phone, recording what it posts.
Future<(AppState, List<(String, Object?)>)> signedIn({
  List<Map<String, dynamic>>? debts,
  List<Map<String, dynamic>> payments = const [],
  List<Map<String, dynamic>> activities = const [],
  List<String> permissions = const [
    'credit:view',
    'credit:payment',
    'credit:followup',
    'credit:duedate',
  ],
  String? customerPhone = '+251912000222',
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <(String, Object?)>[];
  final rows = debts ?? [_debt()];
  asked.clear();

  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (request.method == 'POST' || request.method == 'PATCH') {
      posted.add((path, jsonDecode(request.body)));
      // The server answers with the balance as it now stands.
      body = _debt(balance: '3200.00', paid: '5000.00', status: 'partially_paid');
      if (path.endsWith('/activities')) {
        body = {
          'id': 'a1',
          'kind': 'called',
          'occurred_at': '2026-11-10T09:00:00Z',
          'note': 'Said Friday',
        };
      }
    } else if (path.endsWith('/credit/summary')) {
      body = _summary;
    } else if (path.endsWith('/payments')) {
      body = payments;
    } else if (path.endsWith('/activities')) {
      body = activities;
    } else if (path.endsWith('/credit/transactions')) {
      asked.add(request.url.queryParameters);
      final needle = request.url.queryParameters['q']?.toLowerCase();
      final forCustomer = request.url.queryParameters['customer_id'];
      var found = rows;
      if (needle != null) {
        found = rows
            .where((r) =>
                '${r['counterparty_name']}'.toLowerCase().contains(needle))
            .toList();
      } else if (forCustomer != null) {
        found =
            rows.where((r) => r['customer_id'] == forCustomer).toList();
      }
      body = {
        'items': found,
        'total': found.length,
        'limit': 100,
        'offset': 0,
      };
    } else if (path.contains('/credit/transactions/')) {
      body = rows.first;
    } else {
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
    branches: const [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
  );
  state.customers = [
    Customer(id: 'cust-1', name: 'Yonas Alemu', phone: customerPhone),
  ];
  return (state, posted);
}

Future<void> open(WidgetTester tester, AppState state, Widget screen) async {
  await tester.pumpWidget(
    AppScope(state: state, child: MaterialApp(home: screen)),
  );
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('who owes what', () {
    testWidgets('the list says it in people, not in balance(s)',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditScreen());

      expect(find.text('from 1 customer'), findsOneWidget);
      expect(find.textContaining('balance(s)'), findsNothing);
    });

    test('two unpaid sales to one customer are one person to chase', () {
      // The count of balances is not the count of people, and saying
      // "from 2 customers" about one of them is simply untrue.
      expect(owedBy({'transaction_count': 2, 'party_count': 1}),
          'from 1 customer');
      expect(owedBy({'transaction_count': 6, 'party_count': 5}),
          'from 5 customers');
      // An older server says only how many balances there are.
      expect(owedBy({'transaction_count': 3}), '3 unpaid sales');
      expect(owedBy({'transaction_count': 1}), '1 unpaid sale');
    });

    testWidgets('late is what gets the loud chip', (tester) async {
      // The chip used to carry the bookkeeping word, so the one row that
      // needed chasing wore the calmest grey on the screen.
      final (state, _) = await signedIn();
      await open(tester, state, const CreditScreen());

      expect(find.text('overdue'), findsOneWidget);
      expect(find.text('outstanding'), findsNothing);
    });

    testWidgets('it can be searched by name, across every view',
        (tester) async {
      final (state, _) = await signedIn(debts: [
        _debt(),
        _debt(
          id: 'c2',
          reference: 'CR-2026-000004',
          name: 'Abebe Kebede',
          overdue: false,
          daysOverdue: null,
          status: 'partially_paid',
        ),
      ]);
      await open(tester, state, const CreditScreen());
      expect(find.text('Abebe Kebede'), findsOneWidget);

      await tester.enterText(find.byType(TextField).first, 'yonas');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(seconds: 1));

      expect(find.text('Yonas Alemu'), findsOneWidget);
      expect(find.text('Abebe Kebede'), findsNothing);
      // Looking for a person means looking everywhere, not in whichever
      // view happened to be chosen.
      expect(asked.last['q'], 'yonas');
      expect(asked.last['view'], 'all');
    });

    testWidgets('a row opens the debt rather than doing nothing',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditScreen());

      await tester.tap(find.text('Yonas Alemu'));
      await tester.pumpAndSettle();

      expect(find.byType(CreditDetailScreen), findsOneWidget);
      expect(find.text('Take a payment'), findsOneWidget);
    });
  });

  group('one debt', () {
    testWidgets('it leads with the balance and where it came from',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('8,200.00 ETB'), findsOneWidget);
      expect(find.text('23 days overdue'), findsOneWidget);
      expect(find.textContaining('CR-2026-000003'), findsOneWidget);
      expect(find.textContaining('0.00 paid of 8,200.00'), findsOneWidget);
      expect(find.text('Was due last week; follow up.'), findsOneWidget);
    });

    testWidgets('the number to ring is right there', (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('+251912000222'), findsOneWidget);
    });

    testWidgets('and is simply absent when nobody wrote one down',
        (tester) async {
      final (state, _) = await signedIn(customerPhone: null);
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.byIcon(Icons.phone_outlined), findsNothing);
      expect(find.text('Log a call'), findsOneWidget);
    });

    testWidgets('somebody who may not take money is not offered the button',
        (tester) async {
      final (state, _) = await signedIn(
        permissions: const ['credit:view', 'credit:followup'],
      );
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('Take a payment'), findsNothing);
      expect(find.text('Change the date'), findsNothing);
      // Looking and logging are still fine, for somebody allowed to log.
      expect(find.text('Log a call'), findsOneWidget);
    });

    testWidgets('it says what else the same customer has open',
        (tester) async {
      // One sale is not what anybody is really asking when they decide
      // whether to take 5,000 and let somebody walk.
      final (state, _) = await signedIn(debts: [
        _debt(),
        _debt(
          id: 'c2',
          reference: 'CR-2026-000009',
          balance: '4000.00',
          overdue: false,
          daysOverdue: null,
        ),
      ]);
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await tester.pumpAndSettle();

      expect(
        find.text('Also owes 4,000.00 ETB on one other sale'),
        findsOneWidget,
      );
    });

    testWidgets('and says nothing when there is nothing else',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await tester.pumpAndSettle();

      expect(find.textContaining('Also owes'), findsNothing);
    });

    testWidgets('a settled debt says so and offers nothing further',
        (tester) async {
      final (state, _) = await signedIn(debts: [
        _debt(
          balance: '0.00',
          paid: '8200.00',
          status: 'paid',
          overdue: false,
          daysOverdue: null,
        ),
      ]);
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('Nothing owing'), findsOneWidget);
      expect(find.text('Paid in full'), findsOneWidget);
      expect(find.text('Take a payment'), findsNothing);
    });
  });

  group('taking money at the counter', () {
    Future<void> openSheet(WidgetTester tester) async {
      await tester.tap(find.byKey(const Key('takePayment')));
      await tester.pumpAndSettle();
    }

    testWidgets('it opens on the whole balance, which is the usual answer',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await openSheet(tester);

      expect(find.text('8,200.00 ETB owing'), findsOneWidget);
      expect(find.text('Take 8,200.00 ETB'), findsOneWidget);
    });

    testWidgets('part of it is one tap, because part of it is usual too',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await openSheet(tester);

      // 8,200 owing: the round amounts below it are 8,000 and 5,000.
      expect(find.text('8,000.00'), findsOneWidget);
      expect(find.text('5,000.00'), findsOneWidget);

      await tester.tap(find.text('5,000.00'));
      await tester.pump();
      expect(find.text('Take 5,000.00 ETB'), findsOneWidget);

      await tester.tap(find.byKey(const Key('confirmPayment')));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/credit/transactions/c1/payments'));
      final body = posted.single.$2! as Map;
      expect(body['amount'], '5000');
      expect(body['method'], 'cash');
      expect(body['idempotency_key'], isNotNull);
    });

    testWidgets('more than is owed is refused before it is sent',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await openSheet(tester);

      await tester.enterText(
          find.byKey(const Key('paymentAmount')), '9000');
      await tester.pump();

      expect(find.textContaining('More than is owed'), findsOneWidget);
      expect(find.text('That is more than is owed'), findsOneWidget);

      await tester.tap(find.byKey(const Key('confirmPayment')));
      await tester.pumpAndSettle();

      expect(posted, isEmpty, reason: 'the button is dead until it is sane');
    });

    testWidgets('what is left over is said out loud afterwards',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));
      await openSheet(tester);
      await tester.tap(find.byKey(const Key('confirmPayment')));
      await tester.pumpAndSettle();

      expect(find.textContaining('still owing'), findsOneWidget);
    });
  });

  group('chasing it', () {
    testWidgets('a call can be logged without touching the balance',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      await tester.tap(find.text('Log a call'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('They promised to pay'));
      await tester.pump();
      await tester.enterText(find.byType(TextField).last, 'Friday');
      await tester.tap(find.byKey(const Key('confirmFollowUp')));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/credit/transactions/c1/activities'));
      expect((posted.single.$2! as Map)['kind'], 'promise_to_pay');
      expect(find.textContaining('does not change the balance'),
          findsOneWidget);
    });

    testWidgets('the due date can be moved from the phone', (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      await tester.tap(find.text('Change the date'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('In 7 days'));
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/credit/transactions/c1/due-date'));
      expect((posted.single.$2! as Map)['due_date_preset'], '7_days');
    });

    testWidgets('what has been paid and said is kept where it happened',
        (tester) async {
      final (state, _) = await signedIn(
        payments: [
          {
            'id': 'p1',
            'method': 'cash',
            'amount': '5000.00',
            'paid_at': '2026-11-10T09:30:00Z',
            'is_reversed': false,
          },
        ],
        activities: [
          {
            'id': 'a1',
            'kind': 'called',
            'occurred_at': '2026-11-09T09:00:00Z',
            'note': 'Said Friday',
          },
        ],
      );
      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('5,000.00 ETB'), findsOneWidget);
      expect(find.text('Called them'), findsOneWidget);
      expect(find.textContaining('Said Friday'), findsOneWidget);
    });
  });

  group('off the air', () {
    testWidgets('a balance is never shown, or changed, out of date',
        (tester) async {
      final prefs = await SharedPreferences.getInstance();
      final state = AppState(
        api: ApiClient(
          baseUrl: 'http://test/api/v1',
          httpClient: MockClient((_) async => throw http.ClientException('x')),
        ),
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
        permissions: ['credit:view', 'credit:payment'],
        branches: [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
      );

      await open(tester, state, const CreditDetailScreen(transactionId: 'c1'));

      expect(find.text('Credit needs a connection'), findsOneWidget);
      expect(find.byKey(const Key('takePayment')), findsNothing);
    });
  });
}
