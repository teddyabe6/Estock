import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/core/server_address.dart';
import 'package:estock_mobile/main.dart';
import 'package:estock_mobile/models/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A copy of the app built for [server] — empty for one built without, the
/// way a phone trying Estock against a computer is — recording where each
/// request went.
Future<(AppState, List<Uri>)> app({String server = ''}) async {
  final prefs = await SharedPreferences.getInstance();
  final asked = <Uri>[];
  final state = AppState(
    api: ApiClient(
      baseUrl: server,
      httpClient: MockClient((request) async {
        asked.add(request.url);
        throw http.ClientException('nobody there');
      }),
    ),
    outbox: Outbox(preferences: prefs),
    catalogue: CatalogueCache(preferences: prefs),
  );
  state.loading = false;
  return (state, asked);
}

Future<void> signIn(WidgetTester tester, {String? server}) async {
  if (server != null) {
    await tester.enterText(find.byKey(const Key('server')), server);
  }
  await tester.enterText(find.byKey(const Key('email')), 'owner@merkato-demo.et');
  await tester.enterText(find.byKey(const Key('password')), 'demo-password-123');
  await tester.tap(find.byKey(const Key('signIn')));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('an address however it is typed', () {
    test('is the same server', () {
      const base = 'http://192.168.1.20:8000/api/v1';
      for (final typed in [
        '192.168.1.20:8000',
        ' 192.168.1.20:8000 ',
        'http://192.168.1.20:8000',
        'http://192.168.1.20:8000/',
        '192.168.1.20:8000/api/v1',
        'HTTP://192.168.1.20:8000/api/v1/',
      ]) {
        expect(apiBaseFor(typed), base, reason: typed);
      }
    });

    test('keeps https, a name, and a path in front of the API', () {
      expect(apiBaseFor('https://api.shop.et'), 'https://api.shop.et/api/v1');
      expect(apiBaseFor('my-laptop.local:8000'),
          'http://my-laptop.local:8000/api/v1');
      expect(apiBaseFor('shop.et/estock'), 'http://shop.et/estock/api/v1');
    });

    test('is not taken for an address when it is not one', () {
      for (final typed in ['', '   ', 'not a server', 'ftp://shop.et', 'http://']) {
        expect(apiBaseFor(typed), isNull, reason: typed);
      }
    });

    test('is said back the way a person would say it', () {
      expect(serverLabel('http://192.168.1.20:8000/api/v1'), '192.168.1.20:8000');
      expect(serverLabel('https://api.shop.et/api/v1'), 'https://api.shop.et');
    });
  });

  testWidgets('a copy built without a server asks for one, and signs in there',
      (tester) async {
    final (state, asked) = await app();
    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    expect(find.byKey(const Key('server')), findsOneWidget);

    await signIn(tester, server: '192.168.1.20:8000');

    expect(asked.single.toString(), 'http://192.168.1.20:8000/api/v1/auth/login');
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('estock.server.v1'), 'http://192.168.1.20:8000/api/v1',
        reason: 'typed once, not at every sign-in');
  });

  testWidgets('a server that does not answer says what to check',
      (tester) async {
    final (state, _) = await app();
    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    await signIn(tester, server: '192.168.1.20');

    expect(find.textContaining('Could not reach 192.168.1.20.'), findsOneWidget);
    expect(find.textContaining('it usually ends in :8000'), findsOneWidget,
        reason: 'the port is what gets left off');
    expect(find.textContaining('same Wi-Fi'), findsOneWidget);
  });

  testWidgets('an address that is not one is caught before anything is sent',
      (tester) async {
    final (state, asked) = await app();
    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    await signIn(tester, server: '');

    expect(find.text('Enter the server address, like 192.168.1.20:8000'),
        findsOneWidget);
    expect(asked, isEmpty);
  });

  test('the server comes back when the app is opened again', () async {
    SharedPreferences.setMockInitialValues({
      'estock.server.v1': 'http://192.168.1.20:8000/api/v1',
    });
    final (state, _) = await app();
    await state.start();

    expect(state.server, 'http://192.168.1.20:8000/api/v1');
  });

  testWidgets('the next sign-in starts from the server used last time',
      (tester) async {
    final (state, _) = await app();
    await state.useServer('192.168.1.20:8000');
    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    expect(
      tester.widget<TextField>(find.descendant(
        of: find.byKey(const Key('server')),
        matching: find.byType(TextField),
      )).controller!.text,
      '192.168.1.20:8000',
    );
  });

  testWidgets('a copy built for a shop never asks', (tester) async {
    final (state, _) = await app(server: 'https://api.shop.et/api/v1');
    await tester.pumpWidget(EstockApp(state: state));
    await tester.pump();

    expect(state.asksForServer, isFalse);
    expect(find.byKey(const Key('server')), findsNothing);
  });

  group('More says which server', () {
    Future<void> openMore(WidgetTester tester, AppState state) async {
      state.session = const UserSession(
        userId: 'u1',
        fullName: 'Tigist Bekele',
        email: 'owner@merkato-demo.et',
        tenantId: 't1',
        tenantName: 'Merkato Wholesale',
        currency: 'ETB',
        role: 'owner',
        permissions: ['sale:view'],
        branches: [],
      );
      await tester.pumpWidget(EstockApp(state: state));
      await tester.pump();
      await tester.tap(find.text('More'));
      await tester.pump(const Duration(seconds: 1));
    }

    testWidgets('in a copy where somebody typed it in', (tester) async {
      final (state, _) = await app();
      await state.useServer('192.168.1.20:8000');
      await openMore(tester, state);

      await tester.scrollUntilVisible(
        find.byKey(const Key('moreServer')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('192.168.1.20:8000 · sign out to use another'),
          findsOneWidget);
    });

    testWidgets('and not in a copy built for a shop', (tester) async {
      final (state, _) = await app(server: 'https://api.shop.et/api/v1');
      await openMore(tester, state);

      expect(find.byKey(const Key('moreServer')), findsNothing);
    });
  });
}
