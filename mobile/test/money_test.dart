import 'package:estock_mobile/core/money.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('amounts', () {
    test('formats ETB with two decimals and thousands separators', () {
      expect(Money.format('1234.5'), '1,234.50 ETB');
      expect(Money.format(0), '0.00 ETB');
    });

    test('the API sends decimals as strings, so strings must parse', () {
      expect(Money.parse('36540.00'), 36540.0);
      expect(Money.amount('36540.00'), '36,540.00');
    });

    test('missing values read as an em dash, not zero', () {
      expect(Money.format(null), '—');
      expect(Money.format(''), '—');
      expect(Money.amount('not a number'), '—');
    });

    test('quantities keep three decimals for goods sold by weight', () {
      expect(Money.quantity('10.5'), '10.5');
      expect(Money.quantity('10.500'), '10.5');
      expect(Money.quantity('1234.125'), '1,234.125');
    });
  });

  group('due dates', () {
    test('no due date never reads as late', () {
      expect(Money.dueLabel(null, false, null), 'No due date');
      expect(Money.dueLabel('', false, null), 'No due date');
    });

    test('overdue states how many days', () {
      expect(Money.dueLabel('2026-01-01', true, 1), '1 day overdue');
      expect(Money.dueLabel('2026-01-01', true, 6), '6 days overdue');
    });

    test('due today is not yet overdue', () {
      final today = DateTime.now();
      final iso =
          '${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}';
      expect(Money.dueLabel(iso, false, null), 'Due today');
    });

    test('future dates count forward', () {
      final future = DateTime.now().add(const Duration(days: 21));
      final iso =
          '${future.year}-${future.month.toString().padLeft(2, '0')}-${future.day.toString().padLeft(2, '0')}';
      expect(Money.dueLabel(iso, false, null), 'Due in 21 days');
    });
  });

  test('Amharic text is not mangled by formatting helpers', () {
    // Formatting never touches product names, but guard against a regression
    // that would run them through a numeric formatter.
    expect(Money.format('ቡና'), '—');
  });
}
