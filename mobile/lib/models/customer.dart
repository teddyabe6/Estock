/// A customer, as far as the shop floor needs one: someone to put a credit
/// sale against (PRD 12, A2).
class Customer {
  const Customer({
    required this.id,
    required this.name,
    this.phone,
    this.company,
    this.outstandingBalance,
    this.address,
    this.email,
    this.telegramUsername,
    this.notes,
    this.creditLimit,
    this.creditLimitBehaviour,
  });

  final String id;
  final String name;
  final String? phone;
  final String? company;

  /// Where to find them or deliver to — "Bole, near Edna Mall".
  final String? address;
  final String? email;
  final String? telegramUsername;

  /// What the shop wants to remember about them.
  final String? notes;

  /// The most they may owe, and what happens past it.  Only present for
  /// somebody allowed to see credit.
  final String? creditLimit;
  final String? creditLimitBehaviour;

  /// What the server last said they owe. Advisory only — the credit screen
  /// always asks the server, never the cache.
  final String? outstandingBalance;

  String get label => phone == null || phone!.isEmpty ? name : '$name · $phone';

  factory Customer.fromJson(Map<String, dynamic> json) => Customer(
        id: json['id'] as String,
        name: json['name'] as String,
        phone: json['phone'] as String?,
        company: json['company'] as String?,
        outstandingBalance: json['outstanding_balance']?.toString(),
        address: json['address'] as String?,
        email: json['email'] as String?,
        telegramUsername: json['telegram_username'] as String?,
        notes: json['notes'] as String?,
        creditLimit: json['credit_limit']?.toString(),
        creditLimitBehaviour: json['credit_limit_behaviour'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone': phone,
        'company': company,
        'outstanding_balance': outstandingBalance,
        'address': address,
        'email': email,
        'telegram_username': telegramUsername,
        'notes': notes,
        'credit_limit': creditLimit,
        'credit_limit_behaviour': creditLimitBehaviour,
      };
}
