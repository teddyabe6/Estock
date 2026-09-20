import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../core/money.dart';
import '../widgets/common.dart';

/// Stock levels, served from the device so a lookup works anywhere in the shop.
class StockScreen extends StatefulWidget {
  const StockScreen({super.key});

  @override
  State<StockScreen> createState() => _StockScreenState();
}

class _StockScreenState extends State<StockScreen> {
  final _search = TextEditingController();
  bool _lowOnly = false;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    var products = state.search(_search.text).where((p) => p.trackStock).toList();
    if (_lowOnly) {
      products = products
          .where((p) => p.stockStatus != null && p.stockStatus != 'ok')
          .toList();
    }
    products.sort((a, b) => a.name.compareTo(b.name));

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: TextField(
            controller: _search,
            decoration: const InputDecoration(
              hintText: 'Search stock',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (_) => setState(() {}),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(
            children: [
              FilterChip(
                label: const Text('Needs restocking'),
                selected: _lowOnly,
                onSelected: (value) => setState(() => _lowOnly = value),
              ),
              const Spacer(),
              if (state.catalogueFetchedAt != null)
                Text(
                  'Updated ${Money.dateTime(state.catalogueFetchedAt)}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
            ],
          ),
        ),
        Expanded(
          child: products.isEmpty
              ? EmptyState(
                  icon: Icons.inventory_2_outlined,
                  title: _lowOnly ? 'Nothing needs restocking' : 'No products',
                  message: _lowOnly
                      ? 'Every tracked product is above its reorder level.'
                      : 'Products appear here once they are added.',
                )
              : RefreshIndicator(
                  onRefresh: state.refresh,
                  child: ListView.builder(
                    itemCount: products.length,
                    itemBuilder: (context, index) {
                      final product = products[index];
                      return ListTile(
                        title: Text(product.name),
                        subtitle: Text(
                          [
                            if (product.categoryName != null) product.categoryName!,
                            'per ${product.unitOfMeasure}',
                          ].join(' · '),
                        ),
                        trailing: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              Money.quantity(product.quantityOnHand),
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            if (product.stockStatus != null &&
                                product.stockStatus != 'ok')
                              StatusChip(status: product.stockStatus!),
                          ],
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }
}
