import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../models/customer.dart';
import '../widgets/common.dart';
import 'credit_detail_screen.dart';
import 'customer_form_screen.dart';
import 'sale_detail_screen.dart';

/// The shop's customers: find one, see what they owe, add a new one.
///
/// Read from the server when there is a connection, so what each owes is
/// today's figure; from the copy on the phone when there is not, so a name
/// and a number can still be found on a bad day.
class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  final _search = TextEditingController();
  List<Customer> _rows = const [];
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

  /// Search once somebody stops typing, not once per letter.
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
      final dynamic page = await state.api.get('/customers', query: {
        if (needle.isNotEmpty) 'q': needle,
        'limit': '200',
      });
      if (!mounted) return;
      setState(() {
        _rows = (((page as Map)['items'] as List<dynamic>?) ?? const [])
            .map((item) => Customer.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
        _offline = false;
        _loading = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _rows = state.searchCustomers(needle);
        _loading = false;
      });
    }
  }

  Future<void> _open(Customer customer) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
      builder: (_) => CustomerScreen(customerId: customer.id),
    ));
    if (mounted) await _load();
  }

  Future<void> _add([String? name]) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
      builder: (_) => CustomerFormScreen(name: name),
    ));
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final mayAdd = state.session?.can('customer:manage') ?? false;
    final currency = state.session?.currency ?? 'ETB';
    final typed = _search.text.trim();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Customers'),
        actions: [
          if (mayAdd)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: TextButton.icon(
                key: const Key('addCustomer'),
                onPressed: () => _add(),
                icon: const Icon(Icons.person_add_alt_1_outlined),
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
                key: const Key('customersSearch'),
                controller: _search,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: 'Name, phone or business',
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
            if (_offline)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  'No connection: these are the customers saved on this '
                  'phone, without what they owe.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: _rows.isEmpty
                          ? ListView(
                              children: [
                                EmptyState(
                                  icon: Icons.people_outline,
                                  title: typed.isEmpty
                                      ? 'No customers yet'
                                      : 'Nobody matches that',
                                  message: typed.isEmpty
                                      ? 'Add the people who buy on credit, '
                                          'or who come back often.'
                                      : 'Try part of the name or the number.',
                                ),
                                if (mayAdd)
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 24),
                                    child: FilledButton.tonalIcon(
                                      key: const Key('addCustomerFromSearch'),
                                      onPressed: () =>
                                          _add(typed.isEmpty ? null : typed),
                                      icon: const Icon(Icons.person_add_alt_1),
                                      label: Text(typed.isEmpty
                                          ? 'Add a customer'
                                          : 'Add “$typed” as a new customer'),
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

  Widget _row(BuildContext context, Customer customer, String currency) {
    final theme = Theme.of(context);
    final owes = Money.parse(customer.outstandingBalance) ?? 0;
    final details = [
      if ((customer.phone ?? '').isNotEmpty) customer.phone!,
      if ((customer.company ?? '').isNotEmpty) customer.company!,
    ];
    return ListTile(
      key: Key('customer-${customer.id}'),
      title: Text(customer.name),
      subtitle: details.isEmpty ? null : Text(details.join(' · ')),
      trailing: owes > 0
          ? Text(
              'owes ${Money.format(owes, currency: currency)}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: EstockTheme.statusColour('warning', theme.colorScheme),
                fontWeight: FontWeight.w600,
              ),
            )
          : const Icon(Icons.chevron_right),
      onTap: () => _open(customer),
    );
  }
}

/// One customer: how to reach them, what they owe, what they have bought.
class CustomerScreen extends StatefulWidget {
  const CustomerScreen({super.key, required this.customerId});

  final String customerId;

  @override
  State<CustomerScreen> createState() => _CustomerScreenState();
}

class _CustomerScreenState extends State<CustomerScreen> {
  Map<String, dynamic>? _history;
  bool _loading = true;
  bool _offline = false;
  bool _allSales = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic history =
          await state.api.get('/customers/${widget.customerId}/history');
      if (!mounted) return;
      final map = Map<String, dynamic>.from(history as Map);
      setState(() {
        _history = map;
        _offline = false;
        _error = null;
        _loading = false;
      });
      // The copy on the phone catches up with what was just read.
      final fresh = Map<String, dynamic>.from(map['customer'] as Map)
        ..['outstanding_balance'] = map['outstanding_balance'];
      await state.putCustomer(Customer.fromJson(fresh));
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

  Future<void> _edit(Customer customer) async {
    final changed = await Navigator.of(context).push<Customer>(
      MaterialPageRoute(
        builder: (_) => CustomerFormScreen(customer: customer),
      ),
    );
    if (changed != null && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final cached =
        state.customers.where((c) => c.id == widget.customerId).firstOrNull;
    final history = _history;
    final customer = history == null
        ? cached
        : Customer.fromJson(Map<String, dynamic>.from(
            history['customer'] as Map,
          ));
    final mayEdit = state.session?.can('customer:manage') ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(customer?.name ?? 'Customer'),
        actions: [
          if (customer != null && mayEdit && !_offline)
            IconButton(
              key: const Key('editCustomer'),
              tooltip: 'Change their details',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () => _edit(customer),
            ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : customer == null
                ? EmptyState(
                    icon: Icons.person_off_outlined,
                    title: 'Not found',
                    message: _error ??
                        'This customer is not on this phone. Try again with a '
                            'connection.',
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: _body(context, state, customer),
                  ),
      ),
    );
  }

  Widget _body(BuildContext context, AppState state, Customer customer) {
    final theme = Theme.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final history = _history;
    final seesCredit = session?.can('credit:view') ?? false;
    final owes = Money.parse(history?['outstanding_balance']) ?? 0;
    final debts = ((history?['credit_transactions'] as List<dynamic>?) ??
            const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .where((row) => (Money.parse(row['balance']) ?? 0) > 0)
        .toList();
    final late = debts.any((row) => row['is_overdue'] == true);
    final sales = ((history?['sales'] as List<dynamic>?) ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final shownSales = _allSales ? sales : sales.take(5).toList();
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final phone = (customer.phone ?? '').trim();
    final telegram = (customer.telegramUsername ?? '').replaceFirst('@', '');
    final limit = Money.parse(customer.creditLimit);
    final rule = creditLimitRules
        .where((entry) => entry.$1 == customer.creditLimitBehaviour)
        .map((entry) => entry.$2)
        .firstOrNull;

    return ListView(
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if ((customer.company ?? '').isNotEmpty)
                Text(customer.company!, style: theme.textTheme.titleMedium),
              if (history != null && seesCredit) ...[
                const SizedBox(height: 4),
                Text(
                  owes > 0
                      ? 'Owes ${Money.format(owes, currency: currency)}'
                      : 'Owes nothing',
                  key: const Key('customerOwes'),
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: owes <= 0
                        ? EstockTheme.statusColour('ok', theme.colorScheme)
                        : late
                            ? theme.colorScheme.error
                            : null,
                  ),
                ),
                if (limit != null)
                  Text(
                    'May owe up to ${Money.format(limit, currency: currency)}'
                    '${rule == null || customer.creditLimitBehaviour == null ? '' : ' · past that: ${rule.toLowerCase()}'}',
                    style: muted,
                  ),
              ],
            ],
          ),
        ),
        // How to reach them, first: it is most of what a customer record
        // is for on a phone.
        if (phone.isNotEmpty || telegram.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (phone.isNotEmpty)
                  FilledButton.tonalIcon(
                    key: const Key('callCustomer'),
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
        if ((customer.address ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.place_outlined),
            title: Text(customer.address!),
          ),
        if ((customer.email ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.mail_outline),
            title: Text(customer.email!),
          ),
        if ((customer.notes ?? '').isNotEmpty)
          ListTile(
            dense: true,
            leading: const Icon(Icons.sticky_note_2_outlined),
            title: Text('“${customer.notes}”'),
          ),
        if (_offline)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
            child: Text(
              'No connection: what they owe and what they bought show when '
              'you are back online.',
              style: muted,
            ),
          ),
        if (history != null && seesCredit && debts.isNotEmpty) ...[
          const Divider(height: 24),
          const SectionTitle('What they owe'),
          for (final row in debts)
            ListTile(
              key: Key('debt-${row['id']}'),
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
              onTap: () async {
                await Navigator.of(context).push<void>(MaterialPageRoute(
                  builder: (_) =>
                      CreditDetailScreen(transactionId: row['id'] as String),
                ));
                if (mounted) await _load();
              },
            ),
        ],
        if (history != null && (session?.can('sale:view') ?? false)) ...[
          const Divider(height: 24),
          SectionTitle(sales.isEmpty
              ? 'What they bought'
              : 'What they bought (${sales.length})'),
          if (sales.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text('Nothing yet.', style: muted),
            ),
          for (final sale in shownSales)
            ListTile(
              key: Key('sale-${sale['id']}'),
              title: Text(Money.format(sale['total_amount'], currency: currency)),
              subtitle: Text([
                '${sale['number']}',
                Money.dateTime(DateTime.tryParse('${sale['sold_at']}')),
                if ((Money.parse(sale['balance_due']) ?? 0) > 0)
                  '${Money.amount(sale['balance_due'])} still owing',
              ].join(' · ')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push<void>(MaterialPageRoute(
                builder: (_) => SaleDetailScreen(saleId: sale['id'] as String),
              )),
            ),
          if (sales.length > shownSales.length)
            Center(
              child: TextButton(
                onPressed: () => setState(() => _allSales = true),
                child: Text('Show all ${sales.length}'),
              ),
            ),
        ],
      ],
    );
  }
}
