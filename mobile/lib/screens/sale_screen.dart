import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../core/offline/outbox.dart';
import '../models/customer.dart';
import '../models/product.dart';
import '../widgets/common.dart';
import 'sale_detail_screen.dart';
import 'sales_history_screen.dart';

class _CartLine {
  _CartLine({
    required this.variantId,
    required this.name,
    required this.unitPrice,
    this.available,
  });

  final String variantId;
  final String name;
  final double unitPrice;
  double quantity = 1;

  /// What the device last knew about stock. Advisory only — the server decides.
  final double? available;

  double get total => unitPrice * quantity;
}

const _paymentMethods = <(String, String)>[
  ('cash', 'Cash'),
  ('telebirr', 'Telebirr'),
  ('cbe_birr', 'CBE Birr'),
  ('bank_transfer', 'Bank transfer'),
];

const _duePresets = <(String?, String)>[
  (null, 'No due date'),
  ('today', 'Today'),
  ('tomorrow', 'Tomorrow'),
  ('7_days', 'In 7 days'),
  ('15_days', 'In 15 days'),
  ('30_days', 'In 30 days'),
];

/// What the till offers besides selling: the sales already made.
///
/// The tab opens the till rather than the list, because a counter sells all
/// day and looks a sale up only when a customer comes back. The list is one
/// tap away for when they do.
List<Widget> salesTabActions(BuildContext context, AppState state) {
  if (!(state.session?.can('sale:view') ?? false)) return const [];
  return [
    IconButton(
      tooltip: 'Sales already made',
      icon: const Icon(Icons.receipt_long_outlined),
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const SalesHistoryScreen()),
      ),
    ),
  ];
}

/// Record a sale. Works with or without a connection.
///
/// Offline, the sale is captured in the outbox with an idempotency key and
/// replayed when the device reconnects. The interface says plainly that such a
/// sale is waiting to sync rather than implying it is already in the books.
class SaleScreen extends StatefulWidget {
  const SaleScreen({super.key});

  @override
  State<SaleScreen> createState() => _SaleScreenState();
}

class _SaleScreenState extends State<SaleScreen> {
  final _search = TextEditingController();
  final _paid = TextEditingController();
  final _lines = <_CartLine>[];

  String _method = 'cash';
  String? _duePreset;
  Customer? _customer;
  bool _busy = false;
  // One key per cart, so a double tap cannot post the sale twice.
  String _idempotencyKey = Outbox.newId();

  @override
  void dispose() {
    _search.dispose();
    _paid.dispose();
    super.dispose();
  }

  double get _total => _lines.fold(0, (sum, line) => sum + line.total);

  /// What was handed over, which is not the same as what the sale is worth.
  double get _received => double.tryParse(_paid.text.trim()) ?? 0;

  /// What goes in the books: a sale is worth what it is worth, however big
  /// the note was.  Recording the note itself would overstate the day's
  /// takings by the change, and the server refuses it outright.
  double get _paidAmount => _received > _total ? _total : _received;

  /// What to hand back across the counter.  The one number a till is for
  /// and the one this screen never showed: typing what the customer
  /// actually gave you used to fail the sale with "could not be saved".
  double get _change => (_received - _total).clamp(0, double.infinity);

  double get _balance => (_total - _paidAmount).clamp(0, double.infinity);

  /// Round amounts somebody is likely to be handed, just above the total.
  ///
  /// A counter deals in notes, not in exact change: for 2,160 the customer
  /// holds out 2,200 or 3,000, and typing it should be one tap rather than
  /// a sum done in the head while they wait.
  List<double> get _notes {
    if (_total <= 0) return const [];
    final steps = [50, 100, 500, 1000, 5000];
    final seen = <double>{};
    for (final step in steps) {
      final up = (_total / step).ceil() * step.toDouble();
      if (up > _total) seen.add(up);
    }
    final sorted = seen.toList()..sort();
    return sorted.take(3).toList();
  }

  void _add(Product product) {
    final variant = product.defaultVariant;
    if (variant == null) return;
    setState(() {
      final existing =
          _lines.where((line) => line.variantId == variant.id).firstOrNull;
      if (existing != null) {
        existing.quantity += 1;
      } else {
        _lines.add(_CartLine(
          variantId: variant.id,
          name: product.name,
          unitPrice: Money.parse(variant.sellingPrice) ?? 0,
          available: product.trackStock
              ? Money.parse(product.quantityOnHand) ?? 0
              : null,
        ));
      }
      _search.clear();
      _paid.text = _total.toStringAsFixed(2);
    });
  }

  Future<void> _complete() async {
    if (_lines.isEmpty) return;
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);

    if (_balance > 0 && _customer == null) {
      messenger.showSnackBar(const SnackBar(
        content: Text('Choose a customer before selling on credit.'),
      ));
      await _pickCustomer();
      return;
    }

    setState(() => _busy = true);
    try {
      final body = <String, dynamic>{
        'lines': _lines
            .map((line) => {
                  'variant_id': line.variantId,
                  'quantity': line.quantity.toString(),
                })
            .toList(),
        'payments': _paidAmount > 0
            ? [
                {'method': _method, 'amount': _paidAmount.toStringAsFixed(2)}
              ]
            : <Map<String, dynamic>>[],
        if (_customer != null) 'customer_id': _customer!.id,
        if (_balance > 0 && _duePreset != null) 'due_date_preset': _duePreset,
        'idempotency_key': _idempotencyKey,
      };

      final result = await state.sync.submit(
        path: '/sales',
        body: body,
        summary: 'Sale · ${Money.format(_total, currency: state.session?.currency ?? 'ETB')}',
      );

      if (!mounted) return;

      // A sale the server threw out is not a sale waiting to sync.  The
      // basket stays exactly as it was, so whatever was wrong can be put
      // right and the customer is not asked to start again; and the
      // rejected copy goes, because the work is still here on the screen.
      if (result.isRefused) {
        await state.sync.dismissRejected(result.entryId!);
        if (!mounted) return;
        setState(() {});
        messenger.showSnackBar(SnackBar(
          duration: const Duration(seconds: 8),
          content: Text(result.reason ?? 'The sale was not accepted.'),
        ));
        return;
      }

      final change = _change;
      final number = (result.body?['sale'] as Map?)?['number'] as String?;
      final saleId = (result.body?['sale'] as Map?)?['id'] as String?;
      messenger.showSnackBar(SnackBar(
        content: Text(result.isQueued
            ? 'Saved on this phone. It will sync when you are back online.'
            : change > 0
                ? 'Sale $number recorded. '
                    'Change ${Money.format(change, currency: state.session?.currency ?? 'ETB')}.'
                : 'Sale $number recorded.'),
        // The customer standing there usually wants the receipt, and this is
        // the one moment the app knows exactly which sale they mean.
        action: saleId == null || !(state.session?.can('sale:view') ?? false)
            ? null
            : SnackBarAction(
                label: 'Receipt',
                onPressed: () => navigator.push(
                  MaterialPageRoute(
                    builder: (_) => SaleDetailScreen(saleId: saleId),
                  ),
                ),
              ),
      ));

      setState(() {
        _lines.clear();
        _paid.clear();
        _customer = null;
        _duePreset = null;
        _idempotencyKey = Outbox.newId();
      });
      // Refresh stock figures where possible; harmless when offline.
      unawaited(state.refresh());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickCustomer() async {
    final state = AppScope.of(context);
    final picked = await showModalBottomSheet<Customer?>(
      context: context,
      isScrollControlled: true,
      builder: (_) => CustomerPicker(state: state, selected: _customer),
    );
    if (!mounted || picked == null) return;
    setState(() => _customer = picked.id.isEmpty ? null : picked);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final currency = state.session?.currency ?? 'ETB';
    final matches = _search.text.trim().isEmpty
        ? const <Product>[]
        : state.search(_search.text).take(8).toList();

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: TextField(
            key: const Key('productSearch'),
            controller: _search,
            decoration: InputDecoration(
              hintText: 'Search or scan a product',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => setState(_search.clear),
                    ),
            ),
            onChanged: (_) => setState(() {}),
            onSubmitted: (value) {
              // A barcode scanner types fast and ends with Enter.
              final found = state.findByBarcode(value);
              if (found != null) {
                _add(found);
              } else if (matches.isNotEmpty) {
                _add(matches.first);
              }
            },
          ),
        ),
        if (matches.isNotEmpty)
          SizedBox(
            height: 160,
            child: ListView(
              children: matches
                  .map((product) => ListTile(
                        dense: true,
                        title: Text(product.name),
                        subtitle: Text(
                          product.trackStock
                              ? '${Money.quantity(product.quantityOnHand)} on hand'
                              : 'Not stocked',
                        ),
                        trailing: Text(
                          Money.format(product.defaultVariant?.sellingPrice,
                              currency: currency),
                        ),
                        onTap: () => _add(product),
                      ))
                  .toList(),
            ),
          ),
        const Divider(height: 1),
        Expanded(
          child: _lines.isEmpty
              ? const EmptyState(
                  icon: Icons.shopping_basket_outlined,
                  title: 'Nothing added yet',
                  message: 'Search above, or scan a barcode.',
                )
              : ListView.builder(
                  itemCount: _lines.length,
                  itemBuilder: (context, index) =>
                      _basketLine(context, index, currency),
                ),
        ),
        if (_lines.isNotEmpty) _paymentPanel(context, currency),
      ],
    );
  }

  /// One thing in the basket, with its sum shown.
  ///
  /// The price alone was all this said, so three coffees read "720.00" and
  /// the customer querying the total had nothing to check it against — the
  /// printed receipt did the arithmetic and the screen in front of them
  /// did not.
  Widget _basketLine(BuildContext context, int index, String currency) {
    final line = _lines[index];
    final short = line.available != null && line.quantity > line.available!;
    final many = line.quantity != 1;

    return ListTile(
      title: Text(line.name),
      subtitle: Row(
        children: [
          Flexible(
            child: Text(
              many
                  ? '${Money.quantity(line.quantity)} × '
                      '${Money.amount(line.unitPrice)} = '
                      '${Money.format(line.total, currency: currency)}'
                  : Money.format(line.unitPrice, currency: currency),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (short) ...[
            const SizedBox(width: 8),
            StatusChip(
              status: 'warning',
              label: 'only ${Money.quantity(line.available)} known',
            ),
          ],
        ],
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: () => setState(() {
              if (line.quantity <= 1) {
                _lines.removeAt(index);
              } else {
                line.quantity -= 1;
              }
              _paid.text = _total.toStringAsFixed(2);
            }),
          ),
          // Twelve sacks used to be eleven taps.  The figure is the way in
          // to typing one, so it is drawn as something you can press.
          InkWell(
            onTap: () => _askQuantity(line),
            borderRadius: BorderRadius.circular(8),
            child: Container(
              constraints: const BoxConstraints(minWidth: 36),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              decoration: BoxDecoration(
                border: Border.all(color: Theme.of(context).dividerColor),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                Money.quantity(line.quantity),
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.add_circle_outline),
            onPressed: () => setState(() {
              line.quantity += 1;
              _paid.text = _total.toStringAsFixed(2);
            }),
          ),
        ],
      ),
    );
  }

  /// Type a quantity rather than tapping up to it.
  Future<void> _askQuantity(_CartLine line) async {
    final typed = await showDialog<double>(
      context: context,
      builder: (_) => _QuantityDialog(line: line),
    );
    if (!mounted || typed == null) return;
    setState(() {
      if (typed <= 0) {
        _lines.remove(line);
      } else {
        line.quantity = typed;
      }
      _paid.text = _total.toStringAsFixed(2);
    });
  }

  Widget _paymentPanel(BuildContext context, String currency) {
    final theme = Theme.of(context);
    return Material(
      elevation: 8,
      color: theme.colorScheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: DropdownButtonFormField<String>(
                      isExpanded: true,
                      value: _method,
                      decoration: const InputDecoration(
                        labelText: 'Payment',
                        isDense: true,
                      ),
                      items: _paymentMethods
                          .map((entry) => DropdownMenuItem(
                                value: entry.$1,
                                child: Text(entry.$2),
                              ))
                          .toList(),
                      onChanged: (value) =>
                          setState(() => _method = value ?? 'cash'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      key: const Key('amountPaid'),
                      controller: _paid,
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(
                        labelText: 'Received',
                        isDense: true,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                ],
              ),
              // The notes somebody is actually holding out, so the amount
              // received is one tap rather than a sum done in the head.
              if (_notes.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    for (final note in _notes)
                      ActionChip(
                        label: Text(Money.amount(note)),
                        onPressed: () => setState(
                          () => _paid.text = note.toStringAsFixed(2),
                        ),
                      ),
                  ],
                ),
              ],
              const SizedBox(height: 8),
              ListTile(
                key: const Key('customerRow'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: const Icon(Icons.person_outline),
                title: Text(_customer?.name ?? 'Walk-in customer'),
                subtitle: Text(
                  _customer?.phone ??
                      (_balance > 0
                          ? 'A customer is needed for credit'
                          : 'Optional for a cash sale'),
                ),
                trailing: TextButton(
                  onPressed: _pickCustomer,
                  child: Text(_customer == null ? 'Choose' : 'Change'),
                ),
              ),
              if (_balance > 0) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String?>(
                  isExpanded: true,
                  value: _duePreset,
                  decoration: const InputDecoration(
                    labelText: 'Payment due',
                    isDense: true,
                  ),
                  items: _duePresets
                      .map((entry) => DropdownMenuItem(
                            value: entry.$1,
                            child: Text(entry.$2),
                          ))
                      .toList(),
                  onChanged: (value) => setState(() => _duePreset = value),
                ),
                const SizedBox(height: 4),
                Text(
                  _duePreset == null
                      ? 'Without a due date this stays outstanding, but is never marked overdue.'
                      : 'A reminder is scheduled for staff. Nothing is sent to the customer.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Total', style: theme.textTheme.titleMedium),
                  Text(
                    Money.format(_total, currency: currency),
                    style: theme.textTheme.titleLarge
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ],
              ),
              // The number the counter is waiting on, said as plainly as
              // the total and in the same place every time.
              if (_change > 0)
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Change', style: theme.textTheme.titleMedium),
                    Text(
                      Money.format(_change, currency: currency),
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: EstockTheme.statusColour(
                            'ok', theme.colorScheme),
                      ),
                    ),
                  ],
                ),
              if (_balance > 0)
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('On credit', style: theme.textTheme.bodyMedium),
                    Text(
                      Money.format(_balance, currency: currency),
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: const Color(0xFF9A6200),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('completeSale'),
                onPressed: _busy ? null : _complete,
                child: Text(_busy
                    ? 'Saving…'
                    : _change > 0
                        ? 'Complete sale · '
                            '${Money.format(_change, currency: currency)} change'
                        : 'Complete sale · '
                            '${Money.format(_total, currency: currency)}'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}


/// Ask how many of one thing, for a quantity nobody wants to tap up to.
///
/// It owns its own field, and so its own controller: disposing one the
/// moment `showDialog` returns throws, because the dialog is still on
/// screen animating away and rebuilding the field as it goes.
class _QuantityDialog extends StatefulWidget {
  const _QuantityDialog({required this.line});

  final _CartLine line;

  @override
  State<_QuantityDialog> createState() => _QuantityDialogState();
}

class _QuantityDialogState extends State<_QuantityDialog> {
  late final TextEditingController _field =
      TextEditingController(text: Money.plain(widget.line.quantity));

  @override
  void dispose() {
    _field.dispose();
    super.dispose();
  }

  void _done() =>
      Navigator.of(context).pop(double.tryParse(_field.text.trim()));

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.line.name),
      content: TextField(
        key: const Key('howMany'),
        controller: _field,
        autofocus: true,
        textAlign: TextAlign.right,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: const InputDecoration(labelText: 'How many?'),
        onSubmitted: (_) => _done(),
      ),
      actions: [
        DialogActions(
          back: OutlinedButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          confirm: FilledButton(
            onPressed: _done,
            child: const Text('Set'),
          ),
        ),
      ],
    );
  }
}

/// Pick a customer from the list held on the device, or add one.
///
/// Returns the chosen customer, a customer with an empty id for "walk-in"
/// (clearing the selection), or null when dismissed.
class CustomerPicker extends StatefulWidget {
  const CustomerPicker({super.key, required this.state, this.selected});

  final AppState state;
  final Customer? selected;

  @override
  State<CustomerPicker> createState() => _CustomerPickerState();
}

class _CustomerPickerState extends State<CustomerPicker> {
  final _query = TextEditingController();
  final _newName = TextEditingController();
  final _newPhone = TextEditingController();
  bool _adding = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _query.dispose();
    _newName.dispose();
    _newPhone.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    if (_newName.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final customer = await widget.state.createCustomer(
        name: _newName.text,
        phone: _newPhone.text,
      );
      if (mounted) Navigator.of(context).pop(customer);
    } on ApiException catch (exception) {
      setState(() => _error = exception.isNetworkError
          ? 'Adding a customer needs a connection. Pick an existing one, or '
              'take cash for now.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final matches = widget.state.searchCustomers(_query.text).take(30).toList();
    final theme = Theme.of(context);
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.7,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text('Customer', style: theme.textTheme.titleMedium),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(
                      const Customer(id: '', name: 'Walk-in customer'),
                    ),
                    child: const Text('Walk-in'),
                  ),
                ],
              ),
            ),
            if (_adding) ...[
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text(_error!,
                            style: TextStyle(color: theme.colorScheme.error)),
                      ),
                    TextField(
                      key: const Key('newCustomerName'),
                      controller: _newName,
                      autofocus: true,
                      decoration: const InputDecoration(labelText: 'Name'),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('newCustomerPhone'),
                      controller: _newPhone,
                      keyboardType: TextInputType.phone,
                      decoration:
                          const InputDecoration(labelText: 'Phone (optional)'),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => setState(() => _adding = false),
                            child: const Text('Back'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: FilledButton(
                            key: const Key('saveCustomer'),
                            onPressed: _busy ? null : _create,
                            child: Text(_busy ? 'Saving…' : 'Save'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ] else ...[
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: TextField(
                  key: const Key('customerSearch'),
                  controller: _query,
                  autofocus: true,
                  decoration: const InputDecoration(
                    hintText: 'Search by name or phone',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: (_) => setState(() {}),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.person_add_outlined),
                title: const Text('Add a new customer'),
                subtitle: widget.state.sync.isOnline
                    ? null
                    : const Text('Needs a connection'),
                onTap: () => setState(() => _adding = true),
              ),
              const Divider(height: 1),
              Expanded(
                child: matches.isEmpty
                    ? const EmptyState(
                        icon: Icons.person_search_outlined,
                        title: 'No matching customer',
                        message: 'Try another name, or add them.',
                      )
                    : ListView.builder(
                        itemCount: matches.length,
                        itemBuilder: (context, index) {
                          final customer = matches[index];
                          return ListTile(
                            title: Text(customer.name),
                            subtitle: customer.phone == null
                                ? null
                                : Text(customer.phone!),
                            selected: customer.id == widget.selected?.id,
                            onTap: () => Navigator.of(context).pop(customer),
                          );
                        },
                      ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
