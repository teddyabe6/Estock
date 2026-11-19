/// Somebody the shop buys from (PRD 12).
class Supplier {
  const Supplier({
    required this.id,
    required this.name,
    this.phone,
    this.email,
    this.telegramUsername,
    this.contactPerson,
    this.address,
    this.tin,
    this.notes,
    this.outstandingBalance,
  });

  final String id;
  final String name;
  final String? phone;
  final String? email;
  final String? telegramUsername;

  /// The person the shop deals with there.
  final String? contactPerson;
  final String? address;

  /// Their tax number, for invoices.
  final String? tin;
  final String? notes;

  /// What the shop owes them, when this user may see it.
  final String? outstandingBalance;

  factory Supplier.fromJson(Map<String, dynamic> json) => Supplier(
        id: json['id'] as String,
        name: json['name'] as String,
        phone: json['phone'] as String?,
        email: json['email'] as String?,
        telegramUsername: json['telegram_username'] as String?,
        contactPerson: json['contact_person'] as String?,
        address: json['address'] as String?,
        tin: json['tin'] as String?,
        notes: json['notes'] as String?,
        outstandingBalance: json['outstanding_balance']?.toString(),
      );
}
