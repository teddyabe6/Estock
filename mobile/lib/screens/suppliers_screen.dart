import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../models/supplier.dart';
import '../widgets/common.dart';
import 'credit_detail_screen.dart';
import 'stock_receive_screen.dart';
import 'supplier_form_screen.dart';

/// Who the shop buys from: find one, see what is owed to them, add one.
///
/// Read from the server only.  Suppliers are reached for when a delivery
/// is being written down or a payment made, and both of those need a
/// connection anyway.
class SuppliersScreen extends StatefulWidget {
  const SuppliersScreen({super.key});

  @override
  State<SuppliersScreen> createState() => _SuppliersScreenState();
}

class _SuppliersScreenState extends State<SuppliersScreen> {
  final _search = TextEditingController();
  List<Supplier> _rows = const [];
  bool _loading = true;
  bool _offline = false;
  Timer? _typing;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _typing?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _searchLater() {
    _typing?.cancel();
    _typing = Timer(const Duration(milliseconds: 350), () {
      if (mounted) _load();
    });
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    final needle = _search.text.trim();
    try {
      final dynamic page = await state.api.get('/suppliers', query: {
        if (needle.isNotEmpty) 'q': needle,
        'limit': '200',
      });
      if (!mounted) return;
      setState(() {
        _rows = (((page as Map)['items'] as List<dynamic>?) ?? const [])
            .map((item) => Supplier.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
        _offline = false;
        _loading = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _loading = false;
      });
    }
  }

  Future<void> _open(Supplier supplier) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
      builder: (_) => SupplierScreen(supplierId: supplier.id, known: _rows),
    ));
    if (mounted) await _load();
  }

  Future<void> _add([String? name]) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
      builder: (_) => SupplierFormScreen(name: name, known: _rows),
    ));
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final mayAdd = state.session?.can('supplier:manage') ?? false;
    final currency = state.session?.currency ?? 'ETB';
    final typed = _search.text.trim();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Suppliers'),
        actions: [
          if (mayAdd)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: TextButton.icon(
                key: const Key('addSupplier'),
                onPressed: () => _add(),
                icon: const Icon(Icons.add_business_outlined),
                label: const Text('Add'),
              ),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: TextField(
                key: const Key('suppliersSearch'),
                controller: _search,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: 'Name, phone or who you deal with',
                  prefixIcon: const Icon(Icons.search),
                  isDense: true,
                  suffixIcon: typed.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.close),
                          onPressed: () {
                            _search.clear();
                            _load();
                          },
                        ),
                ),
                onChanged: (_) {
                  setState(() {});
                  _searchLater();
                },
                onSubmitted: (_) => _load(),
              ),
            ),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _offline
                      ? const EmptyState(
                          icon: Icons.cloud_off,
                          title: 'Suppliers need a connection',
                          message: 'Pull down to try again once you are back '
                              'online.',
                        )
                      : RefreshIndicator(
                          onRefresh: _load,
                          child: _rows.isEmpty
                              ? ListView(
                                  children: [
                                    EmptyState(
                                      icon: Icons.local_shipping_outlined,
                                      title: typed.isEmpty
                                          ? 'No suppliers yet'
                                          : 'Nobody matches that',
                                      message: typed.isEmpty
                                          ? 'Add the people you buy from, so '
                                              'deliveries and what you owe '
                                              'them say who.'
                                          : 'Try part of the name or the '
                                              'number.',
                                    ),
                                    if (mayAdd)
                                      Padding(
                                        padding: const EdgeInsets.symmetric(
                                            horizontal: 24),
                                        child: FilledButton.tonalIcon(
                                          key: const Key(
                                              'addSupplierFromSearch'),
                                          onPressed: () =>
                                              _add(typed.isEmpty ? null : typed),
                                          icon: const Icon(
                                              Icons.add_business_outlined),
                                          label: Text(typed.isEmpty
                                              ? 'Add a supplier'
                                              : 'Add “$typed” as a new supplier'),
                                        ),
                                      ),
                                  ],
                                )
                              : ListView.separated(
                                  itemCount: _rows.length,
                                  separatorBuilder: (_, __) =>
                                      const Divider(height: 1),
                                  itemBuilder: (context, index) =>
                                      _row(context, _rows[index], currency),
                                ),
                        ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _row(BuildContext context, Supplier supplier, String currency) {
    final theme = Theme.of(context);
    final owed = Money.parse(supplier.outstandingBalance) ?? 0;
    final details = [
      if ((supplier.phone ?? '').isNotEmpty) supplier.phone!,
      if ((supplier.contactPerson ?? '').isNotEmpty) supplier.contactPerson!,
    ];
    return ListTile(
      key: Key('supplier-${supplier.id}'),
      title: Text(supplier.name),
      subtitle: details.isEmpty ? null : Text(details.join(' · ')),
      trailing: owed > 0
          ? Text(
              'you owe ${Money.format(owed, currency: currency)}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: EstockTheme.statusColour('warning', theme.colorScheme),
                fontWeight: FontWeight.w600,
              ),
            )
          : const Icon(Icons.chevron_right),
      onTap: () => _open(supplier),
    );
  }
}

/// One supplier: how to reach them, what is owed to them, what they have
/// delivered.
class SupplierScreen extends StatefulWidget {
  const SupplierScreen({
    super.key,
    required this.supplierId,
    this.known = const [],
  });

  final String supplierId;

  /// The other suppliers, so a change of number can be checked against them.
  final List<Supplier> known;

  @override
  State<SupplierScreen> createState() => _SupplierScreenState();
}

class _SupplierScreenState extends State<SupplierScreen> {
  Supplier? _supplier;
  List<Map<String, dynamic>> _owed = const [];
  List<Map<String, dynamic>> _deliveries = const [];
  bool _loading = true;
  bool _offline = false;
  bool _allDeliveries = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  static List<Map<String, dynamic>> _items(dynamic page) =>
      (((page as Map?)?['items'] as List<dynamic>?) ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();

  Future<void> _load() async {
    final state = AppScope.of(context);
    final session = state.session;
    final id = widget.supplierId;
    try {
      final dynamic record = await state.api.get('/suppliers/$id');
      var owed = const <Map<String, dynamic>>[];
      var deliveries = const <Map<String, dynamic>>[];
      // Each of these is its own permission, and each is a nicety beside
      // the record: one failing does not take the page with it.
      if ((session?.can('credit:view') ?? false) &&
          (session?.can('purchase:view') ?? false)) {
        try {
          owed = _items(await state.api.get('/credit/transactions', query: {
            'kind': 'payable',
            'supplier_id': id,
            'view': 'outstanding',
            'limit': '50',
          }));
        } on ApiException catch (exception) {
          if (exception.isNetworkError) rethrow;
        }
      }
      if ((session?.can('purchase:view') ?? false) &&
          (session?.can('cost:view') ?? false)) {
        try {
          deliveries = _items(await state.api.get('/purchases', query: {
            'supplier_id': id,
            'limit': '30',
          }));
        } on ApiException catch (exception) {
          if (exception.isNetworkError) rethrow;
        }
      }
      if (!mounted) return;
      setState(() {
        _supplier = Supplier.fromJson(Map<String, dynamic>.from(record as Map));
        _owed = owed;
        _deliveries = deliveries;
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

  Future<void> _launch(Uri uri) async {
    final messenger = ScaffoldMessenger.of(context);
    var opened = false;
    try {
      opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      opened = false;
    }
    if (!opened) {
      messenger.showSnackBar(const SnackBar(
        content: Text('This phone has nothing to open that with.'),
      ));
    }
  }

  Future<void> _edit(Supplier supplier) async {
    final changed = await Navigator.of(context).push<Supplier>(
      MaterialPageRoute(
        builder: (_) =>
            SupplierFormScreen(supplier: supplier, known: widget.known),
      ),
    );
    if (changed != null && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final supplier = _supplier;
    final mayEdit = state.session?.can('supplier:manage') ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(supplier?.name ?? 'Supplier'),
        actions: [
          if (supplier != null && mayEdit)
            IconButton(
              key: const Key('editSupplier'),
              tooltip: 'Change their details',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () => _edit(supplier),
            ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : supplier == null
                ? EmptyState(
                    icon: _offline ? Icons.cloud_off : Icons.search_off,
                    title: _offline
                        ? 'Suppliers need a connection'
                        : 'Not found',
                    message: _offline
                        ? 'Pull down to try again once you are back online.'
                        : _error ?? 'This supplier is no longer there.',
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: _body(context, state, supplier),
                  ),
      ),
    );
  }

  Widget _body(BuildContext context, AppState state, Supplier supplier) {
    final theme = Theme.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final seesOwed = (session?.can('credit:view') ?? false) &&
        (session?.can('purchase:view') ?? false);
    final owed = Money.parse(supplier.outstandingBalance) ?? 0;
    final late = _owed.any((row) => row['is_overdue'] == true);
    final phone = (supplier.phone ?? '').trim();
    final telegram = (supplier.telegramUsername ?? '').replaceFirst('@', '');
    final mayReceive = (session?.can('purchase:create') ?? false) &&
        (session?.can('stock:receive') ?? false);
    final shown =
        _allDeliveries ? _deliveries : _deliveries.take(5).toList();

    return ListView(
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if ((supplier.contactPerson ?? '').isNotEmpty)
                Text(
                  'You deal with ${supplier.contactPerson}',
                  style: theme.textTheme.titleMedium,
                ),
              if (seesOwed) ...[
                const SizedBox(height: 4),
                Text(
                  owed > 0
                      ? 'You owe them ${Money.format(owed, currency: currency)}'
                      : 'You owe them nothing',
                  key: const Key('supplierOwed'),
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: owed <= 0
                        ? EstockTheme.statusColour('ok', theme.colorScheme)
                        : late
                            ? theme.colorScheme.error
                            : null,
                  ),
                ),
              ],
            ],
          ),
        ),
        if (phone.isNotEmpty || telegram.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (phone.isNotEmpty)
                  FilledButton.tonalIcon(
                    key: const Key('callSupplier'),
                    onPressed: () => _launch(Uri(scheme: 'tel', path: phone)),
                    icon: const Icon(Icons.phone_outlined),
                    label: Text('Call $phone'),
                  ),
                if (telegram.isNotEmpty)
                  OutlinedButton.icon(
                    onPressed: () =>
                        _launch(Uri.parse('https://t.me/$telegram')),
                    icon: const Icon(Icons.send_outlined),
                    label: const Text('Telegram'),
                  ),
              ],
            ),
          ),
        // The most common reason to open a supplier on the phone: their van
        // is at the door.
        if (mayReceive)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
            child: OutlinedButton.icon(
              key: const Key('deliveryFromSupplier'),
              onPressed: () async {
                await Navigator.of(context).push<bool>(MaterialPageRoute(
                  builder: (_) => StockReceiveScreen(supplierId: supplier.id),
                ));
                if (mounted) await _load();
              },
              icon: const Icon(Icons.inventory_outlined),
              label: const Text('A delivery from them arrived'),
            ),
          ),
        if ((supplier.address ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.place_outlined),
            title: Text(supplier.address!),
          ),
        if ((supplier.tin ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.badge_outlined),
            title: Text('TIN ${supplier.tin}'),
          ),
        if ((supplier.email ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.mail_outline),
            title: Text(supplier.email!),
          ),
        if ((supplier.notes ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.sticky_note_2_outlined),
            title: Text('“${supplier.notes}”'),
          ),
        if (seesOwed && _owed.isNotEmpty) ...[
          const Divider(height: 24),
          const SectionTitle('What you owe them'),
          for (final row in _owed)
            ListTile(
              key: Key('owed-${row['id']}'),
              title: Text('${row['reference']}'),
              subtitle: Text(Money.dueLabel(
                row['due_date'] as String?,
                row['is_overdue'] as bool? ?? false,
                (row['days_overdue'] as num?)?.toInt(),
              )),
              trailing: Text(
                Money.format(row['balance'], currency: currency),
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: row['is_overdue'] == true
                      ? theme.colorScheme.error
                      : null,
                ),
              ),
              // Opens the debt, where "Pay them" is.
              onTap: () async {
                await Navigator.of(context).push<void>(MaterialPageRoute(
                  builder: (_) =>
                      CreditDetailScreen(transactionId: row['id'] as String),
                ));
                if (mounted) await _load();
              },
            ),
        ],
        if ((session?.can('purchase:view') ?? false) &&
            (session?.can('cost:view') ?? false)) ...[
          const Divider(height: 24),
          SectionTitle(_deliveries.isEmpty
              ? 'What they delivered'
              : 'What they delivered (${_deliveries.length})'),
          if (_deliveries.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text('Nothing recorded yet.', style: muted),
            ),
          for (final delivery in shown)
            ListTile(
              key: Key('delivery-${delivery['id']}'),
              title: Text(
                Money.format(delivery['total_amount'], currency: currency),
              ),
              subtitle: Text([
                _goods(delivery),
                '${delivery['number']}',
                Money.dateTime(DateTime.tryParse('${delivery['received_at']}')),
                if ((Money.parse(delivery['balance_due']) ?? 0) > 0)
                  '${Money.amount(delivery['balance_due'])} still owed',
              ].where((part) => part.isNotEmpty).join(' · ')),
            ),
          if (_deliveries.length > shown.length)
            Center(
              child: TextButton(
                onPressed: () => setState(() => _allDeliveries = true),
                child: Text('Show all ${_deliveries.length}'),
              ),
            ),
        ],
      ],
    );
  }

  /// What came, in a few words: the first two things and how many more.
  static String _goods(Map<String, dynamic> delivery) {
    final lines = ((delivery['lines'] as List<dynamic>?) ?? const [])
        .map((line) => Map<String, dynamic>.from(line as Map))
        .toList();
    if (lines.isEmpty) return '';
    final named = lines
        .take(2)
        .map((line) =>
            '${line['description']} × ${Money.quantity(line['quantity'])}')
        .join(', ');
    return lines.length > 2 ? '$named and ${lines.length - 2} more' : named;
  }
}
