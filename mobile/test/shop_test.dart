import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/product.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/notifications_screen.dart';
import 'package:estock_mobile/screens/shop_order_screen.dart';
import 'package:estock_mobile/screens/shop_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _line(
  String variant,
  String name,
  String quantity,
  String price,
) =>
    {
      'id': 'l-$variant',
      'product_id': 'p-$variant',
      'variant_id': variant,
      'description': name,
      'quantity': quantity,
      'unit_price': price,
      'discount_amount': '0.00',
      'tax_rate': '0',
      'tax_amount': '0.00',
      'line_total':
          (double.parse(quantity) * double.parse(price)).toStringAsFixed(2),
    };

Map<String, dynamic> _order({
  String id = 'q1',
  String number = 'PF-2026-000014',
  String status = 'requested',
  String source = 'storefront',
  String name = 'Abebe Kebede',
  String created = '2026-11-10T09:00:00Z',
  String? message = 'Can you deliver to Bole?',
  String delivery = '0.00',
  List<Map<String, dynamic>>? lines,
}) {
  final rows = lines ??
      [
        _line('v1', 'Berbere 1kg', '2', '450.00'),
        _line('v2', 'Shiro 1kg', '1', '300.00'),
      ];
  return {
    'id': id,
    'number': number,
    'status': status,
    'source': source,
    'can_edit': const {'requested', 'draft', 'sent', 'expired'}.contains(status),
    'customer_message': message,
    'created_at': created,
    'customer_id': 'cust-$id',
    'customer_name': name,
    'customer_phone': '+251911000111',
    'customer_email': null,
    'customer_company': null,
    'delivery_location': null,
    'valid_until': status == 'requested' ? null : '2026-11-20',
    'delivery_charge': delivery,
    'total_amount': _total(rows, delivery),
    'currency': 'ETB',
    'lines': rows,
    'share': {
      'url': 'https://estock.et/q/token-$id',
      'telegram': 'https://t.me/share/url?url=x',
      'mailto': 'mailto:',
    },
    'converted_sale_id': null,
    'slips_to_check': 0,
    'slips_found': 0,
  };
}

String _total(List<Map<String, dynamic>> lines, String delivery) =>
    (lines.fold<double>(
              0,
              (sum, line) => sum + double.parse('${line['line_total']}'),
            ) +
            double.parse(delivery))
        .toStringAsFixed(2);

Map<String, dynamic> _slip({
  String id = 's1',
  String status = 'submitted',
  String amount = '1200.00',
}) =>
    {
      'id': id,
      'status': status,
      'amount_claimed': amount,
      'method': 'telebirr',
      'reference': 'TX123',
      'paid_on': '2026-11-10',
      'note': null,
      'sender_name': 'Hana Tesfaye',
      'sender_phone': '+251911000222',
      'submitted_at': '2026-11-10T10:00:00Z',
      'reviewed_at': null,
      'review_note': null,
      'file_asset_id': 'f1',
    };

Map<String, dynamic> _enquiry({
  String id = 'e1',
  String status = 'new',
}) =>
    {
      'id': id,
      'reference': 'ENQ-0001',
      'status': status,
      'contact_name': 'Meron Haile',
      'contact_phone': '+251911000333',
      'contact_email': null,
      'company': null,
      'delivery_location': null,
      'message': 'Do you have red lentils in 50 kg sacks?',
      'wants_proforma': false,
      'created_at': '2026-11-11T08:00:00Z',
      'items': <dynamic>[],
    };

/// The shop's side of the server, holding what the phone changes.
class ShopServer {
  ShopServer({
    List<Map<String, dynamic>>? orders,
    Map<String, List<Map<String, dynamic>>>? slips,
    List<Map<String, dynamic>>? enquiries,
    List<Map<String, dynamic>>? notices,
  })  : orders = orders ?? [_order()],
        slips = slips ?? {},
        enquiries = enquiries ?? [],
        notices = notices ?? [];

  final List<Map<String, dynamic>> orders;
  final Map<String, List<Map<String, dynamic>>> slips;
  final List<Map<String, dynamic>> enquiries;
  final List<Map<String, dynamic>> notices;
  bool open = true;
  bool offline = false;

  /// Everything the phone asked to have done, in order.
  final done = <(String, String, Object?)>[];

  Map<String, dynamic> _find(String id) =>
      orders.firstWhere((order) => order['id'] == id);

  void _recount(Map<String, dynamic> order) {
    final rows = slips[order['id']] ?? const [];
    order['slips_to_check'] =
        rows.where((slip) => slip['status'] == 'submitted').length;
    order['slips_found'] =
        rows.where((slip) => slip['status'] == 'accepted').length;
  }

  Future<http.Response> handle(http.Request request) async {
    if (offline) throw http.ClientException('offline');
    final path = request.url.path.replaceFirst('/api/v1', '');
    final method = request.method;
    final Object? sent =
        request.body.isEmpty ? null : jsonDecode(request.body);
    if (method != 'GET') {
      done.add((method, path, sent ?? request.url.queryParameters));
    }
    final parts = path.split('/').where((part) => part.isNotEmpty).toList();
    for (final order in orders) {
      _recount(order);
    }

    dynamic body;
    if (path == '/shop/settings') {
      if (method == 'PATCH') open = (sent! as Map)['is_published'] as bool;
      body = {
        'id': 'st1',
        'slug': 'merkato',
        'display_name': 'Merkato Wholesale',
        'is_published': open,
        'show_prices': true,
        'public_url': 'https://estock.et/shop/merkato',
      };
    } else if (path == '/shop/summary') {
      body = {
        'proforma_requests':
            orders.where((order) => order['status'] == 'requested').length,
        'new_enquiries': enquiries.where((row) => row['status'] == 'new').length,
        'slips_to_check': orders.fold<int>(
            0, (sum, order) => sum + (order['slips_to_check'] as int)),
        'orders_waiting': orders.where(orderNeedsYou).length,
      };
    } else if (path == '/shop/quotations') {
      body = {
        'items': orders,
        'total': orders.length,
        'limit': 100,
        'offset': 0,
      };
    } else if (parts.length == 3 && parts[1] == 'quotations') {
      final order = _find(parts[2]);
      if (method == 'PATCH') {
        final lines = [
          for (final line in (sent! as Map)['lines'] as List<dynamic>)
            _line(
              '${line['variant_id']}',
              '${line['description']}',
              '${line['quantity']}',
              '${line['unit_price']}',
            ),
        ];
        order['lines'] = lines;
        order['total_amount'] =
            _total(lines, '${order['delivery_charge']}');
      }
      body = order;
    } else if (parts.length == 4 && parts[1] == 'quotations') {
      final order = _find(parts[2]);
      switch (parts[3]) {
        case 'payment-slips':
          body = {'items': slips[order['id']] ?? const []};
        case 'send':
          order['status'] = 'sent';
          body = order;
        case 'cancel':
          order['status'] = 'cancelled';
          order['can_edit'] = false;
          body = order;
        case 'convert':
          order['status'] = 'converted';
          order['can_edit'] = false;
          order['converted_sale_id'] = 'sale-9';
          body = {
            'sale': {'id': 'sale-9', 'number': 'S-2026-000099'},
            'credit_transaction_id': null,
            'warnings': <String>[],
          };
      }
    } else if (parts.length == 4 && parts[1] == 'payment-slips') {
      final slip = slips.values
          .expand((rows) => rows)
          .firstWhere((slip) => slip['id'] == parts[2]);
      slip['status'] =
          (sent! as Map)['accept'] == true ? 'accepted' : 'rejected';
      slip['review_note'] = (sent as Map)['note'];
      body = slip;
    } else if (path == '/shop/enquiries') {
      body = {
        'items': enquiries,
        'total': enquiries.length,
        'limit': 50,
        'offset': 0,
      };
    } else if (parts.length == 3 && parts[1] == 'enquiries') {
      final enquiry = enquiries.firstWhere((row) => row['id'] == parts[2]);
      if (method == 'PATCH') {
        enquiry['status'] = request.url.queryParameters['status'];
      }
      body = enquiry;
    } else if (path == '/notifications') {
      body = {
        'items': notices,
        'total': notices.length,
        'unread': notices.where((n) => n['read'] != true).length,
      };
    } else if (path.endsWith('/read')) {
      body = {'ok': true};
    } else {
      throw http.ClientException('not mocked: $path');
    }
    return http.Response(
      jsonEncode(body),
      200,
      headers: {'content-type': 'application/json'},
    );
  }
}

const _seller = [
  'shop:view',
  'shop:manage',
  'quotation:view',
  'quotation:manage',
  'enquiry:view',
  'enquiry:manage',
  'sale:create',
  'credit:create',
];

Future<AppState> signedIn(
  ShopServer server, {
  List<String> permissions = _seller,
  List<Product> products = const [],
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
  state.products = products;
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
  return state;
}

/// The size of the phone most of the shop's people hold, rather than the
/// test's default landscape window, so what is above the fold here is what
/// is above the fold there.
void phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(390 * 3, 844 * 3);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
}

/// Scroll to something, then tap it, the way a thumb would.
Future<void> reachAndTap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
}

Future<void> settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

Future<void> openShop(WidgetTester tester, AppState state) async {
  phone(tester);
  await tester.pumpWidget(AppScope(
    state: state,
    child: const MaterialApp(home: Scaffold(body: ShopScreen())),
  ));
  await settle(tester);
}

Future<void> openOrder(
  WidgetTester tester,
  AppState state, [
  String id = 'q1',
]) async {
  phone(tester);
  await tester.pumpWidget(AppScope(
    state: state,
    child: MaterialApp(home: ShopOrderScreen(orderId: id)),
  ));
  await settle(tester);
}

bool enabled(WidgetTester tester, Key key) =>
    tester.widget<ButtonStyleButton>(find.byKey(key)).enabled;

double top(WidgetTester tester, String text) =>
    tester.getTopLeft(find.text(text)).dy;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('the shop tab', () {
    testWidgets('puts what is waiting on the seller first', (tester) async {
      final server = ShopServer(
        orders: [
          _order(id: 'q1', name: 'Abebe Kebede'),
          _order(
            id: 'q2',
            name: 'Hana Tesfaye',
            status: 'sent',
            created: '2026-11-11T09:00:00Z',
          ),
          _order(id: 'q3', name: 'Meron Haile', status: 'sent'),
          _order(id: 'q4', name: 'Dawit Bekele', status: 'converted'),
          _order(id: 'q5', name: 'Selam Girma', status: 'expired'),
        ],
        slips: {
          'q2': [_slip()],
        },
      );
      final state = await signedIn(server);
      await openShop(tester, state);

      expect(find.text('Waiting for you (2)'), findsOneWidget);
      expect(find.text('Waiting for the customer (1)'), findsOneWidget);
      expect(find.text('Earlier orders (2)'), findsOneWidget);

      // Somebody saying they have paid outranks a new order, however much
      // newer it is.
      expect(find.text('says paid'), findsOneWidget);
      expect(find.text('new'), findsOneWidget);
      expect(top(tester, 'Hana Tesfaye'), lessThan(top(tester, 'Abebe Kebede')));
      expect(top(tester, 'Abebe Kebede'), lessThan(top(tester, 'Meron Haile')));

      // What is finished is out of the way until asked for.
      expect(find.text('Dawit Bekele'), findsNothing);
      await reachAndTap(tester, find.byKey(const Key('shopEarlier')));
      await tester.pump();
      await tester.scrollUntilVisible(
        find.text('Selam Girma'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Dawit Bekele'), findsOneWidget);
      expect(find.text('sold'), findsOneWidget);
      expect(find.text('ran out'), findsOneWidget);

      // The badge on the tab is the same count as the list.
      expect(state.shopNeedsYou, 2);
    });

    testWidgets('a paid order stays the seller\'s until it is sold, '
        'ahead of new ones', (tester) async {
      final server = ShopServer(
        orders: [
          _order(id: 'q1', name: 'Abebe Kebede', created: '2026-11-01T09:00:00Z'),
          _order(
            id: 'q2',
            name: 'Hana Tesfaye',
            status: 'sent',
            created: '2026-11-11T09:00:00Z',
          ),
          _order(
            id: 'q3',
            name: 'Meron Haile',
            status: 'sent',
            created: '2026-11-11T10:00:00Z',
          ),
        ],
        slips: {
          'q2': [_slip(status: 'accepted')],
          'q3': [_slip(id: 's3')],
        },
      );
      await openShop(tester, await signedIn(server));

      expect(find.text('Waiting for you (3)'), findsOneWidget);
      expect(find.text('paid'), findsOneWidget);
      // Asking about their money, then waiting for their goods, then
      // waiting for a price — however long the last has waited.
      expect(top(tester, 'Meron Haile'), lessThan(top(tester, 'Hana Tesfaye')));
      expect(top(tester, 'Hana Tesfaye'), lessThan(top(tester, 'Abebe Kebede')));
    });

    testWidgets('says when nothing is waiting, rather than going quiet',
        (tester) async {
      final server = ShopServer(orders: [_order(status: 'sent')]);
      await openShop(tester, await signedIn(server));

      expect(find.textContaining('Nothing is waiting for you'), findsOneWidget);
      expect(find.text('Waiting for the customer (1)'), findsOneWidget);
    });

    testWidgets('the store card says how many products customers see',
        (tester) async {
      Product product(String id, {bool shown = true}) => Product(
            id: id,
            name: id,
            unitOfMeasure: 'pcs',
            trackStock: true,
            isPublished: shown,
            variants: const [],
          );
      final state = await signedIn(
        ShopServer(),
        products: [product('a'), product('b'), product('c', shown: false)],
      );
      await openShop(tester, state);

      expect(find.text('open'), findsOneWidget);
      expect(find.text('2 products on show to customers.'), findsOneWidget);
      expect(find.text('estock.et/shop/merkato'), findsOneWidget);
      expect(find.byKey(const Key('shopCopyLink')), findsOneWidget);
    });

    testWidgets('closing the shop asks first, then says it is closed',
        (tester) async {
      final server = ShopServer();
      await openShop(tester, await signedIn(server));

      await tester.tap(find.byKey(const Key('shopOpenSwitch')));
      await tester.pumpAndSettle();
      expect(find.text('Close your online shop?'), findsOneWidget);

      await tester.tap(find.byKey(const Key('shopCloseConfirm')));
      await settle(tester);

      expect(server.done.single.$2, '/shop/settings');
      expect(server.done.single.$3, {'is_published': false});
      expect(find.text('closed'), findsOneWidget);
      expect(find.textContaining('Customers cannot see your shop'),
          findsOneWidget);
    });

    testWidgets('a question opens with the number to call back',
        (tester) async {
      final server = ShopServer(orders: [], enquiries: [_enquiry()]);
      final state = await signedIn(server);
      await openShop(tester, state);
      expect(find.text('Questions from customers (1)'), findsOneWidget);
      expect(state.shopNeedsYou, 1);

      await tester.tap(find.text('Meron Haile'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('enquiryCall')), findsOneWidget);
      expect(find.text('Call +251911000333'), findsOneWidget);
      // Opening it is reading it: it is no longer "new" to anybody.
      expect(server.done.first.$2, '/shop/enquiries/e1');
      expect(server.done.first.$3, {'status': 'in_review'});

      await tester.tap(find.byKey(const Key('enquiryAnswered')));
      await settle(tester);

      expect(server.done.last.$3, {'status': 'closed'});
      expect(find.text('answered'), findsOneWidget);
      expect(state.shopNeedsYou, 0);
    });

    testWidgets('with no connection it says so', (tester) async {
      final server = ShopServer()..offline = true;
      await openShop(tester, await signedIn(server));

      expect(find.text('The shop needs a connection'), findsOneWidget);
    });
  });

  group('an order', () {
    testWidgets('says whose move it is, and shows what was asked for',
        (tester) async {
      await openOrder(tester, await signedIn(ShopServer()));

      expect(find.text('PF-2026-000014'), findsOneWidget);
      expect(
        find.text('A new order. Check the prices, then send it to the '
            'customer.'),
        findsOneWidget,
      );
      expect(find.text('“Can you deliver to Bole?”'), findsOneWidget);
      expect(find.text('2 × 450.00'), findsOneWidget);
      expect(find.text('1,200.00 ETB'), findsOneWidget);
      expect(find.text('Call'), findsOneWidget);
    });

    testWidgets('a marketplace order says others were asked too',
        (tester) async {
      final server = ShopServer(orders: [_order(source: 'marketplace')]);
      await openOrder(tester, await signedIn(server));

      expect(find.textContaining('other shops were asked too'), findsOneWidget);
    });

    testWidgets('is priced and sent from the phone', (tester) async {
      final server = ShopServer();
      await openOrder(tester, await signedIn(server));

      await tester.tap(find.byKey(const Key('orderSend')));
      await settle(tester);

      expect(server.done.single.$2, '/shop/quotations/q1/send');
      expect(
        find.text('Sent. Waiting for the customer to say yes or pay.'),
        findsOneWidget,
      );
      expect(find.byKey(const Key('orderCopyLink')), findsOneWidget);
    });

    testWidgets('an item with no price is priced before it can be sent',
        (tester) async {
      final server = ShopServer(orders: [
        _order(lines: [
          _line('v1', 'Berbere 1kg', '2', '450.00'),
          _line('v2', 'Shiro 1kg', '1', '0.00'),
        ]),
      ]);
      await openOrder(tester, await signedIn(server));

      expect(find.text('Give every item a price first'), findsOneWidget);
      expect(enabled(tester, const Key('orderSend')), isFalse);
      expect(find.text('1 wanted · no price yet'), findsOneWidget);

      await tester.tap(find.byKey(const Key('orderLine1')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('linePrice')), '320');
      await tester.pump();
      expect(find.text('1 × 320.00 = 320.00'), findsOneWidget);

      await tester.tap(find.byKey(const Key('lineSave')));
      await settle(tester);

      final (method, path, body) = server.done.single;
      expect((method, path), ('PATCH', '/shop/quotations/q1'));
      final lines = (body! as Map)['lines'] as List<dynamic>;
      expect(lines.map((line) => line['unit_price']), ['450.00', '320']);
      expect(lines.map((line) => line['quantity']), ['2', '1'],
          reason: 'the line not touched goes back as it was');
      expect(find.text('1,220.00 ETB'), findsOneWidget);
      expect(enabled(tester, const Key('orderSend')), isTrue);
    });

    testWidgets('a slip is checked, not believed', (tester) async {
      final server = ShopServer(
        orders: [_order(status: 'sent')],
        slips: {
          'q1': [_slip()],
        },
      );
      await openOrder(tester, await signedIn(server));

      expect(find.textContaining('The customer says they have paid'),
          findsOneWidget);
      expect(find.text('Proof of payment'), findsOneWidget);
      expect(find.text('to check'), findsOneWidget);
      expect(find.byKey(const Key('orderSell')), findsNothing,
          reason: 'the slip is answered before anything is sold');

      await reachAndTap(tester, find.byKey(const Key('slipFound')));
      await tester.pumpAndSettle();
      expect(find.text('You found 1,200.00 ETB in your account?'),
          findsOneWidget);
      await tester.tap(find.byKey(const Key('slipFoundConfirm')));
      await settle(tester);

      expect(server.done.single.$2, '/shop/payment-slips/s1/review');
      expect(server.done.single.$3, {'accept': true});
      expect(find.text('arrived'), findsOneWidget);
      // The next step is in view where the thumb already is...
      expect(find.textContaining('Turn the order into a sale'), findsOneWidget);
      expect(find.byKey(const Key('orderSell')), findsOneWidget);
      // ...and the order says what it is now, at the top.
      await tester.scrollUntilVisible(
        find.textContaining('Paid — the money arrived'),
        -200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.textContaining('Paid — the money arrived'), findsOneWidget);
    });

    testWidgets('a slip whose money never came says so, with a note',
        (tester) async {
      final server = ShopServer(
        orders: [_order(status: 'sent')],
        slips: {
          'q1': [_slip()],
        },
      );
      await openOrder(tester, await signedIn(server));

      await reachAndTap(tester, find.byKey(const Key('slipNotFound')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'Nothing from TX123');
      await tester.tap(find.widgetWithText(FilledButton, 'Not found'));
      await settle(tester);

      expect(server.done.single.$3,
          {'accept': false, 'note': 'Nothing from TX123'});
      expect(find.text('not found'), findsOneWidget);
    });

    testWidgets('turning it into a sale takes what was paid, and no more',
        (tester) async {
      final server = ShopServer(orders: [_order(status: 'accepted')]);
      await openOrder(tester, await signedIn(server));
      expect(find.textContaining('The customer said yes'), findsOneWidget);

      await tester.tap(find.byKey(const Key('orderSell')));
      await tester.pumpAndSettle();

      // Paid in full is the starting point.
      expect(find.text('Sell it · paid in full'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('sellPaid')), '1500');
      await tester.pump();
      expect(find.text('That is more than the goods'), findsOneWidget);
      expect(enabled(tester, const Key('sellConfirm')), isFalse);

      await tester.enterText(find.byKey(const Key('sellPaid')), '1000');
      await tester.pump();
      expect(find.textContaining('200.00 ETB stays owing'), findsOneWidget);
      expect(find.text('Sell it · 200.00 ETB on credit'), findsOneWidget);

      await tester.tap(find.byKey(const Key('sellDue')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('In 7 days').last);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('sellConfirm')));
      await settle(tester);
      await tester.pumpAndSettle();

      final (_, path, body) = server.done.single;
      expect(path, '/shop/quotations/q1/convert');
      expect(body, {
        'branch_id': 'b1',
        'payments': [
          {'method': 'cash', 'amount': '1000.00'},
        ],
        'due_date_preset': '7_days',
      });
      expect(find.textContaining('Sold. The goods are off the shelf'),
          findsOneWidget);
    });

    testWidgets('a seller who may not give credit is asked for it all',
        (tester) async {
      final server = ShopServer(orders: [_order(status: 'accepted')]);
      final state = await signedIn(
        server,
        permissions: _seller.where((p) => p != 'credit:create').toList(),
      );
      await openOrder(tester, state);

      await tester.tap(find.byKey(const Key('orderSell')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('sellPaid')), '1000');
      await tester.pump();

      expect(find.text('Needs the full amount'), findsOneWidget);
      expect(enabled(tester, const Key('sellConfirm')), isFalse);
      expect(find.byKey(const Key('sellDue')), findsNothing);
    });

    testWidgets('delivery is said to be outside the sale before selling',
        (tester) async {
      final server =
          ShopServer(orders: [_order(status: 'accepted', delivery: '150.00')]);
      await openOrder(tester, await signedIn(server));

      await tester.tap(find.byKey(const Key('orderSell')));
      await tester.pumpAndSettle();

      expect(find.textContaining('Delivery (150.00 ETB) is not part'),
          findsOneWidget);
      // What is sold is the goods: 1,200, not the 1,350 the order totals.
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('sellPaid')))
            .controller!
            .text,
        '1200',
      );
    });

    testWidgets('can be turned down, with a reason', (tester) async {
      final server = ShopServer();
      await openOrder(tester, await signedIn(server));

      await reachAndTap(tester, find.byKey(const Key('orderTurnDown')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'Out of Shiro');
      await tester.tap(find.widgetWithText(FilledButton, 'Turn it down'));
      await settle(tester);

      expect(server.done.single.$2, '/shop/quotations/q1/cancel');
      expect(server.done.single.$3, {'reason': 'Out of Shiro'});
      expect(find.text('Turned down.'), findsWidgets);
      expect(find.byKey(const Key('orderTurnDown')), findsNothing);
    });

    testWidgets('an order that ran out can be sent again', (tester) async {
      final server = ShopServer(orders: [_order(status: 'expired')]);
      await openOrder(tester, await signedIn(server));

      expect(find.textContaining('Send it again to give them more time'),
          findsOneWidget);
      expect(find.text('Send it again'), findsOneWidget);
    });

    testWidgets('once somebody says they have paid, the figures stand',
        (tester) async {
      // The price ran out while the slip sat unchecked: the customer paid
      // in time, and the shop was slow.
      final server = ShopServer(
        orders: [_order(status: 'expired')],
        slips: {
          'q1': [_slip(amount: '1200.00')],
        },
      );
      await openOrder(tester, await signedIn(server));

      expect(find.textContaining('The customer says they have paid'),
          findsOneWidget);
      expect(find.text('Send it again'), findsNothing);
      expect(find.textContaining('Tap a line'), findsNothing);
      expect(find.textContaining('The price ran out'), findsNothing);
      // The slip is answered first; selling comes after.
      expect(find.byKey(const Key('orderSell')), findsNothing);
    });

    testWidgets('someone who may only look sees no buttons', (tester) async {
      final server = ShopServer();
      final state =
          await signedIn(server, permissions: ['shop:view', 'quotation:view']);
      await openOrder(tester, state);

      expect(find.byKey(const Key('orderSend')), findsNothing);
      expect(find.byKey(const Key('orderTurnDown')), findsNothing);
      expect(find.textContaining('Tap a line'), findsNothing);
    });
  });

  testWidgets('a notice about an order opens that order', (tester) async {
    final server = ShopServer(notices: [
      {
        'id': 'n1',
        'kind': 'payment_slip',
        'title': 'Abebe Kebede says they have paid PF-2026-000014',
        'body': null,
        'link': '/shop?tab=proformas&open=q1',
        'created_at': '2026-11-10T10:00:00Z',
        'read': false,
      },
    ]);
    final state = await signedIn(server);
    await tester.pumpWidget(AppScope(
      state: state,
      child: const MaterialApp(home: NotificationsScreen()),
    ));
    await settle(tester);

    await tester.tap(find.textContaining('says they have paid'));
    await settle(tester);

    expect(find.byType(ShopOrderScreen), findsOneWidget);
    expect(find.text('PF-2026-000014'), findsOneWidget);
    expect(server.done.single.$2, '/notifications/n1/read');
  });

  testWidgets('the shop tab carries the count of what is waiting',
      (tester) async {
    // One order to price, one question nobody has opened, and one order
    // with the customer, which is not the shop's to count.
    final server = ShopServer(
      orders: [_order(), _order(id: 'q2', status: 'sent')],
      enquiries: [_enquiry()],
    );
    final state = await signedIn(server);
    phone(tester);
    await tester.pumpWidget(EstockApp(state: state));
    await settle(tester);

    final badge = find.descendant(
      of: find.byType(NavigationBar),
      matching: find.byType(Badge),
    );
    expect(badge, findsOneWidget);
    expect(
      find.descendant(of: badge, matching: find.text('2')),
      findsOneWidget,
    );

    // Answered from somewhere else, the count follows on the next look.
    server.orders.first['status'] = 'sent';
    server.enquiries.first['status'] = 'closed';
    await state.refreshShopWaiting();
    await settle(tester);
    expect(badge, findsNothing);
  });
}
