import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/sale.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/sale_detail_screen.dart';
import 'package:estock_mobile/screens/sale_return_screen.dart';
import 'package:estock_mobile/screens/sales_history_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _sale({
  String id = 's1',
  String number = 'S-2026-000012',
  String status = 'completed',
  String total = '1750.00',
  String paid = '1000.00',
  String balance = '750.00',
  List<Map<String, dynamic>>? returns,
  String? profit,
}) =>
    {
      'id': id,
      'number': number,
      'branch_id': 'b1',
      'status': status,
      'sold_at': '2026-10-31T11:32:00Z',
      'subtotal': '1800.00',
      'discount_total': '100.00',
      'tax_total': '50.00',
      'total_amount': total,
      'currency': 'ETB',
      'amount_paid': paid,
      'balance_due': balance,
      'returned_total': returns == null ? '0.00' : '900.00',
      'cost_total': profit == null ? null : '1100.00',
      'gross_profit': profit,
      'lines': [
        {
          'id': 'l1',
          'product_id': 'p1',
          'variant_id': 'v1',
          'description': 'Cement bag 50kg',
          'quantity': '2.000',
          'unit_price': '900.00',
          'discount_amount': '100.00',
          'tax_rate': '0',
          'tax_amount': '50.00',
          'line_total': '1750.00',
        }
      ],
      'payments': [
        {'id': 'pay1', 'method': 'cash', 'amount': paid, 'paid_at': '2026-10-31T11:32:00Z'}
      ],
      'returns': returns ?? const [],
    };

Map<String, dynamic> _receipt({bool refunded = false}) => {
      'business': {
        'name': 'Merkato Wholesale',
        'phone': '0911223344',
        'address': 'Merkato',
        'tin': '0001234567',
      },
      'branch': {'name': 'Merkato Main'},
      'sale': {
        'number': 'S-2026-000012',
        'sold_at': '2026-10-31T11:32:00Z',
        'status': 'completed',
        'currency': 'ETB',
        'subtotal': '1800.00',
        'discount_total': '100.00',
        'tax_total': '50.00',
        'total_amount': '1750.00',
        'amount_paid': '1000.00',
        'balance_due': '750.00',
      },
      'customer': {'name': 'Abebe Kebede', 'phone': '0922334455'},
      'lines': [
        {
          'description': 'Cement bag 50kg',
          'quantity': '2.000',
          'unit_price': '900.00',
          'discount_amount': '100.00',
          'line_total': '1750.00',
        }
      ],
      'payments': [
        {'method': 'cash', 'amount': '1000.00', 'direction': 'in'},
        if (refunded) {'method': 'cash', 'amount': '400.00', 'direction': 'out'},
      ],
    };

final _returnable = [
  {
    'sale_line_id': 'l1',
    'variant_id': 'v1',
    'description': 'Cement bag 50kg',
    'quantity_sold': '2.000',
    'quantity_returned': '0.000',
    'quantity_returnable': '2.000',
    'unit_price': '900.00',
  },
];

/// A signed-in device, recording what it is asked to post.
Future<(AppState, List<(String, Object?)>)> signedIn({
  List<String> permissions = const ['sale:view', 'sale:create'],
  List<Map<String, dynamic>>? sales,
  List<Map<String, dynamic>>? returnable,
  bool refundedReceipt = false,
  List<Branch> branches = const [Branch(id: 'b1', name: 'Merkato Main', isDefault: true)],
}) async {
  final prefs = await SharedPreferences.getInstance();
  final posted = <(String, Object?)>[];
  final rows = sales ?? [_sale()];
  final client = MockClient((request) async {
    final path = request.url.path;
    dynamic body;
    if (request.method == 'POST') {
      posted.add((path, jsonDecode(request.body)));
      if (path.endsWith('/returns')) {
        body = {
          'id': 'r1',
          'number': 'SR-2026-000001',
          'sale_id': 's1',
          'branch_id': 'b1',
          'returned_at': '2026-10-31T12:00:00Z',
          'reason': 'wrong size',
          'subtotal': '900.00',
          'discount_total': '0.00',
          'tax_total': '0.00',
          'total_amount': '900.00',
          'currency': 'ETB',
          'refund_method': 'credit_note',
          'refunded_amount': '0.00',
          'credited_amount': '900.00',
          'lines': <dynamic>[],
        };
      } else {
        body = _sale(status: 'voided');
      }
    } else if (path.endsWith('/returnable')) {
      body = {'sale_id': 's1', 'lines': returnable ?? _returnable};
    } else if (path.endsWith('/receipt')) {
      body = _receipt(refunded: refundedReceipt);
    } else if (path.contains('/sales/')) {
      body = rows.first;
    } else if (path.endsWith('/sales')) {
      body = {'items': rows, 'total': rows.length, 'limit': 100, 'offset': 0};
    } else {
      throw http.ClientException('not mocked: $path');
    }
    return http.Response(jsonEncode(body), request.method == 'POST' ? 201 : 200,
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
    permissions: permissions,
    branches: branches,
  );
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

  group('reading a sale', () {
    test('a sale carries what is owed and what came back', () {
      final sale = Sale.fromJson(_sale(returns: [
        {
          'id': 'r1',
          'number': 'SR-1',
          'sale_id': 's1',
          'branch_id': 'b1',
          'returned_at': '2026-10-31T12:00:00Z',
          'reason': 'wrong size',
          'subtotal': '900.00',
          'discount_total': '0.00',
          'tax_total': '0.00',
          'total_amount': '900.00',
          'currency': 'ETB',
          'refund_method': 'cash',
          'refunded_amount': '900.00',
          'credited_amount': '0.00',
          'lines': <dynamic>[],
        }
      ]));

      expect(sale.total, 1750);
      expect(sale.balanceDue, 750);
      expect(sale.returnedTotal, 900);
      expect(sale.hasReturns, isTrue);
      expect(sale.returns.single.refunded, 900);
      expect(sale.isVoided, isFalse);
    });

    test('cost is absent for somebody not allowed to see it', () {
      expect(Sale.fromJson(_sale()).grossProfit, isNull);
      expect(Sale.fromJson(_sale(profit: '650.00')).grossProfit, 650);
    });

    test('a receipt knows the shop it came from', () {
      final receipt = Receipt.fromJson(_receipt());
      expect(receipt.businessName, 'Merkato Wholesale');
      expect(receipt.branchName, 'Merkato Main');
      expect(receipt.customerName, 'Abebe Kebede');
      expect(receipt.lines.single.description, 'Cement bag 50kg');
      expect(receipt.balanceDue, 750);
    });
  });

  group('the sales list', () {
    testWidgets('it shows what was sold and what is still owed',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const SalesHistoryScreen());

      expect(find.text('S-2026-000012'), findsOneWidget);
      expect(find.text('1,750.00 ETB'), findsOneWidget);
      expect(find.textContaining('750.00 on credit'), findsOneWidget);
      expect(find.textContaining('1 sale'), findsOneWidget);
    });

    testWidgets('a voided sale is struck through, not hidden from itself',
        (tester) async {
      final (state, _) = await signedIn(sales: [_sale(status: 'voided')]);
      await open(tester, state, const SalesHistoryScreen());

      expect(find.text('voided'), findsOneWidget);
      final amount = tester.widget<Text>(find.text('1,750.00 ETB'));
      expect(amount.style?.decoration, TextDecoration.lineThrough);
    });

    testWidgets('one branch means no branch chips', (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const SalesHistoryScreen());

      expect(find.text('All branches'), findsNothing);
      expect(find.text('Today'), findsOneWidget);
      expect(find.text('With voided'), findsOneWidget);
    });
  });

  group('one sale', () {
    testWidgets('it reads as the receipt the customer was given',
        (tester) async {
      final (state, _) = await signedIn();
      await open(tester, state, const SaleDetailScreen(saleId: 's1'));

      expect(find.text('Merkato Wholesale'), findsOneWidget);
      expect(find.textContaining('Merkato Main'), findsWidgets);
      expect(find.textContaining('TIN 0001234567'), findsOneWidget);
      expect(find.textContaining('Abebe Kebede'), findsOneWidget);
      expect(find.text('Cement bag 50kg'), findsOneWidget);
      expect(find.text('1,750.00 ETB'), findsOneWidget);
      expect(find.text('Balance on credit'), findsOneWidget);
    });

    testWidgets('a refund reads as money back, not money taken',
        (tester) async {
      // Listing it as another payment would make a 1,750 sale look as though
      // 1,400 had been handed over for it.
      final (state, _) = await signedIn(refundedReceipt: true);
      await open(tester, state, const SaleDetailScreen(saleId: 's1'));

      expect(find.text('Paid by cash'), findsOneWidget);
      expect(find.text('Refunded by cash'), findsOneWidget);
      expect(find.text('−400.00'), findsOneWidget);
    });

    testWidgets('the actions follow the permissions, not the screen',
        (tester) async {
      final (plain, _) = await signedIn();
      await open(tester, plain, const SaleDetailScreen(saleId: 's1'));
      expect(find.text('Take goods back'), findsNothing);
      expect(find.text('Void this sale'), findsNothing);

      final (allowed, _) = await signedIn(
        permissions: const ['sale:view', 'sale:refund', 'sale:void'],
      );
      await open(tester, allowed, const SaleDetailScreen(saleId: 's1'));
      expect(find.text('Take goods back'), findsOneWidget);
      expect(find.text('Void this sale'), findsOneWidget);
    });

    testWidgets('a voided sale offers nothing further and says why',
        (tester) async {
      final (state, _) = await signedIn(
        sales: [_sale(status: 'voided')],
        permissions: const ['sale:view', 'sale:refund', 'sale:void'],
      );
      await open(tester, state, const SaleDetailScreen(saleId: 's1'));

      expect(find.textContaining('This sale was voided'), findsOneWidget);
      expect(find.text('Void this sale'), findsNothing);
      expect(find.text('Take goods back'), findsNothing);
    });

    testWidgets('voiding asks why, and will not go without one',
        (tester) async {
      final (state, posted) = await signedIn(
        permissions: const ['sale:view', 'sale:void'],
      );
      await open(tester, state, const SaleDetailScreen(saleId: 's1'));

      await tester.tap(find.text('Void this sale'));
      await tester.pumpAndSettle();
      expect(find.textContaining('goods go back on the shelf'), findsOneWidget);

      final confirm = find.widgetWithText(FilledButton, 'Void it');
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);

      await tester.enterText(find.byType(TextField), 'Rung up twice');
      await tester.pump();
      await tester.tap(confirm);
      await tester.pumpAndSettle();

      expect(posted.single.$1, endsWith('/sales/s1/void'));
      expect((posted.single.$2! as Map)['reason'], 'Rung up twice');
    });
  });

  group('taking goods back', () {
    testWidgets('it will not send until it knows how many and why',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const SaleReturnScreen(saleId: 's1'));

      expect(find.text('Type what is coming back'), findsOneWidget);

      await tester.tap(find.text('All'));
      await tester.pump();
      expect(find.text('Say why it is coming back'), findsOneWidget);

      await tester.enterText(
          find.widgetWithText(TextField, 'Why it is coming back'), 'Wrong size');
      await tester.pump();
      expect(find.text('Take back 1 line'), findsOneWidget);

      await tester.tap(find.text('Take back 1 line'));
      await tester.pumpAndSettle();

      final body = posted.single.$2! as Map;
      expect(posted.single.$1, endsWith('/sales/s1/returns'));
      expect(body['reason'], 'Wrong size');
      expect((body['lines'] as List).single, {
        'sale_line_id': 'l1',
        'quantity': '2.0',
        'restock': true,
      });
    });

    testWidgets('more than was sold cannot come back', (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const SaleReturnScreen(saleId: 's1'));

      await tester.enterText(find.byType(TextField).first, '5');
      await tester.pump();
      expect(find.textContaining('Only 2 of this line can come back'),
          findsOneWidget);

      await tester.enterText(
          find.widgetWithText(TextField, 'Why it is coming back'), 'Wrong size');
      await tester.pump();
      await tester.tap(find.text('Take back 1 line'));
      await tester.pumpAndSettle();

      // Clamped on the way out, not merely complained about.
      expect(((posted.single.$2! as Map)['lines'] as List).single['quantity'],
          '2.0');
    });

    testWidgets('goods that cannot be sold again are marked as such',
        (tester) async {
      final (state, posted) = await signedIn();
      await open(tester, state, const SaleReturnScreen(saleId: 's1'));

      await tester.tap(find.text('All'));
      await tester.pump();
      expect(find.text('Goes back on the shelf'), findsOneWidget);

      await tester.tap(find.byType(SwitchListTile));
      await tester.pump();
      expect(find.text('Comes back and is written off'), findsOneWidget);

      await tester.enterText(
          find.widgetWithText(TextField, 'Why it is coming back'), 'Broken');
      await tester.pump();
      await tester.tap(find.text('Take back 1 line'));
      await tester.pumpAndSettle();

      expect(((posted.single.$2! as Map)['lines'] as List).single['restock'],
          isFalse);
    });

    testWidgets('a sale already fully returned says so', (tester) async {
      final (state, _) = await signedIn(returnable: [
        {
          'sale_line_id': 'l1',
          'variant_id': 'v1',
          'description': 'Cement bag 50kg',
          'quantity_sold': '2.000',
          'quantity_returned': '2.000',
          'quantity_returnable': '0.000',
          'unit_price': '900.00',
        }
      ]);
      await open(tester, state, const SaleReturnScreen(saleId: 's1'));

      expect(find.text('Nothing left to come back'), findsOneWidget);
    });
  });
}
