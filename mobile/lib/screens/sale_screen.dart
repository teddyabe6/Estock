import 'dart:async';

import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
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
  String? _customerId;
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

    if (_balance > 0 && _customerId == null) {
      messenger.showSnackBar(const SnackBar(
        content: Text('Choose a customer before selling on credit.'),
      ));
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
        if (_customerId != null) 'customer_id': _customerId,
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
        _customerId = null;
        _duePreset = null;
        _idempotencyKey = Outbox.newId();
      });
      // Refresh stock figures where possible; harmless when offline.
      unawaited(state.refresh());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
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
