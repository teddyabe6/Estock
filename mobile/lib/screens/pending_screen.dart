import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
import '../widgets/common.dart';

/// Work captured on this device: what is waiting, and what the server refused.
///
/// A refused item is never discarded quietly. What to do about a sale that
/// could not be posted — because the stock ran out while the phone was offline,
/// say — is a decision for a person, not the app.
class PendingScreen extends StatefulWidget {
  const PendingScreen({super.key});

  @override
  State<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends State<PendingScreen> {
  List<OutboxEntry> _entries = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final entries = await AppScope.of(context).outbox.all();
    if (!mounted) return;
    setState(() {
      _entries = entries.toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final rejected =
        _entries.where((e) => e.status == OutboxStatus.rejected).toList();
    final pending =
        _entries.where((e) => e.status == OutboxStatus.pending).toList();
    final synced =
        _entries.where((e) => e.status == OutboxStatus.synced).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Waiting to sync'),
        actions: [
          IconButton(
            icon: const Icon(Icons.sync),
            tooltip: 'Try now',
            onPressed: state.sync.isSyncing
                ? null
                : () async {
                    await state.sync.sync();
                    await _load();
                  },
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _entries.isEmpty
              ? const EmptyState(
                  icon: Icons.cloud_done_outlined,
                  title: 'Everything is synced',
                  message: 'Nothing is waiting on this device.',
                )
              : ListView(
                  children: [
                    if (rejected.isNotEmpty) ...[
                      const SectionTitle('Needs your attention'),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                        child: Text(
                          'These could not be saved. Nothing has been posted to '
                          'your records, and nothing has been thrown away.',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: Theme.of(context).colorScheme.onSurfaceVariant,
                              ),
                        ),
                      ),
                      ...rejected.map((entry) => _rejectedTile(context, entry)),
                    ],
                    if (pending.isNotEmpty) ...[
                      const SectionTitle('Waiting for a connection'),
                      ...pending.map((entry) => ListTile(
                            leading: const Icon(Icons.schedule),
                            title: Text(entry.summary),
                            subtitle: Text(
                              'Captured ${Money.dateTime(entry.createdAt)}'
                              '${entry.attempts > 0 ? ' · ${entry.attempts} attempt(s)' : ''}',
                            ),
                          )),
                    ],
                    if (synced.isNotEmpty) ...[
                      const SectionTitle('Recently synced'),
                      ...synced.map((entry) => ListTile(
                            leading: Icon(Icons.check_circle_outline,
                                color: Theme.of(context).colorScheme.primary),
                            title: Text(entry.summary),
                            subtitle: Text(entry.serverReference == null
                                ? 'Saved to your records'
                                : 'Saved as ${entry.serverReference}'),
                          )),
                    ],
                  ],
                ),
    );
  }

  Widget _rejectedTile(BuildContext context, OutboxEntry entry) {
    final state = AppScope.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.error_outline,
                    color: Theme.of(context).colorScheme.error, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    entry.summary,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(entry.lastError ?? 'The server refused this.'),
            const SizedBox(height: 4),
            Text(
              'Captured ${Money.dateTime(entry.createdAt)}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: () async {
                    await state.sync.dismissRejected(entry.id);
                    await _load();
                  },
                  child: const Text('Discard'),
                ),
                const SizedBox(width: 8),
                FilledButton.tonal(
                  onPressed: () async {
                    await state.sync.retryRejected(entry.id);
                    await _load();
                  },
                  child: const Text('Try again'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
