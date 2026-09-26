/// A customer, as far as the shop floor needs one: someone to put a credit
/// sale against (PRD 12, A2).
class Customer {
  const Customer({
    required this.id,
    required this.name,
    this.phone,
    this.company,
    this.outstandingBalance,
  });

  final String id;
  final String name;
  final String? phone;
  final String? company;

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
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone': phone,
        'company': company,
        'outstanding_balance': outstandingBalance,
      };
}
