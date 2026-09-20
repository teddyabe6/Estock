import 'package:flutter/material.dart';

/// One place for colour and shape, so the app reads as a whole.
class EstockTheme {
  EstockTheme._();

  static const seed = Color(0xFF0F766E);

  static ThemeData light() => _base(Brightness.light);
  static ThemeData dark() => _base(Brightness.dark);

  static ThemeData _base(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(seedColor: seed, brightness: brightness);
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: brightness == Brightness.light
          ? const Color(0xFFF6F7F9)
          : scheme.surface,
      // Bundled so the app reads correctly with no connection, and falls
      // back to Ethiopic for Amharic text (PRD 16).
      fontFamily: 'NotoSans',
      fontFamilyFallback: const ['NotoSansEthiopic'],
      appBarTheme: AppBarTheme(
        centerTitle: false,
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        elevation: 0,
        scrolledUnderElevation: 1,
      ),
      cardTheme: CardTheme(
        elevation: 0,
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surface,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          // A comfortable target for a shop counter, not a desktop pointer.
          minimumSize: const Size.fromHeight(48),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      ),
    );
  }

  /// Colour for a stock or credit status chip.
  static Color statusColour(String status, ColorScheme scheme) {
    switch (status) {
      case 'out_of_stock':
      case 'critical':
      case 'overdue':
        return scheme.error;
      case 'warning':
      case 'partially_paid':
        return const Color(0xFF9A6200);
      case 'paid':
      case 'ok':
      case 'completed':
        return const Color(0xFF157F46);
      default:
        return scheme.onSurfaceVariant;
    }
  }
}
