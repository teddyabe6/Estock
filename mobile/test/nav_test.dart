import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A signed-in device with no connection, allowed to do exactly [permissions].
Future<AppState> signedIn(List<String> permissions) async {
  final prefs = await SharedPreferences.getInstance();
  final state = AppState(
    api: ApiClient(
      baseUrl: 'http://test/api/v1',
      httpClient: MockClient((_) async => throw http.ClientException('offline')),
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
    branches: const [],
  );
  return state;
}

/// The screens load in a post-frame callback and fail offline; let them.
Future<void> open(WidgetTester tester, AppState state) async {
  await tester.pumpWidget(EstockApp(state: state));
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

Finder tab(String label) => find.descendant(
      of: find.byType(NavigationBar),
      matching: find.text(label),
    );

const everything = [
  'sale:create',
  'sale:view',
  'stock:view',
  'shop:view',
  'credit:view',
  'product:view',
];

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('an owner gets the five the web shows on a phone, in order',
      (tester) async {
    await open(tester, await signedIn(everything));

    expect(find.byType(NavigationDestination), findsNWidgets(5));
    for (final label in ['Home', 'Sales', 'Stock', 'Shop', 'More']) {
      expect(tab(label), findsOneWidget, reason: '$label should be in the bar');
    }

    final labels = tester
        .widgetList<NavigationDestination>(find.byType(NavigationDestination))
        .map((destination) => destination.label)
        .toList();
    expect(labels, ['Home', 'Sales', 'Stock', 'Shop', 'More']);
  });

  testWidgets('a till-only role is not shown tabs it cannot open',
      (tester) async {
    await open(tester, await signedIn(['sale:create']));

    expect(tab('Home'), findsOneWidget);
    expect(tab('Sales'), findsOneWidget);
    expect(tab('More'), findsOneWidget);
    expect(tab('Stock'), findsNothing);
    expect(tab('Shop'), findsNothing);
  });

  testWidgets('a role allowed nothing still has a bar it can use',
      (tester) async {
    await open(tester, await signedIn(const []));

    expect(find.byType(NavigationDestination), findsNWidgets(2));
    expect(tab('Home'), findsOneWidget);
    expect(tab('More'), findsOneWidget);
  });

  testWidgets('the heading follows whichever tab is open', (tester) async {
    await open(tester, await signedIn(everything));

    // Home draws its own heading, so the shell adds none.
    expect(find.byType(AppBar), findsNothing);

    await tester.tap(tab('Stock'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('Stock')),
      findsOneWidget,
    );

    // The Sales tab opens the till, and that is what the heading says.
    await tester.tap(tab('Sales'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('New sale')),
      findsOneWidget,
    );
  });

  testWidgets('the heading is right even when earlier tabs are missing',
      (tester) async {
    // Shop is the third tab here, not the fourth. An index into the five
    // would land on Stock.
    await open(tester, await signedIn(['shop:view']));

    await tester.tap(tab('Shop'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('Shop')),
      findsOneWidget,
    );
  });

  testWidgets('More hides what the role may not open', (tester) async {
    await open(tester, await signedIn(const []));
    await tester.tap(tab('More'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Receivables'), findsNothing);
    expect(find.text('Waiting to sync'), findsOneWidget);

    await open(tester, await signedIn(everything));
    await tester.tap(tab('More'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Receivables'), findsOneWidget);
  });
}
