import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';

/// The online shop: what is published, and enquiries waiting for an answer.
class ShopScreen extends StatefulWidget {
  const ShopScreen({super.key});

  @override
  State<ShopScreen> createState() => _ShopScreenState();
}

class _ShopScreenState extends State<ShopScreen> {
  Map<String, dynamic>? _store;
  List<Map<String, dynamic>> _enquiries = const [];
  bool _loading = true;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    if (!(state.session?.can('shop:view') ?? false)) {
      setState(() => _loading = false);
      return;
    }
    try {
      final dynamic store = await state.api.get('/shop/settings');
      final dynamic page =
          await state.api.get('/shop/enquiries', query: {'limit': '20'});
      if (!mounted) return;
      setState(() {
        _store = Map<String, dynamic>.from(store as Map);
        _enquiries = ((page as Map<String, dynamic>)['items'] as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _offline = false;
        _loading = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final published = state.products.where((p) => p.isPublished).length;

    if (!(state.session?.can('shop:view') ?? false)) {
      return const EmptyState(
        icon: Icons.lock_outline,
        title: 'Not available for your role',
        message: 'Ask an owner or manager if you need access to the online shop.',
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        children: [
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_offline)
            const EmptyState(
              icon: Icons.cloud_off,
              title: 'The shop needs a connection',
              message: 'Enquiries and shop settings load when you are online.',
            )
          else ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            _store?['display_name'] as String? ?? 'Your shop',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                        ),
                        StatusChip(
                          status: (_store?['is_published'] as bool? ?? false)
                              ? 'ok'
                              : 'warning',
                          label: (_store?['is_published'] as bool? ?? false)
                              ? 'live'
                              : 'not published',
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text('$published product(s) published'),
                    if (_store?['public_url'] != null) ...[
                      const SizedBox(height: 6),
                      SelectableText(
                        _store!['public_url'] as String,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.primary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            SectionTitle('Enquiries (${_enquiries.length})'),
            if (_enquiries.isEmpty)
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 0, 16, 16),
                child: Text('No enquiries yet.'),
              )
            else
              ..._enquiries.map((row) => ListTile(
                    title: Text(row['contact_name'] as String? ?? ''),
                    subtitle: Text(
                      [
                        row['contact_phone'],
                        if (row['message'] != null) row['message'],
                      ].whereType<String>().join(' · '),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        StatusChip(status: row['status'] as String? ?? 'new'),
                        Text(
                          Money.dateTime(row['created_at']),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  )),
          ],
        ],
      ),
    );
  }
}
