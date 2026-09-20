import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:estock_mobile/core/api_client.dart';
import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:estock_mobile/core/offline/sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Connectivity that never reports a change, so tests drive sync directly.
class _StaticConnectivity implements Connectivity {
  @override
  Future<List<ConnectivityResult>> checkConnectivity() async =>
      [ConnectivityResult.wifi];

  @override
  Stream<List<ConnectivityResult>> get onConnectivityChanged =>
      const Stream.empty();

  @override
  noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Outbox outbox;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    outbox = Outbox(preferences: await SharedPreferences.getInstance());
  });

  SyncService serviceWith(MockClient client) {
    final api = ApiClient(baseUrl: 'http://test/api/v1', httpClient: client);
    api.token = 'test-token';
    return SyncService(
      api: api,
      outbox: outbox,
      connectivity: _StaticConnectivity(),
    );
  }

  test('an accepted sale is marked synced and records its number', () async {
    final service = serviceWith(MockClient((request) async =>
        http.Response(jsonEncode({'sale': {'number': 'S-2026-000042'}}), 201)));

    await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    final result = await service.sync();

    expect(result.synced, 1);
    expect(result.rejected, 0);
    final entry = (await outbox.all()).single;
    expect(entry.status, OutboxStatus.synced);
    expect(entry.serverReference, 'S-2026-000042');
  });

  test('every replay sends the same idempotency key', () async {
    final keysSeen = <String>[];
    final service = serviceWith(MockClient((request) async {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      keysSeen.add(body['idempotency_key'] as String);
      // First attempt fails at the network; second succeeds.
      if (keysSeen.length == 1) throw http.ClientException('offline');
      return http.Response(jsonEncode({'sale': {'number': 'S-1'}}), 201);
    }));

    await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    await service.sync();
    await service.sync();

    expect(keysSeen.length, 2);
    expect(keysSeen.first, keysSeen.last,
        reason: 'the server deduplicates on this key, so it must not change');
  });

  test('a sale the server refuses is rejected, not dropped', () async {
    // Two phones both sold the last unit offline; this is the second one.
    final service = serviceWith(MockClient((request) async => http.Response(
          jsonEncode({
            'code': 'insufficient_stock',
            'message': 'Not enough stock for Berbere 1kg: 0 available, 1 required',
          }),
          409,
        )));

    await outbox.add(path: '/sales', body: {}, summary: 'Sale · 450.00 ETB');
    final result = await service.sync();

    expect(result.rejected, 1);
    final entry = (await outbox.all()).single;
    expect(entry.status, OutboxStatus.rejected);
    expect(entry.lastError, contains('Not enough stock'));
    // The record is kept so a person can decide what to do about it.
    expect((await outbox.all()).length, 1);
  });

  test('a network failure leaves the entry pending for a later retry', () async {
    final service = serviceWith(
        MockClient((request) async => throw http.ClientException('no route')));

    await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    final result = await service.sync();

    expect(result.synced, 0);
    expect(result.rejected, 0);
    expect((await outbox.pending()).length, 1);
    expect(service.isOnline, isFalse);
  });

  test('an expired session keeps the work instead of discarding it', () async {
    final service = serviceWith(MockClient((request) async => http.Response(
          jsonEncode({'code': 'not_authenticated', 'message': 'Session expired'}),
          401,
        )));

    await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    await service.sync();

    final entry = (await outbox.all()).single;
    expect(entry.status, OutboxStatus.pending);
    expect(entry.lastError, contains('Sign in again'));
  });

  test('queued sales replay oldest first', () async {
    final order = <String>[];
    final service = serviceWith(MockClient((request) async {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      order.add(body['label'] as String);
      return http.Response(jsonEncode({'number': 'S-1'}), 201);
    }));

    await outbox.add(path: '/sales', body: {'label': 'first'}, summary: 'First');
    await Future<void>.delayed(const Duration(milliseconds: 5));
    await outbox.add(path: '/sales', body: {'label': 'second'}, summary: 'Second');
    await Future<void>.delayed(const Duration(milliseconds: 5));
    await outbox.add(path: '/sales', body: {'label': 'third'}, summary: 'Third');

    await service.sync();

    expect(order, ['first', 'second', 'third'],
        reason: 'stock must be drawn down in the order the shop sold');
  });

  test('sync stops at the first network failure rather than hammering', () async {
    var attempts = 0;
    final service = serviceWith(MockClient((request) async {
      attempts++;
      throw http.ClientException('offline');
    }));

    for (var i = 0; i < 5; i++) {
      await outbox.add(path: '/sales', body: {}, summary: 'Sale $i');
    }
    await service.sync();

    expect(attempts, 1);
    expect((await outbox.pending()).length, 5);
  });

  test('a rejected entry can be retried after the cause is fixed', () async {
    var shouldFail = true;
    final service = serviceWith(MockClient((request) async {
      if (shouldFail) {
        return http.Response(
          jsonEncode({'code': 'insufficient_stock', 'message': 'Not enough stock'}),
          409,
        );
      }
      return http.Response(jsonEncode({'number': 'S-9'}), 201);
    }));

    final entry = await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    await service.sync();
    expect(service.rejectedCount, 1);

    // Stock was received, so the sale can go through now.
    shouldFail = false;
    await service.retryRejected(entry.id);
    await service.sync();

    expect((await outbox.all()).single.status, OutboxStatus.synced);
  });

  test('counts reflect what is waiting and what needs attention', () async {
    final service = serviceWith(MockClient((request) async => http.Response(
          jsonEncode({'code': 'insufficient_stock', 'message': 'No stock'}),
          409,
        )));

    await outbox.add(path: '/sales', body: {}, summary: 'Will fail');
    await service.refreshCounts();
    expect(service.pendingCount, 1);
    expect(service.hasUnsyncedWork, isTrue);

    await service.sync();
    expect(service.pendingCount, 0);
    expect(service.rejectedCount, 1);
    expect(service.hasUnsyncedWork, isTrue);

    await service.dismissRejected((await outbox.all()).single.id);
    expect(service.hasUnsyncedWork, isFalse);
  });

  test('submitting while offline queues without sending', () async {
    var calls = 0;
    final service = serviceWith(MockClient((request) async {
      calls++;
      throw http.ClientException('offline');
    }));

    // First attempt discovers there is no connection.
    await outbox.add(path: '/sales', body: {}, summary: 'Probe');
    await service.sync();
    expect(service.isOnline, isFalse);
    final callsAfterProbe = calls;

    final response = await service.submit(
      path: '/sales',
      body: {'lines': []},
      summary: 'Sale · 100.00 ETB',
    );

    expect(response, isNull, reason: 'queued, not posted');
    expect(calls, callsAfterProbe, reason: 'no request while known to be offline');
    expect(service.pendingCount, 2);
  });
}
