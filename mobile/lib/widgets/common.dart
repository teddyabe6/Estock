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
  });

  final String label;
  final String value;
  final String? note;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.all(4),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label.toUpperCase(),
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w600,
                color: tone,
              ),
            ),
            if (note != null) ...[
              const SizedBox(height: 2),
              Text(
                note!,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: colour.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label ?? status.replaceAll('_', ' '),
        style: Theme.of(context)
            .textTheme
            .labelSmall
            ?.copyWith(color: colour, fontWeight: FontWeight.w600),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null)
              Icon(icon, size: 40, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(height: 12),
            Text(title, style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
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

/// Section heading inside a scrolling screen.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}
