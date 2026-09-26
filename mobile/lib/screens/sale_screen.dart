import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
import '../models/customer.dart';
import '../models/product.dart';
import '../widgets/common.dart';

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
  double get _paidAmount => double.tryParse(_paid.text.trim()) ?? 0;
  double get _balance => (_total - _paidAmount).clamp(0, double.infinity);

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

      final response = await state.sync.submit(
        path: '/sales',
        body: body,
        summary: 'Sale · ${Money.format(_total, currency: state.session?.currency ?? 'ETB')}',
      );

      if (!mounted) return;
      final queued = response == null;
      final number = queued
          ? null
          : ((response['sale'] as Map?)?['number'] as String?);

      messenger.showSnackBar(SnackBar(
        content: Text(queued
            ? 'Saved on this phone. It will sync when you are back online.'
            : 'Sale $number recorded.'),
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
                  itemBuilder: (context, index) {
                    final line = _lines[index];
                    final short = line.available != null &&
                        line.quantity > line.available!;
                    return ListTile(
                      title: Text(line.name),
                      subtitle: Row(
                        children: [
                          Text(Money.format(line.unitPrice, currency: currency)),
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
                          Text(Money.quantity(line.quantity)),
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
                  },
                ),
        ),
        if (_lines.isNotEmpty) _paymentPanel(context, currency),
      ],
    );
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
                    : 'Complete sale · ${Money.format(_total, currency: currency)}'),
              ),
            ],
          ),
        ),
      ),
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
