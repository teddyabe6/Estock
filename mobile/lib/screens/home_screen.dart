import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
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
      Color colour,
      String title,
      String? subtitle,
      String route,
    ) {
      rows.add(ListTile(
        key: key,
        leading: IconBadge(icon, colour: colour),
        title: Text(title),
        subtitle: subtitle == null ? null : Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => navigator.pushNamed(route),
      ));
    }

    final palette = context.palette;

    final orders = state.shopOrdersWaiting;
    final slips = state.shopSlipsToCheck;
    if (orders > 0) {
      line(
        const Key('homeOrders'),
        Icons.storefront_outlined,
        palette.warn,
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
        palette.info,
        '${countOf(state.shopQuestions, 'question')} from customers',
        null,
        '/shop',
      );
    }
    if (state.transfersNeedingMe > 0) {
      line(
        const Key('homeTransfers'),
        Icons.move_down_outlined,
        theme.colorScheme.primary,
        '${countOf(state.transfersNeedingMe, 'stock transfer')} to answer',
        null,
        '/stock/transfers',
      );
    }
    if (rows.isEmpty) return const [];
    return [
      const SectionTitle('Waiting for you'),
      TileGroup(dividerIndent: 70, children: rows),
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
          // Who and where, and how today is going, in one place at the top.
          _hero(context, state, today, currency, maySeeSales),
          // What is waiting on whoever holds the phone, straight after: the
          // figures say how the day went, this says what to do next.
          ..._waiting(context, state),
          if (_loading)
            const SizedBox.shrink()
          else if (_offline && _dashboard == null)
            const EmptyState(
              icon: Icons.cloud_off,
              title: 'Today\'s figures need a connection',
              message:
                  'You can still record sales and look up stock. Figures update '
                  'when you are back online.',
            )
          else ...[
            if (receivables != null) ...[
              SectionTitle(
                'Money owed',
                trailing: TextButton(
                  onPressed: () => Navigator.of(context).pushNamed('/credit'),
                  child: const Text('See all'),
                ),
              ),
              _grid(context, [
                StatTile(
                  icon: Icons.account_balance_wallet_outlined,
                  label: 'Customers owe you',
                  value: Money.format(receivables['total_outstanding'],
                      currency: currency),
                  note: owedBy(receivables),
                  onTap: () => Navigator.of(context).pushNamed('/credit'),
                ),
                StatTile(
                  icon: Icons.schedule_rounded,
                  accent: (Money.parse(receivables['overdue']) ?? 0) > 0
                      ? Theme.of(context).colorScheme.error
                      : context.palette.muted,
                  label: 'Overdue',
                  value: Money.format(receivables['overdue'], currency: currency),
                  tone: (Money.parse(receivables['overdue']) ?? 0) > 0
                      ? Theme.of(context).colorScheme.error
                      : null,
                  onTap: () => Navigator.of(context).pushNamed('/credit'),
                ),
                // The other side of the same book: deliveries taken on
                // credit, which the phone can now record and so has to be
                // able to show.
                if (owesSuppliers)
                  StatTile(
                    key: const Key('homePayables'),
                    icon: Icons.local_shipping_outlined,
                    accent: context.palette.warn,
                    label: 'You owe suppliers',
                    value: Money.format(payables['total_outstanding'],
                        currency: currency),
                    note: owedBy(payables, toSuppliers: true),
                    onTap: () =>
                        Navigator.of(context).pushNamed('/credit/payables'),
                  ),
              ]),
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
              TileGroup(
                children: [
                  ListTile(
                    leading: IconBadge(
                      Icons.check_rounded,
                      colour: context.palette.good,
                    ),
                    title: const Text('Nothing needs restocking right now.'),
                  ),
                ],
              )
            else
              // The same product can be short at one branch and fine at
              // another; without the branch they read as the same row twice.
              // The worst few, not the whole list: the list has a screen of
              // its own, and five rows here leave the rest of today in
              // sight.
              TileGroup(
                dividerIndent: 70,
                children: lowStock.take(5).map((item) {
                final row = Map<String, dynamic>.from(item as Map);
                final branch = row['branch_name'] as String?;
                final productId = row['product_id'] as String?;
                final unit = state.products
                    .where((p) => p.id == productId)
                    .map((p) => p.unitOfMeasure)
                    .firstOrNull;
                final severity = row['severity'] as String? ?? '';
                return ListTile(
                  leading: IconBadge(
                    Icons.inventory_2_outlined,
                    colour: EstockTheme.statusColour(
                      severity,
                      Theme.of(context).colorScheme,
                    ),
                  ),
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
              }).toList(),
              ),
          ],
        ],
      ),
    );
  }

  /// The top of the screen: a greeting, whose shop it is, and today's
  /// takings large enough to read from across the counter, with the
  /// three figures that explain them underneath. Opens today's sales.
  Widget _hero(
    BuildContext context,
    AppState state,
    Map<String, dynamic>? today,
    String currency,
    bool maySeeSales,
  ) {
    final theme = Theme.of(context);
    final palette = context.palette;
    final session = state.session;
    final firstName = (session?.fullName ?? '').trim().split(' ').first;
    final hour = DateTime.now().hour;
    final greeting = hour < 12
        ? 'Good morning'
        : hour < 17
            ? 'Good afternoon'
            : 'Good evening';
    final soft = Colors.white.withValues(alpha: 0.78);

    Widget figure(String value, String label) => Expanded(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    value,
                    style: theme.textTheme.titleMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                      fontFeatures: EstockTheme.figures,
                    ),
                  ),
                ),
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall?.copyWith(color: soft),
                ),
              ],
            ),
          ),
        );

    final figures = today == null
        ? const <Widget>[]
        : [
            figure('${today['sale_count'] ?? 0}', 'sales made'),
            figure(Money.quantity(today['items_sold']), 'items sold'),
            if (today['gross_profit'] != null)
              figure(
                Money.format(today['gross_profit'], currency: currency),
                'profit',
              ),
          ];

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [palette.heroStart, palette.heroEnd],
        ),
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: palette.heroEnd.withValues(alpha: 0.25),
            blurRadius: 20,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(24),
          onTap: today != null && maySeeSales ? () => _openSales(context) : null,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  firstName.isEmpty ? greeting : '$greeting, $firstName',
                  style: theme.textTheme.labelMedium?.copyWith(color: soft),
                ),
                const SizedBox(height: 2),
                Text(
                  session?.tenantName ?? 'Estock',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleLarge?.copyWith(color: Colors.white),
                ),
                Text(
                  'Today, ${Money.date(DateTime.now())}',
                  style: theme.textTheme.bodySmall?.copyWith(color: soft),
                ),
                if (today != null) ...[
                  const SizedBox(height: 18),
                  Text(
                    'SALES TODAY',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: soft,
                      letterSpacing: 0.8,
                    ),
                  ),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      Money.format(today['net_sales'], currency: currency),
                      style: theme.textTheme.displaySmall?.copyWith(
                        color: Colors.white,
                        fontFeatures: EstockTheme.figures,
                      ),
                    ),
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      for (var i = 0; i < figures.length; i++) ...[
                        if (i > 0) const SizedBox(width: 8),
                        figures[i],
                      ],
                    ],
                  ),
                ] else if (_loading) ...[
                  const SizedBox(height: 18),
                  const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.4,
                      color: Colors.white,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _openSales(BuildContext context) => Navigator.of(context).push<void>(
        MaterialPageRoute(builder: (_) => const SalesHistoryScreen()),
      );

  /// Two tiles to a row on a phone, four on a tablet, each row as tall as
  /// its tallest tile so the cards line up.
  Widget _grid(BuildContext context, List<Widget> tiles) {
    final columns = MediaQuery.sizeOf(context).width > 624 ? 4 : 2;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 11),
      child: Column(
        children: [
          for (var i = 0; i < tiles.length; i += columns)
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var j = i; j < i + columns; j++)
                    Expanded(
                      child: j < tiles.length ? tiles[j] : const SizedBox.shrink(),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
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
