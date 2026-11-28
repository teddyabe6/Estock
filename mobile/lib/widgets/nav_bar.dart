import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/theme.dart';

/// The bottom bar: a rounded bar floating just above the bottom of the
/// screen, with a pill that glides to whichever tab is open.
///
/// Every tab keeps its word as well as its icon. Icons alone are tidier,
/// but somebody new to a phone app reads "Stock" faster than they decode a
/// box, and the bar is how they find their way around everything else.
class EstockNavBar extends StatelessWidget {
  const EstockNavBar({
    super.key,
    required this.destinations,
    required this.selectedIndex,
    required this.onDestinationSelected,
  });

  final List<EstockNavDestination> destinations;
  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  static const _height = 64.0;
  static const _radius = 24.0;

  /// How far the pill sits inside the bar's edge.
  static const _inset = 6.0;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final palette = context.palette;
    final dark = theme.brightness == Brightness.dark;
    return SafeArea(
      top: false,
      // Clear of the phone's own gesture bar, and never flush with the edge.
      minimum: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 4, 14, 0),
        child: Container(
          height: _height,
          decoration: BoxDecoration(
            color: theme.cardTheme.color ?? theme.colorScheme.surface,
            borderRadius: BorderRadius.circular(_radius),
            border: dark ? Border.all(color: palette.line) : null,
            boxShadow: [
              BoxShadow(
                color: dark ? Colors.black54 : const Color(0x240F2A27),
                blurRadius: 24,
                offset: const Offset(0, 8),
              ),
              BoxShadow(
                color: dark ? Colors.black26 : const Color(0x0F0F2A27),
                blurRadius: 4,
                offset: const Offset(0, 1),
              ),
            ],
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth / destinations.length;
              return Stack(
                children: [
                  AnimatedPositioned(
                    duration: const Duration(milliseconds: 320),
                    curve: Curves.easeOutCubic,
                    left: width * selectedIndex + _inset,
                    top: _inset,
                    bottom: _inset,
                    width: width - _inset * 2,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: palette.brandTint,
                        borderRadius: BorderRadius.circular(_radius - _inset),
                      ),
                    ),
                  ),
                  Row(
                    children: [
                      for (var i = 0; i < destinations.length; i++)
                        Expanded(
                          child: _DestinationState(
                            selected: i == selectedIndex,
                            onTap: () {
                              if (i != selectedIndex) {
                                HapticFeedback.selectionClick();
                              }
                              onDestinationSelected(i);
                            },
                            child: destinations[i],
                          ),
                        ),
                    ],
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

/// One tab: its icon (filled while it is open), its word, and how many
/// things wait there, if any.
class EstockNavDestination extends StatelessWidget {
  const EstockNavDestination({
    super.key,
    required this.icon,
    required this.selectedIcon,
    required this.label,
    this.waiting = 0,
  });

  final IconData icon;
  final IconData selectedIcon;
  final String label;

  /// Shown as a red count on the icon.
  final int waiting;

  @override
  Widget build(BuildContext context) {
    final state = _DestinationState.of(context);
    final selected = state.selected;
    final palette = context.palette;
    final colour = selected ? palette.brandStrong : palette.muted;

    Widget glyph = AnimatedSwitcher(
      duration: const Duration(milliseconds: 220),
      transitionBuilder: (child, animation) => FadeTransition(
        opacity: animation,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.8, end: 1).animate(animation),
          child: child,
        ),
      ),
      child: Icon(
        selected ? selectedIcon : icon,
        key: ValueKey(selected),
        size: 24,
        color: colour,
      ),
    );
    if (waiting > 0) glyph = Badge.count(count: waiting, child: glyph);

    return Semantics(
      button: true,
      selected: selected,
      child: InkResponse(
        onTap: state.onTap,
        containedInkWell: true,
        highlightShape: BoxShape.rectangle,
        borderRadius: BorderRadius.circular(18),
        highlightColor: Colors.transparent,
        splashColor: palette.brandStrong.withValues(alpha: 0.08),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            glyph,
            const SizedBox(height: 3),
            AnimatedDefaultTextStyle(
              duration: const Duration(milliseconds: 220),
              style: Theme.of(context).textTheme.labelSmall!.copyWith(
                    fontSize: 11.5,
                    letterSpacing: 0,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                    color: colour,
                  ),
              child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      ),
    );
  }
}

/// Whether the tab below it is the open one, and what tapping it does.
class _DestinationState extends InheritedWidget {
  const _DestinationState({
    required this.selected,
    required this.onTap,
    required super.child,
  });

  final bool selected;
  final VoidCallback onTap;

  static _DestinationState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<_DestinationState>()!;

  @override
  bool updateShouldNotify(_DestinationState old) =>
      selected != old.selected || onTap != old.onTap;
}
