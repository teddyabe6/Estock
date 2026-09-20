import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../widgets/offline_banner.dart';
import 'home_screen.dart';
import 'more_screen.dart';
import 'sale_screen.dart';
import 'shop_screen.dart';
import 'stock_screen.dart';

/// The signed-in frame.
///
/// Primary navigation is deliberately short — Home, Sales, Stock, Shop, More
/// (PRD 7) — and the offline banner sits above it so the state of unsynced
/// work is visible from every screen.
class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});

  @override
  State<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends State<ShellScreen> {
  int _index = 0;

  static const _titles = ['Home', 'New sale', 'Stock', 'Shop', 'More'];

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final readOnly = state.session?.readOnly ?? false;

    return Scaffold(
      appBar: _index == 0
          ? null
          : AppBar(
              title: Text(_titles[_index]),
              actions: [
                if (state.sync.isSyncing)
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 16),
                    child: Center(
                      child: SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                  ),
              ],
            ),
      body: SafeArea(
        child: Column(
          children: [
            const OfflineBanner(),
            if (readOnly)
              Material(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  child: Text(
                    state.session?.subscriptionMessage ??
                        'This account is read-only. Your data is safe — '
                            'subscribe to record new transactions.',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.onErrorContainer,
                      fontSize: 12,
                    ),
                  ),
                ),
              ),
            Expanded(
              child: IndexedStack(
                index: _index,
                children: const [
                  HomeScreen(),
                  SaleScreen(),
                  StockScreen(),
                  ShopScreen(),
                  MoreScreen(),
                ],
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.point_of_sale_outlined),
            selectedIcon: Icon(Icons.point_of_sale),
            label: 'Sales',
          ),
          NavigationDestination(
            icon: Icon(Icons.inventory_2_outlined),
            selectedIcon: Icon(Icons.inventory_2),
            label: 'Stock',
          ),
          NavigationDestination(
            icon: Icon(Icons.storefront_outlined),
            selectedIcon: Icon(Icons.storefront),
            label: 'Shop',
          ),
          NavigationDestination(
            icon: Icon(Icons.more_horiz),
            label: 'More',
          ),
        ],
      ),
    );
  }
}
