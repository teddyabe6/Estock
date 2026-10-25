import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';

/// What the shop has been told: proforma requests, enquiries, payment slips,
/// low stock and subscription notices (PRD 9, 11.4).
///
/// The web has carried these since the storefront was built and the phone had
/// nowhere to show them, which mattered most for the thing a phone is best
/// at: a buyer asks several shops for a price at once, and the shop that
/// answers first is the one that sells. A notice nobody sees is a sale lost.
///
/// They live on the server, not in the outbox: a notice is something the shop
/// is told, never something it captures. With no connection this screen says
/// so rather than showing a stale list as if it were current.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  List<Map<String, dynamic>> _items = const [];
  bool _loading = true;
  bool _offline = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  int get _unread => _items.where((item) => item['read'] != true).length;

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic page =
          await state.api.get('/notifications', query: {'limit': '50'});
      if (!mounted) return;
      setState(() {
        _items = ((page as Map<String, dynamic>)['items'] as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        state.unreadNotifications = (page['unread'] as num?)?.toInt() ?? 0;
        _offline = false;
        _error = null;
        _loading = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _error = exception.isNetworkError ? null : exception.message;
        _loading = false;
      });
    }
  }

  /// Marking one read is optimistic: the row is the only thing it changes,
  /// and a failed call puts it back rather than leaving the screen lying.
  Future<void> _markRead(Map<String, dynamic> item) async {
    if (item['read'] == true) return;
    final state = AppScope.of(context);
    setState(() {
      item['read'] = true;
      // Counted down rather than recounted from the rows on screen: the
      // server's total covers more than the fifty this screen asked for.
      state.unreadNotifications =
          state.unreadNotifications > 0 ? state.unreadNotifications - 1 : 0;
    });
    try {
      await state.api.post('/notifications/${item['id']}/read');
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        item['read'] = false;
        state.unreadNotifications = state.unreadNotifications + 1;
        _error = exception.isNetworkError
            ? 'No connection — it is still unread.'
            : exception.message;
      });
    }
  }

  /// One call each, because the API marks one at a time. Stops at the first
  /// failure rather than reporting a tidy screen over a half-done job.
  Future<void> _markAllRead() async {
    setState(() => _busy = true);
    try {
      for (final item
          in _items.where((item) => item['read'] != true).toList()) {
        await _markRead(item);
        if (_error != null) break;
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          if (_unread > 0)
            TextButton(
              onPressed: _busy ? null : _markAllRead,
              child: const Text('Mark all read'),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _body(state),
      ),
    );
  }

  Widget _body(AppState state) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_offline) {
      return ListView(
        children: const [
          SizedBox(height: 80),
          EmptyState(
            icon: Icons.cloud_off,
            title: 'No connection',
            message: 'Notices are kept on the server. Pull down to try again '
                'once you are back online.',
          ),
        ],
      );
    }
    if (_items.isEmpty) {
      return ListView(
        children: [
          const SizedBox(height: 80),
          EmptyState(
            icon: Icons.notifications_none,
            title: _error ?? 'Nothing yet',
            message: _error == null
                ? 'Requests from your shop page, questions from buyers and '
                    'low-stock warnings land here.'
                : null,
          ),
        ],
      );
    }

    return ListView.separated(
      itemCount: _items.length + (_error == null ? 0 : 1),
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, index) {
        if (_error != null && index == 0) {
          return Material(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Text(
                _error!,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer,
                ),
              ),
            ),
          );
        }
        final item = _items[index - (_error == null ? 0 : 1)];
        final unread = item['read'] != true;
        return ListTile(
          leading: Icon(
            _iconFor(item['kind'] as String? ?? ''),
            color: unread
                ? Theme.of(context).colorScheme.primary
                : Theme.of(context).colorScheme.onSurfaceVariant,
          ),
          title: Text(
            item['title'] as String? ?? '',
            style: TextStyle(
              fontWeight: unread ? FontWeight.w600 : FontWeight.w400,
            ),
          ),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if ((item['body'] as String?)?.isNotEmpty ?? false)
                Text(item['body'] as String),
              Text(
                Money.dateTime(item['created_at']),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
          isThreeLine: (item['body'] as String?)?.isNotEmpty ?? false,
          trailing: unread
              ? Icon(Icons.circle,
                  size: 10, color: Theme.of(context).colorScheme.primary)
              : null,
          onTap: () => _markRead(item),
        );
      },
    );
  }

  /// A glance at the list should say what kind of thing happened.
  IconData _iconFor(String kind) {
    switch (kind) {
      case 'proforma_request':
        return Icons.request_quote_outlined;
      case 'proforma_waiting':
        return Icons.pending_actions_outlined;
      case 'proforma_response':
        return Icons.mark_chat_read_outlined;
      case 'new_enquiry':
        return Icons.help_outline;
      case 'payment_slip':
        return Icons.receipt_long_outlined;
      case 'low_stock':
        return Icons.inventory_2_outlined;
      case 'credit_reminder':
        return Icons.account_balance_wallet_outlined;
      case 'trial_expiry':
      case 'subscription_expiry':
        return Icons.schedule;
      case 'import_complete':
        return Icons.file_download_done_outlined;
      default:
        return Icons.notifications_none;
    }
  }
}
