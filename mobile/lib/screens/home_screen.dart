import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/stock.dart';
import '../widgets/common.dart';
import 'sales_history_screen.dart';
import 'stock_product_screen.dart';

/// Today's figures and what needs attention.
///
/// With no connection it shows what it can from the device and says so, rather
/// than showing a spinner or, worse, stale numbers presented as current.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? _dashboard;
  bool _loading = true;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic data = await state.api.get('/dashboard');
      if (!mounted) return;
      setState(() {
        _dashboard = Map<String, dynamic>.from(data as Map);
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

  /// One line for each kind of thing waiting, each opening where it is
  /// dealt with.  Nothing at all when nothing waits: an empty "to do" is
  /// one more thing to read.
  List<Widget> _waiting(BuildContext context, AppState state) {
    final theme = Theme.of(context);
    final navigator = Navigator.of(context);
    final rows = <Widget>[];

    void line(
      Key key,
      IconData icon,
      String title,
      String? subtitle,
      String route,
    ) {
      rows.add(ListTile(
        key: key,
        leading: Icon(icon, color: theme.colorScheme.primary),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: subtitle == null ? null : Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => navigator.pushNamed(route),
      ));
    }

    final orders = state.shopOrdersWaiting;
    final slips = state.shopSlipsToCheck;
    if (orders > 0) {
      line(
        const Key('homeOrders'),
        Icons.storefront_outlined,
        '${countOf(orders, 'online order')} ${orders == 1 ? 'needs' : 'need'} you',
        slips > 0
            ? '${countOf(slips, 'customer')} ${slips == 1 ? 'says' : 'say'} '
                'they have paid'
            : null,
        '/shop',
      );
    }
    if (state.shopQuestions > 0) {
      line(
        const Key('homeQuestions'),
        Icons.help_outline,
        '${countOf(state.shopQuestions, 'question')} from customers',
        null,
        '/shop',
      );
    }
    if (state.transfersNeedingMe > 0) {
      line(
        const Key('homeTransfers'),
        Icons.move_down_outlined,
        '${countOf(state.transfersNeedingMe, 'stock transfer')} to answer',
        null,
        '/stock/transfers',
      );
    }
    if (rows.isEmpty) return const [];
    return [
      const SectionTitle('Waiting for you'),
      Card(
        margin: const EdgeInsets.symmetric(horizontal: 12),
        clipBehavior: Clip.antiAlias,
        child: Column(children: rows),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final today = _dashboard?['today'] as Map<String, dynamic>?;
    final receivables = _dashboard?['receivables'] as Map<String, dynamic>?;
    final payables = _dashboard?['payables'] as Map<String, dynamic>?;
    // Only when there is something owed: a shop that pays on the spot has
    // no use for a tile saying it owes nothing.
    final owesSuppliers =
        payables != null && (Money.parse(payables['total_outstanding']) ?? 0) > 0;
    final lowStock = (_dashboard?['low_stock'] as List<dynamic>?) ?? const [];
    final maySeeSales = session?.can('sale:view') ?? false;
    final maySeeStock = session?.can('stock:view') ?? false;

    return RefreshIndicator(
      onRefresh: () async {
        await state.refresh();
        await _load();
      },
      child: ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  session?.tenantName ?? 'Estock',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                Text(
                  'Today, ${Money.date(DateTime.now())}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
          // What is waiting on whoever holds the phone, before the figures:
          // the figures say how the day went, this says what to do next.
          ..._waiting(context, state),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_offline && _dashboard == null)
            const EmptyState(
              icon: Icons.cloud_off,
              title: 'Today\'s figures need a connection',
              message:
                  'You can still record sales and look up stock. Figures update '
                  'when you are back online.',
            )
          else ...[
            if (today != null) ...[
              const SectionTitle('Today'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Wrap(
                  children: [
                    SizedBox(
                      width: _tileWidth(context),
                      child: StatTile(
                        label: 'Sales',
                        value: Money.format(today['net_sales'], currency: currency),
                        // Today's figure opens today's sales: the list it
                        // was added up from.
                        onTap: maySeeSales ? () => _openSales(context) : null,
                      ),
                    ),
                    SizedBox(
                      width: _tileWidth(context),
                      child: StatTile(
                        label: 'Sales made',
                        value: '${today['sale_count'] ?? 0}',
                        onTap: maySeeSales ? () => _openSales(context) : null,
                      ),
                    ),
                    SizedBox(
                      width: _tileWidth(context),
                      child: StatTile(
                        label: 'Items sold',
                        value: Money.quantity(today['items_sold']),
                      ),
                    ),
                    if (today['gross_profit'] != null)
                      SizedBox(
                        width: _tileWidth(context),
                        child: StatTile(
                          label: 'Gross profit',
                          value: Money.format(today['gross_profit'],
                              currency: currency),
                        ),
                      ),
                  ],
                ),
              ),
            ],
            if (receivables != null) ...[
              SectionTitle(
                'Money owed',
                trailing: TextButton(
                  onPressed: () => Navigator.of(context).pushNamed('/credit'),
                  child: const Text('See all'),
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Wrap(
                  children: [
                    SizedBox(
                      width: _tileWidth(context),
                      child: StatTile(
                        label: 'Customers owe you',
                        value: Money.format(receivables['total_outstanding'],
                            currency: currency),
                        note: owedBy(receivables),
                        onTap: () =>
                            Navigator.of(context).pushNamed('/credit'),
                      ),
                    ),
                    SizedBox(
                      width: _tileWidth(context),
                      child: StatTile(
                        label: 'Overdue',
                        value:
                            Money.format(receivables['overdue'], currency: currency),
                        tone: (Money.parse(receivables['overdue']) ?? 0) > 0
                            ? Theme.of(context).colorScheme.error
                            : null,
                        onTap: () =>
                            Navigator.of(context).pushNamed('/credit'),
                      ),
                    ),
                    // The other side of the same book: deliveries taken
                    // on credit, which the phone can now record and so
                    // has to be able to show.
                    if (owesSuppliers)
                      SizedBox(
                        width: _tileWidth(context),
                        child: StatTile(
                          key: const Key('homePayables'),
                          label: 'You owe suppliers',
                          value: Money.format(payables['total_outstanding'],
                              currency: currency),
                          note: owedBy(payables, toSuppliers: true),
                          onTap: () => Navigator.of(context)
                              .pushNamed('/credit/payables'),
                        ),
                      ),
                  ],
                ),
              ),
            ],
            SectionTitle(
              'Low stock',
              trailing: lowStock.isEmpty || !maySeeStock
                  ? null
                  : TextButton(
                      onPressed: () =>
                          Navigator.of(context).pushNamed('/stock/low'),
                      child: const Text('See all'),
                    ),
            ),
            if (lowStock.isEmpty)
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text('Nothing needs restocking right now.'),
              )
            else
              // The same product can be short at one branch and fine at
              // another; without the branch they read as the same row twice.
              // The worst few, not the whole list: the list has a screen of
              // its own, and five rows here leave the rest of today in
              // sight.
              ...lowStock.take(5).map((item) {
                final row = Map<String, dynamic>.from(item as Map);
                final branch = row['branch_name'] as String?;
                final productId = row['product_id'] as String?;
                final unit = state.products
                    .where((p) => p.id == productId)
                    .map((p) => p.unitOfMeasure)
                    .firstOrNull;
                return ListTile(
                  title: Text(row['name'] as String? ?? ''),
                  subtitle: Text(
                    [
                      if (state.hasManyBranches && branch != null) branch,
                      '${Money.quantity(row['quantity'])} '
                          '${unit ?? ''} left'.replaceAll('  ', ' '),
                    ].join(' · '),
                  ),
                  trailing: StatusChip(
                    status: row['severity'] as String? ?? '',
                    label: stockLabel(row['severity'] as String? ?? ''),
                  ),
                  // A short shelf opens the product: where the rest of it
                  // is, and what can be done about it.
                  onTap: productId == null || !maySeeStock
                      ? null
                      : () => Navigator.of(context).push<void>(
                            MaterialPageRoute(
                              builder: (_) => StockProductScreen(
                                productId: productId,
                                branchId: state.hasManyBranches
                                    ? row['branch_id'] as String?
                                    : null,
                              ),
                            ),
                          ),
                );
              }),
          ],
        ],
      ),
    );
  }

  void _openSales(BuildContext context) => Navigator.of(context).push<void>(
        MaterialPageRoute(builder: (_) => const SalesHistoryScreen()),
      );

  /// Two tiles per row on a phone, more on a tablet.
  double _tileWidth(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width - 24;
    final columns = width > 600 ? 4 : 2;
    return width / columns;
  }
}

/// Who the money is owed by, in people where the server says how many and
/// in sales where it does not.
///
/// It used to read "6 balance(s)": a count of rows, with the plural left
/// for the reader to work out.  Three unpaid sales to one customer are one
/// person to chase.
String owedBy(Map<String, dynamic> summary, {bool toSuppliers = false}) {
  final people = (summary['party_count'] as num?)?.toInt() ?? 0;
  final sales = (summary['transaction_count'] as num?)?.toInt() ?? 0;
  if (toSuppliers) {
    if (people > 0) {
      return people == 1 ? 'to 1 supplier' : 'to $people suppliers';
    }
    return sales == 1 ? '1 unpaid delivery' : '$sales unpaid deliveries';
  }
  if (people > 0) {
    return people == 1 ? 'from 1 customer' : 'from $people customers';
  }
  return sales == 1 ? '1 unpaid sale' : '$sales unpaid sales';
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
