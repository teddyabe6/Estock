import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';

/// Everything that does not earn a place in the bottom bar (PRD 7).
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;

    return ListView(
      children: [
        if (session != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(session.fullName,
                    style: Theme.of(context).textTheme.titleMedium),
                Text(
                  '${session.role.replaceAll('_', ' ')} · ${session.tenantName}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
        const SectionTitle('Credit'),
        ListTile(
          leading: const Icon(Icons.receipt_long_outlined),
          title: const Text('Receivables'),
          subtitle: const Text('What customers owe you'),
          trailing: const Icon(Icons.chevron_right),
          enabled: session?.can('credit:view') ?? false,
          onTap: () => Navigator.of(context).pushNamed('/credit'),
        ),
        const SectionTitle('This device'),
        ListTile(
          leading: Icon(
            state.sync.isOnline ? Icons.cloud_done_outlined : Icons.cloud_off,
          ),
          title: const Text('Waiting to sync'),
          subtitle: Text(
            state.sync.hasUnsyncedWork
                ? '${state.sync.pendingCount} waiting, ${state.sync.rejectedCount} need attention'
                : 'Everything is synced',
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).pushNamed('/pending'),
        ),
        ListTile(
          leading: const Icon(Icons.download_outlined),
          title: const Text('Update offline catalogue'),
          subtitle: Text(
            state.catalogueFetchedAt == null
                ? 'Never updated'
                : 'Last updated ${Money.dateTime(state.catalogueFetchedAt)}',
          ),
          onTap: () async {
            final messenger = ScaffoldMessenger.of(context);
            await state.refresh();
            messenger.showSnackBar(
              SnackBar(
                content: Text(
                  state.sync.isOnline
                      ? 'Catalogue updated.'
                      : 'Still offline — the saved catalogue is unchanged.',
                ),
              ),
            );
          },
        ),
        const Divider(),
        ListTile(
          leading: const Icon(Icons.logout),
          title: const Text('Sign out'),
          subtitle: state.sync.hasUnsyncedWork
              ? const Text('Unsynced work is kept on this device')
              : null,
          onTap: () => _confirmSignOut(context, state),
        ),
      ],
    );
  }

  Future<void> _confirmSignOut(BuildContext context, AppState state) async {
    final unsynced = state.sync.hasUnsyncedWork;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: Text(
          unsynced
              ? 'You have work that has not synced yet. It stays on this device '
                  'and will sync after you sign in again.'
              : 'You will need a connection to sign back in.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );
    if (confirmed ?? false) await state.signOut();
  }
}
