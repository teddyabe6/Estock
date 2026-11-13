import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../models/session.dart';
import '../widgets/common.dart';

/// Walking the shelves, writing down what is actually there (PRD 8.3, 9).
///
/// A new branch opens holding every product and none of the quantities, and
/// somebody has to say what is really on its shelves.  That is a job done on
/// foot, one shelf at a time, with a phone in one hand — which is why it
/// belongs here more than it does on a desk.
///
/// It asks for counted quantities, not changes, because that is the only
/// question somebody standing in front of a shelf can answer.  The difference
/// against what is recorded is what gets saved, so a figure that is already
/// right saves nothing and a second pass corrects rather than doubles.
class StockCountScreen extends StatefulWidget {
  const StockCountScreen({super.key, this.branchId});

  /// The branch to open on, when something sent the user straight here.
  final String? branchId;

  @override
  State<StockCountScreen> createState() => _StockCountScreenState();
}

class _StockCountScreenState extends State<StockCountScreen> {
  final _search = TextEditingController();
  final _fields = <String, TextEditingController>{};

  /// What the branch is recorded as holding, by variant, as last loaded.
  final _recorded = <String, double>{};

  List<Map<String, dynamic>> _rows = const [];
  String? _branchId;
  String _branchName = '';
  String _locationName = '';
  int _total = 0;
  int _counted = 0;
  bool _loading = true;
  bool _saving = false;
  bool _offline = false;
  String? _error;
  String _idempotencyKey = UniqueKey().toString();

  @override
  void initState() {
    super.initState();
    _branchId = widget.branchId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final state = AppScope.of(context);
      _branchId ??= state.branchesToCount.isNotEmpty
          ? state.branchesToCount.first.branchId
          : (state.branches.isNotEmpty ? state.branches.first.id : null);
      _load();
    });
  }

  @override
  void dispose() {
    _search.dispose();
    for (final field in _fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final branchId = _branchId;
    if (branchId == null) {
      setState(() => _loading = false);
      return;
    }
    setState(() => _loading = true);
    final state = AppScope.of(context);
    try {
      final dynamic sheet = await state.api.get('/stock/opening', query: {
        'branch_id': branchId,
        if (_search.text.trim().isNotEmpty) 'q': _search.text.trim(),
        'limit': '200',
      });
      if (!mounted) return;
      final payload = Map<String, dynamic>.from(sheet as Map);
      setState(() {
        _rows = (payload['rows'] as List<dynamic>)
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
        for (final row in _rows) {
          _recorded[row['variant_id'] as String] =
              Money.parse(row['quantity']) ?? 0;
        }
        _branchName = payload['branch_name'] as String? ?? '';
        _locationName = payload['location_name'] as String? ?? '';
        _total = (payload['product_count'] as num?)?.toInt() ?? 0;
        _counted = (payload['recorded'] as num?)?.toInt() ?? 0;
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

  /// Only what somebody typed, and only where it differs from the shelf as
  /// recorded.  An empty box means "I did not count this one", never zero.
  Map<String, String> get _changes {
    final changed = <String, String>{};
    _fields.forEach((variantId, field) {
      final text = field.text.trim();
      if (text.isEmpty) return;
      final typed = double.tryParse(text);
      if (typed == null || typed < 0) return;
      if (typed == (_recorded[variantId] ?? 0)) return;
      changed[variantId] = text;
    });
    return changed;
  }

  /// Each change as a sentence, for the summary before it is written.
  List<String> get _changeLines {
    final lines = <String>[];
    for (final row in _rows) {
      final variantId = row['variant_id'] as String;
      final text = _changes[variantId];
      if (text == null) continue;
      final was = _recorded[variantId] ?? 0;
      final now = double.tryParse(text) ?? 0;
      final by = now - was;
      lines.add(
        '${row['name']}   ${Money.quantity(was)} → ${Money.quantity(now)}'
        '   ${by > 0 ? '+' : '−'}${Money.quantity(by.abs())}',
      );
    }
    return lines;
  }

  /// What is about to be written, before it is written.
  ///
  /// A count goes straight to a ledger that is never edited — a wrong
  /// figure is corrected by another count, not taken back — and this screen
  /// is reached with a phone in one hand halfway down a shelf.  Reading the
  /// changes back is the difference between saving a count and saving a
  /// typing mistake.
  Future<bool> _confirm() async {
    final lines = _changeLines;
    final theme = Theme.of(context);
    final ok = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(sheet).size.height * 0.75,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      lines.length == 1
                          ? 'One quantity to change'
                          : '${lines.length} quantities to change',
                      style: theme.textTheme.titleMedium,
                    ),
                    Text(
                      'At $_branchName. The difference goes on the ledger; '
                      'nothing already there is removed.',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final line in lines)
                      ListTile(dense: true, title: Text(line)),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: DialogActions(
                  back: OutlinedButton(
                    onPressed: () => Navigator.of(sheet).pop(false),
                    child: const Text('Keep counting'),
                  ),
                  confirm: FilledButton(
                    onPressed: () => Navigator.of(sheet).pop(true),
                    child: const Text('Save the count'),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    return ok ?? false;
  }

  Future<void> _save() async {
    final branchId = _branchId;
    final changes = _changes;
    if (branchId == null || changes.isEmpty) return;
    if (!await _confirm()) return;
    if (!mounted) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final state = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final dynamic result = await state.api.post('/stock/opening', body: {
        'branch_id': branchId,
        'lines': [
          for (final entry in changes.entries)
            {'variant_id': entry.key, 'quantity': entry.value}
        ],
        'idempotency_key': _idempotencyKey,
      });
      final saved = (result as Map<String, dynamic>)['recorded'] as num? ?? 0;
      for (final field in _fields.values) {
        field.clear();
      }
      _idempotencyKey = UniqueKey().toString();
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            'Recorded $saved product${saved == 1 ? '' : 's'} at $_branchName.',
          ),
        ),
      );
      await state.refresh();
      await _load();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. Counting needs one — your typing is still here.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final branches = state.branches;
    final changes = _changes.length;

    return Scaffold(
      appBar: AppBar(title: const Text('Count stock')),
      body: SafeArea(
        child: Column(
          children: [
            if (branches.length > 1)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: DropdownButtonFormField<String>(
                  isExpanded: true,
                  value: _branchId,
                  decoration: const InputDecoration(labelText: 'Branch'),
                  items: [
                    for (final branch in branches)
                      DropdownMenuItem(
                        value: branch.id,
                        child: Text(_branchLabel(state, branch)),
                      ),
                  ],
                  onChanged: _saving
                      ? null
                      : (value) {
                          // A different branch is a different count, so
                          // nothing typed for the last one carries over.
                          for (final field in _fields.values) {
                            field.clear();
                          }
                          setState(() => _branchId = value);
                          _load();
                        },
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: TextField(
                controller: _search,
                textInputAction: TextInputAction.search,
                decoration: const InputDecoration(
                  hintText: 'Find a product',
                  prefixIcon: Icon(Icons.search),
                ),
                onSubmitted: (_) => _load(),
                onChanged: (_) => setState(() {}),
              ),
            ),
            if (_locationName.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  _progress(changes),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            Expanded(child: _body()),
            if (!_loading && _rows.isNotEmpty)
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                  child: FilledButton(
                    onPressed: _saving || changes == 0 ? null : _save,
                    child: Text(
                      _saving
                          ? 'Saving…'
                          : changes == 0
                              ? 'Type what you count'
                              : 'Save $changes quantit${changes == 1 ? 'y' : 'ies'}',
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// How far through the walk somebody is, in their own terms.
  ///
  /// It used to read "12 of 12 counted", which is the server's sentence:
  /// twelve products carry a quantity here, from any source, sales
  /// included.  Standing in front of a shelf with every box still empty,
  /// that reads as "finished" — the one thing it does not mean.  What the
  /// counter wants to know is how much of their own walk is done.
  String _progress(int written) {
    if (_counted == 0) {
      return 'Nothing recorded here yet · $_total to count';
    }
    if (written == 0) {
      return '$_total products on this shelf list';
    }
    if (written == _total) return 'All $_total written down';
    return '$written of $_total written down';
  }

  String _branchLabel(AppState state, Branch branch) {
    final waiting =
        state.branchesToCount.any((item) => item.branchId == branch.id);
    return waiting ? '${branch.name} — nothing recorded' : branch.name;
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_offline) {
      return const EmptyState(
        icon: Icons.cloud_off,
        title: 'Counting needs a connection',
        message:
            'The count is written straight to the ledger, so it cannot wait '
            'in the outbox. Try again when you are back online.',
      );
    }
    if (_rows.isEmpty) {
      return EmptyState(
        icon: Icons.inventory_2_outlined,
        title: _search.text.trim().isEmpty
            ? 'No products to count'
            : 'Nothing matches that',
        message: _search.text.trim().isEmpty
            ? 'Add products to your catalogue first.'
            : 'Try part of the product name.',
      );
    }
    return ListView.builder(
      itemCount: _rows.length,
      itemBuilder: (context, index) {
        final row = _rows[index];
        final variantId = row['variant_id'] as String;
        final field = _fields.putIfAbsent(variantId, TextEditingController.new);
        final onRecord = Money.parse(row['quantity']) ?? 0;
        final unit = '${row['unit'] ?? ''}';
        final typed = double.tryParse(field.text.trim());
        final difference = typed == null ? null : typed - onRecord;
        final theme = Theme.of(context);

        return ListTile(
          title: Text(row['name'] as String? ?? ''),
          // A branch nobody has counted shows "0" against every line, which
          // reads as twelve facts when it is really one: nothing is recorded
          // yet.  There, the unit is the useful thing to say.
          //
          // Once something is typed the difference takes over, because that
          // is the figure that matters and the one that catches a slip: a
          // missing nought reads as "−540" long before it reaches the
          // ledger.
          subtitle: difference == null
              ? Text(
                  onRecord > 0
                      ? 'On record: ${Money.quantity(onRecord)} $unit'
                      : unit,
                )
              : Text(
                  difference == 0
                      ? 'Same as the record'
                      : '${difference > 0 ? '+' : '−'}'
                          '${Money.quantity(difference.abs())} $unit '
                          'on ${Money.quantity(onRecord)}',
                  style: TextStyle(
                    fontWeight:
                        difference == 0 ? FontWeight.w400 : FontWeight.w600,
                    color: difference == 0
                        ? theme.colorScheme.onSurfaceVariant
                        : difference > 0
                            ? EstockTheme.statusColour('ok', theme.colorScheme)
                            : theme.colorScheme.error,
                  ),
                ),
          trailing: SizedBox(
            width: 96,
            child: TextField(
              controller: field,
              textAlign: TextAlign.right,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              // Walking a shelf is one line after another, so the keyboard
              // offers the next box rather than closing itself.
              textInputAction: TextInputAction.next,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              // No hint: the record is already under the name, and a greyed
              // figure inside the box makes an empty one look answered.
              decoration: const InputDecoration(isDense: true),
              onChanged: (_) => setState(() {}),
            ),
          ),
        );
      },
    );
  }
}
