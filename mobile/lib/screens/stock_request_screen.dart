import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../models/product.dart';
import '../models/stock.dart';
import '../widgets/common.dart';

/// Asking another branch for stock you have run out of (PRD 9).
///
/// The branch that asks needs no authority over the branch it is asking —
/// that is the whole point of asking — so it gets the branch names and
/// nothing else.  What each branch holds is for whoever decides; a shop
/// assistant in one branch has no business reading another's shelves.
class StockRequestScreen extends StatefulWidget {
  const StockRequestScreen({super.key, this.productId});

  /// Opened from a product, so that product starts in the basket.
  final String? productId;

  @override
  State<StockRequestScreen> createState() => _StockRequestScreenState();
}

class _RequestLine {
  _RequestLine({required this.variantId, required this.name, required this.quantity});

  final String variantId;
  final String name;
  final TextEditingController quantity;
}

class _StockRequestScreenState extends State<StockRequestScreen> {
  final _search = TextEditingController();
  final _note = TextEditingController();
  final _lines = <_RequestLine>[];

  List<TransferBranch> _branches = const [];
  String? _fromBranchId;
  String? _toBranchId;
  bool _loading = true;
  bool _sending = false;
  bool _offline = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _search.dispose();
    _note.dispose();
    for (final line in _lines) {
      line.quantity.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final state = AppScope.of(context);
    try {
      final dynamic rows = await state.api.get('/stock/branches');
      if (!mounted) return;
      final branches = (rows as List<dynamic>)
          .map((item) => TransferBranch.fromJson(Map<String, dynamic>.from(item as Map)))
          .where((branch) => branch.locationId != null)
          .toList();
      setState(() {
        _branches = branches;
        _toBranchId = branches
            .where((branch) => branch.isMine)
            .map((branch) => branch.branchId)
            .firstOrNull;
        _fromBranchId = branches
            .where((branch) => branch.branchId != _toBranchId)
            .map((branch) => branch.branchId)
            .firstOrNull;
        _offline = false;
        _loading = false;
      });
      final productId = widget.productId;
      if (productId != null) {
        final product =
            state.products.where((item) => item.id == productId).firstOrNull;
        if (product != null) _add(product);
      }
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        _offline = exception.isNetworkError;
        _error = exception.isNetworkError ? null : exception.message;
        _loading = false;
      });
    }
  }

  void _add(Product product) {
    final variant = product.defaultVariant;
    if (variant == null) return;
    if (_lines.any((line) => line.variantId == variant.id)) return;
    setState(() {
      _lines.add(_RequestLine(
        variantId: variant.id,
        name: product.name,
        quantity: TextEditingController(text: '1'),
      ));
      _search.clear();
    });
  }

  bool get _ready =>
      _lines.isNotEmpty &&
      _fromBranchId != null &&
      _toBranchId != null &&
      _fromBranchId != _toBranchId &&
      _lines.every((line) => (double.tryParse(line.quantity.text.trim()) ?? 0) > 0);

  Future<void> _send() async {
    if (!_ready) return;
    setState(() {
      _sending = true;
      _error = null;
    });
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    try {
      await state.api.post('/stock/requests', body: {
        'from_location_id': _location(_fromBranchId),
        'to_location_id': _location(_toBranchId),
        'lines': [
          for (final line in _lines)
            {'variant_id': line.variantId, 'quantity': line.quantity.text.trim()}
        ],
        if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
      });
      navigator.pop(true);
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A request has to reach the other branch, so it '
              'cannot wait in the outbox.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  String? _location(String? branchId) => _branches
      .where((branch) => branch.branchId == branchId)
      .map((branch) => branch.locationId)
      .firstOrNull;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final mine = _branches.where((branch) => branch.isMine).toList();
    final sources =
        _branches.where((branch) => branch.branchId != _toBranchId).toList();
    final results = _search.text.trim().isEmpty
        ? const <Product>[]
        : state.search(_search.text).where((product) => product.trackStock).take(6).toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Ask for stock')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _offline
                ? const EmptyState(
                    icon: Icons.cloud_off,
                    title: 'Asking needs a connection',
                    message:
                        'A request has to reach the branch you are asking, so '
                        'it cannot wait in the outbox.',
                  )
                : mine.isEmpty || _branches.length < 2
                    ? const EmptyState(
                        icon: Icons.store_outlined,
                        title: 'Only one branch',
                        message:
                            'A request needs another branch to ask. Add one '
                            'under Settings on the web first.',
                      )
                    : ListView(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                        children: [
                          DropdownButtonFormField<String>(
                            value: sources.any((b) => b.branchId == _fromBranchId)
                                ? _fromBranchId
                                : null,
                            decoration: const InputDecoration(
                              labelText: 'From',
                              helperText: 'The branch you are asking',
                            ),
                            items: [
                              for (final branch in sources)
                                DropdownMenuItem(
                                  value: branch.branchId,
                                  child: Text(branch.branchName),
                                ),
                            ],
                            onChanged: (value) =>
                                setState(() => _fromBranchId = value),
                          ),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<String>(
                            value: _toBranchId,
                            decoration: const InputDecoration(
                              labelText: 'To',
                              helperText: 'Where you need it',
                            ),
                            items: [
                              for (final branch in mine)
                                DropdownMenuItem(
                                  value: branch.branchId,
                                  child: Text(branch.branchName),
                                ),
                            ],
                            onChanged: (value) => setState(() {
                              _toBranchId = value;
                              if (_fromBranchId == value) _fromBranchId = null;
                            }),
                          ),
                          const SizedBox(height: 16),
                          TextField(
                            controller: _search,
                            decoration: const InputDecoration(
                              hintText: 'Find a product',
                              prefixIcon: Icon(Icons.search),
                            ),
                            onChanged: (_) => setState(() {}),
                          ),
                          for (final product in results)
                            ListTile(
                              dense: true,
                              title: Text(product.name),
                              trailing: const Icon(Icons.add),
                              onTap: () => _add(product),
                            ),
                          const SizedBox(height: 8),
                          if (_lines.isEmpty)
                            Text(
                              'Search above and tap a product to add it.',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                            ),
                          for (final line in _lines)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Row(
                                children: [
                                  Expanded(child: Text(line.name)),
                                  SizedBox(
                                    width: 84,
                                    child: TextField(
                                      controller: line.quantity,
                                      textAlign: TextAlign.right,
                                      keyboardType: const TextInputType
                                          .numberWithOptions(decimal: true),
                                      inputFormatters: [
                                        FilteringTextInputFormatter.allow(
                                            RegExp(r'[0-9.]')),
                                      ],
                                      decoration: const InputDecoration(
                                          isDense: true),
                                      onChanged: (_) => setState(() {}),
                                    ),
                                  ),
                                  IconButton(
                                    tooltip: 'Remove',
                                    icon: const Icon(Icons.close),
                                    onPressed: () => setState(() {
                                      line.quantity.dispose();
                                      _lines.remove(line);
                                    }),
                                  ),
                                ],
                              ),
                            ),
                          const SizedBox(height: 8),
                          TextField(
                            controller: _note,
                            decoration: const InputDecoration(
                              labelText: 'Why you need it',
                              hintText: 'e.g. sold out before lunch',
                            ),
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 12),
                            Text(
                              _error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error),
                            ),
                          ],
                          const SizedBox(height: 20),
                          FilledButton(
                            onPressed: _sending || !_ready ? null : _send,
                            // A disabled button that does not say what is
                            // missing is a dead end.
                            child: Text(
                              _sending
                                  ? 'Sending…'
                                  : _lines.isEmpty
                                      ? 'Add a product first'
                                      : 'Send the request',
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Nothing moves until it is allowed and you take it up.',
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant,
                                ),
                          ),
                        ],
                      ),
      ),
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
