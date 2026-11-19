import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/phone.dart';
import '../models/supplier.dart';
import 'suppliers_screen.dart';

/// Add a supplier, or change one, from the phone — often with the delivery
/// van still at the door.
///
/// Only the name is needed.  The phone number and the person dealt with
/// come next, because those are what is reached for when a delivery is
/// short or a payment is due.
class SupplierFormScreen extends StatefulWidget {
  const SupplierFormScreen({
    super.key,
    this.supplier,
    this.name,
    this.known = const [],
    this.returnSupplier = false,
  });

  /// The supplier being changed; null to add one.
  final Supplier? supplier;

  /// What somebody searched for and did not find, to start the name with.
  final String? name;

  /// The suppliers already known, to notice a number one of them has.
  final List<Supplier> known;

  /// Hand the supplier back to whoever opened this — a delivery that wants
  /// to say who brought it — rather than opening their page.
  final bool returnSupplier;

  @override
  State<SupplierFormScreen> createState() => _SupplierFormScreenState();
}

class _SupplierFormScreenState extends State<SupplierFormScreen> {
  Supplier? get _supplier => widget.supplier;
  bool get _editing => _supplier != null;

  late final _name = TextEditingController(
      text: _supplier?.name ?? widget.name?.trim() ?? '');
  late final _phone = TextEditingController(text: _supplier?.phone ?? '');
  late final _contact =
      TextEditingController(text: _supplier?.contactPerson ?? '');
  late final _address = TextEditingController(text: _supplier?.address ?? '');
  late final _notes = TextEditingController(text: _supplier?.notes ?? '');
  late final _tin = TextEditingController(text: _supplier?.tin ?? '');
  late final _telegram =
      TextEditingController(text: _supplier?.telegramUsername ?? '');
  late final _email = TextEditingController(text: _supplier?.email ?? '');
  late bool _more = _editing &&
      [_supplier?.tin, _supplier?.telegramUsername, _supplier?.email]
          .any((value) => (value ?? '').isNotEmpty);
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final field in [
      _name,
      _phone,
      _contact,
      _address,
      _notes,
      _tin,
      _telegram,
      _email,
    ]) {
      field.dispose();
    }
    super.dispose();
  }

  /// A supplier already saved with this number.  Said, not forbidden: two
  /// companies can share an agent.
  Supplier? get _sameNumber {
    final key = phoneKey(_phone.text);
    if (key.length < 9) return null;
    return widget.known
        .where((s) => s.id != _supplier?.id && phoneKey(s.phone) == key)
        .firstOrNull;
  }

  bool get _emailRight {
    final text = _email.text.trim();
    return text.isEmpty || RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(text);
  }

  String? _value(TextEditingController field) {
    final text = field.text.trim();
    return text.isEmpty ? null : text;
  }

  /// What the edit changes, and nothing else; an emptied field is sent as
  /// nothing, so it is cleared rather than left as it was.
  Map<String, dynamic> get _changes {
    final supplier = _supplier!;
    return {
      if (_name.text.trim() != supplier.name) 'name': _name.text.trim(),
      if (_value(_phone) != supplier.phone) 'phone': _value(_phone),
      if (_value(_contact) != supplier.contactPerson)
        'contact_person': _value(_contact),
      if (_value(_address) != supplier.address) 'address': _value(_address),
      if (_value(_notes) != supplier.notes) 'notes': _value(_notes),
      if (_value(_tin) != supplier.tin) 'tin': _value(_tin),
      if (_value(_telegram) != supplier.telegramUsername)
        'telegram_username': _value(_telegram),
      if (_value(_email) != supplier.email) 'email': _value(_email),
    };
  }

  (String, bool) get _button {
    if (_name.text.trim().isEmpty) return ('Give them a name first', false);
    if (!_emailRight) return ('Check the email address', false);
    if (_editing) {
      return _changes.isEmpty
          ? ('Nothing has changed', false)
          : ('Save the changes', true);
    }
    if (_phone.text.trim().isEmpty) {
      return ('Add them without a phone number', true);
    }
    return ('Add this supplier', true);
  }

  Future<void> _save() async {
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final dynamic saved = _editing
          ? await state.api.patch('/suppliers/${_supplier!.id}', body: _changes)
          : await state.api.post('/suppliers', body: {
              'name': _name.text.trim(),
              for (final (key, field) in [
                ('phone', _phone),
                ('contact_person', _contact),
                ('address', _address),
                ('notes', _notes),
                ('tin', _tin),
                ('telegram_username', _telegram),
                ('email', _email),
              ])
                if (_value(field) != null) key: _value(field),
            });
      final supplier = Supplier.fromJson(Map<String, dynamic>.from(saved as Map));
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text(_editing ? 'Saved.' : 'Added ${supplier.name}.'),
      ));
      if (_editing || widget.returnSupplier) {
        navigator.pop(supplier);
      } else {
        await navigator.pushReplacement<void, void>(MaterialPageRoute(
          builder: (_) => SupplierScreen(supplierId: supplier.id),
        ));
      }
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A supplier is not kept on the phone until the '
              'server has them, so this has to wait until you are back online.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final same = _sameNumber;
    final (label, ready) = _button;

    void changed(_) => setState(() {});

    return Scaffold(
      appBar: AppBar(
        title: Text(_editing ? 'Change ${_supplier!.name}' : 'A new supplier'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            TextField(
              key: const Key('supplierName'),
              controller: _name,
              autofocus: !_editing && _name.text.isEmpty,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'What are they called?',
                hintText: 'Highland Grain Suppliers, say',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('supplierPhone'),
              controller: _phone,
              keyboardType: TextInputType.phone,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9+ \-]')),
              ],
              decoration: const InputDecoration(
                labelText: 'Phone number',
                hintText: '09…',
                helperText: 'For a short delivery, or a payment due',
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
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    child: Text(
                      '${same.name} already has this number.',
                      style: TextStyle(
                        color: theme.colorScheme.onTertiaryContainer,
                      ),
                    ),
                  ),
                ),
              ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('supplierContact'),
              controller: _contact,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'Who you deal with there',
                helperText: 'optional — the person who answers that phone',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('supplierAddress'),
              controller: _address,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Where they are',
                hintText: 'Merkato, near the bus station',
                helperText: 'optional',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('supplierNotes'),
              controller: _notes,
              minLines: 2,
              maxLines: 4,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Anything to remember',
                hintText: 'Delivers on Tuesdays, say',
                alignLabelWithHint: true,
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: const Key('supplierMore'),
                onPressed: () => setState(() => _more = !_more),
                icon: Icon(_more ? Icons.expand_less : Icons.expand_more),
                label: Text(_more ? 'Fewer details' : 'More details'),
              ),
            ),
            if (_more) ...[
              TextField(
                key: const Key('supplierTin'),
                controller: _tin,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Their TIN',
                  helperText: 'for tax invoices',
                ),
                onChanged: changed,
              ),
              const SizedBox(height: 14),
              TextField(
                key: const Key('supplierTelegram'),
                controller: _telegram,
                decoration: const InputDecoration(
                  labelText: 'Telegram username',
                  prefixText: '@',
                ),
                onChanged: changed,
              ),
              const SizedBox(height: 14),
              TextField(
                key: const Key('supplierEmail'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: InputDecoration(
                  labelText: 'Email',
                  errorText: _emailRight ? null : 'That is not an email address',
                ),
                onChanged: changed,
              ),
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
                key: const Key('supplierSave'),
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
