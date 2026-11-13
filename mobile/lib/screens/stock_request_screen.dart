import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/product.dart';
import '../models/stock.dart';
import '../widgets/common.dart';

/// Asking another branch for stock you have run out of (PRD 9).
///
/// The branch that asks needs no authority over the branch it is asking —
/// that is the whole point of asking — so the list of branches it is given
/// carries names and nothing else.  What each branch holds is for whoever
/// decides; a shop assistant in one branch has no business reading
/// another's shelves.
///
/// Where the phone already holds the cross-branch picture, though, it is
/// because this user was allowed to see it, and then arriving here blind
/// is a nuisance rather than a safeguard: the branch to ask and the amount
/// to ask for are both already known.  So the figures are shown when they
/// are in hand, and simply left out when they are not.
class StockRequestScreen extends StatefulWidget {
  const StockRequestScreen({super.key, this.productId, this.sending = false});

  /// Opened from a product, so that product starts in the basket.
  final String? productId;

  /// Sending what this branch has to spare, rather than asking for what it
  /// lacks.  The same form the other way round: it leaves at once instead
  /// of waiting to be allowed, because whoever is loading the lorry is the
  /// one with the say over that shelf.
  final bool sending;

  @override
  State<StockRequestScreen> createState() => _StockRequestScreenState();
}

class _RequestLine {
  _RequestLine({
    required this.productId,
    required this.variantId,
    required this.name,
    required this.unit,
    required this.quantity,
  });

  final String productId;
  final String variantId;
  final String name;
  final String unit;
  final TextEditingController quantity;
}

class _StockRequestScreenState extends State<StockRequestScreen> {
  final _search = TextEditingController();
  final _note = TextEditingController();
  final _lines = <_RequestLine>[];

  List<TransferBranch> _branches = const [];
  String? _fromBranchId;
  String? _toBranchId;
  bool _loading = true;
  bool _sending = false;
  bool _offline = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _search.dispose();
    _note.dispose();
    for (final line in _lines) {
      line.quantity.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic rows = await state.api.get('/stock/branches');
      if (!mounted) return;
      final branches = (rows as List<dynamic>)
          .map((item) => TransferBranch.fromJson(Map<String, dynamic>.from(item as Map)))
          .where((branch) => branch.locationId != null)
          .toList();
      setState(() {
        _branches = branches;
        final mine = branches
            .where((branch) => branch.isMine)
            .map((branch) => branch.branchId)
            .toList();
        if (widget.sending) {
          // Both ends have to be yours to send between them.
          _fromBranchId = mine.firstOrNull;
          _toBranchId = mine.where((id) => id != _fromBranchId).firstOrNull;
        } else {
          _toBranchId = mine.firstOrNull;
          _fromBranchId = _bestSource(null);
        }
        _offline = false;
        _loading = false;
      });
      final productId = widget.productId;
      if (productId != null) {
        final product =
            state.products.where((item) => item.id == productId).firstOrNull;
        if (product != null) {
          _add(product);
          // Now that there is something to ask for, ask the branch with
          // the most of it rather than whichever is first in the list.
          if (!widget.sending) {
            setState(() => _fromBranchId = _bestSource(productId));
          }
        }
      }
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _error = exception.isNetworkError ? null : exception.message;
        _loading = false;
      });
    }
  }

  void _add(Product product) {
    final variant = product.defaultVariant;
    if (variant == null) return;
    if (_lines.any((line) => line.variantId == variant.id)) return;
    setState(() {
      _lines.add(_RequestLine(
        productId: product.id,
        variantId: variant.id,
        name: product.name,
        unit: product.unitOfMeasure,
        quantity: TextEditingController(text: _suggested(product.id)),
      ));
      _search.clear();
    });
  }

  /// What one branch holds of a product, when the phone knows.
  ///
  /// Null, not zero: "we were never told" and "there is none" look alike
  /// as a figure and must not look alike on the screen.
  double? _held(String? productId, String? branchId) {
    if (productId == null || branchId == null) return null;
    final state = AppScope.of(context);
    final spread = state.branchStock.forProduct(productId);
    if (spread == null) return null;
    if (!state.branchStock.branches.any((b) => b.id == branchId)) return null;
    return spread.carriedAt(branchId) ? spread.at(branchId) : null;
  }

  /// The branch with the most of it to spare, or the first one going.
  String? _bestSource(String? productId) {
    final others =
        _branches.where((branch) => branch.branchId != _toBranchId).toList();
    if (others.isEmpty) return null;
    final holdings = {
      for (final branch in others)
        branch.branchId: _held(productId, branch.branchId),
    };
    if (holdings.values.every((amount) => amount == null)) {
      return others.first.branchId;
    }
    others.sort((a, b) =>
        (holdings[b.branchId] ?? -1).compareTo(holdings[a.branchId] ?? -1));
    return others.first.branchId;
  }

  /// How much to ask for: enough to put the shelf back where it should be.
  ///
  /// A box that opens on "1" is a box somebody has to think about before
  /// they can use it, and "1" is never the answer when the reason you are
  /// here is an empty shelf.  Asking for the gap up to the reorder level
  /// is both a sensible request and an obvious one to correct.
  String _suggested(String productId) {
    final spread = AppScope.of(context).branchStock.forProduct(productId);
    final target = spread?.reorderLevel ?? spread?.minStock;
    if (spread == null || target == null) return '1';
    final gap = target - spread.at(_toBranchId);
    if (gap <= 0) return '1';
    // Sending cannot be more than is on the shelf it leaves from.
    final there = widget.sending ? _held(productId, _fromBranchId) : null;
    final most = there != null && there > 0 && there < gap ? there : gap;
    return Money.plain(most.ceilToDouble());
  }

  /// True where a line asks to send more than the shelf it leaves holds.
  bool _tooMany(_RequestLine line) {
    if (!widget.sending) return false;
    final there = _held(line.productId, _fromBranchId);
    final typed = double.tryParse(line.quantity.text.trim()) ?? 0;
    return there != null && typed > there;
  }

  String _name(String? branchId) => _branches
      .where((branch) => branch.branchId == branchId)
      .map((branch) => branch.branchName)
      .firstOrNull ??
      'the other branch';

  bool get _ready =>
      _lines.isNotEmpty &&
      _fromBranchId != null &&
      _toBranchId != null &&
      _fromBranchId != _toBranchId &&
      _lines.every((line) =>
          (double.tryParse(line.quantity.text.trim()) ?? 0) > 0 &&
          !_tooMany(line));

  Future<void> _send() async {
    if (!_ready) return;
    setState(() {
      _sending = true;
      _error = null;
    });
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    try {
      await state.api.post(
        widget.sending ? '/stock/transfers' : '/stock/requests',
        body: {
          'from_location_id': _location(_fromBranchId),
          'to_location_id': _location(_toBranchId),
          'lines': [
            for (final line in _lines)
              {
                'variant_id': line.variantId,
                'quantity': line.quantity.text.trim(),
              }
          ],
          if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
          // Written down and sent as one thing, so a shelf too empty to
          // send from refuses both rather than leaving half of it behind.
          if (widget.sending) 'dispatch_now': true,
        },
      );
      if (widget.sending) await state.refresh();
      navigator.pop(true);
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A request has to reach the other branch, so it '
              'cannot wait in the outbox.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  /// A source branch, with what it holds of the thing being asked for.
  String _sourceLabel(TransferBranch branch) {
    final productId = _lines.firstOrNull?.productId;
    final amount = _held(productId, branch.branchId);
    if (amount == null) return branch.branchName;
    return '${branch.branchName} — ${Money.quantity(amount)} '
        '${_lines.first.unit}';
  }

  /// One thing being asked for: what it is, how much of it, and why that
  /// number — the shelf it is meant to refill is the reason.
  Widget _lineRow(BuildContext context, _RequestLine line) {
    final theme = Theme.of(context);
    final have = _held(line.productId, _toBranchId);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(line.name),
                if (_tooMany(line))
                  Text(
                    'Only ${Money.quantity(_held(line.productId, _fromBranchId))} '
                    '${line.unit} at ${_name(_fromBranchId)}',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.error),
                  )
                else if (have != null)
                  Text(
                    widget.sending
                        ? '${_name(_toBranchId)} has '
                            '${Money.quantity(have)} ${line.unit}'
                        : 'You have ${Money.quantity(have)} ${line.unit} here',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
              ],
            ),
          ),
          SizedBox(
            width: 96,
            child: TextField(
              controller: line.quantity,
              textAlign: TextAlign.right,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              decoration: InputDecoration(
                isDense: true,
                suffixText: line.unit,
              ),
              onChanged: (_) => setState(() {}),
            ),
          ),
          IconButton(
            tooltip: 'Remove',
            icon: const Icon(Icons.close),
            onPressed: () => setState(() {
              line.quantity.dispose();
              _lines.remove(line);
            }),
          ),
        ],
      ),
    );
  }

  String? _location(String? branchId) => _branches
      .where((branch) => branch.branchId == branchId)
      .map((branch) => branch.locationId)
      .firstOrNull;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final mine = _branches.where((branch) => branch.isMine).toList();
    final sending = widget.sending;
    // Asking can be of any branch; sending is from one of your own.
    final sources = sending
        ? mine
        : _branches.where((branch) => branch.branchId != _toBranchId).toList();
    final destinations = sending
        ? mine.where((branch) => branch.branchId != _fromBranchId).toList()
        : mine;
    final results = _search.text.trim().isEmpty
        ? const <Product>[]
        : state.search(_search.text).where((product) => product.trackStock).take(6).toList();

    return Scaffold(
      appBar: AppBar(title: Text(sending ? 'Send stock' : 'Ask for stock')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'Asking needs a connection',
                    message:
                        'A request has to reach the branch you are asking, so '
                        'it cannot wait in the outbox.',
                  )
                : mine.isEmpty ||
                        _branches.length < 2 ||
                        (sending && mine.length < 2)
                    ? EmptyState(
                        icon: Icons.store_outlined,
                        title: 'Only one branch',
                        message: sending
                            ? 'Sending needs two branches you work at. Ask '
                                'the other branch for stock instead.'
                            : 'A request needs another branch to ask. Add '
                                'one under Settings on the web first.',
                      )
                    : ListView(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                        children: [
                          DropdownButtonFormField<String>(
                            isExpanded: true,
                            value: sources.any((b) => b.branchId == _fromBranchId)
                                ? _fromBranchId
                                : null,
                            decoration: InputDecoration(
                              labelText: 'From',
                              helperText: sending
                                  ? 'Where it is leaving'
                                  : 'The branch you are asking',
                            ),
                            items: [
                              for (final branch in sources)
                                DropdownMenuItem(
                                  value: branch.branchId,
                                  child: Text(_sourceLabel(branch)),
                                ),
                            ],
                            onChanged: (value) => setState(() {
                              _fromBranchId = value;
                              if (_toBranchId == value) _toBranchId = null;
                            }),
                          ),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<String>(
                            isExpanded: true,
                            value: destinations
                                    .any((b) => b.branchId == _toBranchId)
                                ? _toBranchId
                                : null,
                            decoration: InputDecoration(
                              labelText: 'To',
                              helperText: sending
                                  ? 'Where it is going'
                                  : 'Where you need it',
                            ),
                            items: [
                              for (final branch in destinations)
                                DropdownMenuItem(
                                  value: branch.branchId,
                                  child: Text(branch.branchName),
                                ),
                            ],
                            onChanged: (value) => setState(() {
                              _toBranchId = value;
                              if (_fromBranchId == value) _fromBranchId = null;
                            }),
                          ),
                          const SizedBox(height: 16),
                          TextField(
                            controller: _search,
                            decoration: const InputDecoration(
                              hintText: 'Find a product',
                              prefixIcon: Icon(Icons.search),
                            ),
                            onChanged: (_) => setState(() {}),
                          ),
                          for (final product in results)
                            ListTile(
                              dense: true,
                              title: Text(product.name),
                              trailing: const Icon(Icons.add),
                              onTap: () => _add(product),
                            ),
                          const SizedBox(height: 8),
                          if (_lines.isEmpty)
                            Text(
                              'Search above and tap a product to add it.',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                            ),
                          for (final line in _lines) _lineRow(context, line),
                          const SizedBox(height: 8),
                          TextField(
                            controller: _note,
                            decoration: InputDecoration(
                              labelText:
                                  sending ? 'Note' : 'Why you need it',
                              hintText: sending
                                  ? 'optional — for whoever unloads it'
                                  : 'e.g. sold out before lunch',
                            ),
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 12),
                            Text(
                              _error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error),
                            ),
                          ],
                          const SizedBox(height: 20),
                          FilledButton(
                            onPressed: _sending || !_ready ? null : _send,
                            // A disabled button that does not say what is
                            // missing is a dead end.
                            child: Text(
                              _sending
                                  ? 'Sending…'
                                  : _lines.isEmpty
                                      ? 'Add a product first'
                                      : _lines.any(_tooMany)
                                          ? 'That is more than is there'
                                          : sending
                                              ? 'Send it now'
                                              : 'Send the request',
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            sending
                                ? 'It leaves ${_name(_fromBranchId)} now, and goes '
                                    'on the shelves at ${_name(_toBranchId)} when '
                                    'somebody there says it arrived.'
                                : 'Nothing moves until it is allowed and you '
                                    'take it up.',
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant,
                                ),
                          ),
                        ],
                      ),
      ),
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
