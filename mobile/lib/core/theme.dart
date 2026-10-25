import 'package:flutter/material.dart';

/// One place for colour and shape, so the app reads as a whole.
class EstockTheme {
  EstockTheme._();

  static const seed = Color(0xFF0F766E);

  /// The web's --brand-strong and --text-muted, in both schemes. The bottom
  /// bar marks where you are with colour alone, so these are what says it.
  static const _selectedLight = Color(0xFF0B5A54);
  static const _selectedDark = Color(0xFF5EEAD4);
  static const _restingLight = Color(0xFF5B6876);
  static const _restingDark = Color(0xFF9DABB8);

  static ThemeData light() => _base(Brightness.light);
  static ThemeData dark() => _base(Brightness.dark);

  static ThemeData _base(Brightness brightness) {
    final scheme =
        ColorScheme.fromSeed(seedColor: seed, brightness: brightness);
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
      navigationBarTheme: _bottomBar(brightness, scheme),
    );
  }

  /// The bottom bar, drawn the way the web draws its own on a phone: no pill
  /// behind the selected tab, the same outline icon whichever tab you are on,
  /// and colour as the only thing that says which one that is.
  ///
  /// Material would put a filled icon inside a tinted pill. That reads well on
  /// its own, but next to the web bar it is plainly a different thing, and a
  /// shop owner moving between the two should not have to notice.
  static NavigationBarThemeData _bottomBar(
    Brightness brightness,
    ColorScheme scheme,
  ) {
    final light = brightness == Brightness.light;
    final selected = light ? _selectedLight : _selectedDark;
    final resting = light ? _restingLight : _restingDark;
    return NavigationBarThemeData(
      backgroundColor: light ? const Color(0xFFFFFFFF) : scheme.surface,
      // Flat, like the web's bar, which is a rule and a shadow rather than a
      // raised surface with a tint over it.
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      indicatorColor: Colors.transparent,
      // Shorter than Material's 80, closer to the web's 57, and still a
      // larger target than the 48 the web settles for.
      height: 64,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 22,
          color: states.contains(WidgetState.selected) ? selected : resting,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: states.contains(WidgetState.selected) ? selected : resting,
        ),
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
