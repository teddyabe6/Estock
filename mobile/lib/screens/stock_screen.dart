import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../models/product.dart';
import '../models/session.dart';
import '../widgets/common.dart';

/// What is on the shelves, branch by branch.
///
/// The one question this screen exists to answer is "how many have we got",
/// asked on the shop floor with a customer waiting — so it is served from the
/// device, it is one tap from the bottom bar, and the figure is the largest
/// thing on the row.
///
/// For a shop with one branch that is all it is.  For a shop with several,
/// the figure has to say *which* branch, or it is worse than no figure at
/// all: 114 across the business is no comfort to the branch holding none of
/// them.  The chips pick the branch; tapping a product says where the rest
/// of it is.
/// The two jobs on this tab that are not looking something up: answering a
/// request, and counting a branch.  They sit in the app bar rather than above
/// the list, because the list is what the tab is for and every row of chrome
/// above it is a row of stock somebody cannot see.
List<Widget> stockTabActions(BuildContext context, AppState state) {
  final session = state.session;
  if (session == null) return const [];
  return [
    if (session.can('stock:transfer') && state.branches.length > 1)
      IconButton(
        tooltip: 'Between branches',
        icon: state.transfersNeedingMe > 0
            ? Badge.count(
                count: state.transfersNeedingMe,
                child: const Icon(Icons.local_shipping_outlined),
              )
            : const Icon(Icons.local_shipping_outlined),
        onPressed: () => Navigator.of(context).pushNamed('/stock/transfers'),
      ),
    if (session.can('stock:adjust'))
      IconButton(
        tooltip: 'Count stock',
        icon: const Icon(Icons.fact_check_outlined),
        onPressed: () => Navigator.of(context).pushNamed('/stock/count'),
      ),
  ];
}

class StockScreen extends StatefulWidget {
  const StockScreen({super.key});

  @override
  State<StockScreen> createState() => _StockScreenState();
}

class _StockScreenState extends State<StockScreen> {
  final _search = TextEditingController();
  bool _lowOnly = false;

  /// Null means every branch together.  A user assigned to one branch starts
  /// on it: that is the shelf they are standing in front of.
  String? _branchId;
  bool _pickedABranch = false;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final branches = state.branches;
    final many = branches.length > 1;

    // Settled once, from the branches the user can see, and theirs to change
    // after that.
    if (!_pickedABranch && !many) {
      _branchId = branches.length == 1 ? branches.first.id : null;
    }

    final products = _visible(state);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: TextField(
            controller: _search,
            textInputAction: TextInputAction.search,
            decoration: const InputDecoration(
              hintText: 'Search stock',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (_) => setState(() {}),
          ),
        ),
        _filters(context, branches, many),
        _countPrompt(context, state),
        Expanded(
          child: products.isEmpty
              ? _empty(state)
              : RefreshIndicator(
                  onRefresh: state.refresh,
                  child: ListView.builder(
                    // One past the products: the last row says how fresh the
                    // figures above it are, which matters most offline.
                    itemCount: products.length + 1,
                    itemBuilder: (context, index) => index == products.length
                        ? _freshness(context, state)
                        : _row(context, state, products[index]),
                  ),
                ),
        ),
      ],
    );
  }

  /// Products matching the search and the low-stock filter, in name order.
  List<Product> _visible(AppState state) {
    var products =
        state.search(_search.text).where((product) => product.trackStock).toList();
    if (_lowOnly) {
      products = products.where((product) => _status(state, product) != 'ok').toList();
    }
    products.sort((a, b) => a.name.compareTo(b.name));
    return products;
  }

  /// What this product is worth worrying about, at the branch in view.
  String _status(AppState state, Product product) {
    if (!state.branchStock.isEmpty) {
      return state.branchStock.statusFor(product.id, _branchId);
    }
    return product.stockStatus ?? 'ok';
  }

  /// How many of it are here, and how many are elsewhere.
  (double?, double) _held(AppState state, Product product) {
    final spread = state.branchStock.forProduct(product.id);
    if (spread == null) {
      // No branch picture yet: the catalogue's own figure is the business's.
      return (Money.parse(product.quantityOnHand), 0);
    }
    final here = spread.at(_branchId);
    return (here, _branchId == null ? 0 : spread.total - here);
  }

  Widget _filters(BuildContext context, List<Branch> branches, bool many) {
    return SizedBox(
      // Tall enough for a chip's 48-pixel tap target, whatever the chip
      // itself looks like.
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        children: [
          FilterChip(
            label: const Text('Needs restocking'),
            selected: _lowOnly,
            onSelected: (value) => setState(() => _lowOnly = value),
          ),
          if (many) ...[
            const VerticalDivider(width: 17, indent: 10, endIndent: 10),
            _branchChip(label: 'All branches', id: null),
            for (final branch in branches)
              _branchChip(label: branch.name, id: branch.id),
          ],
        ],
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
        onSelected: (_) => setState(() {
          _branchId = id;
          _pickedABranch = true;
        }),
      ),
    );
  }

  /// A branch with nothing recorded is not an empty branch — it is a branch
  /// nobody has counted.  Saying so is the difference between the two.
  Widget _countPrompt(BuildContext context, AppState state) {
    final session = state.session;
    if (session == null || !session.can('stock:adjust')) {
      return const SizedBox.shrink();
    }
    final waiting = state.branchesToCount;
    if (waiting.isEmpty) return const SizedBox.shrink();
    final first = waiting.first;
    final theme = Theme.of(context);

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
      child: Material(
        color: theme.colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => Navigator.of(context)
              .pushNamed('/stock/count', arguments: first.branchId),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Icon(Icons.fact_check_outlined,
                    color: theme.colorScheme.onSecondaryContainer),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        waiting.length == 1
                            ? '${first.branchName} has nothing recorded'
                            : '${waiting.length} branches have nothing recorded',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: theme.colorScheme.onSecondaryContainer,
                        ),
                      ),
                      Text(
                        'Count what is on the shelves',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSecondaryContainer,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(Icons.chevron_right,
                    color: theme.colorScheme.onSecondaryContainer),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _row(BuildContext context, AppState state, Product product) {
    final theme = Theme.of(context);
    final (here, elsewhere) = _held(state, product);
    final status = _status(state, product);

    return ListTile(
      onTap: state.branchStock.isEmpty
          ? null
          : () => _showSpread(context, state, product),
      title: Text(product.name),
      subtitle: _subtitle(product, elsewhere),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: Money.quantity(here),
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                TextSpan(
                  text: ' ${product.unitOfMeasure}',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          if (status != 'ok') StatusChip(status: status),
        ],
      ),
    );
  }

  /// What is worth saying under the name: which branch has the rest of it,
  /// or failing that what kind of thing it is.
  Widget? _subtitle(Product product, double elsewhere) {
    final parts = [
      if (elsewhere > 0) '${Money.quantity(elsewhere)} at other branches',
      if (product.categoryName != null) product.categoryName!,
    ];
    if (parts.isEmpty) return null;
    return Text(parts.join(' · '));
  }

  /// Where the rest of it is, and the offer to go and get some.
  void _showSpread(BuildContext context, AppState state, Product product) {
    final spread = state.branchStock.forProduct(product.id);
    if (spread == null) return;
    final session = state.session;
    final mayAsk = (session?.can('stock:transfer') ?? false) &&
        state.branchStock.branches.length > 1;

    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(product.name,
                      style: Theme.of(sheet).textTheme.titleMedium),
                  Text(
                    '${Money.quantity(spread.total)} ${product.unitOfMeasure} '
                    'across ${state.branchStock.branches.length} branches',
                    style: Theme.of(sheet).textTheme.bodySmall?.copyWith(
                          color: Theme.of(sheet).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ),
            ),
            for (final branch in state.branchStock.branches)
              ListTile(
                dense: true,
                title: Text(
                  branch.name,
                  style: branch.id == _branchId
                      ? const TextStyle(fontWeight: FontWeight.w700)
                      : null,
                ),
                trailing: Text(
                  Money.quantity(spread.at(branch.id)),
                  style: Theme.of(sheet)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
            if (mayAsk)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.of(sheet).pop();
                    Navigator.of(context).pushNamed(
                      '/stock/ask',
                      arguments: product.id,
                    );
                  },
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('Ask another branch for some'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _empty(AppState state) {
    if (_lowOnly) {
      return const EmptyState(
        icon: Icons.inventory_2_outlined,
        title: 'Nothing needs restocking',
        message: 'Every tracked product is above its reorder level here.',
      );
    }
    if (_search.text.trim().isNotEmpty) {
      return const EmptyState(
        icon: Icons.search_off,
        title: 'Nothing matches that',
        message: 'Try part of the name, the SKU, or scan the barcode.',
      );
    }
    return const EmptyState(
      icon: Icons.inventory_2_outlined,
      title: 'No products',
      message: 'Products appear here once they are added.',
    );
  }

  Widget _freshness(BuildContext context, AppState state) {
    if (state.catalogueFetchedAt == null) return const SizedBox(height: 16);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      child: Text(
        'Figures from ${Money.dateTime(state.catalogueFetchedAt)}',
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
      ),
    );
  }
}
