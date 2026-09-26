import 'dart:convert';

import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/app_state.dart';
import 'package:estock_mobile/core/offline/catalogue_cache.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/models/customer.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('customers survive a restart alongside the catalogue', () async {
    final prefs = await SharedPreferences.getInstance();
    final cache = CatalogueCache(preferences: prefs);
    await cache.saveCustomers(const [
      Customer(id: 'c1', name: 'Almaz Tadesse', phone: '+251911000111'),
      Customer(id: 'c2', name: 'ሰላም ኮንስትራክሽን'),
    ]);

    final loaded = await CatalogueCache(preferences: prefs).loadCustomers();
    expect(loaded.map((c) => c.name), ['Almaz Tadesse', 'ሰላም ኮንስትራክሽን']);
    expect(loaded.first.label, 'Almaz Tadesse · +251911000111');
  });

  test('corrupt customer storage reads as empty rather than crashing', () async {
    SharedPreferences.setMockInitialValues({
      'estock.catalogue.customers.v1': 'not json',
    });
    final cache = CatalogueCache(preferences: await SharedPreferences.getInstance());
    expect(await cache.loadCustomers(), isEmpty);
  });

  test('a credit sale can find its customer with no connection', () async {
    final prefs = await SharedPreferences.getInstance();
    final cache = CatalogueCache(preferences: prefs);
    await cache.saveCustomers(const [
      Customer(id: 'c1', name: 'Yonas Alemu', phone: '+251912000222'),
      Customer(id: 'c2', name: 'Selam Construction PLC', company: 'Selam'),
    ]);
    final state = AppState(
      api: ApiClient(
        baseUrl: 'http://test/api/v1',
        httpClient: MockClient((_) async => throw http.ClientException('offline')),
      ),
      outbox: Outbox(preferences: prefs),
      catalogue: cache,
    );
    await state.start();

    expect(state.searchCustomers('yon').single.name, 'Yonas Alemu');
    expect(state.searchCustomers('912').single.name, 'Yonas Alemu');
    expect(state.searchCustomers('selam').single.name, 'Selam Construction PLC');
    expect(state.searchCustomers('').length, 2);
  });

  test('adding a customer needs the server, and is then cached', () async {
    final prefs = await SharedPreferences.getInstance();
    final cache = CatalogueCache(preferences: prefs);
    final state = AppState(
      api: ApiClient(
        baseUrl: 'http://test/api/v1',
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/customers'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({'id': 'new-1', 'name': body['name'], 'phone': body['phone']}),
            201,
          );
        }),
      ),
      outbox: Outbox(preferences: prefs),
      catalogue: cache,
    );

    final created = await state.createCustomer(name: '  Abebe Kebede ', phone: '0911223344');
    expect(created.id, 'new-1');
    expect(created.name, 'Abebe Kebede');
    expect((await cache.loadCustomers()).single.id, 'new-1');
  });
}
