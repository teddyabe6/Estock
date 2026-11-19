/// The part of a phone number that says whose it is, however it was typed:
/// "0911 22 33 44", "+251911223344" and "911223344" are one number.
String phoneKey(String? phone) {
  final digits = (phone ?? '').replaceAll(RegExp(r'\D'), '');
  return digits.length > 9 ? digits.substring(digits.length - 9) : digits;
}
