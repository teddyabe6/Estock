import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
import '../models/product.dart';
import '../models/stock.dart';
import '../widgets/common.dart';
import 'product_form_screen.dart';

const _methods = <(String, String)>[
  ('cash', 'Cash'),
  ('telebirr', 'Telebirr'),
  ('cbe_birr', 'CBE Birr'),
  ('bank_transfer', 'Bank transfer'),
];

const _duePresets = <(String?, String)>[
  (null, 'No date agreed'),
  ('7_days', 'In 7 days'),
  ('15_days', 'In 15 days'),
  ('30_days', 'In 30 days'),
];

class _Line {
  _Line({
    required this.product,
    required this.quantity,
    required this.cost,
  });

  final Product product;
  final TextEditingController quantity;
  final TextEditingController cost;

  double get many => double.tryParse(quantity.text.trim()) ?? 0;
  double? get each => double.tryParse(cost.text.trim());
  double get total => many * (each ?? 0);

  void dispose() {
    quantity.dispose();
    cost.dispose();
  }
}

/// A delivery arriving: what came, how many, and what it cost (PRD 11.2).
///
/// This is how stock gets into a shop, and it happens at the back door with
/// a delivery note in one hand — so it belongs on the phone more than
/// anywhere.  It asks only what is written on that note.  Shared transport,
/// repricing and the rest of what a purchase can carry stay on the web,
/// where there is a desk to do them at.
class StockReceiveScreen extends StatefulWidget {
  const StockReceiveScreen({super.key, this.productId, this.branchId});

  /// Opened from a product, so that product starts on the list.
  final String? productId;

  /// The branch somebody was looking at when they opened it.
  final String? branchId;

  @override
  State<StockReceiveScreen> createState() => _StockReceiveScreenState();
}

class _StockReceiveScreenState extends State<StockReceiveScreen> {
  final _search = TextEditingController();
  final _paid = TextEditingController();
  final _lines = <_Line>[];

  List<TransferBranch> _branches = const [];
  List<Map<String, dynamic>> _suppliers = const [];
  String? _branchId;
  String? _supplierId;
  String _method = 'cash';
  String? _duePreset;

  /// Until somebody types in the box it follows the total: paying for a
  /// delivery in full is the usual thing.
  bool _paidTouched = false;

  bool _loading = true;
  bool _saving = false;
  bool _offline = false;
  String? _error;
  String _idempotencyKey = Outbox.newId();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _search.dispose();
    _paid.dispose();
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic rows = await state.api.get('/stock/branches');
      List<Map<String, dynamic>> suppliers = const [];
      if (state.session?.can('supplier:view') ?? false) {
        try {
          final dynamic page =
              await state.api.get('/suppliers', query: {'limit': '200'});
          suppliers = ((page as Map<String, dynamic>)['items'] as List<dynamic>)
              .map((item) => Map<String, dynamic>.from(item as Map))
              .toList();
        } on ApiException {
          // Who it came from is optional, so a failed list is not a failed
          // delivery.
        }
      }
      if (!mounted) return;
      final branches = (rows as List<dynamic>)
          .map((item) =>
              TransferBranch.fromJson(Map<String, dynamic>.from(item as Map)))
          .where((branch) => branch.isMine && branch.locationId != null)
          .toList();
      setState(() {
        _branches = branches;
        _suppliers = suppliers;
        _branchId = branches.any((b) => b.branchId == widget.branchId)
            ? widget.branchId
            : branches.map((b) => b.branchId).firstOrNull;
        _offline = false;
        _loading = false;
      });
      final id = widget.productId;
      if (id != null) {
        final product = state.products.where((p) => p.id == id).firstOrNull;
        if (product != null) _add(product);
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

  /// A product the shop has never had, added and put on this delivery.
  ///
  /// The form is not asked how many are here: the delivery says that, and
  /// asking twice would count them twice.
  Future<void> _addNew(String name) async {
    final product = await Navigator.of(context).push<Product>(
      MaterialPageRoute(
        builder: (_) => ProductFormScreen(
          name: name,
          askStock: false,
          returnProduct: true,
          branchId: _branchId,
        ),
      ),
    );
    if (product != null && mounted) _add(product);
  }

  void _add(Product product) {
    if (product.defaultVariant == null) return;
    if (_lines.any((line) => line.product.id == product.id)) {
      setState(_search.clear);
      return;
    }
    setState(() {
      _lines.add(_Line(
        product: product,
        quantity: TextEditingController(),
        // What it cost last time, where this user may see cost: a price
        // that has not moved is then nothing to type.
        cost: TextEditingController(
          text: Money.plain(product.defaultVariant!.purchasePrice),
        ),
      ));
      _search.clear();
    });
  }

  double get _total => _lines.fold(0, (sum, line) => sum + line.total);

  double get _paidAmount => _paidTouched
      ? (double.tryParse(_paid.text.trim()) ?? 0)
      : _total;

  double get _owing => (_total - _paidAmount).clamp(0, double.infinity);
  bool get _overpaid => _paidAmount > _total;

  /// What is still missing, in the order somebody would fix it.
  String? get _missing {
    if (_lines.isEmpty) return 'Add what arrived';
    if (_lines.any((line) => line.many <= 0)) return 'Type how many arrived';
    if (_lines.any((line) => line.each == null)) {
      return 'Type what each one cost';
    }
    if (_overpaid) return 'Paid is more than the delivery cost';
    return null;
  }

  Future<bool> _confirm(String currency) async {
    final theme = Theme.of(context);
    final where = _branches
        .where((b) => b.branchId == _branchId)
        .map((b) => b.branchName)
        .firstOrNull;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(sheet).size.height * 0.75,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Add this to the shelves?',
                      style: theme.textTheme.titleMedium,
                    ),
                    Text(
                      [
                        if (where != null) 'At $where',
                        Money.format(_total, currency: currency),
                        if (_owing > 0)
                          '${Money.amount(_owing)} still to pay',
                      ].join(' · '),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final line in _lines)
                      ListTile(
                        dense: true,
                        title: Text(line.product.name),
                        subtitle: Text(
                          'at ${Money.amount(line.each)} each',
                        ),
                        trailing: Text(
                          '+${Money.quantity(line.many)} '
                          '${line.product.unitOfMeasure}',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: DialogActions(
                  back: OutlinedButton(
                    onPressed: () => Navigator.of(sheet).pop(false),
                    child: const Text('Not yet'),
                  ),
                  confirm: FilledButton(
                    key: const Key('receiveConfirm'),
                    onPressed: () => Navigator.of(sheet).pop(true),
                    child: const Text('Add it'),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    return ok ?? false;
  }

  Future<void> _save() async {
    if (_missing != null || _branchId == null) return;
    final state = AppScope.of(context);
    final currency = state.session?.currency ?? 'ETB';
    // A delivery writes quantities and costs straight to the books, and a
    // slipped nought here is thirty sacks nobody has.  Read it back first.
    if (!await _confirm(currency)) return;
    if (!mounted) return;

    setState(() {
      _saving = true;
      _error = null;
    });
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      final dynamic response = await state.api.post('/purchases', body: {
        'branch_id': _branchId,
        'lines': [
          for (final line in _lines)
            {
              'variant_id': line.product.defaultVariant!.id,
              'quantity': Money.plain(line.many),
              'unit_cost': Money.plain(line.each),
            }
        ],
        if (_supplierId != null) 'supplier_id': _supplierId,
        'amount_paid': _paidAmount.toStringAsFixed(2),
        'payment_method': _method,
        if (_owing > 0 && _duePreset != null) 'due_date_preset': _duePreset,
        'idempotency_key': _idempotencyKey,
      });
      final number =
          ((response as Map?)?['purchase'] as Map?)?['number'] as String?;
      messenger.showSnackBar(SnackBar(
        content: Text(
          _lines.length == 1
              ? '${Money.quantity(_lines.first.many)} '
                  '${_lines.first.product.unitOfMeasure} of '
                  '${_lines.first.product.name} added'
                  '${number == null ? '' : ' · $number'}.'
              : '${_lines.length} products added'
                  '${number == null ? '' : ' · $number'}.',
        ),
      ));
      _idempotencyKey = Outbox.newId();
      await state.refresh();
      navigator.pop(true);
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A delivery changes stock and cost together, so '
              'it cannot wait in the outbox — what you typed is still here.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('A delivery arrived')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'Receiving needs a connection',
                    message:
                        'A delivery changes stock and cost together, so it '
                        'cannot wait in the outbox the way a sale can.',
                  )
                : _branches.isEmpty
                    ? EmptyState(
                        icon: Icons.store_outlined,
                        title: 'No branch to receive at',
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
    final currency = state.session?.currency ?? 'ETB';
    final results = _search.text.trim().isEmpty
        ? const <Product>[]
        : state
            .search(_search.text)
            .where((p) => p.trackStock)
            .take(6)
            .toList();
    final missing = _missing;

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            children: [
              if (_branches.length > 1) ...[
                DropdownButtonFormField<String>(
                  isExpanded: true,
                  value: _branchId,
                  decoration:
                      const InputDecoration(labelText: 'Where it arrived'),
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
              TextField(
                key: const Key('receiveSearch'),
                controller: _search,
                decoration: const InputDecoration(
                  hintText: 'What arrived?',
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
              // Something on the delivery note the shop has never stocked:
              // add it here and it goes straight onto this delivery.
              if (results.isEmpty &&
                  _search.text.trim().isNotEmpty &&
                  (state.session?.can('product:manage') ?? false))
                ListTile(
                  key: const Key('receiveNewProduct'),
                  dense: true,
                  leading: const Icon(Icons.add_box_outlined),
                  title: Text('Add “${_search.text.trim()}” as a new product'),
                  subtitle: const Text('It goes onto this delivery'),
                  onTap: () => _addNew(_search.text.trim()),
                ),
              const SizedBox(height: 8),
              if (_lines.isEmpty)
                Text(
                  'Search above and tap each product on the delivery note.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              for (final line in _lines) _lineCard(context, line, currency),
              if (_lines.isNotEmpty) ...[
                const SizedBox(height: 4),
                if (_suppliers.isNotEmpty) ...[
                  DropdownButtonFormField<String?>(
                    isExpanded: true,
                    value: _supplierId,
                    decoration:
                        const InputDecoration(labelText: 'Who it came from'),
                    items: [
                      const DropdownMenuItem<String?>(
                        value: null,
                        child: Text('Not recorded'),
                      ),
                      for (final supplier in _suppliers)
                        DropdownMenuItem<String?>(
                          value: supplier['id'] as String,
                          child: Text(supplier['name'] as String? ?? ''),
                        ),
                    ],
                    onChanged: (value) => setState(() => _supplierId = value),
                  ),
                  const SizedBox(height: 12),
                ],
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        key: const Key('receivePaid'),
                        controller: _paid,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        inputFormatters: [
                          FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                        ],
                        decoration: InputDecoration(
                          labelText: 'Paid now',
                          // Until somebody types, the box shows what will
                          // be recorded: all of it.
                          hintText: Money.amount(_total),
                          errorText: _overpaid
                              ? 'More than the delivery cost.'
                              : null,
                        ),
                        onChanged: (_) => setState(() => _paidTouched = true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        isExpanded: true,
                        value: _method,
                        decoration:
                            const InputDecoration(labelText: 'Paid by'),
                        items: [
                          for (final entry in _methods)
                            DropdownMenuItem(
                              value: entry.$1,
                              child: Text(entry.$2),
                            ),
                        ],
                        onChanged: (value) =>
                            setState(() => _method = value ?? 'cash'),
                      ),
                    ),
                  ],
                ),
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    _paidTouched
                        ? (_owing > 0
                            ? '${Money.format(_owing, currency: currency)} '
                                'still to pay the supplier.'
                            : 'Paid in full.')
                        : 'Leave it empty if you paid for all of it.',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: _owing > 0
                          ? const Color(0xFF9A6200)
                          : theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
                if (_owing > 0) ...[
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String?>(
                    isExpanded: true,
                    value: _duePreset,
                    decoration:
                        const InputDecoration(labelText: 'Pay the rest by'),
                    items: [
                      for (final entry in _duePresets)
                        DropdownMenuItem<String?>(
                          value: entry.$1,
                          child: Text(entry.$2),
                        ),
                    ],
                    onChanged: (value) => setState(() => _duePreset = value),
                  ),
                ],
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
        Material(
          elevation: 8,
          color: theme.colorScheme.surface,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (_lines.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(
                      children: [
                        // The figure keeps its room; the words give way,
                        // so large text on a small phone still fits.
                        Expanded(
                          child: Text(
                            'Delivery cost',
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.titleMedium,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          Money.format(_total, currency: currency),
                          style: theme.textTheme.titleLarge
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ],
                    ),
                  ),
                FilledButton(
                  key: const Key('receiveSave'),
                  onPressed: _saving || missing != null ? null : _save,
                  // A disabled button that does not say what is missing is
                  // a dead end.
                  child: Text(
                    _saving ? 'Saving…' : missing ?? 'Add to the shelves',
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  /// One product on the delivery note: how many, and what each cost.
  Widget _lineCard(BuildContext context, _Line line, String currency) {
    final theme = Theme.of(context);
    final unit = line.product.unitOfMeasure;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    line.product.name,
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                IconButton(
                  tooltip: 'Remove',
                  icon: const Icon(Icons.close),
                  onPressed: () => setState(() {
                    _lines.remove(line);
                    line.dispose();
                  }),
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: line.quantity,
                      textAlign: TextAlign.right,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                      ],
                      textInputAction: TextInputAction.next,
                      decoration: InputDecoration(
                        labelText: 'How many',
                        suffixText: unit,
                        isDense: true,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      controller: line.cost,
                      textAlign: TextAlign.right,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Cost each',
                        isDense: true,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                ],
              ),
            ),
            if (line.many > 0 && line.each != null)
              Padding(
                padding: const EdgeInsets.only(top: 6, right: 8),
                child: Align(
                  alignment: Alignment.centerRight,
                  child: Text(
                    '${Money.quantity(line.many)} × '
                    '${Money.amount(line.each)} = '
                    '${Money.format(line.total, currency: currency)}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
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
