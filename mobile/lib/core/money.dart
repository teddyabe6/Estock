import 'package:intl/intl.dart';

/// Formatting for ETB amounts, quantities and dates (PRD 16).
///
/// The API returns decimals as strings so no precision is lost in transit;
/// these helpers parse and present them.
class Money {
  Money._();

  static final NumberFormat _amount = NumberFormat('#,##0.00');
  static final NumberFormat _quantity = NumberFormat('#,##0.###');
  static final DateFormat _shortDate = DateFormat('d MMM yyyy');
  static final DateFormat _dateTime = DateFormat('d MMM, HH:mm');

  /// "1,234.00 ETB", or an em dash when there is no value.
  static String format(Object? value, {String currency = 'ETB'}) {
    final parsed = parse(value);
    if (parsed == null) return '—';
    return '${_amount.format(parsed)} $currency';
  }

  /// "1,234.00" — for tables where the currency is stated once in the header.
  static String amount(Object? value) {
    final parsed = parse(value);
    return parsed == null ? '—' : _amount.format(parsed);
  }

  static String quantity(Object? value) {
    final parsed = parse(value);
    return parsed == null ? '—' : _quantity.format(parsed);
  }

  static double? parse(Object? value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    final text = value.toString().trim();
    if (text.isEmpty) return null;
    return double.tryParse(text);
  }

  static String date(Object? value) {
    final parsed = _parseDate(value);
    return parsed == null ? '—' : _shortDate.format(parsed);
  }

  static String dateTime(Object? value) {
    final parsed = _parseDate(value);
    return parsed == null ? '—' : _dateTime.format(parsed.toLocal());
  }

  static DateTime? _parseDate(Object? value) {
    if (value == null) return null;
    if (value is DateTime) return value;
    return DateTime.tryParse(value.toString());
  }

  /// Plain-language due-date text.
  ///
  /// A balance with no due date is outstanding but never overdue (PRD 11.3),
  /// so it must not read as late.
  static String dueLabel(String? dueDate, bool isOverdue, int? daysOverdue) {
    if (dueDate == null || dueDate.isEmpty) return 'No due date';
    if (isOverdue) {
      final days = daysOverdue ?? 0;
      return days == 1 ? '1 day overdue' : '$days days overdue';
    }
    final due = DateTime.tryParse(dueDate);
    if (due == null) return 'No due date';
    final today = DateTime.now();
    final days = DateTime(due.year, due.month, due.day)
        .difference(DateTime(today.year, today.month, today.day))
        .inDays;
    if (days == 0) return 'Due today';
    if (days == 1) return 'Due tomorrow';
    return 'Due in $days days';
  }
}
