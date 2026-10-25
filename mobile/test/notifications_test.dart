import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:estock_mobile/screens/notifications_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _notices = [
  {
    'id': 'n1',
    'kind': 'proforma_request',
    'title': 'Marketplace request PF-2026-000014 from Abebe Kebede',
    'body':
        '2 item(s) · 900.00 ETB · other shops were asked for the same basket',
    'link': '/shop?tab=proformas&open=q1',
    'created_at': '2026-10-25T09:00:00Z',
    'read': false,
  },
  {
    'id': 'n2',
    'kind': 'low_stock',
    'title': 'Teff 25kg is running low',
    'body': '3 bags left',
    'link': '/stock',
    'created_at': '2026-10-24T09:00:00Z',
    'read': true,
  },
];

/// A signed-in device whose server answers with [_notices], recording the
/// reads it is asked to make.
Future<(AppState, List<String>)> signedIn({
  bool offline = false,
  List<Map<String, dynamic>>? notices,
}) async {
  final prefs = await SharedPreferences.getInstance();
  final reads = <String>[];
  final rows = notices ?? _notices.map((n) => {...n}).toList();
  final client = MockClient((request) async {
    if (offline) throw http.ClientException('offline');
    final path = request.url.path;
    if (path.endsWith('/read')) {
      reads.add(request.url.pathSegments[request.url.pathSegments.length - 2]);
      return http.Response(jsonEncode({'ok': true}), 200,
          headers: {'content-type': 'application/json'});
    }
    if (path.endsWith('/notifications')) {
      return http.Response(
        jsonEncode({
          'total': rows.length,
          'unread': rows.where((n) => n['read'] != true).length,
          'items': rows,
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }
    throw http.ClientException('not mocked: $path');
  });

  final state = AppState(
    api: ApiClient(baseUrl: 'http://test/api/v1', httpClient: client),
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
    permissions: ['sale:create', 'stock:view', 'shop:view', 'credit:view'],
    branches: [],
  );
  return (state, reads);
}

Future<void> openNotifications(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(
    AppScope(
      state: state,
      child: const MaterialApp(home: NotificationsScreen()),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('the shop can read what it has been told', (tester) async {
    final (state, _) = await signedIn();
    await openNotifications(tester, state);

    expect(find.textContaining('Marketplace request PF-2026-000014'),
        findsOneWidget);
    expect(find.textContaining('other shops were asked'), findsOneWidget);
    expect(find.text('Teff 25kg is running low'), findsOneWidget);
  });

  testWidgets('tapping a notice marks it read, on the server too',
      (tester) async {
    final (state, reads) = await signedIn();
    await openNotifications(tester, state);
    expect(find.text('Mark all read'), findsOneWidget);

    await tester.tap(find.textContaining('Marketplace request'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(reads, ['n1'], reason: 'the one that was tapped, and only it');
    expect(find.text('Mark all read'), findsNothing,
        reason: 'nothing is unread any more');
    expect(state.unreadNotifications, 0);
  });

  testWidgets('mark all read clears every unread notice', (tester) async {
    final rows = [
      {..._notices[0]},
      {..._notices[0], 'id': 'n3', 'title': 'Another request'},
      {..._notices[1]},
    ];
    final (state, reads) = await signedIn(notices: rows);
    await openNotifications(tester, state);

    await tester.tap(find.text('Mark all read'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(reads..sort(), ['n1', 'n3'], reason: 'the read one is left alone');
    expect(state.unreadNotifications, 0);
  });

  testWidgets('with no connection it says so rather than looking empty',
      (tester) async {
    final (state, _) = await signedIn(offline: true);
    await openNotifications(tester, state);

    expect(find.text('No connection'), findsOneWidget);
    expect(find.textContaining('kept on the server'), findsOneWidget);
    expect(find.text('Nothing yet'), findsNothing,
        reason: 'offline is not the same as having nothing');
  });

  testWidgets('an empty list says what will land there', (tester) async {
    final (state, _) = await signedIn(notices: []);
    await openNotifications(tester, state);

    expect(find.text('Nothing yet'), findsOneWidget);
    expect(find.textContaining('low-stock'), findsOneWidget);
  });

  testWidgets('the More tab carries the count, and only when there is one',
      (tester) async {
    final (state, _) = await signedIn();

    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(Badge), findsNothing);

    state.unreadNotifications = 3;
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(Badge), findsWidgets);
    expect(find.text('3'), findsOneWidget);
  });
}
