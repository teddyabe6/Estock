import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/money.dart';
import '../core/theme.dart';
import '../models/product.dart';
import '../widgets/common.dart';
import 'stock_product_screen.dart';

/// Units a small shop sells by, for a shop with few of its own yet.
const _commonUnits = ['pcs', 'kg', 'bag', 'litre', 'box', 'bottle', 'sack'];

/// The marker for "a kind of thing not in the list yet" in the category
/// dropdown; never a category name anybody would type.
const _newCategory = '\u0000new';

final _decimal = FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'));

/// A number typed into a field, or null when the field is empty.
///
/// Anything that is typed but is not a number comes back as NaN, so a
/// form can tell "left empty" from "typed wrong".
double? _typed(TextEditingController field) {
  final text = field.text.trim();
  if (text.isEmpty) return null;
  return double.tryParse(text) ?? double.nan;
}

/// One of a unit, in words: "one piece", not "one pcs".
String oneOf(String unit) => switch (unit) {
      'pcs' || 'pc' => 'piece',
      '' => 'one',
      _ => unit,
    };

/// What a price leaves after what it costs, said as a sentence — or a
/// warning, when it leaves nothing.
String? marginSentence({
  required double? price,
  required double? cost,
  required String unit,
  required String currency,
}) {
  if (price == null || cost == null || price.isNaN || cost.isNaN) return null;
  if (price <= 0 || cost <= 0) return null;
  final left = price - cost;
  if (left < 0) {
    return 'That is less than it costs you: you lose '
        '${Money.format(-left, currency: currency)} on each ${oneOf(unit)}.';
  }
  return 'You make ${Money.format(left, currency: currency)} on each '
      '${oneOf(unit)}.';
}

/// Add a product, or change one — from the phone, where the shopkeeper is
/// when a new line arrives or a price moves.
///
/// Only the name is needed.  The price, the unit and how many are here are
/// asked for in that order because that is what the till and the shelf need
/// next; codes, the warning level and the online shop are folded away.
class ProductFormScreen extends StatefulWidget {
  const ProductFormScreen({
    super.key,
    this.product,
    this.name,
    this.askStock = true,
    this.branchId,
    this.returnProduct = false,
  });

  /// The product being changed; null to add one.
  final Product? product;

  /// What somebody searched for and did not find, to start the name with.
  final String? name;

  /// Whether to ask how many are here now.  Not when the product is being
  /// added from a delivery: the delivery itself puts them on the shelf, and
  /// asking twice would count them twice.
  final bool askStock;

  /// Where the stock typed here is, when there is more than one branch.
  final String? branchId;

  /// Hand the new product back to whoever opened this, rather than opening
  /// its page — for a delivery that wants it as a line.
  final bool returnProduct;

  @override
  State<ProductFormScreen> createState() => _ProductFormScreenState();
}

class _ProductFormScreenState extends State<ProductFormScreen> {
  Product? get _product => widget.product;
  Variant? get _variant => _product?.defaultVariant;
  bool get _editing => _product != null;

  /// One price for the product, or one per kind of it.  The form edits the
  /// first sort only; kinds are priced from the product page.
  bool get _simple => (_product?.variants.length ?? 1) <= 1;

  late final _name =
      TextEditingController(text: _product?.name ?? widget.name?.trim() ?? '');
  late final _price =
      TextEditingController(text: Money.plain(_variant?.sellingPrice));
  late final _cost =
      TextEditingController(text: Money.plain(_variant?.purchasePrice));
  final _stock = TextEditingController();
  late final _warnAt =
      TextEditingController(text: Money.plain(_variant?.reorderLevel));
  late final _barcode = TextEditingController(text: _variant?.barcode ?? '');
  late final _sku = TextEditingController(text: _product?.sku ?? '');
  final _otherUnit = TextEditingController();
  final _categoryName = TextEditingController();

  late String _unit = _product?.unitOfMeasure ?? 'pcs';
  bool _otherUnitChosen = false;
  late String? _category = _product?.categoryName;
  late bool _published = _product?.isPublished ?? false;
  String? _branchId;
  late bool _more = _editing &&
      ((_variant?.barcode ?? '').isNotEmpty ||
          (_product?.sku ?? '').isNotEmpty ||
          (_variant?.reorderLevel ?? '').isNotEmpty);
  bool _busy = false;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final branches = AppScope.of(context).branches;
    _branchId ??= branches.any((branch) => branch.id == widget.branchId)
        ? widget.branchId
        : branches.firstOrNull?.id;
  }

  @override
  void dispose() {
    for (final field in [
      _name,
      _price,
      _cost,
      _stock,
      _warnAt,
      _barcode,
      _sku,
      _otherUnit,
      _categoryName,
    ]) {
      field.dispose();
    }
    super.dispose();
  }

  /// The units to offer: this shop's own, most used first, then the common
  /// ones it has not used yet.
  List<String> _units(AppState state) {
    final counted = <String, int>{};
    for (final product in state.products) {
      counted.update(product.unitOfMeasure, (n) => n + 1, ifAbsent: () => 1);
    }
    final own = counted.keys.toList()
      ..sort((a, b) => counted[b]!.compareTo(counted[a]!));
    final units = <String>[...own];
    for (final unit in _commonUnits) {
      if (units.length >= 8) break;
      if (!units.contains(unit)) units.add(unit);
    }
    if (!units.contains(_unit)) units.insert(0, _unit);
    return units;
  }

  List<String> _categories(AppState state) {
    final names = state.products
        .map((product) => product.categoryName)
        .whereType<String>()
        .toSet()
        .toList()
      ..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    if (_product?.categoryName != null && !names.contains(_product!.categoryName)) {
      names.add(_product!.categoryName!);
    }
    return names;
  }

  String get _chosenUnit =>
      _otherUnitChosen ? _otherUnit.text.trim() : _unit;

  String? get _chosenCategory {
    if (_category == _newCategory) {
      final typed = _categoryName.text.trim();
      return typed.isEmpty ? null : typed;
    }
    return _category;
  }

  bool get _numbersRight => [_price, _cost, _stock, _warnAt]
      .map(_typed)
      .every((value) => value == null || (!value.isNaN && value >= 0));

  /// What the edit changes, product by product and price by price.  Only
  /// what changed is sent, so two people changing different things do not
  /// put each other's figures back.
  (Map<String, dynamic>, Map<String, dynamic>) _changes(AppState state) {
    final product = _product!;
    final variant = _variant;
    final session = state.session;
    final seesCost = session?.can('cost:view') ?? false;
    final mayPublish = session?.can('shop:manage') ?? false;

    String plain(String? value) => Money.plain(value);
    final productChanges = <String, dynamic>{
      if (_name.text.trim() != product.name) 'name': _name.text.trim(),
      if (_chosenUnit != product.unitOfMeasure) 'unit_of_measure': _chosenUnit,
      if (_chosenCategory != product.categoryName)
        'category_name': _chosenCategory ?? '',
      if (_simple && _barcode.text.trim() != (variant?.barcode ?? ''))
        'barcode': _barcode.text.trim(),
      if (_sku.text.trim() != (product.sku ?? '')) 'sku': _sku.text.trim(),
      if (mayPublish && _published != product.isPublished)
        'is_published': _published,
    };
    final variantChanges = <String, dynamic>{
      if (_simple && _price.text.trim() != plain(variant?.sellingPrice))
        'selling_price':
            _price.text.trim().isEmpty ? null : _price.text.trim(),
      if (_simple &&
          seesCost &&
          _cost.text.trim() != plain(variant?.purchasePrice))
        'purchase_price': _cost.text.trim().isEmpty ? null : _cost.text.trim(),
      if (_simple && _warnAt.text.trim() != plain(variant?.reorderLevel))
        'reorder_level':
            _warnAt.text.trim().isEmpty ? null : _warnAt.text.trim(),
    };
    return (productChanges, variantChanges);
  }

  Future<void> _save() async {
    final state = AppScope.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final session = state.session;
    final seesCost = session?.can('cost:view') ?? false;
    final mayPublish = session?.can('shop:manage') ?? false;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_editing) {
        final (productChanges, variantChanges) = _changes(state);
        if (productChanges.isNotEmpty) {
          await state.api.patch('/products/${_product!.id}', body: productChanges);
        }
        if (variantChanges.isNotEmpty && _variant != null) {
          await state.api.patch('/variants/${_variant!.id}', body: variantChanges);
        }
        final dynamic fresh = await state.api.get('/products/${_product!.id}');
        await state.putProduct(
          Product.fromJson(Map<String, dynamic>.from(fresh as Map)),
        );
        if (!mounted) return;
        messenger.showSnackBar(const SnackBar(content: Text('Saved.')));
        navigator.pop(true);
        return;
      }

      final stock = _typed(_stock) ?? 0;
      final dynamic created = await state.api.post('/products', body: {
        'name': _name.text.trim(),
        'unit_of_measure': _chosenUnit,
        if (_price.text.trim().isNotEmpty) 'selling_price': _price.text.trim(),
        if (seesCost && _cost.text.trim().isNotEmpty)
          'purchase_price': _cost.text.trim(),
        if (_chosenCategory != null) 'category_name': _chosenCategory,
        if (widget.askStock && stock > 0) ...{
          'opening_stock': _stock.text.trim(),
          if (_branchId != null) 'branch_id': _branchId,
        },
        if (_warnAt.text.trim().isNotEmpty)
          'reorder_level': _warnAt.text.trim(),
        if (_barcode.text.trim().isNotEmpty) 'barcode': _barcode.text.trim(),
        if (_sku.text.trim().isNotEmpty) 'sku': _sku.text.trim(),
        if (mayPublish && _published) 'is_published': true,
      });
      final product =
          Product.fromJson(Map<String, dynamic>.from(created as Map));
      // Into the catalogue on the phone, so the till and the shelves know
      // it straight away; the branch figures catch up behind it.
      await state.putProduct(product);
      unawaited(state.refresh());
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text('Added ${product.name}.')));
      if (widget.returnProduct) {
        navigator.pop(product);
      } else {
        await navigator.pushReplacement<void, void>(MaterialPageRoute(
          builder: (_) => StockProductScreen(
            productId: product.id,
            branchId: state.hasManyBranches ? _branchId : null,
          ),
        ));
      }
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() => _error = exception.isNetworkError
          ? 'No connection. A product is not kept on the phone until the '
              'server has it, so this has to wait until you are back online.'
          : exception.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// The button says what will happen — or what is missing.
  (String, bool) _button(AppState state) {
    if (_name.text.trim().isEmpty) return ('Give it a name first', false);
    if (_otherUnitChosen && _otherUnit.text.trim().isEmpty) {
      return ('Say what it is sold by', false);
    }
    if (_category == _newCategory && _categoryName.text.trim().isEmpty) {
      return ('Name the new kind', false);
    }
    if (!_numbersRight) return ('Check the numbers', false);
    if (_editing) {
      final (productChanges, variantChanges) = _changes(state);
      if (productChanges.isEmpty && variantChanges.isEmpty) {
        return ('Nothing has changed', false);
      }
      return ('Save the changes', true);
    }
    final stock = _typed(_stock) ?? 0;
    if (_price.text.trim().isEmpty) return ('Add it without a price', true);
    if (widget.askStock && stock > 0) {
      return ('Add it · ${Money.quantity(stock)} $_chosenUnit here', true);
    }
    return ('Add it', true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final session = state.session;
    final currency = session?.currency ?? 'ETB';
    final seesCost = session?.can('cost:view') ?? false;
    final mayPublish = session?.can('shop:manage') ?? false;
    final units = _units(state);
    final categories = _categories(state);
    final unit = oneOf(_chosenUnit);
    final margin = marginSentence(
      price: _typed(_price),
      cost: seesCost ? _typed(_cost) : null,
      unit: unit,
      currency: currency,
    );
    final losing = margin?.startsWith('That is less') ?? false;
    final (label, ready) = _button(state);
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);

    void changed(_) => setState(() {});

    return Scaffold(
      appBar: AppBar(
        title: Text(_editing ? 'Change ${_product!.name}' : 'A new product'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            TextField(
              key: const Key('productName'),
              controller: _name,
              autofocus: !_editing && _name.text.isEmpty,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'What is it called?',
                hintText: 'Berbere 1kg, say',
              ),
              onChanged: changed,
            ),
            const SizedBox(height: 18),
            Text('Sold by the', style: theme.textTheme.labelLarge),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                for (final option in units)
                  ChoiceChip(
                    key: Key('unit-$option'),
                    label: Text(option),
                    selected: !_otherUnitChosen && _unit == option,
                    onSelected: (_) => setState(() {
                      _unit = option;
                      _otherUnitChosen = false;
                    }),
                  ),
                ChoiceChip(
                  key: const Key('unit-other'),
                  label: const Text('something else'),
                  selected: _otherUnitChosen,
                  onSelected: (_) => setState(() => _otherUnitChosen = true),
                ),
              ],
            ),
            if (_otherUnitChosen)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: TextField(
                  key: const Key('unitOther'),
                  controller: _otherUnit,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'What is it sold by?',
                    hintText: 'dozen, roll, metre',
                  ),
                  onChanged: changed,
                ),
              ),
            const SizedBox(height: 18),
            if (_simple) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('productPrice'),
                      controller: _price,
                      textAlign: TextAlign.right,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      inputFormatters: [_decimal],
                      decoration: InputDecoration(
                        labelText: 'Sells for',
                        suffixText: currency,
                        helperText: 'for one $unit',
                      ),
                      onChanged: changed,
                    ),
                  ),
                  if (seesCost) ...[
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        key: const Key('productCost'),
                        controller: _cost,
                        textAlign: TextAlign.right,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        inputFormatters: [_decimal],
                        decoration: InputDecoration(
                          labelText: 'It costs you',
                          suffixText: currency,
                          helperText: 'optional',
                        ),
                        onChanged: changed,
                      ),
                    ),
                  ],
                ],
              ),
              if (margin != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    margin,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: losing
                          ? theme.colorScheme.error
                          : EstockTheme.statusColour('ok', theme.colorScheme),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
            ] else
              Text(
                'Each kind of this product has its own price. Change them '
                'from the product page.',
                style: muted,
              ),
            if (!_editing && widget.askStock) ...[
              const SizedBox(height: 18),
              TextField(
                key: const Key('productStock'),
                controller: _stock,
                textAlign: TextAlign.right,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                inputFormatters: [_decimal],
                decoration: InputDecoration(
                  labelText: 'How many do you have now?',
                  suffixText: _chosenUnit,
                  helperText: 'Leave it empty to count them later',
                ),
                onChanged: changed,
              ),
              if (state.branches.length > 1)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: DropdownButtonFormField<String>(
                    key: const Key('productBranch'),
                    isExpanded: true,
                    value: _branchId,
                    decoration: const InputDecoration(labelText: 'At'),
                    items: [
                      for (final branch in state.branches)
                        DropdownMenuItem(
                          value: branch.id,
                          child: Text(branch.name),
                        ),
                    ],
                    onChanged: (value) => setState(() => _branchId = value),
                  ),
                ),
            ],
            const SizedBox(height: 18),
            DropdownButtonFormField<String?>(
              key: const Key('productCategory'),
              isExpanded: true,
              value: _category,
              decoration: const InputDecoration(
                labelText: 'What kind of thing is it?',
                helperText: 'optional — it groups the shelves',
              ),
              items: [
                const DropdownMenuItem<String?>(
                  value: null,
                  child: Text('Not grouped'),
                ),
                for (final name in categories)
                  DropdownMenuItem<String?>(value: name, child: Text(name)),
                const DropdownMenuItem<String?>(
                  value: _newCategory,
                  child: Text('A new kind…'),
                ),
              ],
              onChanged: (value) => setState(() => _category = value),
            ),
            if (_category == _newCategory)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: TextField(
                  key: const Key('categoryName'),
                  controller: _categoryName,
                  autofocus: true,
                  textCapitalization: TextCapitalization.words,
                  decoration: const InputDecoration(
                    labelText: 'Name the kind',
                    hintText: 'Spices, say',
                  ),
                  onChanged: changed,
                ),
              ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: const Key('productMore'),
                onPressed: () => setState(() => _more = !_more),
                icon: Icon(_more ? Icons.expand_less : Icons.expand_more),
                label: Text(_more ? 'Fewer details' : 'More details'),
              ),
            ),
            if (_more) ...[
              if (_simple) ...[
                TextField(
                  key: const Key('productWarnAt'),
                  controller: _warnAt,
                  textAlign: TextAlign.right,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [_decimal],
                  decoration: InputDecoration(
                    labelText: 'Warn me when it is down to',
                    suffixText: _chosenUnit,
                    helperText: 'It shows as running low from there',
                  ),
                  onChanged: changed,
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('productBarcode'),
                  controller: _barcode,
                  decoration: const InputDecoration(
                    labelText: 'Barcode',
                    helperText: 'the number under the stripes, if it has one',
                  ),
                  onChanged: changed,
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                key: const Key('productSku'),
                controller: _sku,
                decoration: const InputDecoration(
                  labelText: 'Your own code for it',
                  helperText: 'optional',
                ),
                onChanged: changed,
              ),
              if (mayPublish)
                SwitchListTile(
                  key: const Key('productPublished'),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Show it in your online shop'),
                  value: _published,
                  onChanged: (value) => setState(() => _published = value),
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
                key: const Key('productSave'),
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

/// Change what one product sells for — the one change made most often,
/// so it is one field and one button, not the whole form.
///
/// Returns true when the price was changed.
Future<bool> changePrice(
  BuildContext context,
  Product product,
  Variant variant,
) async {
  final state = AppScope.of(context);
  final messenger = ScaffoldMessenger.of(context);
  final currency = state.session?.currency ?? 'ETB';
  final answer = await showDialog<(String, String?)>(
    context: context,
    builder: (_) => _PriceDialog(product: product, variant: variant),
  );
  if (answer == null) return false;
  final (price, cost) = answer;
  try {
    await state.api.patch('/variants/${variant.id}', body: {
      'selling_price': price,
      if (cost != null) 'purchase_price': cost,
    });
    final dynamic fresh = await state.api.get('/products/${product.id}');
    await state.putProduct(
      Product.fromJson(Map<String, dynamic>.from(fresh as Map)),
    );
    final name = variant.name == null || variant.name!.isEmpty
        ? product.name
        : '${product.name} — ${variant.name}';
    messenger.showSnackBar(SnackBar(
      content: Text(
        '$name now sells for ${Money.format(price, currency: currency)}.',
      ),
    ));
    return true;
  } on ApiException catch (exception) {
    messenger.showSnackBar(SnackBar(
      content: Text(exception.isNetworkError
          ? 'No connection. The price is as it was; try again when you are '
              'back online.'
          : exception.message),
    ));
    return false;
  }
}

class _PriceDialog extends StatefulWidget {
  const _PriceDialog({required this.product, required this.variant});

  final Product product;
  final Variant variant;

  @override
  State<_PriceDialog> createState() => _PriceDialogState();
}

class _PriceDialogState extends State<_PriceDialog> {
  late final _price =
      TextEditingController(text: Money.plain(widget.variant.sellingPrice));
  late final _cost =
      TextEditingController(text: Money.plain(widget.variant.purchasePrice));

  @override
  void dispose() {
    _price.dispose();
    _cost.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final currency = state.session?.currency ?? 'ETB';
    final seesCost = state.session?.can('cost:view') ?? false;
    final unit = widget.product.unitOfMeasure;
    final price = _typed(_price);
    final cost = seesCost ? _typed(_cost) : null;
    final valid = price != null &&
        !price.isNaN &&
        price >= 0 &&
        (cost == null || (!cost.isNaN && cost >= 0));
    final priceMoved =
        _price.text.trim() != Money.plain(widget.variant.sellingPrice);
    final costMoved = seesCost &&
        _cost.text.trim() != Money.plain(widget.variant.purchasePrice);
    final margin = marginSentence(
      price: price,
      cost: cost,
      unit: unit,
      currency: currency,
    );
    final losing = margin?.startsWith('That is less') ?? false;
    final was = widget.variant.sellingPrice;

    return AlertDialog(
      title: Text(
        widget.variant.name == null || widget.variant.name!.isEmpty
            ? widget.product.name
            : '${widget.product.name} — ${widget.variant.name}',
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: const Key('priceNew'),
            controller: _price,
            autofocus: true,
            textAlign: TextAlign.right,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [_decimal],
            decoration: InputDecoration(
              labelText: 'Sells for',
              suffixText: currency,
              helperText: was == null
                  ? 'for one ${oneOf(unit)} · no price until now'
                  : 'for one ${oneOf(unit)} · was '
                      '${Money.format(was, currency: currency)}',
            ),
            onChanged: (_) => setState(() {}),
          ),
          if (seesCost) ...[
            const SizedBox(height: 12),
            TextField(
              key: const Key('priceCost'),
              controller: _cost,
              textAlign: TextAlign.right,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [_decimal],
              decoration: InputDecoration(
                labelText: 'It costs you',
                suffixText: currency,
              ),
              onChanged: (_) => setState(() {}),
            ),
          ],
          if (margin != null)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                margin,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: losing
                      ? theme.colorScheme.error
                      : EstockTheme.statusColour('ok', theme.colorScheme),
                  fontWeight: FontWeight.w600,
                ),
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
            key: const Key('priceSave'),
            onPressed: valid && (priceMoved || costMoved)
                ? () => Navigator.of(context).pop((
                      _price.text.trim(),
                      costMoved
                          ? (_cost.text.trim().isEmpty ? null : _cost.text.trim())
                          : null,
                    ))
                : null,
            child: const Text('Save'),
          ),
        ),
      ],
    );
  }
}
