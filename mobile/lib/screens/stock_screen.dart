import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../models/product.dart';
import '../models/session.dart';
import '../models/stock.dart';
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

/// The orders a stock list can be put in.
///
/// Column and direction as one choice, not two: "fewest here" is a thing
/// somebody wants, where "quantity, ascending" is two things they have to
/// assemble.  By category is an order too — ask for the rows that way and a
/// category's products arrive together, which is all grouping is.
enum _Order {
  name('A–Z'),
  urgent('Most urgent'),
  fewest('Fewest here'),
  most('Most here'),
  category('By category');

  const _Order(this.label);
  final String label;
}

/// How much each status is worth worrying about, so "most urgent" is one
/// obvious order rather than the alphabet's opinion of the words.
const _urgency = {'out_of_stock': 0, 'critical': 1, 'warning': 2, 'ok': 3};

class StockScreen extends StatefulWidget {
  const StockScreen({super.key});

  @override
  State<StockScreen> createState() => _StockScreenState();
}

class _StockScreenState extends State<StockScreen> {
  final _search = TextEditingController();
  bool _lowOnly = false;
  _Order _order = _Order.name;

  /// Null means every category.  Held by name: the catalogue on the device
  /// knows a product's category by name and nothing here needs its id.
  String? _category;

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
    final rows = _rows(products);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
          child: Row(
            children: [
              Expanded(
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
              _sortAndFilter(context),
            ],
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
                    // One past the rows: the last says how fresh the figures
                    // above it are, which matters most offline.
                    itemCount: rows.length + 1,
                    itemBuilder: (context, index) {
                      if (index == rows.length) return _freshness(context, state);
                      final row = rows[index];
                      return row is Product
                          ? _row(context, state, row)
                          : _heading(context, row as String);
                    },
                  ),
                ),
        ),
      ],
    );
  }

  /// Products matching the search and the filters, in the chosen order.
  List<Product> _visible(AppState state) {
    var products =
        state.search(_search.text).where((product) => product.trackStock).toList();
    if (_lowOnly) {
      products = products.where((product) => _status(state, product) != 'ok').toList();
    }
    if (_category != null) {
      products =
          products.where((product) => product.categoryName == _category).toList();
    }
    // Alphabetical first, then stable-sorted by the chosen column, so the
    // products under one heading never read backwards.
    products.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    switch (_order) {
      case _Order.name:
        break;
      case _Order.urgent:
        products = _stableBy(products, (p) => _urgency[_status(state, p)] ?? 9);
      case _Order.fewest:
        products = _stableBy(products, (p) => _held(state, p).$1 ?? 0);
      case _Order.most:
        products = _stableBy(products, (p) => -(_held(state, p).$1 ?? 0));
      case _Order.category:
        // Uncategorised last: not a heading anybody wants at the top.
        products = _stableBy(products, (p) => p.categoryName?.toLowerCase() ?? '\uffff');
    }
    return products;
  }

  /// Sorted by one key, keeping the order of anything that ties.
  List<T> _stableBy<T, K extends Comparable<Object>>(
    List<T> items,
    K Function(T) key,
  ) {
    final keyed = [
      for (var i = 0; i < items.length; i++) (key(items[i]), i, items[i]),
    ];
    keyed.sort((a, b) {
      final by = a.$1.compareTo(b.$1);
      return by != 0 ? by : a.$2.compareTo(b.$2);
    });
    return [for (final entry in keyed) entry.$3];
  }

  /// The list as it is drawn: a heading before each run of one category,
  /// and nothing extra in any other order.
  List<Object> _rows(List<Product> products) {
    if (_order != _Order.category) return products;
    final rows = <Object>[];
    String? last;
    for (final product in products) {
      final heading = product.categoryName ?? 'No category';
      if (heading != last) {
        rows.add(heading);
        last = heading;
      }
      rows.add(product);
    }
    return rows;
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

  /// Every category the catalogue actually uses, in order.
  List<String> _categories(BuildContext context) {
    final seen = <String>{};
    for (final product in AppScope.of(context).products) {
      final name = product.categoryName;
      if (product.trackStock && name != null && name.isNotEmpty) seen.add(name);
    }
    final all = seen.toList()
      ..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return all;
  }

  /// A heading over the products that share a category.
  Widget _heading(BuildContext context, String label) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: theme.colorScheme.surfaceContainerHighest,
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Text(
        label.toUpperCase(),
        style: theme.textTheme.labelSmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
    );
  }

  /// One button for the order and the category, beside the search box.
  ///
  /// Not another chip: the branch chips are the most used control on this
  /// screen and anything placed ahead of them pushes them off the edge of a
  /// phone.  A dot says the list is not in its plain order, so a filter left
  /// on yesterday cannot quietly explain a figure today.
  Widget _sortAndFilter(BuildContext context) {
    final touched = _order != _Order.name || _category != null;
    return IconButton(
      tooltip: 'Sort and filter',
      icon: touched
          ? Badge(
              smallSize: 8,
              child: const Icon(Icons.tune),
            )
          : const Icon(Icons.tune),
      onPressed: () => _openSortAndFilter(context),
    );
  }

  void _openSortAndFilter(BuildContext context) {
    final categories = _categories(context);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheet) => StatefulBuilder(
        builder: (sheet, redrawSheet) {
          void change(void Function() apply) {
            redrawSheet(apply);
            setState(apply);
          }

          return SafeArea(
            child: ConstrainedBox(
              // Never more than most of the screen, so the list behind it is
              // still there to come back to.
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(sheet).size.height * 0.8,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // The choices scroll; the way out does not go with them.
                  Flexible(
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        _sheetHeading(sheet, 'Order'),
                        for (final order in _Order.values)
                          RadioListTile<_Order>(
                            value: order,
                            groupValue: _order,
                            dense: true,
                            title: Text(order.label),
                            onChanged: (picked) =>
                                change(() => _order = picked ?? _order),
                          ),
                        if (categories.isNotEmpty) ...[
                          const Divider(height: 1),
                          _sheetHeading(sheet, 'Category'),
                          for (final name in <String?>[null, ...categories])
                            RadioListTile<String?>(
                              value: name,
                              groupValue: _category,
                              dense: true,
                              title: Text(name ?? 'Any category'),
                              onChanged: (picked) =>
                                  change(() => _category = picked),
                            ),
                        ],
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: () => Navigator.of(sheet).pop(),
                        child: const Text('Done'),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _sheetHeading(BuildContext context, String label) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 10, 20, 4),
      child: Text(
        label.toUpperCase(),
        style: theme.textTheme.labelSmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
          color: theme.colorScheme.onSurfaceVariant,
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
    final short = _short(state, product);

    return ListTile(
      onTap: state.branchStock.isEmpty
          ? null
          : () => _showSpread(context, state, product),
      title: Text(product.name),
      subtitle: _subtitle(state, product, elsewhere),
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
          // Beside the figure, the chip has to be about the same thing the
          // figure is about.  With every branch in view the figure is the
          // business's own total, and "164 bag — out of stock" beside it
          // reads as a broken app rather than as four empty shelves; so
          // there the chip counts the shelves instead.
          if (status != 'ok')
            StatusChip(
              status: status,
              label: short.isEmpty
                  ? null
                  : short.length == 1
                      ? '1 branch short'
                      : '${short.length} branches short',
            ),
        ],
      ),
    );
  }

  /// The branches short of this product, worst first — empty unless the
  /// list is showing all of them, and unless there is more than one.
  List<ShortBranch> _short(AppState state, Product product) =>
      _branchId == null && state.branchStock.branches.length > 1
          ? state.branchStock.shortBranches(product.id)
          : const [];

  /// What is worth saying under the name: the emptiest shelf and how
  /// little is on it, which branch has the rest of it, or failing those
  /// what kind of thing it is.
  ///
  /// With every branch in view a figure can be healthy and a shelf still
  /// empty, so the shop to go and look at is the useful thing to say — a
  /// total of 91 across five branches is no help to the one with seven.
  /// The count of the others is on the chip, so it is not repeated here:
  /// one line, naming one shop, is what somebody acts on.
  ///
  /// The category is left out when it is already the answer to the question
  /// — under its own heading, or with the list filtered to it — where it
  /// would be the same word on every row.
  Widget? _subtitle(AppState state, Product product, double elsewhere) {
    final saidAlready = _category != null || _order == _Order.category;
    final worst = _short(state, product).firstOrNull;
    final parts = [
      if (worst != null)
        worst.isEmpty
            ? 'None left at ${worst.name}'
            : 'Down to ${Money.quantity(worst.quantity)} '
                '${product.unitOfMeasure} at ${worst.name}',
      if (elsewhere > 0)
        '${Money.quantity(elsewhere)} ${product.unitOfMeasure} '
            'at other branches',
      if (!saidAlready && product.categoryName != null) product.categoryName!,
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
            // The row says the figure; the chip beside it says whether that
            // figure is a problem, which is the reason somebody opened this
            // sheet after reading "Low at Merkato Main" on the list.
            for (final branch in state.branchStock.branches)
              _spreadRow(sheet, state, product, branch, spread),
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

  /// One branch's line in the spread sheet.
  ///
  /// The figure alone does not say whether it is a problem, and that is the
  /// reason somebody opened this sheet after reading "Down to 7 kg at
  /// Merkato Main" on the list, so the chip comes with it.  A branch that
  /// does not sell the thing at all says so in words instead of showing a
  /// nought that looks like an empty shelf.
  Widget _spreadRow(
    BuildContext sheet,
    AppState state,
    Product product,
    StockBranch branch,
    StockSpread spread,
  ) {
    final theme = Theme.of(sheet);
    final carried = spread.carriedAt(branch.id);
    final here = state.branchStock.statusFor(product.id, branch.id);
    final atHand = branch.id == _branchId;
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
                if (here != 'ok') ...[
                  StatusChip(status: here),
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

  Widget _empty(AppState state) {
    if (_category != null) {
      return EmptyState(
        icon: Icons.sell_outlined,
        title: 'Nothing in $_category',
        message: _lowOnly
            ? 'Nothing in this category needs restocking here.'
            : 'Pick another category, or clear the filter.',
      );
    }
    if (_lowOnly) {
      return EmptyState(
        icon: Icons.inventory_2_outlined,
        title: 'Nothing needs restocking',
        // "Here" is only true when a branch is in view; with all of them
        // showing, there is no here.
        message: _branchId == null
            ? 'Every tracked product is above its reorder level at every '
                'branch.'
            : 'Every tracked product is above its reorder level here.',
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
