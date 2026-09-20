import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';

/// Receivables: who owes what, and what is overdue.
///
/// Credit balances come from the server. They are not cached for offline use:
/// showing a stale balance while someone is deciding whether to extend more
/// credit would be worse than showing nothing.
class CreditScreen extends StatefulWidget {
  const CreditScreen({super.key});

  @override
  State<CreditScreen> createState() => _CreditScreenState();
}

class _CreditScreenState extends State<CreditScreen> {
  Map<String, dynamic>? _summary;
  List<Map<String, dynamic>> _items = const [];
  String _view = 'outstanding';
  bool _loading = true;
  bool _offline = false;

  static const _views = <(String, String)>[
    ('outstanding', 'Outstanding'),
    ('overdue', 'Overdue'),
    ('due_soon', 'Due soon'),
    ('paid', 'Paid'),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final state = AppScope.of(context);
    try {
      final dynamic summary =
          await state.api.get('/credit/summary', query: {'kind': 'receivable'});
      final dynamic page = await state.api.get(
        '/credit/transactions',
        query: {'kind': 'receivable', 'view': _view, 'limit': '100'},
      );
      if (!mounted) return;
      setState(() {
        _summary = Map<String, dynamic>.from(summary as Map);
        _items = ((page as Map<String, dynamic>)['items'] as List<dynamic>)
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
    final currency = state.session?.currency ?? 'ETB';

    return Scaffold(
      appBar: AppBar(title: const Text('Credit')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            if (_summary != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: StatTile(
                        label: 'Owed to you',
                        value: Money.format(_summary!['total_outstanding'],
                            currency: currency),
                        note: '${_summary!['transaction_count']} balance(s)',
                      ),
                    ),
                    Expanded(
                      child: StatTile(
                        label: 'Overdue',
                        value:
                            Money.format(_summary!['overdue'], currency: currency),
                        tone: (Money.parse(_summary!['overdue']) ?? 0) > 0
                            ? Theme.of(context).colorScheme.error
                            : null,
                      ),
                    ),
                  ],
                ),
              ),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Row(
                children: _views
                    .map((entry) => Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: ChoiceChip(
                            label: Text(entry.$2),
                            selected: _view == entry.$1,
                            onSelected: (_) {
                              setState(() => _view = entry.$1);
                              _load();
                            },
                          ),
                        ))
                    .toList(),
              ),
            ),
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(32),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_offline)
              const EmptyState(
                icon: Icons.cloud_off,
                title: 'Credit needs a connection',
                message:
                    'Balances are not stored on the phone, so they are never '
                    'shown out of date.',
              )
            else if (_items.isEmpty)
              const EmptyState(
                icon: Icons.receipt_long_outlined,
                title: 'Nothing here',
                message: 'No balances match this view.',
              )
            else
              ..._items.map((row) => ListTile(
                    title: Text(
                      row['counterparty_name'] as String? ?? 'Not named',
                    ),
                    subtitle: Text(
                      '${row['reference']} · '
                      '${Money.dueLabel(row['due_date'] as String?, row['is_overdue'] as bool? ?? false, row['days_overdue'] as int?)}',
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          Money.format(row['balance'], currency: currency),
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        StatusChip(status: row['status'] as String? ?? ''),
                      ],
                    ),
                  )),
          ],
        ),
      ),
    );
  }
}
