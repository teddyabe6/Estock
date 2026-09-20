import 'package:flutter/material.dart';

import '../core/app_state.dart';

/// Tells the user, without alarm, that work is being held on the device.
///
/// Silence would be worse: a shop owner needs to know that a sale recorded on
/// a phone with no signal has not reached the business records yet.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final sync = state.sync;
    final scheme = Theme.of(context).colorScheme;

    if (sync.isOnline && !sync.hasUnsyncedWork) return const SizedBox.shrink();

    final (IconData icon, Color colour, String message) = switch ((
      sync.isOnline,
      sync.rejectedCount > 0,
      sync.pendingCount,
    )) {
      (_, true, _) => (
          Icons.error_outline,
          scheme.error,
          '${sync.rejectedCount} item(s) could not be saved. Tap to review.',
        ),
      (false, false, 0) => (
          Icons.cloud_off,
          scheme.onSurfaceVariant,
          'Offline. You can keep selling — everything syncs when you reconnect.',
        ),
      (false, false, final pending) => (
          Icons.cloud_off,
          const Color(0xFF9A6200),
          'Offline. $pending item(s) waiting to sync.',
        ),
      (true, false, final pending) => (
          sync.isSyncing ? Icons.sync : Icons.cloud_upload_outlined,
          const Color(0xFF9A6200),
          sync.isSyncing ? 'Syncing $pending item(s)…' : '$pending item(s) waiting to sync.',
        ),
    };

    return Material(
      color: colour.withValues(alpha: 0.1),
      child: InkWell(
        onTap: sync.hasUnsyncedWork
            ? () => Navigator.of(context).pushNamed('/pending')
            : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Icon(icon, size: 18, color: colour),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  message,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: colour, fontWeight: FontWeight.w500),
                ),
              ),
              if (sync.hasUnsyncedWork)
                Icon(Icons.chevron_right, size: 18, color: colour),
            ],
          ),
        ),
      ),
    );
  }
}
