import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/offline/outbox.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

const _methods = <(String, String)>[
  ('cash', 'Cash'),
  ('telebirr', 'Telebirr'),
  ('cbe_birr', 'CBE Birr'),
  ('bank_transfer', 'Bank transfer'),
];

const _duePresets = <(String, String)>[
  ('today', 'Today'),
  ('tomorrow', 'Tomorrow'),
  ('7_days', 'In 7 days'),
  ('15_days', 'In 15 days'),
  ('30_days', 'In 30 days'),
];

const _followUps = <(String, String)>[
  ('called', 'Called them'),
  ('message_sent', 'Sent a message'),
  ('promise_to_pay', 'They promised to pay'),
  ('note', 'Just a note'),
];

/// One debt: what is owed, and the four things a shop does about it.
///
/// The list behind this said who owed what and stopped there, which left
/// the commonest job in the whole of credit — a customer walking in and
/// putting money on the counter — as something only a desk could do.  The
/// person holding the phone is the person being handed the notes.
class CreditDetailScreen extends StatefulWidget {
  const CreditDetailScreen({super.key, required this.transactionId});

  final String transactionId;

  @override
  State<CreditDetailScreen> createState() => _CreditDetailScreenState();
}

class _CreditDetailScreenState extends State<CreditDetailScreen> {
  Map<String, dynamic>? _row;
  List<Map<String, dynamic>> _payments = const [];
  List<Map<String, dynamic>> _activities = const [];

  /// This customer's other open debts.  One sale is not the question
  /// anybody is really asking when they decide how hard to push.
  List<Map<String, dynamic>> _alsoOwes = const [];

  bool _loading = true;
  bool _offline = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final state = AppScope.of(context);
    final id = widget.transactionId;
    try {
      final dynamic row = await state.api.get('/credit/transactions/$id');
      final dynamic payments =
          await state.api.get('/credit/transactions/$id/payments');
      final dynamic activities =
          await state.api.get('/credit/transactions/$id/activities');
      if (!mounted) return;
      setState(() {
        _row = Map<String, dynamic>.from(row as Map);
        _payments = (payments as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _activities = (activities as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _offline = false;
        _error = null;
        _loading = false;
      });
      await _loadOthers();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _error = exception.isNetworkError ? null : exception.message;
        _loading = false;
      });
    }
  }

  /// What else this customer has open, besides the one on screen.
  ///
  /// Best effort: a shop deciding whether to take 5,000 and let somebody
  /// go wants their whole exposure, but not at the cost of the screen
  /// failing when this one call does.
  Future<void> _loadOthers() async {
    final customerId = _row?['customer_id'] as String?;
    if (customerId == null) return;
    try {
      final dynamic page = await AppScope.of(context).api.get(
        '/credit/transactions',
        query: {
          'kind': 'receivable',
          'view': 'outstanding',
          'customer_id': customerId,
          'limit': '50',
        },
      );
      if (!mounted) return;
      setState(() {
        _alsoOwes = ((page as Map<String, dynamic>)['items'] as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .where((item) => item['id'] != widget.transactionId)
            .toList();
      });
    } on ApiException {
      // Not worth an error on the screen: the debt in hand is still right.
    }
  }

  /// What the rest of them come to.
  double get _elsewhere => _alsoOwes.fold(
        0,
        (sum, row) => sum + (Money.parse(row['balance']) ?? 0),
      );

  double get _balance => Money.parse(_row?['balance']) ?? 0;
  bool get _settled => _balance <= 0;

  /// The customer's number, from the copy already on the device.
  String? get _phone {
    final id = _row?['customer_id'] as String?;
    if (id == null) return null;
    final state = AppScope.of(context);
    final found = state.customers.where((c) => c.id == id);
    final phone = found.isEmpty ? null : found.first.phone;
    return (phone == null || phone.isEmpty) ? null : phone;
  }

  // ----------------------------------------------------------------- //
  // Money coming in
  // ----------------------------------------------------------------- //

  Future<void> _takePayment() async {
    final taken = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _PaymentSheet(
        balance: _balance,
        currency: AppScope.of(context).session?.currency ?? 'ETB',
      ),
    );
    if (!mounted || taken == null) return;
    await _post(
      '/credit/transactions/${widget.transactionId}/payments',
      {...taken, 'idempotency_key': Outbox.newId()},
      (body) {
        final left = Money.parse(body['balance']) ?? 0;
        return left <= 0
            ? 'Paid in full. Nothing left on this one.'
            : '${Money.amount(taken['amount'])} taken · '
                '${Money.amount(left)} still owing';
      },
    );
  }

  Future<void> _changeDueDate() async {
    final preset = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        // Five choices and a heading do not fit a short screen, so the
        // list scrolls rather than running off the bottom of it.
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
              child: Text(
                'When should it be paid?',
                style: Theme.of(sheet).textTheme.titleMedium,
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final entry in _duePresets)
                    ListTile(
                      title: Text(entry.$2),
                      onTap: () => Navigator.of(sheet).pop(entry.$1),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
    if (!mounted || preset == null) return;
    await _post(
      '/credit/transactions/${widget.transactionId}/due-date',
      {'due_date_preset': preset},
      (_) => 'Due date moved.',
      method: 'PATCH',
    );
  }

  Future<void> _logFollowUp() async {
    final logged = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const _FollowUpSheet(),
    );
    if (!mounted || logged == null) return;
    await _post(
      '/credit/transactions/${widget.transactionId}/activities',
      logged,
      (_) => 'Noted. This does not change the balance.',
    );
  }

  /// Send one thing, say what came of it, and reload.
  Future<void> _post(
    String path,
    Map<String, dynamic> body,
    String Function(Map<String, dynamic>) said, {
    String method = 'POST',
  }) async {
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _error = null);
    try {
      final dynamic response = method == 'PATCH'
          ? await state.api.patch(path, body: body)
          : await state.api.post(path, body: body);
      if (!mounted) return;
      final payload = response is Map
          ? Map<String, dynamic>.from(response)
          : <String, dynamic>{};
      messenger.showSnackBar(SnackBar(content: Text(said(payload))));
      await _load();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. Money owed is never kept on the phone, so this '
              'has to wait until you are back online.'
          : exception.message);
    }
  }

  Future<void> _call() async {
    final number = _phone;
    if (number == null) return;
    final messenger = ScaffoldMessenger.of(context);
    final uri = Uri(scheme: 'tel', path: number);
    if (!await launchUrl(uri)) {
      messenger.showSnackBar(SnackBar(content: Text('Call $number')));
    }
  }

  // ----------------------------------------------------------------- //

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final currency = state.session?.currency ?? 'ETB';
    final mayTake = state.session?.can('credit:payment') ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(_row?['counterparty_name'] as String? ?? 'Credit'),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'Credit needs a connection',
                    message:
                        'A balance is never kept on the phone, so it is '
                        'never shown — or changed — out of date.',
                  )
                : _row == null
                    ? const EmptyState(
                        icon: Icons.search_off,
                        title: 'Not found',
                        message: 'This balance is no longer there.',
                      )
                    : _body(context, currency, mayTake),
      ),
    );
  }

  Widget _body(BuildContext context, String currency, bool mayTake) {
    final theme = Theme.of(context);
    final session = AppScope.of(context).session;
    final row = _row!;
    final overdue = row['is_overdue'] as bool? ?? false;
    final due = Money.dueLabel(
      row['due_date'] as String?,
      overdue,
      row['days_overdue'] as int?,
    );
    final original = Money.parse(row['original_amount']) ?? 0;
    final paid = Money.parse(row['amount_paid']) ?? 0;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          // The balance, said once and large: the whole question somebody
          // opened this to answer.
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _settled ? 'Nothing owing' : Money.format(_balance, currency: currency),
                  style: theme.textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: _settled
                        ? EstockTheme.statusColour('ok', theme.colorScheme)
                        : overdue
                            ? theme.colorScheme.error
                            : null,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  _settled ? 'Paid in full' : due,
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: overdue && !_settled
                        ? theme.colorScheme.error
                        : theme.colorScheme.onSurfaceVariant,
                    fontWeight: overdue ? FontWeight.w600 : null,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  // Where it came from and how far along it is, so the
                  // balance is not a figure out of nowhere.
                  '${row['reference']} · '
                  '${Money.amount(paid)} paid of ${Money.amount(original)}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                if ((row['agreement_note'] as String?)?.isNotEmpty ?? false) ...[
                  const SizedBox(height: 6),
                  Text(row['agreement_note'] as String),
                ],
                // One sale is not the whole of what somebody owes, and
                // the whole of it is what decides how hard to push.
                if (_elsewhere > 0) ...[
                  const SizedBox(height: 8),
                  Text(
                    _alsoOwes.length == 1
                        ? 'Also owes ${Money.format(_elsewhere, currency: currency)} on one other sale'
                        : 'Also owes ${Money.format(_elsewhere, currency: currency)} on ${_alsoOwes.length} other sales',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
              child: Text(
                _error!,
                style: TextStyle(color: theme.colorScheme.error),
              ),
            ),
          // The thing people come here to do.
          if (!_settled && mayTake)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: FilledButton.icon(
                key: const Key('takePayment'),
                onPressed: _takePayment,
                icon: const Icon(Icons.payments_outlined),
                label: const Text('Take a payment'),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 4,
              alignment: WrapAlignment.center,
              children: [
                if (_phone != null)
                  TextButton.icon(
                    onPressed: _call,
                    icon: const Icon(Icons.phone_outlined),
                    label: Text(_phone!),
                  ),
                // Each of these is its own permission on the server, so
                // each is offered on its own: somebody who may log a call
                // is not thereby somebody who may take the money.
                if (session?.can('credit:followup') ?? false)
                  TextButton.icon(
                    onPressed: _logFollowUp,
                    icon: const Icon(Icons.edit_note_outlined),
                    label: const Text('Log a call'),
                  ),
                if (!_settled && (session?.can('credit:duedate') ?? false))
                  TextButton.icon(
                    onPressed: _changeDueDate,
                    icon: const Icon(Icons.event_outlined),
                    label: const Text('Change the date'),
                  ),
              ],
            ),
          ),
          const Divider(height: 1),
          _section(context, 'Paid so far'),
          if (_payments.isEmpty)
            _muted(context, 'Nothing has been paid yet.')
          else
            for (final payment in _payments)
              ListTile(
                dense: true,
                leading: Icon(
                  (payment['is_reversed'] as bool? ?? false)
                      ? Icons.undo
                      : Icons.check_circle_outline,
                  color: (payment['is_reversed'] as bool? ?? false)
                      ? theme.colorScheme.onSurfaceVariant
                      : EstockTheme.statusColour('ok', theme.colorScheme),
                ),
                title: Text(
                  Money.format(payment['amount'], currency: currency),
                  style: TextStyle(
                    decoration: (payment['is_reversed'] as bool? ?? false)
                        ? TextDecoration.lineThrough
                        : null,
                  ),
                ),
                subtitle: Text(
                  [
                    _methodLabel(payment['method'] as String?),
                    Money.dateTime(DateTime.tryParse('${payment['paid_at']}')),
                    if (payment['reference'] != null) '${payment['reference']}',
                    if (payment['is_reversed'] as bool? ?? false)
                      'reversed — ${payment['reversal_reason'] ?? 'no reason given'}',
                  ].join(' · '),
                ),
              ),
          const Divider(height: 1),
          _section(context, 'What has been said'),
          if (_activities.isEmpty)
            _muted(context, 'Nothing logged yet.')
          else
            for (final activity in _activities)
              ListTile(
                dense: true,
                title: Text(_followUpLabel(activity['kind'] as String?)),
                subtitle: Text(
                  [
                    Money.dateTime(
                        DateTime.tryParse('${activity['occurred_at']}')),
                    if (activity['promised_amount'] != null)
                      'promised ${Money.amount(activity['promised_amount'])}'
                          '${activity['promised_date'] != null ? ' by ${activity['promised_date']}' : ''}',
                    if ((activity['note'] as String?)?.isNotEmpty ?? false)
                      '${activity['note']}',
                  ].join(' · '),
                ),
              ),
        ],
      ),
    );
  }

  Widget _section(BuildContext context, String label) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
        child: Text(label, style: Theme.of(context).textTheme.titleSmall),
      );

  Widget _muted(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
        child: Text(
          text,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
      );

  static String _methodLabel(String? method) => _methods
      .where((entry) => entry.$1 == method)
      .map((entry) => entry.$2)
      .firstOrNull ??
      (method ?? '');

  static String _followUpLabel(String? kind) => _followUps
      .where((entry) => entry.$1 == kind)
      .map((entry) => entry.$2)
      .firstOrNull ??
      (kind ?? '').replaceAll('_', ' ');
}

/// Money across the counter: how much, and how it came.
class _PaymentSheet extends StatefulWidget {
  const _PaymentSheet({required this.balance, required this.currency});

  final double balance;
  final String currency;

  @override
  State<_PaymentSheet> createState() => _PaymentSheetState();
}

class _PaymentSheetState extends State<_PaymentSheet> {
  late final TextEditingController _amount =
      TextEditingController(text: Money.plain(widget.balance));
  final _note = TextEditingController();
  String _method = 'cash';

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  double get _typed => double.tryParse(_amount.text.trim()) ?? 0;
  bool get _ready => _typed > 0 && _typed <= widget.balance;

  /// Part payments a customer is likely to make: a half, and round
  /// amounts below what is owed.  Somebody paying off a debt rarely has
  /// the whole of it, and typing is the slow part.
  List<double> get _parts {
    if (widget.balance <= 0) return const [];
    final steps = [500, 1000, 5000];
    final seen = <double>{};
    for (final step in steps) {
      final down = (widget.balance / step).floor() * step.toDouble();
      if (down > 0 && down < widget.balance) seen.add(down);
    }
    final sorted = seen.toList()..sort((a, b) => b.compareTo(a));
    return sorted.take(2).toList();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final over = _typed > widget.balance;

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Take a payment', style: theme.textTheme.titleMedium),
                    Text(
                      '${Money.format(widget.balance, currency: widget.currency)} owing',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              TextField(
                key: const Key('paymentAmount'),
                controller: _amount,
                autofocus: true,
                textAlign: TextAlign.right,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                ],
                decoration: InputDecoration(
                  labelText: 'How much',
                  suffixText: widget.currency,
                  errorText: over
                      ? 'More than is owed. Take the balance, or less.'
                      : null,
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (_parts.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    for (final part in _parts)
                      ActionChip(
                        label: Text(Money.amount(part)),
                        onPressed: () => setState(
                          () => _amount.text = Money.plain(part),
                        ),
                      ),
                    ActionChip(
                      label: const Text('All of it'),
                      onPressed: () => setState(
                        () => _amount.text = Money.plain(widget.balance),
                      ),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: _method,
                decoration: const InputDecoration(labelText: 'How it came'),
                items: [
                  for (final entry in _methods)
                    DropdownMenuItem(value: entry.$1, child: Text(entry.$2)),
                ],
                onChanged: (value) =>
                    setState(() => _method = value ?? 'cash'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _note,
                decoration: const InputDecoration(
                  labelText: 'Note',
                  hintText: 'optional — a receipt number, say',
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('confirmPayment'),
                onPressed: !_ready
                    ? null
                    : () => Navigator.of(context).pop({
                          'amount': _amount.text.trim(),
                          'method': _method,
                          if (_note.text.trim().isNotEmpty)
                            'note': _note.text.trim(),
                        }),
                child: Text(
                  _typed <= 0
                      ? 'Type what they handed over'
                      : over
                          ? 'That is more than is owed'
                          : 'Take ${Money.format(_typed, currency: widget.currency)}',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A call made, a message sent, a promise given.  Changes no money.
class _FollowUpSheet extends StatefulWidget {
  const _FollowUpSheet();

  @override
  State<_FollowUpSheet> createState() => _FollowUpSheetState();
}

class _FollowUpSheetState extends State<_FollowUpSheet> {
  final _note = TextEditingController();
  final _promised = TextEditingController();
  String _kind = 'called';

  @override
  void dispose() {
    _note.dispose();
    _promised.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final promising = _kind == 'promise_to_pay';

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
                child: Text(
                  'What happened?',
                  style: theme.textTheme.titleMedium,
                ),
              ),
              Wrap(
                spacing: 8,
                children: [
                  for (final entry in _followUps)
                    ChoiceChip(
                      label: Text(entry.$2),
                      selected: _kind == entry.$1,
                      showCheckmark: false,
                      onSelected: (_) => setState(() => _kind = entry.$1),
                    ),
                ],
              ),
              if (promising) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _promised,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                  ],
                  decoration: const InputDecoration(
                    labelText: 'How much did they promise',
                    hintText: 'optional',
                  ),
                ),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: _note,
                decoration: const InputDecoration(
                  labelText: 'Note',
                  hintText: 'optional — what they said',
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('confirmFollowUp'),
                onPressed: () => Navigator.of(context).pop({
                  'kind': _kind,
                  if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
                  if (promising && _promised.text.trim().isNotEmpty)
                    'promised_amount': _promised.text.trim(),
                }),
                child: const Text('Log it'),
              ),
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
