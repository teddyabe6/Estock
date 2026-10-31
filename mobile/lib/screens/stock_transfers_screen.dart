import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../models/stock.dart';
import '../widgets/common.dart';
import 'stock_request_screen.dart';

/// Stock moving between branches, and the asking that comes before it (PRD 9).
///
/// A branch that has run out asks; whoever runs the branch being asked allows
/// or refuses; the branch that asked takes it up, and only then does anything
/// move.  All of it is one record, so what was asked for, allowed, refused
/// and actually moved reads as one history rather than two.
///
/// Cards rather than a table: a phone has one column, and three of the four
/// things on a row here are sentences.
class StockTransfersScreen extends StatefulWidget {
  const StockTransfersScreen({super.key});

  @override
  State<StockTransfersScreen> createState() => _StockTransfersScreenState();
}

class _StockTransfersScreenState extends State<StockTransfersScreen> {
  List<StockTransfer> _transfers = const [];
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
      final dynamic rows =
          await state.api.get('/stock/transfers', query: {'limit': '100'});
      if (!mounted) return;
      setState(() {
        _transfers = (rows as List<dynamic>)
            .map((item) => StockTransfer.fromJson(Map<String, dynamic>.from(item as Map)))
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

  Future<void> _act(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final state = AppScope.of(context);
    try {
      await action();
      await _load();
      // The badge on the Stock tab counts what is still waiting.
      await state.refresh();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;
    final mine = state.branches.map((branch) => branch.id).toSet();
    final mayAsk = (session?.can('stock:transfer') ?? false) && mine.length > 1;

    final toDecide = _transfers
        .where((transfer) =>
            transfer.awaitsDecision &&
            (session?.can('stock:transfer_approve') ?? false) &&
            mine.contains(transfer.fromBranchId))
        .toList();
    final toAccept = _transfers
        .where((transfer) =>
            transfer.awaitsAcceptance && mine.contains(transfer.toBranchId))
        .toList();

    return Scaffold(
      // One way in, not two: the button that says what it does is the one
      // worth keeping.
      appBar: AppBar(title: const Text('Transfers')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'Transfers need a connection',
                    message:
                        'Asking for stock and answering a request both go '
                        'straight to the ledger, so neither can wait in the '
                        'outbox.',
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      padding: const EdgeInsets.only(bottom: 88),
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
                        if (toDecide.isNotEmpty) ...[
                          SectionTitle('Waiting for you (${toDecide.length})'),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                            child: Text(
                              'Allowing it does not move anything yet — the '
                              'branch that asked still has to take it up.',
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
                          for (final transfer in toDecide)
                            _card(context, transfer, _decisionActions(transfer)),
                        ],
                        if (toAccept.isNotEmpty) ...[
                          SectionTitle('Yours to take up (${toAccept.length})'),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                            child: Text(
                              'Taking it up moves the stock now: it leaves the '
                              'other branch and arrives at yours.',
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
                          for (final transfer in toAccept)
                            _card(context, transfer, _acceptActions(transfer)),
                        ],
                        const SectionTitle('Everything between branches'),
                        if (_transfers.isEmpty)
                          const EmptyState(
                            icon: Icons.swap_horiz,
                            title: 'Nothing between branches yet',
                            message:
                                'Ask another branch for stock when you run '
                                'short, and it will all be recorded here.',
                          )
                        else
                          for (final transfer in _transfers)
                            _card(context, transfer, const []),
                      ],
                    ),
                  ),
      ),
      floatingActionButton: mayAsk && !_loading && !_offline
          ? FloatingActionButton.extended(
              onPressed: _busy ? null : () => _ask(context),
              icon: const Icon(Icons.swap_horiz),
              label: const Text('Ask for stock'),
            )
          : null,
    );
  }

  Future<void> _ask(BuildContext context) async {
    final state = AppScope.of(context);
    final sent = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const StockRequestScreen()),
    );
    if (sent ?? false) {
      await _load();
      // The badge on the Stock tab counts what is still waiting.
      await state.refresh();
    }
  }

  /// Ask for the note first, then post.  The client is taken before the
  /// dialog opens, because by the time it closes this widget may be gone and
  /// the context with it.
  Future<void> _answer(
    String path, {
    required String title,
    required String hint,
    required String confirm,
    bool required = false,
  }) async {
    final api = AppScope.of(context).api;
    final note = await _noteDialog(
      title: title,
      hint: hint,
      confirm: confirm,
      required: required,
    );
    if (note == null) return;
    await _act(() async {
      await api.post(path, body: {'note': note.isEmpty ? null : note});
    });
  }

  List<Widget> _decisionActions(StockTransfer transfer) => [
        TextButton(
          onPressed: _busy
              ? null
              : () => _answer(
                    '/stock/transfers/${transfer.id}/approve',
                    title: 'Allow ${transfer.reference}?',
                    hint: 'Note for the branch that asked (optional)',
                    confirm: 'Allow it',
                  ),
          child: const Text('Allow'),
        ),
        TextButton(
          onPressed: _busy
              ? null
              : () => _answer(
                    '/stock/transfers/${transfer.id}/reject',
                    title: 'Turn down ${transfer.reference}?',
                    hint: 'Say why — they will read it',
                    confirm: 'Turn it down',
                    required: true,
                  ),
          child: const Text('Turn down'),
        ),
      ];

  List<Widget> _acceptActions(StockTransfer transfer) => [
        FilledButton(
          onPressed: _busy
              ? null
              : () async {
                  final api = AppScope.of(context).api;
                  if (!await _confirmAccept(transfer)) return;
                  await _act(() async {
                    await api.post('/stock/transfers/${transfer.id}/accept');
                  });
                },
          child: const Text('Take it'),
        ),
        TextButton(
          onPressed: _busy
              ? null
              : () => _answer(
                    '/stock/transfers/${transfer.id}/cancel',
                    title: 'No longer need it?',
                    hint: 'Why (optional)',
                    confirm: 'Cancel the request',
                  ),
          child: const Text('Not any more'),
        ),
      ];

  Widget _card(
    BuildContext context,
    StockTransfer transfer,
    List<Widget> actions,
  ) {
    final theme = Theme.of(context);
    final when = transfer.decidedAt ?? transfer.requestedAt;
    final who = transfer.decidedByName ?? transfer.requestedByName;

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    transfer.route,
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                ),
                StatusChip(status: transfer.status),
              ],
            ),
            const SizedBox(height: 6),
            for (final line in transfer.lines)
              Text(
                '${line.name} × ${Money.quantity(line.quantity)}',
                style: theme.textTheme.bodyMedium,
              ),
            if (transfer.note != null && transfer.note!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                '“${transfer.note}”',
                style: theme.textTheme.bodySmall
                    ?.copyWith(fontStyle: FontStyle.italic),
              ),
            ],
            if (transfer.decisionNote != null &&
                transfer.decisionNote!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                transfer.decisionNote!,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
            const SizedBox(height: 4),
            Text(
              [
                transfer.reference,
                if (who != null) who,
                if (when != null) Money.dateTime(when),
              ].join(' · '),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 8),
              // Equal halves rather than a right-aligned row: these are the
              // two answers to one question, and both have to be a thumb
              // wide.  (The app's filled buttons ask for the full width, so
              // a plain Row would overflow and draw nothing at all.)
              Row(
                children: [
                  for (final action in actions) ...[
                    Expanded(child: action),
                    if (action != actions.last) const SizedBox(width: 8),
                  ],
                ],
              ),
              const SizedBox(height: 6),
            ] else
              const SizedBox(height: 6),
          ],
        ),
      ),
    );
  }

  /// The note that goes with a decision.  Returns null when the user backs
  /// out, so "no note" and "never mind" cannot be confused.
  Future<String?> _noteDialog({
    required String title,
    required String hint,
    required String confirm,
    bool required = false,
  }) async {
    final controller = TextEditingController();
    final note = await showDialog<String>(
      context: context,
      builder: (dialog) => StatefulBuilder(
        builder: (dialog, setDialogState) => AlertDialog(
          title: Text(title),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: InputDecoration(hintText: hint),
            onChanged: (_) => setDialogState(() {}),
          ),
          actions: [
            DialogActions(
              back: OutlinedButton(
                onPressed: () => Navigator.of(dialog).pop(),
                child: const Text('Back'),
              ),
              confirm: FilledButton(
                onPressed: required && controller.text.trim().isEmpty
                    ? null
                    : () => Navigator.of(dialog).pop(controller.text.trim()),
                child: Text(confirm),
              ),
            ),
          ],
        ),
      ),
    );
    controller.dispose();
    return note;
  }

  /// Taking up a request moves stock, so it is worth one clear sentence first.
  Future<bool> _confirmAccept(StockTransfer transfer) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Bring it across?'),
        content: Text(
          '${transfer.lines.map((line) => '${line.name} × '
              '${Money.quantity(line.quantity)}').join('\n')}\n\n'
          'leaves ${transfer.fromBranchName ?? 'the other branch'} and arrives '
          'at ${transfer.toBranchName ?? 'yours'} now.',
        ),
        actions: [
          DialogActions(
            back: OutlinedButton(
              onPressed: () => Navigator.of(dialog).pop(false),
              child: const Text('Back'),
            ),
            confirm: FilledButton(
              onPressed: () => Navigator.of(dialog).pop(true),
              child: const Text('Take it'),
            ),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }
}
