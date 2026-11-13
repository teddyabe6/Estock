import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../models/customer.dart';
import 'customers_screen.dart';

/// The part of a phone number that says whose it is, however it was typed:
/// "0911 22 33 44", "+251911223344" and "911223344" are one number.
String phoneKey(String? phone) {
  final digits = (phone ?? '').replaceAll(RegExp(r'\D'), '');
  return digits.length > 9 ? digits.substring(digits.length - 9) : digits;
}

/// What happens when a customer goes past the most they may owe.
const creditLimitRules = <(String?, String)>[
  (null, 'The shop’s usual rule'),
  ('warn', 'Warn me, but let the sale go'),
  ('require_approval', 'A manager has to allow it'),
  ('block', 'Do not allow it'),
];

/// Add a customer, or change one, from the phone.
///
/// Only the name is needed.  The phone number comes next because it is how
/// a customer is found again and called about what they owe; the rest is
/// what a shopkeeper would otherwise keep in their head.
class CustomerFormScreen extends StatefulWidget {
  const CustomerFormScreen({
    super.key,
    this.customer,
    this.name,
    this.returnCustomer = false,
  });

  /// The customer being changed; null to add one.
  final Customer? customer;

  /// What somebody searched for and did not find, to start the name with.
  final String? name;

  /// Hand the customer back to whoever opened this, rather than opening
  /// their page.
  final bool returnCustomer;

  @override
  State<CustomerFormScreen> createState() => _CustomerFormScreenState();
}

class _CustomerFormScreenState extends State<CustomerFormScreen> {
  Customer? get _customer => widget.customer;
  bool get _editing => _customer != null;

  late final _name = TextEditingController(
      text: _customer?.name ?? widget.name?.trim() ?? '');
  late final _phone = TextEditingController(text: _customer?.phone ?? '');
  late final _company = TextEditingController(text: _customer?.company ?? '');
  late final _address = TextEditingController(text: _customer?.address ?? '');
  late final _notes = TextEditingController(text: _customer?.notes ?? '');
  late final _telegram =
      TextEditingController(text: _customer?.telegramUsername ?? '');
  late final _email = TextEditingController(text: _customer?.email ?? '');
  late final _limit = TextEditingController(
    text: _plain(_customer?.creditLimit),
  );
  late String? _rule = _customer?.creditLimitBehaviour;
  late bool _more = _editing &&
      [
        _customer?.telegramUsername,
        _customer?.email,
        _customer?.creditLimit,
      ].any((value) => (value ?? '').isNotEmpty);
  bool _busy = false;
  String? _error;

  static String _plain(String? value) {
    final parsed = double.tryParse(value ?? '');
    if (parsed == null) return '';
    return parsed == parsed.roundToDouble()
        ? parsed.toStringAsFixed(0)
        : parsed.toString();
  }

  @override
  void dispose() {
    for (final field in [
      _name,
      _phone,
      _company,
      _address,
      _notes,
      _telegram,
      _email,
      _limit,
    ]) {
      field.dispose();
    }
    super.dispose();
  }

  /// Somebody else already saved with this number, as far as this phone
  /// knows.  Said, not forbidden: a husband and wife can share a phone.
  Customer? _sameNumber(AppState state) {
    final key = phoneKey(_phone.text);
    if (key.length < 9) return null;
    return state.customers
        .where((c) => c.id != _customer?.id && phoneKey(c.phone) == key)
        .firstOrNull;
  }

  bool get _limitRight {
    final text = _limit.text.trim();
    if (text.isEmpty) return true;
    final value = double.tryParse(text);
    return value != null && value >= 0;
  }

  bool get _emailRight {
    final text = _email.text.trim();
    return text.isEmpty || RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(text);
  }

  /// What the edit changes, and nothing else — an emptied field is sent as
  /// nothing, so it is cleared rather than left as it was.
  Map<String, dynamic> _changes(AppState state) {
    final customer = _customer!;
    final mayLimit = state.session?.can('credit:limit_override') ?? false;
    String? value(TextEditingController field) {
      final text = field.text.trim();
      return text.isEmpty ? null : text;
    }

    return {
      if (_name.text.trim() != customer.name) 'name': _name.text.trim(),
      if (value(_phone) != customer.phone) 'phone': value(_phone),
      if (value(_company) != customer.company) 'company': value(_company),
      if (value(_address) != customer.address) 'address': value(_address),
      if (value(_notes) != customer.notes) 'notes': value(_notes),
      if (value(_telegram) != customer.telegramUsername)
        'telegram_username': value(_telegram),
      if (value(_email) != customer.email) 'email': value(_email),
      if (mayLimit && _limit.text.trim() != _plain(customer.creditLimit))
        'credit_limit': value(_limit),
      if (mayLimit && _rule != customer.creditLimitBehaviour)
        'credit_limit_behaviour': _rule,
    };
  }

  (String, bool) _button(AppState state) {
    if (_name.text.trim().isEmpty) return ('Give them a name first', false);
    if (!_emailRight) return ('Check the email address', false);
    if (!_limitRight) return ('Check the most they may owe', false);
    if (_editing) {
      return _changes(state).isEmpty
          ? ('Nothing has changed', false)
          : ('Save the changes', true);
    }
    if (_phone.text.trim().isEmpty) {
      return ('Add them without a phone number', true);
    }
    return ('Add this customer', true);
  }

  Future<void> _save() async {
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final mayLimit = state.session?.can('credit:limit_override') ?? false;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final dynamic saved;
      if (_editing) {
        saved = await state.api.patch(
          '/customers/${_customer!.id}',
          body: _changes(state),
        );
      } else {
        String? value(TextEditingController field) {
          final text = field.text.trim();
          return text.isEmpty ? null : text;
        }

        saved = await state.api.post('/customers', body: {
          'name': _name.text.trim(),
          if (value(_phone) != null) 'phone': value(_phone),
          if (value(_company) != null) 'company': value(_company),
          if (value(_address) != null) 'address': value(_address),
          if (value(_notes) != null) 'notes': value(_notes),
          if (value(_telegram) != null) 'telegram_username': value(_telegram),
          if (value(_email) != null) 'email': value(_email),
          if (mayLimit && value(_limit) != null) 'credit_limit': value(_limit),
          if (mayLimit && _rule != null) 'credit_limit_behaviour': _rule,
        });
      }
      final customer = Customer.fromJson(Map<String, dynamic>.from(saved as Map));
      // Into the list on the phone, so the till finds them straight away.
      await state.putCustomer(customer);
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text(_editing ? 'Saved.' : 'Added ${customer.name}.'),
      ));
      if (_editing || widget.returnCustomer) {
        navigator.pop(customer);
      } else {
        await navigator.pushReplacement<void, void>(MaterialPageRoute(
          builder: (_) => CustomerScreen(customerId: customer.id),
        ));
      }
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A customer is not kept on the phone until the '
              'server has them, so this has to wait until you are back online.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final mayLimit = state.session?.can('credit:limit_override') ?? false;
    final currency = state.session?.currency ?? 'ETB';
    final same = _sameNumber(state);
    final (label, ready) = _button(state);

    void changed(_) => setState(() {});

    return Scaffold(
      appBar: AppBar(
        title: Text(_editing ? 'Change ${_customer!.name}' : 'A new customer'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            TextField(
              key: const Key('customerName'),
              controller: _name,
              autofocus: !_editing && _name.text.isEmpty,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'Their name',
                hintText: 'Yonas Alemu, say',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('customerPhone'),
              controller: _phone,
              keyboardType: TextInputType.phone,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9+ \-]')),
              ],
              decoration: const InputDecoration(
                labelText: 'Phone number',
                hintText: '09…',
                helperText: 'How you find them again, and call about money owed',
              ),
              onChanged: changed,
            ),
            if (same != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Material(
                  color: theme.colorScheme.tertiaryContainer,
                  borderRadius: BorderRadius.circular(10),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${same.name} already has this number.',
                            style: TextStyle(
                              color: theme.colorScheme.onTertiaryContainer,
                            ),
                          ),
                        ),
                        TextButton(
                          key: const Key('openSameNumber'),
                          onPressed: () => Navigator.of(context).push<void>(
                            MaterialPageRoute(
                              builder: (_) =>
                                  CustomerScreen(customerId: same.id),
                            ),
                          ),
                          child: const Text('Open them'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('customerCompany'),
              controller: _company,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'Their business',
                helperText: 'optional — for a shop or a company',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('customerAddress'),
              controller: _address,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Where they are',
                hintText: 'Bole, near Edna Mall',
                helperText: 'optional — for deliveries',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('customerNotes'),
              controller: _notes,
              minLines: 2,
              maxLines: 4,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Anything to remember',
                hintText: 'Pays on Fridays, say',
                alignLabelWithHint: true,
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: const Key('customerMore'),
                onPressed: () => setState(() => _more = !_more),
                icon: Icon(_more ? Icons.expand_less : Icons.expand_more),
                label: Text(_more ? 'Fewer details' : 'More details'),
              ),
            ),
            if (_more) ...[
              TextField(
                key: const Key('customerTelegram'),
                controller: _telegram,
                decoration: const InputDecoration(
                  labelText: 'Telegram username',
                  prefixText: '@',
                ),
                onChanged: changed,
              ),
              const SizedBox(height: 14),
              TextField(
                key: const Key('customerEmail'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: InputDecoration(
                  labelText: 'Email',
                  errorText: _emailRight ? null : 'That is not an email address',
                ),
                onChanged: changed,
              ),
              if (mayLimit) ...[
                const SizedBox(height: 14),
                TextField(
                  key: const Key('customerLimit'),
                  controller: _limit,
                  textAlign: TextAlign.right,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                  ],
                  decoration: InputDecoration(
                    labelText: 'The most they may owe',
                    suffixText: currency,
                    helperText: 'Leave it empty for no limit',
                  ),
                  onChanged: changed,
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<String?>(
                  key: const Key('customerLimitRule'),
                  isExpanded: true,
                  value: _rule,
                  decoration: const InputDecoration(
                    labelText: 'If a sale takes them past it',
                  ),
                  items: [
                    for (final (value, words) in creditLimitRules)
                      DropdownMenuItem<String?>(
                        value: value,
                        child: Text(words),
                      ),
                  ],
                  onChanged: (value) => setState(() => _rule = value),
                ),
              ],
            ],
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            8,
            16,
            12 + MediaQuery.of(context).viewInsets.bottom,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    _error!,
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ),
              FilledButton(
                key: const Key('customerSave'),
                onPressed: ready && !_busy ? _save : null,
                child: Text(label),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
