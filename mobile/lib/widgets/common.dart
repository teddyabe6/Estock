import 'package:flutter/material.dart';

import '../core/theme.dart';

/// A labelled figure, used across the home and credit screens.
class StatTile extends StatelessWidget {
  const StatTile({
    super.key,
    required this.label,
    required this.value,
    this.note,
    this.tone,
    this.icon,
    this.accent,
    this.onTap,
  });

  final String label;
  final String value;
  final String? note;

  /// Colour for the figure itself: red for an overdue amount, say.
  final Color? tone;

  /// A picture of what the figure is, in a badge of [accent] (or [tone]).
  final IconData? icon;
  final Color? accent;

  /// Where the figure leads.  A number somebody cannot open is a number
  /// they have to go and find again by hand.
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.all(5),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                IconBadge(
                  icon!,
                  colour: accent ?? tone ?? theme.colorScheme.primary,
                  size: 34,
                ),
                const SizedBox(height: 12),
              ],
              Text(
                label.toUpperCase(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.labelSmall,
              ),
              const SizedBox(height: 4),
              // Long amounts shrink to fit rather than break onto two lines.
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(
                  value,
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontSize: 21,
                    color: tone,
                    fontFeatures: EstockTheme.figures,
                  ),
                ),
              ),
              if (note != null) ...[
                const SizedBox(height: 2),
                Text(note!, style: theme.textTheme.bodySmall),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.status, this.label});

  final String status;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final colour = EstockTheme.statusColour(status, scheme);
    final dark = scheme.brightness == Brightness.dark;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: colour.withValues(alpha: dark ? 0.2 : 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label ?? status.replaceAll('_', ' '),
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: colour,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.2,
            ),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.title, this.message, this.icon});

  final String title;
  final String? message;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final palette = context.palette;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null)
              Container(
                width: 76,
                height: 76,
                decoration: BoxDecoration(
                  color: palette.brandTint,
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 36, color: palette.brandStrong),
              ),
            const SizedBox(height: 16),
            Text(
              title,
              style: theme.textTheme.titleMedium?.copyWith(
                fontSize: 17,
                fontWeight: FontWeight.w700,
              ),
              textAlign: TextAlign.center,
            ),
            if (message != null) ...[
              const SizedBox(height: 6),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// The two answers to a dialog's question, side by side.
///
/// Material stacks a dialog's actions when they will not fit on one line, and
/// the app's filled buttons ask for the full width, so they never fit: the
/// confirming action ends up a full-width slab with the way out tucked above
/// it. Equal halves is both the shape intended and the better thumb target.
class DialogActions extends StatelessWidget {
  const DialogActions({super.key, required this.back, required this.confirm});

  final Widget back;
  final Widget confirm;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: back),
        const SizedBox(width: 8),
        Expanded(child: confirm),
      ],
    );
  }
}

/// Ask for a line of text before doing something — a reason, a note.
///
/// The dialog owns its own field, and so its own controller: disposing one
/// the moment `showDialog` returns throws, because the dialog is still on
/// screen animating away and rebuilding the field as it goes.
class ReasonDialog extends StatefulWidget {
  const ReasonDialog({
    super.key,
    required this.title,
    required this.confirm,
    this.body,
    this.label,
    this.hint,
    this.minLength = 0,
  });

  final String title;

  /// The word on the button that does the thing.
  final String confirm;

  /// What doing it means, said before the field.
  final String? body;
  final String? label;
  final String? hint;

  /// How much has to be typed before the thing can be done. Zero where the
  /// note is optional, so "no note" and "never mind" stay different answers.
  final int minLength;

  @override
  State<ReasonDialog> createState() => _ReasonDialogState();
}

class _ReasonDialogState extends State<ReasonDialog> {
  final _text = TextEditingController();

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (widget.body != null) ...[
            Text(widget.body!),
            const SizedBox(height: 12),
          ],
          TextField(
            controller: _text,
            autofocus: true,
            decoration: InputDecoration(
              labelText: widget.label,
              hintText: widget.hint,
            ),
            onChanged: (_) => setState(() {}),
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
            onPressed: _text.text.trim().length < widget.minLength
                ? null
                : () => Navigator.of(context).pop(_text.text.trim()),
            child: Text(widget.confirm),
          ),
        ),
      ],
    );
  }
}

/// Show a [ReasonDialog]. Null means they backed out, which is not the same
/// as leaving an optional note empty.
Future<String?> askForReason(
  BuildContext context, {
  required String title,
  required String confirm,
  String? body,
  String? label,
  String? hint,
  int minLength = 0,
}) {
  return showDialog<String>(
    context: context,
    builder: (_) => ReasonDialog(
      title: title,
      confirm: confirm,
      body: body,
      label: label,
      hint: hint,
      minLength: minLength,
    ),
  );
}

/// "1 item", "3 items" — a count with the word that goes with it.
///
/// Never "3 item(s)": that is a form asking the reader to finish the
/// sentence, and it reads as a machine on a screen meant to read as a shop.
String countOf(int number, String one, [String? many]) =>
    '$number ${number == 1 ? one : (many ?? '${one}s')}';

/// Section heading inside a scrolling screen.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 22, trailing == null ? 20 : 8, 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

/// An icon in a rounded square of its own colour: what a row or a figure is
/// about, seen before it is read.
class IconBadge extends StatelessWidget {
  const IconBadge(this.icon, {super.key, this.colour, this.size = 38});

  final IconData icon;
  final Color? colour;
  final double size;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tint = colour ?? scheme.primary;
    final dark = scheme.brightness == Brightness.dark;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: tint.withValues(alpha: dark ? 0.22 : 0.12),
        borderRadius: BorderRadius.circular(size * 0.32),
      ),
      child: Icon(icon, size: size * 0.55, color: tint),
    );
  }
}

/// Somebody's or something's initials in a coloured circle, so a long list
/// of names has faces to find rather than only lines of text to read. The
/// colour comes from the name, so the same customer is always the same
/// colour.
class Monogram extends StatelessWidget {
  const Monogram(this.name, {super.key, this.size = 40});

  final String name;
  final double size;

  static const _colours = [
    Color(0xFF0F766E), // teal
    Color(0xFF4F46E5), // indigo
    Color(0xFFB45309), // amber
    Color(0xFFBE185D), // rose
    Color(0xFF0369A1), // sky
    Color(0xFF7C3AED), // violet
    Color(0xFF15803D), // green
    Color(0xFFC2410C), // orange
  ];

  /// The first letter of the first two words — "Selam Construction PLC" is
  /// SC — and a single letter for one word. Ethiopic names keep their first
  /// character whole.
  static String initials(String name) {
    // Words, not sizes: "Berbere 1kg" is B, not B1.
    final words = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((word) => RegExp(r'^\p{L}', unicode: true).hasMatch(word))
        .toList();
    if (words.isEmpty) {
      final text = name.trim();
      return text.isEmpty ? '?' : String.fromCharCode(text.runes.first);
    }
    String first(String word) => String.fromCharCode(word.runes.first);
    final letters = words.length == 1
        ? first(words.first)
        : first(words[0]) + first(words[1]);
    return letters.toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    final hash = name.codeUnits.fold<int>(0, (a, c) => (a * 31 + c) & 0x7fffffff);
    final colour = _colours[hash % _colours.length];
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colour.withValues(alpha: dark ? 0.28 : 0.13),
        shape: BoxShape.circle,
      ),
      child: Text(
        initials(name),
        style: TextStyle(
          fontSize: size * 0.36,
          fontWeight: FontWeight.w700,
          color: dark ? Color.lerp(colour, Colors.white, 0.45) : colour,
        ),
      ),
    );
  }
}

/// Rows that belong together, on one card, with a hairline between them.
class TileGroup extends StatelessWidget {
  const TileGroup({
    super.key,
    required this.children,
    this.margin,
    this.dividerIndent = 16,
  });

  final List<Widget> children;
  final EdgeInsetsGeometry? margin;

  /// Where the hairline starts: under the text rather than the icon, for
  /// rows that have one.
  final double dividerIndent;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: margin ?? const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            children[i],
            if (i < children.length - 1)
              Divider(height: 1, indent: dividerIndent),
          ],
        ],
      ),
    );
  }
}

/// One row of a long list drawn as rounded white groups on the page: the
/// first of a group rounds its top corners, the last its bottom ones, and a
/// hairline separates the rest. For lists built a row at a time, where a
/// [TileGroup] around them all is not possible.
class GroupedRow extends StatelessWidget {
  const GroupedRow({
    super.key,
    required this.child,
    this.first = false,
    this.last = false,
    this.dividerIndent = 16,
  });

  final Widget child;
  final bool first;
  final bool last;
  final double dividerIndent;

  @override
  Widget build(BuildContext context) {
    const radius = Radius.circular(18);
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, first ? 4 : 0, 16, last ? 10 : 0),
      child: Material(
        color: theme.cardTheme.color ?? theme.colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(
            top: first ? radius : Radius.zero,
            bottom: last ? radius : Radius.zero,
          ),
          side: dark
              ? BorderSide(color: context.palette.line)
              : BorderSide.none,
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            child,
            if (!last) Divider(height: 1, indent: dividerIndent),
          ],
        ),
      ),
    );
  }
}

