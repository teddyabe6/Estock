import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../models/product.dart';
import '../models/stock.dart';
import '../widgets/common.dart';
import 'stock_adjust_screen.dart';
import 'stock_receive_screen.dart';

/// What the ledger calls each way stock moves, in a shopkeeper's words.
const _reasons = <String, String>{
  'opening': 'Counted',
  'purchase': 'Delivery',
  'sale': 'Sold',
  'sale_return': 'Came back from a customer',
  'purchase_return': 'Sent back to the supplier',
  'transfer_out': 'Sent to another branch',
  'transfer_in': 'Arrived from another branch',
  'adjustment': 'Corrected',
  'count_adjustment': 'Counted',
  'damage': 'Broke or went off',
  'loss': 'Lost or stolen',
  'sale_void': 'Sale cancelled',
};

/// One product: how much, where, what can be done about it, and its story.
///
/// Tapping a product used to answer only "where is the rest of it".  The
/// question that follows a wrong figure is "what happened to it" — and the
/// ledger has always known: every sale, delivery, count and breakage, with
/// who and when.  This is where the phone finally says so, and where the
/// things somebody does to one product start from the product itself
/// rather than from a menu they have to find first.
class StockProductScreen extends StatefulWidget {
  const StockProductScreen({super.key, required this.productId, this.branchId});

  final String productId;

  /// The branch in view when this was opened; null for all of them.
  final String? branchId;

  @override
  State<StockProductScreen> createState() => _StockProductScreenState();
}

class _StockProductScreenState extends State<StockProductScreen> {
  static const _page = 20;

  List<Map<String, dynamic>> _moves = const [];
  int _total = 0;
  bool _loading = true;
  bool _loadingMore = false;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load({bool more = false}) async {
    setState(() => more ? _loadingMore = true : _loading = true);
    final state = AppScope.of(context);
    try {
      final dynamic page = await state.api.get('/stock/movements', query: {
        'product_id': widget.productId,
        if (widget.branchId != null) 'branch_id': widget.branchId!,
        'limit': '$_page',
        'offset': '${more ? _moves.length : 0}',
      });
      if (!mounted) return;
      final payload = Map<String, dynamic>.from(page as Map);
      final rows = (payload['items'] as List<dynamic>)
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      setState(() {
        _moves = more ? [..._moves, ...rows] : rows;
        _total = (payload['total'] as num?)?.toInt() ?? _moves.length;
        _offline = false;
        _loading = false;
        _loadingMore = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _loading = false;
        _loadingMore = false;
      });
    }
  }

  /// Open one of the things that change stock, and catch up afterwards.
  Future<void> _go(Widget screen) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => screen),
    );
    if (mounted && (changed ?? false)) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final product =
        state.products.where((p) => p.id == widget.productId).firstOrNull;

    return Scaffold(
      appBar: AppBar(title: Text(product?.name ?? 'Product')),
      body: SafeArea(
        child: product == null
            ? const EmptyState(
                icon: Icons.search_off,
                title: 'Not in the catalogue',
                message: 'This product is no longer on this phone.',
              )
            : RefreshIndicator(
                onRefresh: () async {
                  await state.refresh();
                  await _load();
                },
                child: _body(context, state, product),
              ),
      ),
    );
  }

  Widget _body(BuildContext context, AppState state, Product product) {
    final theme = Theme.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final stock = state.branchStock;
    final spread = stock.forProduct(product.id);
    final unit = product.unitOfMeasure;
    final branchId = widget.branchId;
    final many = stock.branches.length > 1;

    final here = spread == null
        ? Money.parse(product.quantityOnHand) ?? 0
        : spread.at(branchId);
    final status = spread == null
        ? (product.stockStatus ?? 'ok')
        : stock.statusFor(product.id, branchId);
    final where = branchId == null
        ? (many ? 'across ${stock.branches.length} branches' : 'on hand')
        : 'at ${stock.branches.where((b) => b.id == branchId).map((b) => b.name).firstOrNull ?? 'this branch'}';

    final mayReceive = (session?.can('purchase:create') ?? false) &&
        (session?.can('stock:receive') ?? false);
    final mayAdjust = session?.can('stock:adjust') ?? false;
    final mayAsk = (session?.can('stock:transfer') ?? false) && many;

    return ListView(
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    Money.quantity(here),
                    style: theme.textTheme.displaySmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: status == 'ok'
                          ? null
                          : EstockTheme.statusColour(
                              status, theme.colorScheme),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text(
                      '$unit $where',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                [
                  'Sells for '
                      '${Money.format(product.defaultVariant?.sellingPrice, currency: currency)}',
                  if (product.categoryName != null) product.categoryName!,
                ].join(' · '),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
        // What somebody does to one product, starting from the product.
        // Three across: stacked full-width they pushed everything worth
        // reading off the first screen.
        if (mayReceive || mayAdjust || mayAsk)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            // One height for all three, whichever label runs to two lines.
            child: IntrinsicHeight(
              child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (mayReceive)
                  _ActionTile(
                    icon: Icons.inventory_outlined,
                    label: 'Delivery',
                    onTap: () => _go(StockReceiveScreen(
                      productId: product.id,
                      branchId: branchId,
                    )),
                  ),
                if (mayAdjust)
                  _ActionTile(
                    icon: Icons.report_gmailerrorred_outlined,
                    label: 'Broke or missing',
                    onTap: () => _go(StockAdjustScreen(
                      productId: product.id,
                      branchId: branchId,
                    )),
                  ),
                if (mayAsk)
                  _ActionTile(
                    icon: Icons.swap_horiz,
                    label: 'Ask a branch',
                    onTap: () => Navigator.of(context).pushNamed(
                      '/stock/ask',
                      arguments: product.id,
                    ),
                  ),
              ],
              ),
            ),
          ),
        if (spread != null && many) ...[
          const Divider(height: 1),
          _section(context, 'Where it is'),
          for (final branch in stock.branches)
            _branchRow(context, stock, product, branch, spread),
        ],
        const Divider(height: 1),
        _section(context, 'What happened to it'),
        if (_loading)
          const Padding(
            padding: EdgeInsets.all(24),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_offline)
          _muted(context, 'The history needs a connection.')
        else if (_moves.isEmpty)
          _muted(context, 'Nothing has happened to it yet.')
        else ...[
          for (final move in _moves) _moveRow(context, move, unit, many),
          if (_moves.length < _total)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
              child: OutlinedButton(
                onPressed: _loadingMore ? null : () => _load(more: true),
                child: Text(_loadingMore ? 'Loading…' : 'Show earlier'),
              ),
            ),
        ],
      ],
    );
  }

  Widget _branchRow(
    BuildContext context,
    StockByBranch stock,
    Product product,
    StockBranch branch,
    StockSpread spread,
  ) {
    final theme = Theme.of(context);
    final carried = spread.carriedAt(branch.id);
    final status = stock.statusFor(product.id, branch.id);
    final atHand = branch.id == widget.branchId;
    return ListTile(
      dense: true,
      title: Text(
        atHand ? '${branch.name} (here)' : branch.name,
        style: atHand ? const TextStyle(fontWeight: FontWeight.w700) : null,
      ),
      trailing: !carried
          ? Text(
              'does not stock it',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            )
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (status != 'ok') ...[
                  StatusChip(status: status, label: stockLabel(status)),
                  const SizedBox(width: 8),
                ],
                Text(
                  Money.quantity(spread.at(branch.id)),
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ],
            ),
    );
  }

  /// One line of the product's story: what, how many, and what was left.
  Widget _moveRow(
    BuildContext context,
    Map<String, dynamic> move,
    String unit,
    bool many,
  ) {
    final theme = Theme.of(context);
    final quantity = Money.parse(move['quantity']) ?? 0;
    final came = quantity > 0;
    final reason = move['reason'] as String? ?? '';
    final note = move['note'] as String?;
    // Counting a shelf goes on the ledger as an opening balance when the
    // figure goes up and as a correction when it goes down, each carrying
    // a note the system wrote.  To whoever did the counting it was one
    // thing both times.
    final counted = (note ?? '').startsWith('Opening stock for');
    return ListTile(
      dense: true,
      title: Text(
        counted
            ? 'Counted'
            : _reasons[reason] ?? reason.replaceAll('_', ' '),
      ),
      subtitle: Text(
        [
          Money.dateTime(move['occurred_at']),
          if (many && move['branch_name'] != null) '${move['branch_name']}',
          if (move['by_name'] != null) '${move['by_name']}',
          // The system's own notes ("Purchase P-2026-000002") say again
          // what the title said; a person's note says something new.
          if (note != null &&
              note.isNotEmpty &&
              !counted &&
              note != _reasons[reason] &&
              const {'adjustment', 'damage', 'loss'}.contains(reason))
            '“$note”',
        ].join(' · '),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            '${came ? '+' : '−'}${Money.quantity(quantity.abs())}',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: came
                  ? EstockTheme.statusColour('ok', theme.colorScheme)
                  : theme.colorScheme.error,
            ),
          ),
          Text(
            '${Money.quantity(move['balance_after'])} left',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }

  Widget _section(BuildContext context, String label) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
        child: Text(label, style: Theme.of(context).textTheme.titleSmall),
      );

  Widget _muted(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
        child: Text(
          text,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
      );
}

/// One thing to do to the product: an icon over a word or two.
class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Material(
          color: theme.colorScheme.secondaryContainer,
          borderRadius: BorderRadius.circular(12),
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(icon, color: theme.colorScheme.onSecondaryContainer),
                  const SizedBox(height: 4),
                  Text(
                    label,
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelMedium?.copyWith(
                      color: theme.colorScheme.onSecondaryContainer,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
