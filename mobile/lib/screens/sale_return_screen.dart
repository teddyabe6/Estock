import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
import '../models/sale.dart';
import '../widgets/common.dart';

/// A customer bringing something back (PRD 1, 10).
///
/// The counter is where this happens, so the phone is the right place for it.
/// It asks only what the person behind the counter can answer: how many of
/// each line are coming back, whether they can be sold again, and why. Stock,
/// value and money all follow on the server from the sale's own lines — an
/// outstanding balance absorbs the value before any cash leaves the till.
class SaleReturnScreen extends StatefulWidget {
  const SaleReturnScreen({super.key, required this.saleId});

  final String saleId;

  @override
  State<SaleReturnScreen> createState() => _SaleReturnScreenState();
}

class _SaleReturnScreenState extends State<SaleReturnScreen> {
  final _reason = TextEditingController();
  final _quantities = <String, TextEditingController>{};
  final _restock = <String, bool>{};

  List<ReturnableLine> _lines = const [];
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
    _reason.dispose();
    for (final field in _quantities.values) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic payload =
          await state.api.get('/sales/${widget.saleId}/returnable');
      if (!mounted) return;
      setState(() {
        _lines = ((payload as Map<String, dynamic>)['lines'] as List<dynamic>)
            .map((item) => ReturnableLine.fromJson(Map<String, dynamic>.from(item as Map)))
            .where((line) => line.returnable > 0)
            .toList();
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

  /// What the counter has actually typed, within what each line can give back.
  Map<String, double> get _coming {
    final coming = <String, double>{};
    for (final line in _lines) {
      final text = _quantities[line.saleLineId]?.text.trim() ?? '';
      if (text.isEmpty) continue;
      final typed = double.tryParse(text);
      if (typed == null || typed <= 0) continue;
      coming[line.saleLineId] =
          typed > line.returnable ? line.returnable : typed;
    }
    return coming;
  }

  bool get _ready => _coming.isNotEmpty && _reason.text.trim().length >= 3;

  /// True where somebody typed more than the line can give back.
  bool _overTyped(ReturnableLine line) {
    final typed = double.tryParse(_quantities[line.saleLineId]?.text.trim() ?? '');
    return typed != null && typed > line.returnable;
  }

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final currency = state.session?.currency ?? 'ETB';
    try {
      final dynamic created =
          await state.api.post('/sales/${widget.saleId}/returns', body: {
        'lines': [
          for (final entry in _coming.entries)
            {
              'sale_line_id': entry.key,
              'quantity': entry.value.toString(),
              'restock': _restock[entry.key] ?? true,
            }
        ],
        'reason': _reason.text.trim(),
        'idempotency_key': _idempotencyKey,
      });
      final result = SaleReturn.fromJson(Map<String, dynamic>.from(created as Map));
      _idempotencyKey = Outbox.newId();
      messenger.showSnackBar(SnackBar(
        content: Text(
          [
            result.number,
            if (result.refunded > 0)
              '${Money.format(result.refunded, currency: currency)} back',
            if (result.credited > 0)
              '${Money.format(result.credited, currency: currency)} off what was owed',
          ].join(' · '),
        ),
      ));
      navigator.pop(true);
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A return moves stock and money, so it cannot '
              'wait in the outbox.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final coming = _coming.length;

    return Scaffold(
      appBar: AppBar(title: const Text('Take goods back')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'A return needs a connection',
                    message:
                        'It moves stock and money together, so it cannot wait '
                        'in the outbox the way a sale can.',
                  )
                : _lines.isEmpty
                    ? const EmptyState(
                        icon: Icons.assignment_turned_in_outlined,
                        title: 'Nothing left to come back',
                        message:
                            'Every line of this sale has already been '
                            'returned.',
                      )
                    : Column(
                        children: [
                          Expanded(
                            child: ListView(
                              padding: const EdgeInsets.only(bottom: 8),
                              children: [
                                Padding(
                                  padding:
                                      const EdgeInsets.fromLTRB(16, 12, 16, 4),
                                  child: Text(
                                    'Type how many of each are coming back. '
                                    'Anything not fit to sell again still '
                                    'comes back on the ledger and is then '
                                    'written off, so the loss has a reason.',
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(
                                          color: Theme.of(context)
                                              .colorScheme
                                              .onSurfaceVariant,
                                        ),
                                  ),
                                ),
                                for (final line in _lines) _line(context, line),
                                Padding(
                                  padding:
                                      const EdgeInsets.fromLTRB(16, 12, 16, 0),
                                  child: TextField(
                                    controller: _reason,
                                    decoration: const InputDecoration(
                                      labelText: 'Why it is coming back',
                                      hintText: 'e.g. wrong size',
                                    ),
                                    onChanged: (_) => setState(() {}),
                                  ),
                                ),
                                if (_error != null)
                                  Padding(
                                    padding: const EdgeInsets.fromLTRB(
                                        16, 12, 16, 0),
                                    child: Text(
                                      _error!,
                                      style: TextStyle(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .error,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          SafeArea(
                            top: false,
                            child: Padding(
                              padding:
                                  const EdgeInsets.fromLTRB(16, 8, 16, 12),
                              child: FilledButton(
                                onPressed: _saving || !_ready ? null : _submit,
                                child: Text(
                                  _saving
                                      ? 'Saving…'
                                      : coming == 0
                                          ? 'Type what is coming back'
                                          : _reason.text.trim().length < 3
                                              ? 'Say why it is coming back'
                                              : 'Take back $coming '
                                                  'line${coming == 1 ? '' : 's'}',
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
      ),
    );
  }

  Widget _line(BuildContext context, ReturnableLine line) {
    final theme = Theme.of(context);
    final field =
        _quantities.putIfAbsent(line.saleLineId, TextEditingController.new);
    final typed = (double.tryParse(field.text.trim()) ?? 0) > 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          title: Text(line.description),
          subtitle: Text(
            [
              '${Money.quantity(line.returnable)} can come back',
              '${Money.amount(line.unitPrice)} each',
              if (line.returned > 0)
                '${Money.quantity(line.returned)} already back',
            ].join(' · '),
            style: _overTyped(line)
                ? TextStyle(color: theme.colorScheme.error)
                : null,
          ),
          trailing: SizedBox(
            width: 128,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Expanded(
                  child: TextField(
                    controller: field,
                    textAlign: TextAlign.right,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                    ],
                    decoration: InputDecoration(
                      isDense: true,
                      errorText: _overTyped(line) ? '' : null,
                      errorStyle: const TextStyle(height: 0),
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ),
                // Most returns are the whole line, so it is one tap.
                TextButton(
                  onPressed: () => setState(() {
                    field.text = Money.plain(line.returnable);
                  }),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    minimumSize: const Size(36, 36),
                  ),
                  child: const Text('All'),
                ),
              ],
            ),
          ),
        ),
        // Only once something is coming back: until then it is a question
        // about nothing.
        if (typed)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: const Text('Fit to sell again'),
              subtitle: Text(
                (_restock[line.saleLineId] ?? true)
                    ? 'Goes back on the shelf'
                    : 'Comes back and is written off',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              value: _restock[line.saleLineId] ?? true,
              onChanged: (value) =>
                  setState(() => _restock[line.saleLineId] = value),
            ),
          ),
        if (_overTyped(line))
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              'Only ${Money.quantity(line.returnable)} of this line can come '
              'back; that is what will be taken.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.error),
            ),
          ),
      ],
    );
  }
}
