import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';
import 'shop_order_screen.dart';

/// What a customer's question is waiting on, in a couple of words.
String enquiryLabel(String status) => switch (status) {
      'new' => 'new',
      'in_review' => 'seen',
      'quoted' => 'priced',
      'closed' => 'answered',
      final other => other.replaceAll('_', ' '),
    };

/// The online shop as the person who runs it sees it: what is waiting on
/// them first, and everything else after.
///
/// It used to be a card saying the shop was live and a list of enquiries
/// nobody could open, while the orders the shop exists to take — and the
/// customers saying they had paid for them — were on the web only.  The
/// phone is where the seller is when the order comes in.
class ShopScreen extends StatefulWidget {
  const ShopScreen({super.key, this.openEnquiryId});

  /// A customer's question to open as soon as the list is in, for a notice
  /// that was about it.
  final String? openEnquiryId;

  @override
  State<ShopScreen> createState() => _ShopScreenState();
}

class _ShopScreenState extends State<ShopScreen> {
  Map<String, dynamic>? _store;
  List<Map<String, dynamic>> _orders = const [];
  List<Map<String, dynamic>> _enquiries = const [];
  bool _loading = true;
  bool _fetching = false;
  bool _offline = false;
  bool _busy = false;
  bool _showEarlier = false;
  String? _error;

  /// The count behind the tab's badge as this list last knew it.
  int? _seen;

  /// Whether the question this was opened for has been shown, so that a
  /// pull to refresh does not open it again.
  bool _openedAsked = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // The badge moved while this list was not looking: an order came in,
    // or one was answered from somewhere else.  A badge saying "1" over a
    // list that does not have it is worse than no badge.
    final now = AppScope.of(context).shopNeedsYou;
    if (_seen != null && now != _seen && !_loading && !_fetching) {
      _seen = now;
      _load();
    }
  }

  static List<Map<String, dynamic>> _rows(dynamic page) =>
      (((page as Map?)?['items'] as List<dynamic>?) ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();

  Future<void> _load() async {
    final state = AppScope.of(context);
    final session = state.session;
    if (!(session?.can('shop:view') ?? false)) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    _fetching = true;
    try {
      final dynamic store = await state.api.get('/shop/settings');
      var orders = const <Map<String, dynamic>>[];
      if (session!.can('quotation:view')) {
        orders = _rows(
          await state.api.get('/shop/quotations', query: {'limit': '100'}),
        );
      }
      var enquiries = const <Map<String, dynamic>>[];
      if (session.can('enquiry:view')) {
        enquiries = _rows(
          await state.api.get('/shop/enquiries', query: {'limit': '50'}),
        );
      }
      // The badge and the list are asked for together, so that neither is
      // ever the older of the two.
      await state.refreshShopWaiting();
      if (!mounted) return;
      setState(() {
        _store = Map<String, dynamic>.from(store as Map);
        _orders = orders;
        _enquiries = enquiries;
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
    } finally {
      _fetching = false;
      _seen = state.shopNeedsYou;
    }
    if (mounted) await _openAsked();
  }

  /// The question a notice was about, opened once the list is in.
  Future<void> _openAsked() async {
    final id = widget.openEnquiryId;
    if (id == null || _openedAsked || _store == null) return;
    _openedAsked = true;
    var row = _enquiries.where((row) => row['id'] == id).firstOrNull;
    if (row == null) {
      try {
        final dynamic one =
            await AppScope.of(context).api.get('/shop/enquiries/$id');
        row = Map<String, dynamic>.from(one as Map);
      } on ApiException {
        return;
      }
    }
    if (mounted) await _openEnquiry(row);
  }

  Future<void> _openOrder(Map<String, dynamic> order) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ShopOrderScreen(orderId: order['id'] as String),
      ),
    );
    // Reloaded whether or not anything was done: the customer may have
    // answered while it was open.
    if (mounted) await _load();
  }

  Future<void> _copyLink(String url) async {
    final messenger = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: url));
    messenger.showSnackBar(const SnackBar(
      content: Text('Link copied. Paste it wherever your customers are.'),
    ));
  }

  Future<void> _launch(String url) async {
    final messenger = ScaffoldMessenger.of(context);
    var opened = false;
    try {
      opened = await launchUrl(
        Uri.parse(url),
        mode: LaunchMode.externalApplication,
      );
    } catch (_) {
      opened = false;
    }
    if (!opened) {
      messenger.showSnackBar(const SnackBar(
        content: Text('This phone has nothing to open that with.'),
      ));
    }
  }

  /// Open the shop to customers, or close it.
  Future<void> _setOpen(bool open) async {
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    if (!open) {
      final sure = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: const Text('Close your online shop?'),
          content: const Text(
            'Customers will not be able to see it or order from it until '
            'you open it again. Orders you already have stay as they are.',
          ),
          actions: [
            DialogActions(
              back: OutlinedButton(
                onPressed: () => Navigator.of(dialog).pop(false),
                child: const Text('Keep it open'),
              ),
              confirm: FilledButton(
                key: const Key('shopCloseConfirm'),
                onPressed: () => Navigator.of(dialog).pop(true),
                child: const Text('Close it'),
              ),
            ),
          ],
        ),
      );
      if (sure != true || !mounted) return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final dynamic store = await state.api
          .patch('/shop/settings', body: {'is_published': open});
      if (!mounted) return;
      setState(() => _store = Map<String, dynamic>.from(store as Map));
      messenger.showSnackBar(SnackBar(
        content: Text(open
            ? 'Your shop is open. Customers can see it now.'
            : 'Your shop is closed.'),
      ));
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection, so the shop is as it was.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openEnquiry(Map<String, dynamic> enquiry) async {
    final state = AppScope.of(context);
    final manage = state.session?.can('enquiry:manage') ?? false;
    // Opening it is reading it: it stops being "new" for everyone, so the
    // badge counts questions nobody has looked at and not ones somebody
    // has and is dealing with.
    if (manage && enquiry['status'] == 'new') {
      unawaited(_setEnquiry(enquiry, 'in_review', quiet: true));
    }
    final answered = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => _EnquirySheet(
        enquiry: enquiry,
        manage: manage,
        onCall: (phone) => _launch('tel:$phone'),
      ),
    );
    if (answered == true && mounted) {
      await _setEnquiry(enquiry, 'closed');
    }
  }

  Future<void> _setEnquiry(
    Map<String, dynamic> enquiry,
    String status, {
    bool quiet = false,
  }) async {
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await state.api
          .patch('/shop/enquiries/${enquiry['id']}?status=$status');
      if (!mounted) return;
      setState(() => enquiry['status'] = status);
      if (!quiet) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Marked as answered.')),
        );
      }
      await state.refreshShopWaiting();
      _seen = state.shopNeedsYou;
    } on ApiException catch (exception) {
      if (!mounted || quiet) return;
      messenger.showSnackBar(SnackBar(
        content: Text(exception.isNetworkError
            ? 'No connection — it is still open.'
            : exception.message),
      ));
    }
  }

  // ------------------------------------------------------------------- //

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);

    if (!(state.session?.can('shop:view') ?? false)) {
      return const EmptyState(
        icon: Icons.lock_outline,
        title: 'Not available for your role',
        message: 'Ask an owner or manager if you need access to the online shop.',
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_offline && _store == null)
            const EmptyState(
              icon: Icons.cloud_off,
              title: 'The shop needs a connection',
              message: 'Orders and questions from customers are kept on the '
                  'server. Pull down to try again once you are back online.',
            )
          else if (_store == null)
            EmptyState(
              icon: Icons.error_outline,
              title: 'The shop could not be opened',
              message: _error,
            )
          else
            ..._sections(context, state),
        ],
      ),
    );
  }

  List<Widget> _sections(BuildContext context, AppState state) {
    final theme = Theme.of(context);
    final session = state.session;
    final seesOrders = session?.can('quotation:view') ?? false;

    // What is the shop's move comes first, the most pressing of it at the
    // top and whoever has waited longest before whoever has not.
    final waiting = _orders.where(orderNeedsYou).toList()
      ..sort((a, b) {
        final byUrgency = orderUrgency(a).compareTo(orderUrgency(b));
        if (byUrgency != 0) return byUrgency;
        return '${a['created_at']}'.compareTo('${b['created_at']}');
      });
    final withCustomer = _orders
        .where((order) => !orderNeedsYou(order) && order['status'] == 'sent')
        .toList();
    final earlier = _orders
        .where((order) => !orderNeedsYou(order) && order['status'] != 'sent')
        .toList();

    return [
      if (_offline)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Text(
            'No connection. This is the shop as it was when last loaded.',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
        ),
      _storeCard(context, state),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
          child: Text(
            _error!,
            style: TextStyle(color: theme.colorScheme.error),
          ),
        ),
      if (seesOrders) ...[
        if (_orders.isEmpty)
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 20, 16, 0),
            child: Text(
              'No orders yet. When a customer orders from your online shop, '
              'it shows here and this tab gets a red number.',
            ),
          ),
        if (waiting.isNotEmpty) ...[
          SectionTitle('Waiting for you (${waiting.length})'),
          ...waiting.map(_orderRow),
        ] else if (_orders.isNotEmpty)
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 20, 16, 0),
            child: Text('Nothing is waiting for you. Every order is answered.'),
          ),
        if (withCustomer.isNotEmpty) ...[
          SectionTitle('Waiting for the customer (${withCustomer.length})'),
          ...withCustomer.map(_orderRow),
        ],
        if (earlier.isNotEmpty) ...[
          SectionTitle(
            'Earlier orders (${earlier.length})',
            trailing: TextButton(
              key: const Key('shopEarlier'),
              onPressed: () => setState(() => _showEarlier = !_showEarlier),
              child: Text(_showEarlier ? 'Hide' : 'Show'),
            ),
          ),
          if (_showEarlier) ...earlier.map(_orderRow),
        ],
      ],
      if (_enquiries.isNotEmpty) ...[
        SectionTitle('Questions from customers (${_enquiries.length})'),
        ..._enquiries.map(_enquiryRow),
      ],
    ];
  }

  Widget _storeCard(BuildContext context, AppState state) {
    final theme = Theme.of(context);
    final store = _store!;
    final open = store['is_published'] as bool? ?? false;
    final url = store['public_url'] as String?;
    final manage = state.session?.can('shop:manage') ?? false;
    final onShow = state.products.where((p) => p.isPublished).length;
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      store['display_name'] as String? ?? 'Your shop',
                      style: theme.textTheme.titleMedium,
                    ),
                  ),
                  StatusChip(
                    status: open ? 'ok' : 'warning',
                    label: open ? 'open' : 'closed',
                  ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                !open
                    ? 'Customers cannot see your shop or order from it.'
                    : onShow == 0
                        ? 'Open, but nothing is on show yet. Choose which '
                            'products customers see from the web.'
                        : '${countOf(onShow, 'product')} on show to '
                            'customers.',
                style: muted,
              ),
            ),
            if (url != null && open) ...[
              const SizedBox(height: 6),
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Text(
                  url.replaceFirst(RegExp(r'^https?://'), ''),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: theme.colorScheme.primary),
                ),
              ),
              Wrap(
                spacing: 4,
                children: [
                  TextButton.icon(
                    key: const Key('shopCopyLink'),
                    onPressed: () => _copyLink(url),
                    icon: const Icon(Icons.copy, size: 18),
                    label: const Text('Copy the link'),
                  ),
                  TextButton.icon(
                    key: const Key('shopOpenLink'),
                    onPressed: () => _launch(url),
                    icon: const Icon(Icons.open_in_new, size: 18),
                    label: const Text('See it as a customer'),
                  ),
                ],
              ),
            ],
            if (manage)
              SwitchListTile(
                key: const Key('shopOpenSwitch'),
                contentPadding: const EdgeInsets.only(right: 4),
                dense: true,
                title: const Text('Open to customers'),
                value: open,
                onChanged: _busy ? null : _setOpen,
              ),
          ],
        ),
      ),
    );
  }

  Widget _orderRow(Map<String, dynamic> order) {
    final currency = AppScope.of(context).session?.currency ?? 'ETB';
    final lines = (order['lines'] as List<dynamic>?)?.length ?? 0;
    return ListTile(
      key: Key('order-${order['id']}'),
      title: Text(order['customer_name'] as String? ?? 'A customer'),
      subtitle: Text(
        [
          countOf(lines, 'item'),
          Money.format(order['total_amount'], currency: currency),
          Money.dateTime(order['created_at']),
        ].join(' · '),
      ),
      trailing: StatusChip(
        status: orderTone(order),
        label: orderLabel(order),
      ),
      onTap: () => _openOrder(order),
    );
  }

  Widget _enquiryRow(Map<String, dynamic> row) {
    final theme = Theme.of(context);
    final status = row['status'] as String? ?? 'new';
    final message = row['message'] as String?;
    final items = (row['items'] as List<dynamic>?) ?? const [];
    return ListTile(
      key: Key('enquiry-${row['id']}'),
      title: Text(row['contact_name'] as String? ?? ''),
      subtitle: Text(
        message != null && message.isNotEmpty
            ? message
            : items.isEmpty
                ? '${row['contact_phone'] ?? ''}'
                : 'Asked about ${countOf(items.length, 'product')}',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          StatusChip(
            status: status == 'new' ? 'warning' : 'neutral',
            label: enquiryLabel(status),
          ),
          Text(
            Money.dateTime(row['created_at']),
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
      onTap: () => _openEnquiry(row),
    );
  }
}

/// One customer's question, with the way to answer it: their number.
class _EnquirySheet extends StatelessWidget {
  const _EnquirySheet({
    required this.enquiry,
    required this.manage,
    required this.onCall,
  });

  final Map<String, dynamic> enquiry;
  final bool manage;
  final void Function(String phone) onCall;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final phone = enquiry['contact_phone'] as String? ?? '';
    final message = enquiry['message'] as String?;
    final items = ((enquiry['items'] as List<dynamic>?) ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              enquiry['contact_name'] as String? ?? 'A customer',
              style: theme.textTheme.titleLarge,
            ),
            const SizedBox(height: 2),
            Text(
              [
                if (phone.isNotEmpty) phone,
                if (enquiry['company'] != null) '${enquiry['company']}',
                if (enquiry['delivery_location'] != null)
                  'Deliver to ${enquiry['delivery_location']}',
                Money.dateTime(enquiry['created_at']),
              ].join(' · '),
              style: muted,
            ),
            if (message != null && message.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(
                '“$message”',
                style: theme.textTheme.bodyLarge
                    ?.copyWith(fontStyle: FontStyle.italic),
              ),
            ],
            if (items.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text('Asked about', style: theme.textTheme.titleSmall),
              const SizedBox(height: 4),
              for (final item in items)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text(
                    '${Money.quantity(item['quantity'] ?? 1)} × '
                    '${item['name'] ?? 'a product'}',
                  ),
                ),
            ],
            const SizedBox(height: 16),
            Text(
              'A question holds no stock. Call them back with a price; if '
              'they want it, sell it at the till.',
              style: muted,
            ),
            const SizedBox(height: 12),
            if (phone.isNotEmpty)
              FilledButton.icon(
                key: const Key('enquiryCall'),
                onPressed: () => onCall(phone),
                icon: const Icon(Icons.phone_outlined),
                label: Text('Call $phone'),
              ),
            if (manage && enquiry['status'] != 'closed') ...[
              const SizedBox(height: 8),
              OutlinedButton(
                key: const Key('enquiryAnswered'),
                onPressed: () => Navigator.of(context).pop(true),
                child: const Text('I have answered it'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
