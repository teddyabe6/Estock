import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/screens/sign_in_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<AppState> buildState({MockClient? client}) async {
  final prefs = await SharedPreferences.getInstance();
  return AppState(
    api: ApiClient(
      baseUrl: 'http://test/api/v1',
      httpClient: client ??
          MockClient((_) async => throw http.ClientException('offline')),
    ),
    outbox: Outbox(preferences: prefs),
    catalogue: CatalogueCache(preferences: prefs),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('a signed-out device opens on the sign-in screen', (tester) async {
    final state = await buildState();
    state.loading = false;

    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(find.text('Estock'), findsOneWidget);
  });

  testWidgets('sign-in validates before calling the API', (tester) async {
    var requests = 0;
    final state = await buildState(
      client: MockClient((_) async {
        requests++;
        throw http.ClientException('should not be called');
      }),
    );
    state.loading = false;

    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    await tester.tap(find.byKey(const Key('signIn')));
    await tester.pump();

    expect(find.text('Enter your email'), findsOneWidget);
    expect(find.text('Enter your password'), findsOneWidget);
    expect(requests, 0);
  });

  testWidgets('a sign-in with no connection explains itself', (tester) async {
    final state = await buildState();
    state.loading = false;

    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    await tester.enterText(find.byKey(const Key('email')), 'owner@shop.et');
    await tester.enterText(find.byKey(const Key('password')), 'secret123');
    await tester.tap(find.byKey(const Key('signIn')));
    await tester.pumpAndSettle();

    expect(find.textContaining('No connection'), findsOneWidget);
  });

  testWidgets('the sign-in screen sets expectations about working offline',
      (tester) async {
    final state = await buildState();
    state.loading = false;

    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    expect(
      find.textContaining('keep working offline'),
      findsOneWidget,
      reason: 'a shop owner should know a first sign-in needs a connection',
    );
  });
}
