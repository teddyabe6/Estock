import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import '../api_client.dart';
import 'outbox.dart';

/// Result of one drain of the outbox.
class SyncResult {
  const SyncResult({this.synced = 0, this.rejected = 0, this.stillPending = 0});

  final int synced;
  final int rejected;
  final int stillPending;

  bool get didAnything => synced > 0 || rejected > 0;
}

/// Replays queued operations once the device is back online.
///
/// ## The conflict policy
///
/// The server stays the authority. An operation captured offline is
/// **provisional** until the server accepts it, and the app says so in the
/// interface rather than implying the sale is final.
///
/// On replay there are three outcomes:
///
/// * **Accepted** — the server posts it and returns the document number. The
///   entry is marked synced. Because the idempotency key was generated when the
///   operation was captured, replaying an operation the server already accepted
///   returns the same record instead of creating a second one.
/// * **Refused on its merits** (4xx) — for example two phones both sold the last
///   unit while offline, and the second one now fails with `insufficient_stock`.
///   The entry is marked *rejected* and surfaced to a person. It is never
///   silently dropped, and the app never invents a correction on its own: what
///   to do about a sale that cannot be posted is a business decision.
/// * **Could not reach the server** — the entry stays pending and is retried.
///
/// Sales replay strictly in the order they were captured, so the stock the
/// server sees is drawn down in the same order the shop actually sold.
class SyncService extends ChangeNotifier {
  SyncService({
    required ApiClient api,
    required Outbox outbox,
    Connectivity? connectivity,
  })  : _api = api,
        _outbox = outbox,
        _connectivity = connectivity ?? Connectivity();

  final ApiClient _api;
  final Outbox _outbox;
  final Connectivity _connectivity;

  StreamSubscription<List<ConnectivityResult>>? _subscription;
  Timer? _retryTimer;

  bool _online = true;
  bool _syncing = false;
  int _pendingCount = 0;
  int _rejectedCount = 0;

  bool get isOnline => _online;
  bool get isSyncing => _syncing;
  int get pendingCount => _pendingCount;
  int get rejectedCount => _rejectedCount;
  bool get hasUnsyncedWork => _pendingCount > 0 || _rejectedCount > 0;

  /// Start watching connectivity and drain whatever is already queued.
  Future<void> start() async {
    await refreshCounts();
    try {
      final current = await _connectivity.checkConnectivity();
      _online = _isConnected(current);
    } catch (_) {
      // Connectivity reporting is unavailable on some platforms; assume online
      // and let a failed request tell us otherwise.
      _online = true;
    }
    _subscription = _connectivity.onConnectivityChanged.listen((results) {
      final wasOffline = !_online;
      _online = _isConnected(results);
      notifyListeners();
      if (_online && wasOffline) unawaited(sync());
    });
    // A periodic sweep covers the case where connectivity never reports a
    // change but the network came back anyway.
    _retryTimer = Timer.periodic(const Duration(minutes: 2), (_) => unawaited(sync()));
    if (_online) unawaited(sync());
  }

  bool _isConnected(List<ConnectivityResult> results) =>
      results.isNotEmpty && !results.every((r) => r == ConnectivityResult.none);

  Future<void> refreshCounts() async {
    _pendingCount = (await _outbox.pending()).length;
    _rejectedCount = (await _outbox.rejected()).length;
    notifyListeners();
  }

  /// Queue an operation for later, or send it now if there is a connection.
  ///
  /// Returns the server's response when it went straight through, and `null`
  /// when it was queued.
  Future<Map<String, dynamic>?> submit({
    required String path,
    required Map<String, dynamic> body,
    required String summary,
  }) async {
    final entry = await _outbox.add(path: path, body: body, summary: summary);
    await refreshCounts();

    if (!_online) return null;

    final response = await _attempt(entry);
    await refreshCounts();
    return response;
  }

  /// Drain the outbox, oldest first.
  Future<SyncResult> sync() async {
    if (_syncing) return const SyncResult();
    final queued = await _outbox.pending();
    if (queued.isEmpty) {
      await _outbox.pruneSynced();
      await refreshCounts();
      return const SyncResult();
    }

    _syncing = true;
    notifyListeners();

    var synced = 0;
    var rejected = 0;
    try {
      // Oldest first: replay in the order the shop actually did the work.
      queued.sort((a, b) => a.createdAt.compareTo(b.createdAt));
      for (final entry in queued) {
        final before = entry.status;
        await _attempt(entry);
        if (entry.status == OutboxStatus.synced && before != OutboxStatus.synced) {
          synced++;
        } else if (entry.status == OutboxStatus.rejected) {
          rejected++;
        } else {
          // Still offline — stop rather than hammering every queued entry.
          break;
        }
      }
      await _outbox.pruneSynced();
    } finally {
      _syncing = false;
      await refreshCounts();
    }

    return SyncResult(
      synced: synced,
      rejected: rejected,
      stillPending: _pendingCount,
    );
  }

  /// Send one entry and record what the server said.
  Future<Map<String, dynamic>?> _attempt(OutboxEntry entry) async {
    entry.attempts++;
    entry.lastTriedAt = DateTime.now();
    try {
      final dynamic response = await _api.post(entry.path, body: entry.body);
      entry.status = OutboxStatus.synced;
      entry.lastError = null;
      entry.serverReference = _referenceFrom(response);
      _online = true;
      await _outbox.update(entry);
      return response is Map<String, dynamic> ? response : null;
    } on ApiException catch (error) {
      if (error.isNetworkError) {
        _online = false;
        entry.lastError = null; // not a failure of the operation itself
        await _outbox.update(entry);
        notifyListeners();
        return null;
      }
      if (error.isAuthError) {
        // The session expired. Keep the work; it replays after signing in.
        entry.lastError = 'Sign in again to finish syncing this.';
        await _outbox.update(entry);
        return null;
      }
      // The server refused it on its merits. A person decides what happens next.
      entry.status = OutboxStatus.rejected;
      entry.lastError = error.message;
      await _outbox.update(entry);
      return null;
    }
  }

  String? _referenceFrom(dynamic response) {
    if (response is! Map<String, dynamic>) return null;
    final sale = response['sale'];
    if (sale is Map<String, dynamic>) return sale['number'] as String?;
    return response['number'] as String? ?? response['reference'] as String?;
  }

  /// Discard a rejected entry once someone has dealt with it.
  Future<void> dismissRejected(String id) async {
    await _outbox.remove(id);
    await refreshCounts();
  }

  /// Put a rejected entry back in the queue, for when the cause was fixed
  /// (stock received, for instance).
  Future<void> retryRejected(String id) async {
    final entries = await _outbox.all();
    final entry = entries.where((item) => item.id == id).firstOrNull;
    if (entry == null) return;
    entry.status = OutboxStatus.pending;
    entry.lastError = null;
    await _outbox.update(entry);
    await refreshCounts();
    unawaited(sync());
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _retryTimer?.cancel();
    super.dispose();
  }
}
