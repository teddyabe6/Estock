import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/sale.dart';
import '../widgets/common.dart';
import 'sale_detail_screen.dart';

/// What has been sold, so a sale can be found again.
///
/// The till is the tab; this is behind it, because selling is what a counter
/// does all day and looking a sale up is what it does when a customer comes
/// back — for a receipt, for a refund, or to settle an argument about what
/// was paid.
///
/// It lives on the server: a sale still in the outbox has no number yet and
/// is listed under "Waiting to sync", where it belongs.
class SalesHistoryScreen extends StatefulWidget {
  const SalesHistoryScreen({super.key});

  @override
  State<SalesHistoryScreen> createState() => _SalesHistoryScreenState();
}

/// How far back to look. Today first: most of the time the sale somebody is
/// looking for happened an hour ago.
enum _Period {
  today('Today', 0),
  week('7 days', 6),
  month('30 days', 29),
  all('All', null);

  const _Period(this.label, this.daysBack);

  final String label;
  final int? daysBack;
}

const _pageSize = 100;

class _SalesHistoryScreenState extends State<SalesHistoryScreen> {
  final _search = TextEditingController();

  List<Sale> _sales = const [];
  _Period _period = _Period.today;
  String? _branchId;
  bool _includeVoided = false;
  int _total = 0;
  bool _loading = true;
  bool _offline = false;
  String? _error;
  Timer? _typing;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _typing?.cancel();
    _search.dispose();
    super.dispose();
  }

  /// Search once somebody stops typing, not once per letter.
  void _searchLater() {
    _typing?.cancel();
    _typing = Timer(const Duration(milliseconds: 350), () {
      if (mounted) _load();
    });
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final state = AppScope.of(context);
    final days = _period.daysBack;
    try {
      final needle = _search.text.trim();
      final dynamic page = await state.api.get('/sales', query: {
        'limit': '$_pageSize',
        if (_includeVoided) 'include_voided': 'true',
        if (_branchId != null) 'branch_id': _branchId!,
        // A name or a number is the whole search somebody can do from
        // memory, and it is worth more than the window it happened in:
        // "Selam, some time last month" beats scrolling through thirty
        // days of receipts.
        if (needle.isNotEmpty) 'q': needle,
        if (days != null && needle.isEmpty) 'date_from': _isoDate(days),
      });
      if (!mounted) return;
      final payload = Map<String, dynamic>.from(page as Map);
      setState(() {
        _sales = (payload['items'] as List<dynamic>)
            .map((item) => Sale.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
        _total = (payload['total'] as num?)?.toInt() ?? _sales.length;
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

  /// The first day of the window, in the shop's own calendar.
  String _isoDate(int daysBack) {
    final day = DateTime.now().subtract(Duration(days: daysBack));
    return '${day.year.toString().padLeft(4, '0')}-'
        '${day.month.toString().padLeft(2, '0')}-'
        '${day.day.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final branches = state.branches;
    final currency = state.session?.currency ?? 'ETB';
    final shown = _sales.fold<double>(0, (sum, sale) => sum + sale.total);

    return Scaffold(
      appBar: AppBar(title: const Text('Sales')),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: TextField(
                controller: _search,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: 'Customer or sale number',
                  prefixIcon: const Icon(Icons.search),
                  isDense: true,
                  suffixIcon: _search.text.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.close),
                          onPressed: () {
                            _search.clear();
                            _load();
                          },
                        ),
                ),
                onChanged: (_) {
                  setState(() {});
                  _searchLater();
                },
                onSubmitted: (_) => _load(),
              ),
            ),
            SizedBox(
              // Tall enough for a chip's 48-pixel tap target.
              height: 52,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  for (final period in _Period.values)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text(period.label),
                        showCheckmark: false,
                        selected: _period == period,
                        onSelected: (_) {
                          setState(() => _period = period);
                          _load();
                        },
                      ),
                    ),
                  const VerticalDivider(width: 17, indent: 10, endIndent: 10),
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: FilterChip(
                      label: const Text('With voided'),
                      selected: _includeVoided,
                      onSelected: (value) {
                        setState(() => _includeVoided = value);
                        _load();
                      },
                    ),
                  ),
                  if (branches.length > 1) ...[
                    const VerticalDivider(width: 17, indent: 10, endIndent: 10),
                    _branchChip(label: 'All branches', id: null),
                    for (final branch in branches)
                      _branchChip(label: branch.name, id: branch.id),
                  ],
                ],
              ),
            ),
            if (!_loading && !_offline && _sales.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  // The figure is the sum of what is on screen, said plainly,
                  // rather than a total the page cannot actually see.
                  [
                    _total > _sales.length
                        ? 'First ${_sales.length} of $_total · '
                            '${Money.format(shown, currency: currency)} shown'
                        : '${_sales.length} sale'
                            '${_sales.length == 1 ? '' : 's'} · '
                            '${Money.format(shown, currency: currency)}',
                    // A search looks everywhere, so the period chips are
                    // not what is on screen and must not look as if they
                    // were.
                    if (_search.text.trim().isNotEmpty) 'any date',
                  ].join(' · '),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            Expanded(child: _body(currency)),
          ],
        ),
      ),
    );
  }

  Widget _branchChip({required String label, required String? id}) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: ChoiceChip(
        label: Text(label),
        showCheckmark: false,
        selected: _branchId == id,
        onSelected: (_) {
          setState(() => _branchId = id);
          _load();
        },
      ),
    );
  }

  Widget _body(String currency) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_offline) {
      return const EmptyState(
        icon: Icons.cloud_off,
        title: 'Sales history needs a connection',
        message:
            'You can still sell: anything recorded offline waits on this '
            'phone and joins the history once it syncs.',
      );
    }
    if (_sales.isEmpty) {
      return EmptyState(
        icon: Icons.receipt_long_outlined,
        title: _period == _Period.all
            ? 'No sales yet'
            : 'Nothing sold in this period',
        message: _period == _Period.all
            ? 'Your first sale will appear here.'
            : 'Try a longer period.',
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        itemCount: _sales.length,
        itemBuilder: (context, index) => _row(_sales[index], currency),
      ),
    );
  }

  /// What was in it, short enough to read at a glance.
  String? _what(Sale sale) {
    if (sale.lines.isEmpty) return null;
    final first = sale.lines.first.description;
    final rest = sale.lines.length - 1;
    return rest == 0 ? first : '$first + $rest more';
  }

  Widget _row(Sale sale, String currency) {
    final theme = Theme.of(context);
    // Lead with whatever tells one sale from another: whose it was, or
    // failing that what was in it.  A number and a time identify a sale
    // only to somebody who already knows which one they want, and a
    // column of "Walk-in customer" tells them nothing at all.
    final what = _what(sale);
    final headline = sale.customerName ?? what ?? sale.number;
    final notes = [
      sale.number,
      Money.dateTime(sale.soldAt),
      if (what != null && headline != what) what,
      if (sale.balanceDue > 0) '${Money.amount(sale.balanceDue)} on credit',
      if (sale.returnedTotal > 0) '${Money.amount(sale.returnedTotal)} returned',
    ];

    return ListTile(
      title: Text(headline, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(
        notes.join(' · '),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            Money.format(sale.total, currency: currency),
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              decoration: sale.isVoided ? TextDecoration.lineThrough : null,
              color: sale.isVoided ? theme.colorScheme.onSurfaceVariant : null,
            ),
          ),
          if (sale.isVoided) StatusChip(status: sale.status),
        ],
      ),
      onTap: () async {
        await Navigator.of(context).push<void>(
          MaterialPageRoute(builder: (_) => SaleDetailScreen(saleId: sale.id)),
        );
        // Voiding or taking goods back changes the row that was tapped.
        if (mounted) await _load();
      },
    );
  }
}
