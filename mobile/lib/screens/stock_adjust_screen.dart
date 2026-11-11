import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/product.dart';
import '../models/stock.dart';
import '../widgets/common.dart';

/// What can happen to stock that is not a sale, a delivery or a count.
///
/// Each carries the ledger's own reason, which way it moves the figure,
/// and the words somebody would actually use for it.
enum _Cause {
  damaged(
    'Broke or went off',
    'damage',
    -1,
    'It is still here, but nobody can sell it.',
    Icons.broken_image_outlined,
  ),
  lost(
    'Lost or stolen',
    'loss',
    -1,
    'It should be on the shelf and it is not.',
    Icons.search_off_outlined,
  ),
  found(
    'Found more',
    'adjustment',
    1,
    'There is more here than the books say.',
    Icons.add_task_outlined,
  );

  const _Cause(this.label, this.reason, this.sign, this.explain, this.icon);

  final String label;
  final String reason;
  final int sign;
  final String explain;
  final IconData icon;
}

/// Something broke, went off, went missing — or turned up (PRD 9).
///
/// The counting screen can only say what a shelf holds now.  This says what
/// happened to it, which is what somebody standing over a dropped crate
/// actually knows: three bottles, broken.  The reason goes on the ledger
/// with the change, so a write-off is a line the owner can read later
/// rather than a shelf that quietly got smaller.
class StockAdjustScreen extends StatefulWidget {
  const StockAdjustScreen({super.key, this.productId, this.branchId});

  /// Opened from a product, so that product is already chosen.
  final String? productId;

  /// The branch somebody was looking at when they opened it.
  final String? branchId;

  @override
  State<StockAdjustScreen> createState() => _StockAdjustScreenState();
}

class _StockAdjustScreenState extends State<StockAdjustScreen> {
  final _search = TextEditingController();
  final _quantity = TextEditingController();
  final _note = TextEditingController();

  List<TransferBranch> _branches = const [];
  String? _branchId;
  Product? _product;
  _Cause _cause = _Cause.damaged;
  bool _loading = true;
  bool _saving = false;
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
    _quantity.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic rows = await state.api.get('/stock/branches');
      if (!mounted) return;
      final branches = (rows as List<dynamic>)
          .map((item) =>
              TransferBranch.fromJson(Map<String, dynamic>.from(item as Map)))
          .where((branch) => branch.isMine && branch.locationId != null)
          .toList();
      setState(() {
        _branches = branches;
        _branchId = branches.any((b) => b.branchId == widget.branchId)
            ? widget.branchId
            : branches.map((b) => b.branchId).firstOrNull;
        final id = widget.productId;
        _product = id == null
            ? null
            : state.products.where((p) => p.id == id).firstOrNull;
        _offline = false;
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

  double get _typed => double.tryParse(_quantity.text.trim()) ?? 0;

  /// What the books say this branch holds, when the phone knows.
  double? get _onRecord {
    final product = _product;
    final branchId = _branchId;
    if (product == null || branchId == null) return null;
    final state = AppScope.of(context);
    final spread = state.branchStock.forProduct(product.id);
    if (spread != null &&
        state.branchStock.branches.any((b) => b.id == branchId)) {
      return spread.at(branchId);
    }
    // One branch: the catalogue's own figure is this branch's.
    if (_branches.length == 1) return Money.parse(product.quantityOnHand);
    return null;
  }

  /// More than is there cannot break.
  bool get _tooMany {
    final have = _onRecord;
    return _cause.sign < 0 && have != null && _typed > have;
  }

  bool get _ready =>
      _product?.defaultVariant != null &&
      _branchId != null &&
      _typed > 0 &&
      !_tooMany;

  Future<void> _save() async {
    if (!_ready) return;
    final product = _product!;
    final location = _branches
        .where((b) => b.branchId == _branchId)
        .map((b) => b.locationId)
        .firstOrNull;
    if (location == null) return;

    setState(() {
      _saving = true;
      _error = null;
    });
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final typed = _note.text.trim();
    try {
      await state.api.post('/stock/adjust', body: {
        'variant_id': product.defaultVariant!.id,
        'location_id': location,
        'quantity': Money.plain(_typed * _cause.sign),
        'reason': _cause.reason,
        // The ledger wants a reason in words.  Somebody holding a broken
        // bottle has already given one by choosing what happened, so that
        // stands unless they have more to say.
        'note': typed.length >= 3 ? typed : _cause.label,
      });
      messenger.showSnackBar(SnackBar(
        content: Text(
          _cause.sign < 0
              ? '${Money.quantity(_typed)} ${product.unitOfMeasure} of '
                  '${product.name} taken off the books.'
              : '${Money.quantity(_typed)} ${product.unitOfMeasure} of '
                  '${product.name} added.',
        ),
      ));
      await state.refresh();
      navigator.pop(true);
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. This goes straight on the ledger, so it cannot '
              'wait in the outbox.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('What happened?')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'This needs a connection',
                    message:
                        'A write-off goes straight on the ledger, so it '
                        'cannot wait in the outbox.',
                  )
                : _branches.isEmpty
                    ? EmptyState(
                        icon: Icons.store_outlined,
                        title: 'No branch to change',
                        message: _error ??
                            'You are not assigned to a branch that holds '
                                'stock.',
                      )
                    : _form(context),
      ),
    );
  }

  Widget _form(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final product = _product;
    final have = _onRecord;
    final unit = product?.unitOfMeasure ?? '';
    final results = product != null || _search.text.trim().isEmpty
        ? const <Product>[]
        : state
            .search(_search.text)
            .where((p) => p.trackStock)
            .take(6)
            .toList();

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            children: [
              // What happened comes first: it is the one thing somebody
              // already knows when they open this.
              for (final cause in _Cause.values)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _causeTile(context, cause),
                ),
              const SizedBox(height: 8),
              if (_branches.length > 1) ...[
                DropdownButtonFormField<String>(
                  value: _branchId,
                  decoration: const InputDecoration(labelText: 'Where'),
                  items: [
                    for (final branch in _branches)
                      DropdownMenuItem(
                        value: branch.branchId,
                        child: Text(branch.branchName),
                      ),
                  ],
                  onChanged: (value) => setState(() => _branchId = value),
                ),
                const SizedBox(height: 12),
              ],
              if (product == null) ...[
                TextField(
                  key: const Key('adjustSearch'),
                  controller: _search,
                  decoration: const InputDecoration(
                    hintText: 'Which product?',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                for (final found in results)
                  ListTile(
                    dense: true,
                    title: Text(found.name),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => setState(() {
                      _product = found;
                      _search.clear();
                    }),
                  ),
              ] else
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(product.name),
                  subtitle: Text(
                    have == null
                        ? unit
                        : 'On record here: ${Money.quantity(have)} $unit',
                  ),
                  // Changing your mind about the product is one tap, not a
                  // trip back out of the screen.
                  trailing: widget.productId != null
                      ? null
                      : TextButton(
                          onPressed: () => setState(() => _product = null),
                          child: const Text('Change'),
                        ),
                ),
              if (product != null) ...[
                const SizedBox(height: 8),
                TextField(
                  key: const Key('adjustQuantity'),
                  controller: _quantity,
                  autofocus: true,
                  textAlign: TextAlign.right,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                  ],
                  decoration: InputDecoration(
                    labelText: 'How many',
                    suffixText: unit,
                    errorText: _tooMany
                        ? 'Only ${Money.quantity(have)} $unit on record here.'
                        : null,
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                // What the shelf will read afterwards, before it is so.
                if (have != null && _typed > 0 && !_tooMany)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      '${Money.quantity(have)} → '
                      '${Money.quantity(have + _typed * _cause.sign)} $unit',
                      textAlign: TextAlign.right,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                const SizedBox(height: 12),
                TextField(
                  controller: _note,
                  decoration: const InputDecoration(
                    labelText: 'Anything to add',
                    hintText: 'optional — dropped the crate, say',
                  ),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ],
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('adjustSave'),
              onPressed: _saving || !_ready ? null : _save,
              // A disabled button that does not say what is missing is a
              // dead end.
              child: Text(
                _saving
                    ? 'Saving…'
                    : product == null
                        ? 'Choose a product'
                        : _typed <= 0
                            ? 'Type how many'
                            : _tooMany
                                ? 'That is more than is there'
                                : _cause.sign < 0
                                    ? 'Take ${Money.quantity(_typed)} $unit '
                                        'off the books'
                                    : 'Add ${Money.quantity(_typed)} $unit',
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _causeTile(BuildContext context, _Cause cause) {
    final theme = Theme.of(context);
    final chosen = _cause == cause;
    return Material(
      color: chosen
          ? theme.colorScheme.secondaryContainer
          : theme.colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: chosen
              ? theme.colorScheme.primary
              : theme.colorScheme.outlineVariant,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => setState(() => _cause = cause),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              Icon(cause.icon, color: theme.colorScheme.primary),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      cause.label,
                      style: theme.textTheme.titleSmall,
                    ),
                    Text(
                      cause.explain,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              if (chosen)
                Icon(Icons.check_circle, color: theme.colorScheme.primary),
            ],
          ),
        ),
      ),
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
