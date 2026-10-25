import 'package:flutter/material.dart';

import '../core/app_state.dart';
import '../widgets/offline_banner.dart';
import 'home_screen.dart';
import 'more_screen.dart';
import 'sale_screen.dart';
import 'shop_screen.dart';
import 'stock_screen.dart';

/// One tab of the bottom bar.
class _Tab {
  const _Tab({
    required this.label,
    required this.title,
    required this.icon,
    required this.screen,
    this.permission,
    this.ownsTitle = false,
    this.showsNotices = false,
  });

  /// What the bar calls it.
  final String label;

  /// What the heading above the screen calls it, which is not always the
  /// same: the Sales tab opens the till, and "New sale" is what that is.
  final String title;

  /// One icon, whichever tab is open: the bar says where you are with colour,
  /// the way the web's does, not by filling the icon in.
  final IconData icon;

  final Widget screen;

  /// What the signed-in user must be allowed to do for the tab to be there.
  /// Null means everyone gets it.
  final String? permission;

  /// Set where the screen draws its own heading and the shell should not add
  /// one above it.
  final bool ownsTitle;

  /// Set on the tab that leads to the notifications, which carries the count
  /// of what is waiting. A notice nobody can see is a sale lost.
  final bool showsNotices;
}

/// The five the web shows on a phone, in the same order and with the same
/// icons: Home, Sales, Stock, Shop, More (PRD 7).
///
/// Home and More carry no permission, so there is always a bar and always a
/// way to the rest of the app, however little a role is allowed to do.
const _tabs = <_Tab>[
  _Tab(
    label: 'Home',
    title: 'Home',
    icon: Icons.home_outlined,
    screen: HomeScreen(),
    ownsTitle: true,
  ),
  _Tab(
    label: 'Sales',
    title: 'New sale',
    icon: Icons.receipt_long_outlined,
    screen: SaleScreen(),
    // The web's Sales tab opens a list of sales, so it asks for sale:view.
    // This one opens the till, which is a sale being made.
    permission: 'sale:create',
  ),
  _Tab(
    label: 'Stock',
    title: 'Stock',
    icon: Icons.inventory_2_outlined,
    screen: StockScreen(),
    permission: 'stock:view',
  ),
  _Tab(
    label: 'Shop',
    title: 'Shop',
    icon: Icons.storefront_outlined,
    screen: ShopScreen(),
    permission: 'shop:view',
  ),
  _Tab(
    label: 'More',
    title: 'More',
    icon: Icons.more_horiz,
    screen: MoreScreen(),
    showsNotices: true,
  ),
];

/// The signed-in frame.
///
/// Primary navigation is deliberately short and hides what the signed-in user
/// may not use — the same rule the web follows, because a tab that opens a
/// screen the server will refuse is worse than no tab at all. The offline
/// banner sits above them, so the state of unsynced work is visible from
/// every screen.
class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});

  @override
  State<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends State<ShellScreen> {
  /// An index into the tabs on screen, not into [_tabs]: which of those are
  /// shown depends on the role.
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final session = state.session;
    final readOnly = session?.readOnly ?? false;

    final tabs = _tabs
        .where((tab) =>
            tab.permission == null || (session?.can(tab.permission!) ?? false))
        .toList();
    // A session refresh can take a tab away while the app is open, so the
    // index is clamped rather than trusted.
    final index = _index.clamp(0, tabs.length - 1);
    final current = tabs[index];

    return Scaffold(
      appBar: current.ownsTitle
          ? null
          : AppBar(
              title: Text(current.title),
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
                    session?.subscriptionMessage ??
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
                index: index,
                children: [for (final tab in tabs) tab.screen],
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: DecoratedBox(
        // The rule along the top that the web's bar has, which a flat bar
        // needs to sit apart from whatever scrolls past underneath it.
        decoration: BoxDecoration(
          border: Border(
            top:
                BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
          ),
        ),
        child: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (next) => setState(() => _index = next),
          destinations: [
            for (final tab in tabs)
              NavigationDestination(
                icon: tab.showsNotices && state.unreadNotifications > 0
                    ? Badge.count(
                        count: state.unreadNotifications,
                        child: Icon(tab.icon),
                      )
                    : Icon(tab.icon),
                label: tab.label,
              ),
          ],
        ),
      ),
    );
  }
}
