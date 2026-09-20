import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// What happened to a queued operation.
enum OutboxStatus {
  /// Waiting for a connection.
  pending,

  /// Accepted by the server. The record is kept briefly so the user can see it.
  synced,

  /// The server refused it on its merits — for example the stock ran out while
  /// the device was offline. Needs a person to decide what to do.
  rejected,
}

/// One operation captured on the device, to be replayed against the API.
///
/// Every entry carries an [idempotencyKey] generated when the operation was
/// captured, never when it is sent. The server deduplicates on that key, so a
/// retry after an ambiguous failure cannot post the same sale twice.
class OutboxEntry {
  OutboxEntry({
    required this.id,
    required this.path,
    required this.body,
    required this.idempotencyKey,
    required this.createdAt,
    required this.summary,
    this.status = OutboxStatus.pending,
    this.attempts = 0,
    this.lastError,
    this.lastTriedAt,
    this.serverReference,
  });

  final String id;

  /// API path, e.g. `/sales`.
  final String path;
  final Map<String, dynamic> body;
  final String idempotencyKey;
  final DateTime createdAt;

  /// Short human description shown in the pending list, e.g. "Sale · 450.00 ETB".
  final String summary;

  OutboxStatus status;
  int attempts;
  String? lastError;
  DateTime? lastTriedAt;

  /// Document number the server assigned once accepted.
  String? serverReference;

  Map<String, dynamic> toJson() => {
        'id': id,
        'path': path,
        'body': body,
        'idempotency_key': idempotencyKey,
        'created_at': createdAt.toIso8601String(),
        'summary': summary,
        'status': status.name,
        'attempts': attempts,
        'last_error': lastError,
        'last_tried_at': lastTriedAt?.toIso8601String(),
        'server_reference': serverReference,
      };

  static OutboxEntry fromJson(Map<String, dynamic> json) => OutboxEntry(
        id: json['id'] as String,
        path: json['path'] as String,
        body: Map<String, dynamic>.from(json['body'] as Map),
        idempotencyKey: json['idempotency_key'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        summary: json['summary'] as String? ?? 'Pending operation',
        status: OutboxStatus.values.firstWhere(
          (value) => value.name == json['status'],
          orElse: () => OutboxStatus.pending,
        ),
        attempts: json['attempts'] as int? ?? 0,
        lastError: json['last_error'] as String?,
        lastTriedAt: json['last_tried_at'] == null
            ? null
            : DateTime.tryParse(json['last_tried_at'] as String),
        serverReference: json['server_reference'] as String?,
      );
}

/// Durable queue of operations captured while offline.
///
/// Entries survive an app restart. Order is preserved: operations replay in the
/// order they were captured, so a sale recorded before a stock adjustment is
/// posted first.
class Outbox {
  Outbox({SharedPreferences? preferences}) : _preferences = preferences;

  static const _storageKey = 'estock.outbox.v1';

  SharedPreferences? _preferences;
  List<OutboxEntry>? _cache;

  Future<SharedPreferences> get _prefs async =>
      _preferences ??= await SharedPreferences.getInstance();

  Future<List<OutboxEntry>> all() async {
    if (_cache != null) return List.unmodifiable(_cache!);
    final prefs = await _prefs;
    final raw = prefs.getString(_storageKey);
    if (raw == null || raw.isEmpty) {
      _cache = [];
    } else {
      try {
        final decoded = jsonDecode(raw) as List<dynamic>;
        _cache = decoded
            .map((item) => OutboxEntry.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
      } catch (_) {
        // Corrupt storage must not brick the app; start clean rather than crash.
        _cache = [];
      }
    }
    return List.unmodifiable(_cache!);
  }

  Future<List<OutboxEntry>> pending() async =>
      (await all()).where((entry) => entry.status == OutboxStatus.pending).toList();

  Future<List<OutboxEntry>> rejected() async =>
      (await all()).where((entry) => entry.status == OutboxStatus.rejected).toList();

  Future<OutboxEntry> add({
    required String path,
    required Map<String, dynamic> body,
    required String summary,
  }) async {
    await all();
    final entry = OutboxEntry(
      id: newId(),
      path: path,
      body: body,
      // Generated at capture time, so every replay of this operation carries
      // the same key and the server posts it at most once.
      idempotencyKey: body['idempotency_key'] as String? ?? newId(),
      createdAt: DateTime.now(),
      summary: summary,
    );
    entry.body['idempotency_key'] = entry.idempotencyKey;
    _cache!.add(entry);
    await _save();
    return entry;
  }

  Future<void> update(OutboxEntry entry) async {
    await all();
    final index = _cache!.indexWhere((item) => item.id == entry.id);
    if (index >= 0) {
      _cache![index] = entry;
      await _save();
    }
  }

  Future<void> remove(String id) async {
    await all();
    _cache!.removeWhere((entry) => entry.id == id);
    await _save();
  }

  /// Drop entries that were accepted more than [keepFor] ago, so the "recently
  /// synced" list does not grow without bound.
  Future<void> pruneSynced({Duration keepFor = const Duration(hours: 12)}) async {
    await all();
    final cutoff = DateTime.now().subtract(keepFor);
    final before = _cache!.length;
    _cache!.removeWhere((entry) =>
        entry.status == OutboxStatus.synced &&
        (entry.lastTriedAt ?? entry.createdAt).isBefore(cutoff));
    if (_cache!.length != before) await _save();
  }

  Future<void> clear() async {
    _cache = [];
    await _save();
  }

  Future<void> _save() async {
    final prefs = await _prefs;
    await prefs.setString(
      _storageKey,
      jsonEncode(_cache!.map((entry) => entry.toJson()).toList()),
    );
  }

  static final Random _random = Random.secure();

  /// Unguessable id, also used as the idempotency key.
  static String newId() {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    return List.generate(24, (_) => chars[_random.nextInt(chars.length)]).join();
  }
}
