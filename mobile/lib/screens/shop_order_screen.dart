import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'sale_detail_screen.dart';

const _methods = <(String, String)>[
  ('cash', 'Cash'),
  ('telebirr', 'Telebirr'),
  ('cbe_birr', 'CBE Birr'),
  ('bank_transfer', 'Bank transfer'),
];

/// The till's own choices for when the rest is due, in the till's words.
const _duePresets = <(String?, String)>[
  (null, 'No due date'),
  ('today', 'Today'),
  ('tomorrow', 'Tomorrow'),
  ('7_days', 'In 7 days'),
  ('15_days', 'In 15 days'),
  ('30_days', 'In 30 days'),
];

int _slipsToCheck(Map<String, dynamic> order) =>
    (order['slips_to_check'] as num?)?.toInt() ?? 0;

/// Whether the shop has looked at a slip and found the money for it: the
/// customer has paid, and is owed the goods.
bool _moneyFound(Map<String, dynamic> order) =>
    ((order['slips_found'] as num?)?.toInt() ?? 0) > 0;

bool _closed(String status) => status == 'converted' || status == 'cancelled';

/// What an order's status means, said as what happens next.
///
/// The status itself is a word from the books — "requested", "sent" —
/// which names where the order is and leaves whoever is reading it to work
/// out whose move that makes it.
String orderSentence(Map<String, dynamic> order) {
  final status = order['status'] as String? ?? '';
  if (_slipsToCheck(order) > 0 && !_closed(status)) {
    return 'The customer says they have paid. Check your account, then say '
        'whether the money arrived.';
  }
  if (_moneyFound(order) && !_closed(status)) {
    return 'Paid — the money arrived. Turn it into a sale when the goods go '
        'out.';
  }
  switch (status) {
    case 'requested':
      return 'A new order. Check the prices, then send it to the customer.';
    case 'draft':
      return 'Not sent yet. Send it when the prices are right.';
    case 'sent':
      return 'Sent. Waiting for the customer to say yes or pay.';
    case 'accepted':
      return 'The customer said yes. Turn it into a sale when they pay or '
          'collect.';
    case 'declined':
      return 'The customer said no.';
    case 'expired':
      return 'It ran out before the customer answered. Send it again to give '
          'them more time.';
    case 'converted':
      return 'Sold. The goods are off the shelf and it is in your sales.';
    case 'cancelled':
      return 'Turned down.';
    default:
      return '';
  }
}

/// The few words for an order's place in a list.
String orderLabel(Map<String, dynamic> order) {
  final status = order['status'] as String? ?? '';
  if (_slipsToCheck(order) > 0 && !_closed(status)) return 'says paid';
  if (_moneyFound(order) && !_closed(status)) return 'paid';
  return switch (status) {
    'requested' => 'new',
    'draft' => 'not sent',
    'sent' => 'waiting',
    'accepted' => 'said yes',
    'declined' => 'said no',
    'expired' => 'ran out',
    'converted' => 'sold',
    'cancelled' => 'turned down',
    final other => other,
  };
}

/// The colour that goes with it: what needs somebody is the loud one.
String orderTone(Map<String, dynamic> order) {
  final status = order['status'] as String? ?? '';
  if (_slipsToCheck(order) > 0 && !_closed(status)) return 'critical';
  if (_moneyFound(order) && !_closed(status)) return 'ok';
  return switch (status) {
    'requested' || 'draft' => 'warning',
    'accepted' || 'converted' => 'ok',
    _ => 'neutral',
  };
}

/// Which of the orders waiting on the seller to do first.
///
/// Somebody asking whether their money arrived comes first; then somebody
/// who has paid and is waiting for the goods; then somebody waiting for a
/// price; then somebody who has said yes and not yet paid.
int orderUrgency(Map<String, dynamic> order) {
  final status = order['status'] as String? ?? '';
  if (_closed(status)) return 9;
  if (_slipsToCheck(order) > 0) return 0;
  if (_moneyFound(order)) return 1;
  if (status == 'requested' || status == 'draft') return 2;
  if (status == 'accepted') return 3;
  return 4;
}

/// Whether an order is waiting on the seller rather than on the customer.
bool orderNeedsYou(Map<String, dynamic> order) {
  final status = order['status'] as String? ?? '';
  if (_closed(status)) return false;
  return _slipsToCheck(order) > 0 ||
      _moneyFound(order) ||
      status == 'requested' ||
      status == 'draft' ||
      status == 'accepted';
}

/// One order from the online shop, and everything a seller does to it.
///
/// The phone rang about these — "a customer asked for a price", "a customer
/// says they have paid" — and then had nowhere to open them: the Shop tab
/// listed enquiries and nothing else, so every order was a walk to a desk.
/// The person holding the phone is the one the customer is waiting on.
class ShopOrderScreen extends StatefulWidget {
  const ShopOrderScreen({super.key, required this.orderId});

  final String orderId;

  @override
  State<ShopOrderScreen> createState() => _ShopOrderScreenState();
}

class _ShopOrderScreenState extends State<ShopOrderScreen> {
  Map<String, dynamic>? _order;
  List<Map<String, dynamic>> _slips = const [];
  bool _loading = true;
  bool _busy = false;
  bool _offline = false;
  bool _changed = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    final id = widget.orderId;
    try {
      final dynamic order = await state.api.get('/shop/quotations/$id');
      final dynamic slips =
          await state.api.get('/shop/quotations/$id/payment-slips');
      if (!mounted) return;
      setState(() {
        _order = Map<String, dynamic>.from(order as Map);
        _slips = (((slips as Map?)?['items'] as List<dynamic>?) ?? const [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        _offline = false;
        _loading = false;
      });
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        if (!exception.isNetworkError) _error = exception.message;
        _loading = false;
      });
    }
  }

  /// Do one thing to the order, say what came of it, and catch up.
  Future<bool> _act(
    Future<dynamic> Function(ApiClient api) work,
    String Function(dynamic response) said,
  ) async {
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final dynamic response = await work(state.api);
      _changed = true;
      final words = said(response);
      if (words.isNotEmpty) {
        messenger.showSnackBar(SnackBar(content: Text(words)));
      }
      if (mounted) await _load();
      return true;
    } on ApiException catch (exception) {
      if (!mounted) return false;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. An order is never kept on the phone, so this '
              'has to wait until you are back online.'
          : exception.message);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _status => _order?['status'] as String? ?? '';
  bool get _canEdit => _order?['can_edit'] as bool? ?? false;
  bool get _live => !const {'converted', 'cancelled'}.contains(_status);
  bool get _awaiting => _status == 'requested' || _status == 'draft';
  bool get _expired => _status == 'expired';

  /// The shop has found the money for it: the goods are the customer's.
  bool get _paid => _slips.any((slip) => slip['status'] == 'accepted');

  /// Somebody says they have paid, and nobody has looked yet.
  bool get _claimed => _slips.any((slip) => slip['status'] == 'submitted');

  /// Whether the figures can still change.  Not once money has been sent
  /// against them: the customer paid for what the order said, and the
  /// order goes on saying it.
  bool _editable(bool manage) => _canEdit && manage && !_paid && !_claimed;

  /// The customer walked away from it, one way or the other — unless they
  /// paid for it, in which case the goods are theirs whatever the date.
  bool get _lapsed => !_paid && (_expired || _status == 'declined');

  /// A product on it with no price yet, which the server will not send.
  bool get _unpriced =>
      ((_order?['lines'] as List<dynamic>?) ?? const []).any((line) =>
          (line as Map)['variant_id'] != null &&
          (Money.parse(line['unit_price']) ?? 0) == 0);

  // ------------------------------------------------------------------- //
  // The seller's moves
  // ------------------------------------------------------------------- //

  Future<void> _send() => _act(
        (api) => api.post('/shop/quotations/${widget.orderId}/send'),
        (_) => 'Sent. The customer can see your prices now.',
      );

  Future<void> _turnDown() async {
    final reason = await askForReason(
      context,
      title: 'Turn this order down?',
      body: 'The customer will see that it is no longer on offer. This '
          'cannot be undone.',
      hint: 'Why (optional) — out of stock, say',
      confirm: 'Turn it down',
    );
    if (reason == null || !mounted) return;
    await _act(
      (api) => api.post(
        '/shop/quotations/${widget.orderId}/cancel',
        body: {'reason': reason.isEmpty ? null : reason},
      ),
      (_) => 'Turned down.',
    );
  }

  /// Change one line's quantity or price, and write the whole list back.
  Future<void> _editLine(int index) async {
    final lines = ((_order?['lines'] as List<dynamic>?) ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final edited = await showDialog<(String, String)>(
      context: context,
      builder: (_) => _LineDialog(line: lines[index]),
    );
    if (edited == null || !mounted) return;
    lines[index]['quantity'] = edited.$1;
    lines[index]['unit_price'] = edited.$2;
    final alreadySent = _status == 'sent';
    await _act(
      (api) => api.patch('/shop/quotations/${widget.orderId}', body: {
        'lines': [
          for (final line in lines)
            {
              if (line['variant_id'] != null) 'variant_id': line['variant_id'],
              'description': line['description'],
              'quantity': '${line['quantity']}',
              'unit_price': '${line['unit_price']}',
              'discount_amount': '${line['discount_amount'] ?? '0'}',
              'tax_rate': '${line['tax_rate'] ?? '0'}',
            }
        ],
      }),
      (_) => alreadySent
          ? 'Changed. The customer sees the new figures on their link.'
          : 'Changed. The customer sees nothing until you send it.',
    );
  }

  Future<void> _sell() async {
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    final total = Money.parse(_order?['total_amount']) ?? 0;
    final delivery = Money.parse(_order?['delivery_charge']) ?? 0;
    // A slip the seller has already found is how it was paid.
    final found = _slips
        .where((slip) => slip['status'] == 'accepted')
        .map((slip) => slip['method'] as String?)
        .toList();
    final taken = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _SellSheet(
        // A sale has no line for delivery, so what is sold is the goods.
        total: total - delivery,
        delivery: delivery,
        currency: state.session?.currency ?? 'ETB',
        method: found.isEmpty
            ? 'cash'
            : _methods.any((entry) => entry.$1 == found.first)
                ? found.first!
                : 'bank_transfer',
        mayCredit: state.session?.can('credit:create') ?? false,
        branches:
            state.branches.map((branch) => (branch.id, branch.name)).toList(),
      ),
    );
    if (taken == null || !mounted) return;
    String? saleId;
    var warnings = const <String>[];
    final ok = await _act(
      (api) => api.post(
        '/shop/quotations/${widget.orderId}/convert',
        body: taken,
      ),
      (response) {
        final map = response as Map?;
        final sale = map?['sale'] as Map?;
        saleId = sale?['id'] as String?;
        warnings = ((map?['warnings'] as List<dynamic>?) ?? const [])
            .map((warning) => '$warning')
            .toList();
        return 'Sold${sale?['number'] == null ? '' : ' · ${sale!['number']}'}.';
      },
    );
    if (!ok || !mounted) return;
    // The shelves and the day's takings both just moved.
    await state.refresh();
    if (!mounted) return;
    if (warnings.isNotEmpty) {
      await showDialog<void>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: const Text('Sold — one thing to know'),
          content: Text(warnings.join('\n\n')),
          actions: [
            FilledButton(
              onPressed: () => Navigator.of(dialog).pop(),
              child: const Text('OK'),
            ),
          ],
        ),
      );
    }
    if (saleId != null && (state.session?.can('sale:view') ?? false)) {
      await navigator.push<void>(
        MaterialPageRoute(builder: (_) => SaleDetailScreen(saleId: saleId!)),
      );
    }
  }

  Future<void> _review(Map<String, dynamic> slip, {required bool found}) async {
    final currency = AppScope.of(context).session?.currency ?? 'ETB';
    String? note;
    if (found) {
      // Nothing moves in the books, but a stranger is told their money
      // arrived, and that is not something to say by a slip of the thumb.
      final amount = slip['amount_claimed'] == null
          ? 'the money'
          : Money.format(slip['amount_claimed'], currency: currency);
      final sure = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: Text('You found $amount in your account?'),
          content: const Text('The customer will be told it arrived.'),
          actions: [
            DialogActions(
              back: OutlinedButton(
                onPressed: () => Navigator.of(dialog).pop(false),
                child: const Text('Not yet'),
              ),
              confirm: FilledButton(
                key: const Key('slipFoundConfirm'),
                onPressed: () => Navigator.of(dialog).pop(true),
                child: const Text('Yes'),
              ),
            ),
          ],
        ),
      );
      if (sure != true || !mounted) return;
    } else {
      note = await askForReason(
        context,
        title: 'The money did not arrive?',
        body: 'The customer will be told it was not found.',
        hint: 'What to tell them (optional)',
        confirm: 'Not found',
      );
      if (note == null || !mounted) return;
    }
    await _act(
      (api) => api.post(
        '/shop/payment-slips/${slip['id']}/review',
        body: {
          'accept': found,
          if (note != null && note.isNotEmpty) 'note': note,
        },
      ),
      (_) => found
          // Finding the money is not the same as selling the goods, and
          // the books only move on the second.
          ? 'Marked as arrived. Turn the order into a sale to put it in '
              'your books.'
          : 'Marked as not found.',
    );
  }

  Future<void> _seeSlip(Map<String, dynamic> slip) async {
    final api = AppScope.of(context).api;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      final (bytes, kind) =
          await api.getBytes('/shop/payment-slips/${slip['id']}/file');
      if (!mounted) return;
      if (!kind.startsWith('image/')) {
        messenger.showSnackBar(const SnackBar(
          content: Text(
            'This slip is a document, not a picture. Open it on the web to '
            'read it.',
          ),
        ));
        return;
      }
      final currency = AppScope.of(context).session?.currency ?? 'ETB';
      await showDialog<void>(
        context: context,
        builder: (dialog) {
          final theme = Theme.of(dialog);
          final height = MediaQuery.of(dialog).size.height;
          return Dialog(
            clipBehavior: Clip.antiAlias,
            insetPadding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Which slip this is, so the figure on it can be read
                // against the figure the customer typed.
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                  child: Text(
                    [
                      if (slip['amount_claimed'] != null)
                        Money.format(slip['amount_claimed'],
                            currency: currency),
                      if (slip['reference'] != null) 'ref ${slip['reference']}',
                    ].join(' · '),
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                // A fixed area, so a photo of a slip fills it whatever size
                // it was taken at, and can be pinched to read the small
                // print.
                SizedBox(
                  height: height * 0.6,
                  child: InteractiveViewer(
                    maxScale: 6,
                    child: Image.memory(
                      bytes,
                      fit: BoxFit.contain,
                      width: double.infinity,
                      height: double.infinity,
                      filterQuality: FilterQuality.medium,
                      errorBuilder: (_, __, ___) => const Center(
                        child: Padding(
                          padding: EdgeInsets.all(24),
                          child: Text(
                            'This picture could not be shown. Open it on '
                            'the web.',
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: TextButton(
                    onPressed: () => Navigator.of(dialog).pop(),
                    child: const Text('Close'),
                  ),
                ),
              ],
            ),
          );
        },
      );
    } on ApiException catch (exception) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text(exception.isNetworkError
            ? 'No connection. The slip is not kept on the phone.'
            : exception.message),
      ));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copyLink() async {
    final url = (_order?['share'] as Map?)?['url'] as String?;
    if (url == null) return;
    final messenger = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: url));
    messenger.showSnackBar(const SnackBar(
      content: Text('Link copied. Paste it to the customer.'),
    ));
  }

  Future<void> _launch(String? url) async {
    if (url == null) return;
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

  // ------------------------------------------------------------------- //

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      // Whatever was done here changes the list this was opened from.
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.of(context).pop(_changed);
      },
      child: Scaffold(
        appBar: AppBar(title: Text(_order?['number'] as String? ?? 'Order')),
        bottomNavigationBar: _order == null ? null : _nextStep(context),
        body: SafeArea(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _order != null
                  ? _body(context)
                  : _offline
                      ? const EmptyState(
                          icon: Icons.cloud_off,
                          title: 'Orders need a connection',
                          message:
                              'An order is never kept on the phone, so it is '
                              'never shown — or answered — out of date.',
                        )
                      : EmptyState(
                          icon: Icons.search_off,
                          title: 'Not found',
                          message: _error ?? 'This order is no longer there.',
                        ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final order = _order!;
    final manage = session?.can('quotation:manage') ?? false;
    final lines = ((order['lines'] as List<dynamic>?) ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
    final phone = order['customer_phone'] as String?;
    final message = order['customer_message'] as String?;
    final share = order['share'] as Map?;
    final awaiting = _awaiting;
    final expired = _expired;
    final lapsed = _lapsed;
    final editable = _editable(manage);
    final delivery = Money.parse(order['delivery_charge']) ?? 0;
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          // Whose move it is, before anything else.
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: Material(
              color: theme.colorScheme.secondaryContainer,
              borderRadius: BorderRadius.circular(12),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      orderSentence(order),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: theme.colorScheme.onSecondaryContainer,
                      ),
                    ),
                    if (order['source'] == 'marketplace' && awaiting)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          'It came through the marketplace, so other shops '
                          'were asked too. A quick, fair price wins it.',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSecondaryContainer,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
          // Who is asking, and how to reach them.
          ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(order['customer_name'] as String? ?? 'A customer'),
            subtitle: Text(
              [
                if (phone != null && phone.isNotEmpty) phone,
                if (order['customer_company'] != null)
                  '${order['customer_company']}',
                if (order['delivery_location'] != null)
                  'Deliver to ${order['delivery_location']}',
                Money.dateTime(order['created_at']),
              ].join(' · '),
            ),
            trailing: phone == null || phone.isEmpty
                ? null
                : TextButton.icon(
                    onPressed: () => _launch('tel:$phone'),
                    icon: const Icon(Icons.phone_outlined, size: 18),
                    label: const Text('Call'),
                  ),
          ),
          if (message != null && message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                '“$message”',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontStyle: FontStyle.italic),
              ),
            ),
          const Divider(height: 1),
          if (editable)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Text(
                _status == 'sent'
                    ? 'Tap a line to change it. The customer sees the new '
                        'figures straight away.'
                    : 'Tap a line to change its price or how many.',
                style: muted,
              ),
            ),
          for (var index = 0; index < lines.length; index += 1)
            _lineTile(context, lines[index], index, editable),
          if (delivery > 0)
            ListTile(
              dense: true,
              title: const Text('Delivery'),
              trailing: Text(Money.amount(delivery)),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 24, 0),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Total', style: theme.textTheme.titleMedium),
                Text(
                  Money.format(order['total_amount'], currency: currency),
                  style: theme.textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
          // How long the price holds matters until somebody pays it.
          if (order['valid_until'] != null &&
              _live &&
              !awaiting &&
              _slips.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 2, 24, 0),
              child: Text(
                expired
                    ? 'The price ran out on ${Money.date(order['valid_until'])}.'
                    : 'The price holds until '
                        '${Money.date(order['valid_until'])}.',
                textAlign: TextAlign.right,
                style: muted,
              ),
            ),
          const SizedBox(height: 8),
          if (_slips.isNotEmpty) ...[
            const Divider(height: 1),
            const SectionTitle('Proof of payment'),
            for (final slip in _slips) _slipCard(context, slip, manage),
          ],
          if (share?['url'] != null && _live && !awaiting && !lapsed)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                children: [
                  TextButton.icon(
                    key: const Key('orderCopyLink'),
                    onPressed: _copyLink,
                    icon: const Icon(Icons.link),
                    label: const Text('Copy the customer’s link'),
                  ),
                  if (share?['telegram'] != null)
                    TextButton.icon(
                      onPressed: () => _launch(share?['telegram'] as String?),
                      icon: const Icon(Icons.send),
                      label: const Text('Telegram'),
                    ),
                ],
              ),
            ),
          if (_live && manage)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Center(
                child: TextButton(
                  key: const Key('orderTurnDown'),
                  onPressed: _busy ? null : _turnDown,
                  child: Text(
                    'Turn it down',
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// The next step, pinned where a thumb finds it whatever is above.
  ///
  /// It sat at the end of the order, under the lines and the slips, so an
  /// order with a slip on it pushed it off the bottom of the phone — just
  /// when the next step mattered most.  Two at most: the one to do, on the
  /// right, and one alternative beside it.
  Widget? _nextStep(BuildContext context) {
    final theme = Theme.of(context);
    final session = AppScope.of(context).session;
    final manage = session?.can('quotation:manage') ?? false;
    final maySell = manage && (session?.can('sale:create') ?? false);
    final saleId = _order?['converted_sale_id'] as String?;
    // Never while a slip is waiting: the customer has paid, or says so, and
    // a fresh price is not what they are waiting for.
    final sendAgain = _expired && _editable(manage);

    final buttons = <Widget>[
      if (_awaiting && manage)
        FilledButton.icon(
          key: const Key('orderSend'),
          onPressed: _busy || _unpriced ? null : _send,
          icon: const Icon(Icons.send_outlined),
          label: Text(_unpriced
              ? 'Give every item a price first'
              : 'Confirm the prices and send'),
        ),
      // Not while a slip waits for an answer: the customer is asking
      // whether their money arrived, and selling first would leave them
      // without one — and record the money by whatever the sheet guessed.
      if (!_awaiting && _live && maySell && !_claimed)
        _lapsed
            ? OutlinedButton.icon(
                key: const Key('orderSell'),
                onPressed: _busy ? null : _sell,
                icon: const Icon(Icons.point_of_sale_outlined),
                label: Text(sendAgain ? 'Sell it' : 'Turn it into a sale'),
              )
            : FilledButton.icon(
                key: const Key('orderSell'),
                onPressed: _busy ? null : _sell,
                icon: const Icon(Icons.point_of_sale_outlined),
                label: const Text('Turn it into a sale'),
              ),
      if (sendAgain)
        FilledButton.icon(
          key: const Key('orderSend'),
          onPressed: _busy || _unpriced ? null : _send,
          icon: const Icon(Icons.send_outlined),
          label: const Text('Send it again'),
        ),
      if (saleId != null && (session?.can('sale:view') ?? false))
        FilledButton.tonalIcon(
          key: const Key('orderSale'),
          onPressed: () => Navigator.of(context).push<void>(
            MaterialPageRoute(
              builder: (_) => SaleDetailScreen(saleId: saleId),
            ),
          ),
          icon: const Icon(Icons.receipt_long_outlined),
          label: const Text('See the sale'),
        ),
    ];
    if (buttons.isEmpty && _error == null) return null;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Why the last step did not happen, beside the button that
            // tried it.
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  _error!,
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ),
            if (buttons.isNotEmpty)
              Row(
                children: [
                  for (var index = 0; index < buttons.length; index += 1) ...[
                    if (index > 0) const SizedBox(width: 8),
                    Expanded(child: buttons[index]),
                  ],
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _lineTile(
    BuildContext context,
    Map<String, dynamic> line,
    int index,
    bool editable,
  ) {
    final theme = Theme.of(context);
    final priced = line['variant_id'] == null ||
        (Money.parse(line['unit_price']) ?? 0) > 0;
    return ListTile(
      key: Key('orderLine$index'),
      dense: true,
      title: Text(line['description'] as String? ?? ''),
      subtitle: Text(
        priced
            ? '${Money.quantity(line['quantity'])} × '
                '${Money.amount(line['unit_price'])}'
            : '${Money.quantity(line['quantity'])} wanted · no price yet',
        style: priced
            ? null
            : TextStyle(
                color: EstockTheme.statusColour('warning', theme.colorScheme),
                fontWeight: FontWeight.w600,
              ),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            Money.amount(line['line_total']),
            style: theme.textTheme.titleSmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          if (editable) ...[
            const SizedBox(width: 6),
            Icon(
              Icons.edit_outlined,
              size: 16,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ],
        ],
      ),
      onTap: editable && !_busy ? () => _editLine(index) : null,
    );
  }

  /// A customer's claim that they have paid, and the seller's answer to it.
  Widget _slipCard(
    BuildContext context,
    Map<String, dynamic> slip,
    bool manage,
  ) {
    final theme = Theme.of(context);
    final currency = AppScope.of(context).session?.currency ?? 'ETB';
    final status = slip['status'] as String? ?? 'submitted';
    final waiting = status == 'submitted';
    final method = slip['method'] as String?;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    slip['amount_claimed'] == null
                        ? 'Amount not given'
                        : Money.format(slip['amount_claimed'],
                            currency: currency),
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                StatusChip(
                  status: waiting
                      ? 'warning'
                      : status == 'accepted'
                          ? 'ok'
                          : 'critical',
                  label: waiting
                      ? 'to check'
                      : status == 'accepted'
                          ? 'arrived'
                          : 'not found',
                ),
              ],
            ),
            Text(
              [
                if (method != null && method.isNotEmpty)
                  _methods
                          .where((entry) => entry.$1 == method)
                          .map((entry) => entry.$2)
                          .firstOrNull ??
                      method.replaceAll('_', ' '),
                if (slip['reference'] != null) 'ref ${slip['reference']}',
                if (slip['sender_name'] != null) 'from ${slip['sender_name']}',
                if (slip['paid_on'] != null)
                  'paid ${Money.date(slip['paid_on'])}',
              ].join(' · '),
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            if ((slip['note'] as String?)?.isNotEmpty ?? false)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('“${slip['note']}”'),
              ),
            if ((slip['review_note'] as String?)?.isNotEmpty ?? false)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'You said: ${slip['review_note']}',
                  style: theme.textTheme.bodySmall,
                ),
              ),
            const SizedBox(height: 4),
            Wrap(
              spacing: 4,
              children: [
                TextButton.icon(
                  key: const Key('slipSee'),
                  onPressed: _busy ? null : () => _seeSlip(slip),
                  icon: const Icon(Icons.image_outlined, size: 18),
                  label: const Text('See the slip'),
                ),
                if (waiting && manage) ...[
                  TextButton(
                    key: const Key('slipFound'),
                    onPressed: _busy ? null : () => _review(slip, found: true),
                    child: Text(
                      'It arrived',
                      style: TextStyle(
                        color:
                            EstockTheme.statusColour('ok', theme.colorScheme),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  TextButton(
                    key: const Key('slipNotFound'),
                    onPressed:
                        _busy ? null : () => _review(slip, found: false),
                    child: const Text('Not found'),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// One line of an order: how many, and at what price.
///
/// It owns its own fields, and so its own controllers: disposing them the
/// moment `showDialog` returns throws, because the dialog is still on
/// screen animating away.
class _LineDialog extends StatefulWidget {
  const _LineDialog({required this.line});

  final Map<String, dynamic> line;

  @override
  State<_LineDialog> createState() => _LineDialogState();
}

class _LineDialogState extends State<_LineDialog> {
  late final _quantity = TextEditingController(
    text: Money.plain(widget.line['quantity']),
  );
  late final _price = TextEditingController(
    text: (Money.parse(widget.line['unit_price']) ?? 0) == 0
        ? ''
        : Money.plain(widget.line['unit_price']),
  );

  @override
  void dispose() {
    _quantity.dispose();
    _price.dispose();
    super.dispose();
  }

  double get _many => double.tryParse(_quantity.text.trim()) ?? 0;
  double? get _each => double.tryParse(_price.text.trim());
  bool get _ready => _many > 0 && (_each ?? 0) > 0;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: Text(widget.line['description'] as String? ?? 'Line'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: const Key('lineQuantity'),
            controller: _quantity,
            textAlign: TextAlign.right,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
            ],
            decoration: const InputDecoration(labelText: 'How many'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('linePrice'),
            controller: _price,
            autofocus: true,
            textAlign: TextAlign.right,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
            ],
            decoration: const InputDecoration(labelText: 'Price each'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 10),
          Text(
            _ready
                ? '${Money.quantity(_many)} × ${Money.amount(_each)} = '
                    '${Money.amount(_many * _each!)}'
                : 'Give it a price and how many.',
            textAlign: TextAlign.right,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
      actions: [
        DialogActions(
          back: OutlinedButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Back'),
          ),
          confirm: FilledButton(
            key: const Key('lineSave'),
            onPressed: !_ready
                ? null
                : () => Navigator.of(context).pop(
                      (_quantity.text.trim(), _price.text.trim()),
                    ),
            child: const Text('Change'),
          ),
        ),
      ],
    );
  }
}

/// The goods are leaving: how much has been paid for them, and how.
///
/// The sheet is the read-back as well as the form — it says what is about
/// to happen to the shelf and to the customer's account before the one
/// button that does it.
class _SellSheet extends StatefulWidget {
  const _SellSheet({
    required this.total,
    required this.delivery,
    required this.currency,
    required this.method,
    required this.mayCredit,
    required this.branches,
  });

  /// What the goods come to: the order's total without its delivery.
  final double total;
  final double delivery;
  final String currency;
  final String method;

  /// Whether this person may let goods go before they are paid for.
  final bool mayCredit;
  final List<(String, String)> branches;

  @override
  State<_SellSheet> createState() => _SellSheetState();
}

class _SellSheetState extends State<_SellSheet> {
  late final _paid = TextEditingController(text: Money.plain(widget.total));
  late String _method = widget.method;
  late String? _branchId =
      widget.branches.isEmpty ? null : widget.branches.first.$1;
  String? _duePreset;

  @override
  void dispose() {
    _paid.dispose();
    super.dispose();
  }

  double get _typed => double.tryParse(_paid.text.trim()) ?? 0;
  bool get _over => _typed > widget.total + 0.004;
  double get _owing {
    final left = widget.total - _typed;
    return left < 0.005 ? 0 : left;
  }

  bool get _blocked => _owing > 0 && !widget.mayCredit;

  String _money(double value) =>
      Money.format(value, currency: widget.currency);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Turn it into a sale', style: theme.textTheme.titleMedium),
              const SizedBox(height: 2),
              Text(
                'The goods come off the shelf now: ${_money(widget.total)}.',
                style: muted,
              ),
              if (widget.delivery > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    'Delivery (${_money(widget.delivery)}) is not part of '
                    'the sale. Collect it separately.',
                    style: muted,
                  ),
                ),
              const SizedBox(height: 14),
              if (widget.branches.length > 1) ...[
                DropdownButtonFormField<String>(
                  key: const Key('sellBranch'),
                  isExpanded: true,
                  value: _branchId,
                  decoration: const InputDecoration(labelText: 'Sold from'),
                  items: [
                    for (final branch in widget.branches)
                      DropdownMenuItem(
                        value: branch.$1,
                        child: Text(branch.$2),
                      ),
                  ],
                  onChanged: (value) => setState(() => _branchId = value),
                ),
                const SizedBox(height: 12),
              ],
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('sellPaid'),
                      controller: _paid,
                      textAlign: TextAlign.right,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                      ],
                      decoration: InputDecoration(
                        labelText: 'Paid so far',
                        errorText: _over ? 'More than the goods' : null,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: DropdownButtonFormField<String>(
                      key: const Key('sellMethod'),
                      isExpanded: true,
                      value: _method,
                      decoration: const InputDecoration(labelText: 'Paid by'),
                      items: [
                        for (final entry in _methods)
                          DropdownMenuItem(
                            value: entry.$1,
                            child: Text(entry.$2),
                          ),
                      ],
                      onChanged: (value) =>
                          setState(() => _method = value ?? 'cash'),
                    ),
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  _over
                      ? 'The goods only come to ${_money(widget.total)}.'
                      : _blocked
                          ? 'You are not allowed to sell on credit, so the '
                              'whole ${_money(widget.total)} has to be paid '
                              'first.'
                          : _owing > 0
                              ? '${_money(_owing)} stays owing, on this '
                                  'customer’s credit.'
                              : 'Paid in full.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: _over || _blocked
                        ? theme.colorScheme.error
                        : _owing > 0
                            ? EstockTheme.statusColour(
                                'warning', theme.colorScheme)
                            : theme.colorScheme.onSurfaceVariant,
                    fontWeight: _owing > 0 ? FontWeight.w600 : null,
                  ),
                ),
              ),
              if (_owing > 0 && !_blocked && !_over) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String?>(
                  key: const Key('sellDue'),
                  isExpanded: true,
                  value: _duePreset,
                  decoration:
                      const InputDecoration(labelText: 'Pay the rest by'),
                  items: [
                    for (final entry in _duePresets)
                      DropdownMenuItem(
                        value: entry.$1,
                        child: Text(entry.$2),
                      ),
                  ],
                  onChanged: (value) => setState(() => _duePreset = value),
                ),
              ],
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('sellConfirm'),
                onPressed: _over || _blocked
                    ? null
                    : () => Navigator.of(context).pop(<String, dynamic>{
                          if (_branchId != null) 'branch_id': _branchId,
                          'payments': _typed > 0
                              ? [
                                  {
                                    'method': _method,
                                    'amount': _typed.toStringAsFixed(2),
                                  }
                                ]
                              : <Map<String, dynamic>>[],
                          if (_owing > 0 && _duePreset != null)
                            'due_date_preset': _duePreset,
                        }),
                child: Text(
                  _over
                      ? 'That is more than the goods'
                      : _blocked
                          ? 'Needs the full amount'
                          : _owing > 0
                              ? 'Sell it · ${_money(_owing)} on credit'
                              : 'Sell it · paid in full',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
