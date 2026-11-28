import 'package:flutter/material.dart';

/// The colours that say something Material's scheme has no word for — money
/// coming in, money owed, a shelf running out — in the light and the dark.
@immutable
class EstockPalette extends ThemeExtension<EstockPalette> {
  const EstockPalette({
    required this.canvas,
    required this.line,
    required this.muted,
    required this.brandTint,
    required this.brandStrong,
    required this.heroStart,
    required this.heroEnd,
    required this.good,
    required this.warn,
    required this.bad,
    required this.info,
  });

  /// Behind everything; cards sit on it in white.
  final Color canvas;

  /// Hairlines between rows and around fields.
  final Color line;

  /// Secondary text: a category, a date, a hint.
  final Color muted;

  /// The brand's palest shade, behind something selected.
  final Color brandTint;
  final Color brandStrong;

  /// The two ends of the brand gradient on the home and sign-in screens.
  final Color heroStart;
  final Color heroEnd;

  final Color good;
  final Color warn;
  final Color bad;
  final Color info;

  static const light = EstockPalette(
    canvas: Color(0xFFF3F6F5),
    line: Color(0xFFE2E8E7),
    muted: Color(0xFF5B6B69),
    brandTint: Color(0xFFE1F2EE),
    brandStrong: Color(0xFF0B5A54),
    heroStart: Color(0xFF0F766E),
    heroEnd: Color(0xFF0A4A45),
    good: Color(0xFF15803D),
    warn: Color(0xFFB45309),
    bad: Color(0xFFC0262D),
    info: Color(0xFF1D5FD8),
  );

  static const dark = EstockPalette(
    canvas: Color(0xFF0E1514),
    line: Color(0xFF263331),
    muted: Color(0xFF9AABA8),
    brandTint: Color(0xFF123833),
    brandStrong: Color(0xFF5EEAD4),
    heroStart: Color(0xFF0F5F58),
    heroEnd: Color(0xFF0A3B37),
    good: Color(0xFF4ADE80),
    warn: Color(0xFFFBBF24),
    bad: Color(0xFFF87171),
    info: Color(0xFF7AA7FF),
  );

  @override
  EstockPalette copyWith({
    Color? canvas,
    Color? line,
    Color? muted,
    Color? brandTint,
    Color? brandStrong,
    Color? heroStart,
    Color? heroEnd,
    Color? good,
    Color? warn,
    Color? bad,
    Color? info,
  }) =>
      EstockPalette(
        canvas: canvas ?? this.canvas,
        line: line ?? this.line,
        muted: muted ?? this.muted,
        brandTint: brandTint ?? this.brandTint,
        brandStrong: brandStrong ?? this.brandStrong,
        heroStart: heroStart ?? this.heroStart,
        heroEnd: heroEnd ?? this.heroEnd,
        good: good ?? this.good,
        warn: warn ?? this.warn,
        bad: bad ?? this.bad,
        info: info ?? this.info,
      );

  @override
  EstockPalette lerp(EstockPalette? other, double t) {
    if (other == null) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t)!;
    return EstockPalette(
      canvas: mix(canvas, other.canvas),
      line: mix(line, other.line),
      muted: mix(muted, other.muted),
      brandTint: mix(brandTint, other.brandTint),
      brandStrong: mix(brandStrong, other.brandStrong),
      heroStart: mix(heroStart, other.heroStart),
      heroEnd: mix(heroEnd, other.heroEnd),
      good: mix(good, other.good),
      warn: mix(warn, other.warn),
      bad: mix(bad, other.bad),
      info: mix(info, other.info),
    );
  }
}

extension EstockThemeOf on BuildContext {
  /// The app's own colours, for the light or the dark, whichever is on.
  EstockPalette get palette =>
      Theme.of(this).extension<EstockPalette>() ?? EstockPalette.light;
}

/// One place for colour, type and shape, so the app reads as a whole.
///
/// The brand teal is the web's, so the two read as one product. Around it:
/// white cards on a pale canvas, round corners, a type scale with real
/// steps between a figure, a heading and a note, and colour kept for what
/// means something — money owed, a shelf running out.
class EstockTheme {
  EstockTheme._();

  static const seed = Color(0xFF0F766E);

  static const _family = 'NotoSans';

  /// Bundled so the app reads correctly with no connection, and falls back
  /// to Ethiopic for Amharic text (PRD 16).
  static const _fallback = ['NotoSansEthiopic'];

  static ThemeData light() => _base(Brightness.light);
  static ThemeData dark() => _base(Brightness.dark);

  /// Figures that line up: every digit the same width, so a column of
  /// amounts reads down as well as across.
  static const figures = [FontFeature.tabularFigures()];

  static TextStyle _style(
    double size,
    FontWeight weight,
    Color colour, {
    double? height,
    double letterSpacing = 0,
  }) =>
      TextStyle(
        fontFamily: _family,
        fontFamilyFallback: _fallback,
        fontSize: size,
        fontWeight: weight,
        color: colour,
        height: height,
        letterSpacing: letterSpacing,
      );

  static ThemeData _base(Brightness brightness) {
    final light = brightness == Brightness.light;
    final palette = light ? EstockPalette.light : EstockPalette.dark;
    final ink = light ? const Color(0xFF13201E) : const Color(0xFFE4ECEA);
    final card = light ? Colors.white : const Color(0xFF162120);

    final scheme = ColorScheme.fromSeed(
      seedColor: seed,
      brightness: brightness,
      dynamicSchemeVariant: DynamicSchemeVariant.fidelity,
    ).copyWith(
      primary: light ? seed : const Color(0xFF2DD4BF),
      onPrimary: light ? Colors.white : const Color(0xFF00201C),
      surface: card,
      onSurface: ink,
      onSurfaceVariant: palette.muted,
      outline: light ? const Color(0xFFC5D0CE) : const Color(0xFF3A4947),
      outlineVariant: palette.line,
      error: palette.bad,
      surfaceTint: Colors.transparent,
      surfaceContainerLowest: card,
      surfaceContainerLow: light ? const Color(0xFFF8FAF9) : const Color(0xFF131C1B),
      surfaceContainer: light ? const Color(0xFFF1F5F4) : const Color(0xFF1A2524),
      surfaceContainerHigh: light ? const Color(0xFFEBF0EF) : const Color(0xFF1F2B2A),
      surfaceContainerHighest:
          light ? const Color(0xFFE4EBEA) : const Color(0xFF253231),
    );

    final text = TextTheme(
      displaySmall: _style(34, FontWeight.w700, ink, letterSpacing: -0.6),
      headlineMedium: _style(28, FontWeight.w700, ink, letterSpacing: -0.4),
      headlineSmall: _style(24, FontWeight.w700, ink, letterSpacing: -0.3),
      titleLarge: _style(20, FontWeight.w700, ink, letterSpacing: -0.2),
      titleMedium: _style(16, FontWeight.w600, ink),
      titleSmall: _style(14, FontWeight.w600, ink),
      bodyLarge: _style(16, FontWeight.w400, ink, height: 1.4),
      bodyMedium: _style(14.5, FontWeight.w400, ink, height: 1.4),
      bodySmall: _style(12.5, FontWeight.w400, palette.muted, height: 1.35),
      labelLarge: _style(15, FontWeight.w600, ink),
      labelMedium: _style(13, FontWeight.w600, ink),
      labelSmall:
          _style(11.5, FontWeight.w600, palette.muted, letterSpacing: 0.4),
    );

    OutlineInputBorder field(Color colour, [double width = 1]) =>
        OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: colour, width: width),
        );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      extensions: [palette],
      scaffoldBackgroundColor: palette.canvas,
      canvasColor: palette.canvas,
      fontFamily: _family,
      fontFamilyFallback: _fallback,
      textTheme: text,
      dividerTheme: DividerThemeData(color: palette.line, thickness: 1, space: 1),
      appBarTheme: AppBarTheme(
        centerTitle: false,
        backgroundColor: palette.canvas,
        foregroundColor: ink,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        titleTextStyle: text.titleLarge,
        iconTheme: IconThemeData(color: ink),
      ),
      cardTheme: CardTheme(
        color: card,
        surfaceTintColor: Colors.transparent,
        // A soft lift in the light; in the dark, where a shadow cannot be
        // seen, a hairline does the same job.
        elevation: light ? 1 : 0,
        shadowColor: const Color(0x260F2A27),
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: light ? BorderSide.none : BorderSide(color: palette.line),
        ),
      ),
      listTileTheme: ListTileThemeData(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
        minVerticalPadding: 10,
        iconColor: palette.muted,
        titleTextStyle: text.titleSmall?.copyWith(fontSize: 15),
        subtitleTextStyle: text.bodySmall?.copyWith(fontSize: 13),
        leadingAndTrailingTextStyle: text.labelMedium,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: card,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        border: field(palette.line),
        enabledBorder: field(palette.line),
        focusedBorder: field(scheme.primary, 1.8),
        errorBorder: field(palette.bad),
        focusedErrorBorder: field(palette.bad, 1.8),
        disabledBorder: field(palette.line.withValues(alpha: 0.6)),
        prefixIconColor: palette.muted,
        suffixIconColor: palette.muted,
        labelStyle: text.bodyMedium?.copyWith(color: palette.muted),
        floatingLabelStyle: text.labelMedium?.copyWith(color: scheme.primary),
        hintStyle: text.bodyMedium?.copyWith(color: palette.muted),
        helperStyle: text.bodySmall,
        errorStyle: text.bodySmall?.copyWith(color: palette.bad),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          // A comfortable target for a shop counter, not a desktop pointer.
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          textStyle: text.labelLarge,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(64, 48),
          foregroundColor: ink,
          side: BorderSide(color: scheme.outline),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          textStyle: text.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: light ? palette.brandStrong : scheme.primary,
          textStyle: text.labelMedium?.copyWith(fontSize: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: card,
        selectedColor: palette.brandTint,
        disabledColor: scheme.surfaceContainer,
        side: BorderSide(color: palette.line),
        shape: const StadiumBorder(),
        labelStyle: text.labelMedium,
        secondaryLabelStyle: text.labelMedium?.copyWith(color: palette.brandStrong),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        checkmarkColor: palette.brandStrong,
      ),
      dialogTheme: DialogTheme(
        backgroundColor: card,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        titleTextStyle: text.titleLarge,
        contentTextStyle: text.bodyMedium,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: card,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: card,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: light ? const Color(0xFF13201E) : const Color(0xFFE4ECEA),
        contentTextStyle: text.bodyMedium?.copyWith(
          color: light ? Colors.white : const Color(0xFF13201E),
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    );
  }

  /// Colour for a stock, credit or transfer status chip.
  static Color statusColour(String status, ColorScheme scheme) {
    final palette = scheme.brightness == Brightness.light
        ? EstockPalette.light
        : EstockPalette.dark;
    switch (status) {
      case 'out_of_stock':
      case 'critical':
      case 'overdue':
      case 'rejected':
        return scheme.error;
      case 'warning':
      case 'partially_paid':
      // Waiting on somebody: a request on its answer, an allowed one on the
      // branch that asked taking it up.
      case 'requested':
      case 'approved':
        return palette.warn;
      case 'paid':
      case 'ok':
      case 'completed':
      case 'received':
        return palette.good;
      default:
        return scheme.onSurfaceVariant;
    }
  }
}
