import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/sale.dart';
import '../models/session.dart';
import '../widgets/common.dart';
import 'sale_return_screen.dart';

/// One sale, as the customer's copy of it.
///
/// A receipt is the only record of this business a customer takes away, so
/// the phone has to be able to produce it again — and on an Ethiopian counter
/// that means sending it, not printing it. Copying puts the whole receipt on
/// the clipboard, ready to paste into Telegram, WhatsApp or SMS, which needs
/// no printer, no PDF and no extra permission.
///
/// Voiding and taking goods back live here too, each behind its own
/// permission, because this is the screen somebody is already on when a
/// customer comes back.
class SaleDetailScreen extends StatefulWidget {
  const SaleDetailScreen({super.key, required this.saleId});

  final String saleId;

  @override
  State<SaleDetailScreen> createState() => _SaleDetailScreenState();
}

class _SaleDetailScreenState extends State<SaleDetailScreen> {
  Sale? _sale;
  Receipt? _receipt;
  bool _loading = true;
  bool _offline = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      // Two calls, together: the sale carries the status, the returns and the
      // profit; the receipt carries the shop's own name and address.
      final results = await Future.wait([
        state.api.get('/sales/${widget.saleId}'),
        state.api.get('/sales/${widget.saleId}/receipt'),
      ]);
      if (!mounted) return;
      setState(() {
        _sale = Sale.fromJson(Map<String, dynamic>.from(results[0] as Map));
        _receipt = Receipt.fromJson(Map<String, dynamic>.from(results[1] as Map));
        _offline = false;
        _error = null;
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

  /// The receipt as plain text, laid out the way a paper one reads.
  String _asText(Receipt receipt) {
    final out = StringBuffer()..writeln(receipt.businessName);
    final where = [receipt.branchName, receipt.address, receipt.phone]
        .whereType<String>()
        .where((part) => part.isNotEmpty)
        .join(' · ');
    if (where.isNotEmpty) out.writeln(where);
    if (receipt.tin != null) out.writeln('TIN ${receipt.tin}');
    out
      ..writeln()
      ..writeln('${receipt.number}  ·  ${Money.dateTime(receipt.soldAt)}');
    if (receipt.customerName != null) {
      out.writeln('Customer: ${receipt.customerName}');
    }
    out.writeln();
    for (final line in receipt.lines) {
      out.writeln(line.description);
      out.writeln('  ${Money.quantity(line.quantity)} × '
          '${Money.amount(line.unitPrice)} = ${Money.amount(line.lineTotal)}');
    }
    out.writeln();
    if (receipt.discountTotal > 0) {
      out.writeln('Discount  −${Money.amount(receipt.discountTotal)}');
    }
    if (receipt.taxTotal > 0) {
      out.writeln('Tax  ${Money.amount(receipt.taxTotal)}');
    }
    out.writeln('Total  ${Money.format(receipt.total, currency: receipt.currency)}');
    for (final payment in receipt.payments) {
      out.writeln(payment.isRefund
          ? 'Refunded by ${payment.label}  −${Money.amount(payment.amount)}'
          : 'Paid by ${payment.label}  ${Money.amount(payment.amount)}');
    }
    if (receipt.balanceDue > 0) {
      out.writeln('Balance on credit  ${Money.amount(receipt.balanceDue)}');
    }
    out.writeln();
    out.writeln('Thank you for your business.');
    return out.toString();
  }

  Future<void> _copy() async {
    final receipt = _receipt;
    if (receipt == null) return;
    final messenger = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: _asText(receipt)));
    messenger.showSnackBar(const SnackBar(
      content: Text('Receipt copied. Paste it into a message to send it.'),
    ));
  }

  Future<void> _void() async {
    final api = AppScope.of(context).api;
    final reason = await askForReason(
      context,
      title: 'Void this sale?',
      body: 'The goods go back on the shelf and the sale is kept as a record. '
          'Nothing is deleted.',
      label: 'Why',
      confirm: 'Void it',
      // The server asks for three characters too; saying so here saves a
      // round trip and a refusal.
      minLength: 3,
    );
    if (reason == null) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await api.post('/sales/${widget.saleId}/void', body: {'reason': reason});
      await _load();
      if (mounted) await AppScope.of(context).refresh();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _takeBack() async {
    final state = AppScope.of(context);
    final done = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => SaleReturnScreen(saleId: widget.saleId),
      ),
    );
    if (done ?? false) {
      await _load();
      await state.refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;
    final sale = _sale;
    final receipt = _receipt;
    final writable = !(session?.readOnly ?? false);

    return Scaffold(
      appBar: AppBar(
        title: Text(sale == null ? 'Sale' : 'Sale ${sale.number}'),
        actions: [
          if (receipt != null)
            IconButton(
              tooltip: 'Copy the receipt',
              icon: const Icon(Icons.copy_all_outlined),
              onPressed: _copy,
            ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'This receipt needs a connection',
                    message:
                        'The sale is safe on the server; the phone just '
                        'cannot fetch it right now.',
                  )
                : sale == null || receipt == null
                    ? EmptyState(
                        icon: Icons.error_outline,
                        title: 'Could not open this sale',
                        message: _error,
                      )
                    : ListView(
                        padding: const EdgeInsets.only(bottom: 24),
                        children: [
                          if (_error != null)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                              child: Text(
                                _error!,
                                style: TextStyle(
                                    color: Theme.of(context).colorScheme.error),
                              ),
                            ),
                          if (sale.isVoided) _voidedBanner(context),
                          _receiptCard(context, receipt, sale),
                          if (sale.hasReturns) _returnsCard(context, sale),
                          if (sale.grossProfit != null) _profitCard(context, sale),
                          if (writable && !sale.isVoided)
                            _actions(context, session),
                        ],
                      ),
      ),
    );
  }

  Widget _voidedBanner(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      child: Material(
        color: theme.colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(
            'This sale was voided. Its stock went back and the record is kept '
            'for the audit trail.',
            style: TextStyle(color: theme.colorScheme.onErrorContainer),
          ),
        ),
      ),
    );
  }

  Widget _receiptCard(BuildContext context, Receipt receipt, Sale sale) {
    final theme = Theme.of(context);
    final where = [receipt.branchName, receipt.address, receipt.phone]
        .whereType<String>()
        .where((part) => part.isNotEmpty)
        .join(' · ');

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Column(
                children: [
                  Text(receipt.businessName,
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700)),
                  if (where.isNotEmpty)
                    Text(
                      where,
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  if (receipt.tin != null)
                    Text(
                      'TIN ${receipt.tin}',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                ],
              ),
            ),
            const Divider(height: 20),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(receipt.number,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(Money.dateTime(receipt.soldAt),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              ],
            ),
            if (receipt.customerName != null)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  [
                    receipt.customerName!,
                    if (receipt.customerPhone != null) receipt.customerPhone!,
                  ].join(' · '),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ),
            const Divider(height: 20),
            for (final line in receipt.lines) ...[
              Text(line.description),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '${Money.quantity(line.quantity)} × '
                    '${Money.amount(line.unitPrice)}'
                    '${line.discount > 0 ? '  −${Money.amount(line.discount)}' : ''}',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                  Text(Money.amount(line.lineTotal)),
                ],
              ),
              const SizedBox(height: 8),
            ],
            const Divider(height: 12),
            if (receipt.discountTotal > 0)
              _figure(context, 'Discount', '−${Money.amount(receipt.discountTotal)}'),
            if (receipt.taxTotal > 0)
              _figure(context, 'Tax', Money.amount(receipt.taxTotal)),
            _figure(
              context,
              'Total',
              Money.format(receipt.total, currency: receipt.currency),
              strong: true,
            ),
            for (final payment in receipt.payments)
              _figure(
                context,
                payment.isRefund
                    ? 'Refunded by ${payment.label}'
                    : 'Paid by ${payment.label}',
                payment.isRefund
                    ? '−${Money.amount(payment.amount)}'
                    : Money.amount(payment.amount),
              ),
            if (receipt.balanceDue > 0)
              _figure(context, 'Balance on credit',
                  Money.amount(receipt.balanceDue),
                  strong: true),
            if (sale.returnedTotal > 0)
              _figure(context, 'Returned',
                  '−${Money.amount(sale.returnedTotal)}'),
          ],
        ),
      ),
    );
  }

  Widget _figure(BuildContext context, String label, String value,
      {bool strong = false}) {
    final theme = Theme.of(context);
    final style = strong
        ? theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)
        : theme.textTheme.bodyMedium
            ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [Text(label, style: style), Text(value, style: style)],
      ),
    );
  }

  Widget _returnsCard(BuildContext context, Sale sale) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Came back',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            for (final item in sale.returns)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(item.number),
                        Text(Money.format(item.total, currency: sale.currency)),
                      ],
                    ),
                    Text(
                      [
                        item.reason,
                        if (item.refunded > 0)
                          '${Money.amount(item.refunded)} refunded',
                        if (item.credited > 0)
                          '${Money.amount(item.credited)} off what was owed',
                        Money.dateTime(item.returnedAt),
                      ].join(' · '),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _profitCard(BuildContext context, Sale sale) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('For the books',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            _figure(context, 'Cost of goods',
                Money.format(sale.costTotal, currency: sale.currency)),
            _figure(context, 'Gross profit',
                Money.format(sale.grossProfit, currency: sale.currency),
                strong: true),
            Text(
              'Sale-time cost snapshots, excluding tax',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _actions(BuildContext context, UserSession? session) {
    final mayRefund = session?.can('sale:refund') ?? false;
    final mayVoid = session?.can('sale:void') ?? false;
    if (!mayRefund && !mayVoid) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Column(
        children: [
          if (mayRefund)
            OutlinedButton.icon(
              onPressed: _busy ? null : _takeBack,
              icon: const Icon(Icons.assignment_return_outlined),
              label: const Text('Take goods back'),
            ),
          if (mayRefund && mayVoid) const SizedBox(height: 8),
          if (mayVoid)
            OutlinedButton.icon(
              onPressed: _busy ? null : _void,
              icon: const Icon(Icons.block_outlined),
              label: const Text('Void this sale'),
            ),
          const SizedBox(height: 8),
          Text(
            mayRefund
                ? 'Taking part of it back keeps the sale; voiding reverses all '
                    'of it.'
                : 'Voiding reverses the whole sale and keeps the record.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}
