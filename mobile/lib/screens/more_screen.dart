import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../core/server_address.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'sales_history_screen.dart';

/// Everything that does not earn a place in the bottom bar (PRD 7).
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;
    final theme = Theme.of(context);
    final palette = context.palette;
    const violet = Color(0xFF7C3AED);

    final shop = <Widget>[
      ListTile(
        leading: IconBadge(Icons.notifications_none, colour: palette.warn),
        title: const Text('Notifications'),
        subtitle: Text(
          state.unreadNotifications > 0
              ? '${state.unreadNotifications} waiting'
              : 'Requests, questions and low-stock warnings',
        ),
        trailing: state.unreadNotifications > 0
            ? Badge.count(count: state.unreadNotifications)
            : const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).pushNamed('/notifications'),
      ),
      // Hidden rather than greyed out, which is what the web does with a
      // screen a role may not open.
      if (session?.can('sale:view') ?? false)
        ListTile(
          leading: IconBadge(
            Icons.receipt_long_outlined,
            colour: theme.colorScheme.primary,
          ),
          title: const Text('Sales'),
          subtitle: const Text('Find a sale, its receipt or a refund'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SalesHistoryScreen()),
          ),
        ),
      if (session?.can('customer:view') ?? false)
        ListTile(
          key: const Key('moreCustomers'),
          leading: IconBadge(Icons.people_outline, colour: palette.info),
          title: const Text('Customers'),
          subtitle: const Text('Who they are, what they bought, what they owe'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).pushNamed('/customers'),
        ),
      if (session?.can('supplier:view') ?? false)
        ListTile(
          key: const Key('moreSuppliers'),
          leading: const IconBadge(Icons.local_shipping_outlined, colour: violet),
          title: const Text('Suppliers'),
          subtitle: const Text('Who you buy from, and what you owe them'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).pushNamed('/suppliers'),
        ),
    ];

    final device = <Widget>[
      ListTile(
        leading: IconBadge(
          state.sync.isOnline ? Icons.cloud_done_outlined : Icons.cloud_off,
          colour: state.sync.hasUnsyncedWork ? palette.warn : palette.good,
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
        leading: IconBadge(Icons.download_outlined, colour: palette.info),
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
      // Only in a copy built without a server, where somebody typed one
      // in: when the phone stops reaching it, this is the first thing to
      // check.
      if (state.asksForServer)
        ListTile(
          key: const Key('moreServer'),
          leading: IconBadge(Icons.dns_outlined, colour: palette.muted),
          title: const Text('Server'),
          subtitle: Text(
            '${serverLabel(state.server)} · sign out to use another',
          ),
        ),
    ];

    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        // Who is signed in, as a card with their initials: the phone is
        // often shared at a counter, and this says whose it is now.
        if (session != null)
          Card(
            margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Monogram(session.fullName, size: 48),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(session.fullName, style: theme.textTheme.titleMedium),
                        Text(
                          '${session.role.replaceAll('_', ' ')} · ${session.tenantName}',
                          style: theme.textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        const SectionTitle('Your shop'),
        TileGroup(dividerIndent: 70, children: shop),
        if (session?.can('credit:view') ?? false) ...[
          const SectionTitle('Credit'),
          TileGroup(
            dividerIndent: 70,
            children: [
              ListTile(
                leading: IconBadge(
                  Icons.account_balance_wallet_outlined,
                  colour: palette.good,
                ),
                title: const Text('Receivables'),
                subtitle: const Text('What customers owe you'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).pushNamed('/credit'),
              ),
            ],
          ),
        ],
        const SectionTitle('This device'),
        TileGroup(dividerIndent: 70, children: device),
        const SizedBox(height: 12),
        TileGroup(
          children: [
            ListTile(
              leading: IconBadge(Icons.logout, colour: theme.colorScheme.error),
              title: Text(
                'Sign out',
                style: TextStyle(color: theme.colorScheme.error),
              ),
              subtitle: state.sync.hasUnsyncedWork
                  ? const Text('Unsynced work is kept on this device')
                  : null,
              onTap: () => _confirmSignOut(context, state),
            ),
          ],
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
          DialogActions(
            back: OutlinedButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            confirm: FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Sign out'),
            ),
          ),
        ],
      ),
    );
    if (confirmed ?? false) await state.signOut();
  }
}
