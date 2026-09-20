import 'package:estock_mobile/core/offline/outbox.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Outbox outbox;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    outbox = Outbox(preferences: await SharedPreferences.getInstance());
  });

  test('an added entry is pending and carries an idempotency key', () async {
    final entry = await outbox.add(
      path: '/sales',
      body: {'lines': []},
      summary: 'Sale · 100.00 ETB',
    );

    expect(entry.status, OutboxStatus.pending);
    expect(entry.idempotencyKey, isNotEmpty);
    expect(entry.body['idempotency_key'], entry.idempotencyKey);
    expect((await outbox.pending()).length, 1);
  });

  test('a caller-supplied idempotency key is kept', () async {
    final entry = await outbox.add(
      path: '/sales',
      body: {'idempotency_key': 'from-the-cart'},
      summary: 'Sale',
    );
    expect(entry.idempotencyKey, 'from-the-cart');
  });

  test('entries survive a restart', () async {
    await outbox.add(path: '/sales', body: {}, summary: 'Sale');

    // A new Outbox reading the same storage stands in for a restart.
    final reopened = Outbox(preferences: await SharedPreferences.getInstance());
    final entries = await reopened.all();

    expect(entries.length, 1);
    expect(entries.first.summary, 'Sale');
    expect(entries.first.idempotencyKey, isNotEmpty);
  });

  test('corrupt storage does not brick the app', () async {
    SharedPreferences.setMockInitialValues({'estock.outbox.v1': 'not json'});
    final recovered = Outbox(preferences: await SharedPreferences.getInstance());
    expect(await recovered.all(), isEmpty);
  });

  test('rejected entries are listed separately and never dropped', () async {
    final entry = await outbox.add(path: '/sales', body: {}, summary: 'Sale');
    entry.status = OutboxStatus.rejected;
    entry.lastError = 'Not enough stock';
    await outbox.update(entry);

    expect(await outbox.pending(), isEmpty);
    expect((await outbox.rejected()).length, 1);
    expect((await outbox.all()).length, 1);
  });

  test('pruning removes old synced entries but keeps pending and rejected', () async {
    final synced = await outbox.add(path: '/sales', body: {}, summary: 'Old sale');
    synced.status = OutboxStatus.synced;
    synced.lastTriedAt = DateTime.now().subtract(const Duration(days: 2));
    await outbox.update(synced);

    final rejected = await outbox.add(path: '/sales', body: {}, summary: 'Refused');
    rejected.status = OutboxStatus.rejected;
    rejected.lastTriedAt = DateTime.now().subtract(const Duration(days: 2));
    await outbox.update(rejected);

    await outbox.add(path: '/sales', body: {}, summary: 'Waiting');

    await outbox.pruneSynced();
    final remaining = await outbox.all();

    expect(remaining.map((e) => e.summary), ['Refused', 'Waiting']);
  });

  test('a recently synced entry is kept so the user can see it', () async {
    final entry = await outbox.add(path: '/sales', body: {}, summary: 'Just now');
    entry.status = OutboxStatus.synced;
    entry.lastTriedAt = DateTime.now();
    await outbox.update(entry);

    await outbox.pruneSynced();
    expect((await outbox.all()).length, 1);
  });

  test('ids are unguessable and unique', () {
    final ids = List.generate(500, (_) => Outbox.newId());
    expect(ids.toSet().length, 500);
    expect(ids.first.length, 24);
  });
}
