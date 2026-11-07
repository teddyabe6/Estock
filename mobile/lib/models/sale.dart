// What was sold, what came back, and the receipt to hand over.
//
// A sale is the one thing this app records that a customer also holds a copy
// of, so the phone has to be able to show it again, give it back, and take
// the goods back (PRD 10).

/// One line of a sale, as the receipt prints it.
class SaleLine {
  const SaleLine({
    required this.description,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    this.id,
    this.discount = 0,
  });

  /// Null on a receipt line: the receipt is for reading, not for acting on.
  final String? id;
  final String description;
  final double quantity;
  final double unitPrice;
  final double lineTotal;
  final double discount;

  factory SaleLine.fromJson(Map<String, dynamic> json) => SaleLine(
        id: json['id'] as String?,
        description: json['description'] as String? ?? '',
        quantity: double.tryParse('${json['quantity']}') ?? 0,
        unitPrice: double.tryParse('${json['unit_price']}') ?? 0,
        lineTotal: double.tryParse('${json['line_total']}') ?? 0,
        discount: double.tryParse('${json['discount_amount']}') ?? 0,
      );
}

class SalePayment {
  const SalePayment({
    required this.method,
    required this.amount,
    this.isRefund = false,
  });

  final String method;
  final double amount;

  /// Money going the other way. A refund is a payment on the sale too, and a
  /// receipt that lists it as money taken reads as if the customer paid twice.
  final bool isRefund;

  String get label => method.replaceAll('_', ' ');

  factory SalePayment.fromJson(Map<String, dynamic> json) => SalePayment(
        method: json['method'] as String? ?? '',
        amount: double.tryParse('${json['amount']}') ?? 0,
        isRefund: json['direction'] == 'out',
      );
}

/// Goods that came back off a sale.
class SaleReturn {
  const SaleReturn({
    required this.id,
    required this.number,
    required this.returnedAt,
    required this.reason,
    required this.total,
    required this.refunded,
    required this.credited,
  });

  final String id;
  final String number;
  final DateTime? returnedAt;
  final String reason;
  final double total;

  /// Money handed back, against value taken off what was still owed.
  final double refunded;
  final double credited;

  factory SaleReturn.fromJson(Map<String, dynamic> json) => SaleReturn(
        id: json['id'] as String,
        number: json['number'] as String? ?? '',
        returnedAt: DateTime.tryParse('${json['returned_at']}'),
        reason: json['reason'] as String? ?? '',
        total: double.tryParse('${json['total_amount']}') ?? 0,
        refunded: double.tryParse('${json['refunded_amount']}') ?? 0,
        credited: double.tryParse('${json['credited_amount']}') ?? 0,
      );
}

/// A sale, as the list shows it and as one screen opens it.
class Sale {
  const Sale({
    required this.id,
    required this.number,
    required this.status,
    required this.total,
    required this.amountPaid,
    required this.balanceDue,
    required this.currency,
    this.branchId,
    this.customerId,
    this.soldAt,
    this.subtotal = 0,
    this.discountTotal = 0,
    this.taxTotal = 0,
    this.returnedTotal = 0,
    this.effectiveTotal,
    this.costTotal,
    this.grossProfit,
    this.lines = const [],
    this.payments = const [],
    this.returns = const [],
  });

  final String id;
  final String number;
  final String status;
  final double total;
  final double amountPaid;
  final double balanceDue;
  final String currency;
  final String? branchId;
  final String? customerId;
  final DateTime? soldAt;
  final double subtotal;
  final double discountTotal;
  final double taxTotal;

  /// Value taken back, and what the sale is worth once it has been.
  final double returnedTotal;
  final double? effectiveTotal;

  /// Only present for somebody allowed to see cost (PRD 5.1).
  final double? costTotal;
  final double? grossProfit;

  final List<SaleLine> lines;
  final List<SalePayment> payments;
  final List<SaleReturn> returns;

  bool get isVoided => status == 'voided';
  bool get hasReturns => returns.isNotEmpty;

  factory Sale.fromJson(Map<String, dynamic> json) => Sale(
        id: json['id'] as String,
        number: json['number'] as String? ?? '',
        status: json['status'] as String? ?? 'completed',
        total: double.tryParse('${json['total_amount']}') ?? 0,
        amountPaid: double.tryParse('${json['amount_paid']}') ?? 0,
        balanceDue: double.tryParse('${json['balance_due']}') ?? 0,
        currency: json['currency'] as String? ?? 'ETB',
        branchId: json['branch_id'] as String?,
        customerId: json['customer_id'] as String?,
        soldAt: DateTime.tryParse('${json['sold_at']}'),
        subtotal: double.tryParse('${json['subtotal']}') ?? 0,
        discountTotal: double.tryParse('${json['discount_total']}') ?? 0,
        taxTotal: double.tryParse('${json['tax_total']}') ?? 0,
        returnedTotal: double.tryParse('${json['returned_total']}') ?? 0,
        effectiveTotal: double.tryParse('${json['effective_total']}'),
        costTotal: double.tryParse('${json['cost_total']}'),
        grossProfit: double.tryParse('${json['gross_profit']}'),
        lines: ((json['lines'] as List<dynamic>?) ?? const [])
            .map((item) => SaleLine.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
        payments: ((json['payments'] as List<dynamic>?) ?? const [])
            .map((item) => SalePayment.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
        returns: ((json['returns'] as List<dynamic>?) ?? const [])
            .map((item) => SaleReturn.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
      );
}

/// The receipt: the sale plus who sold it, for the copy the customer keeps.
class Receipt {
  const Receipt({
    required this.businessName,
    required this.lines,
    required this.payments,
    required this.number,
    required this.currency,
    required this.total,
    this.branchName,
    this.address,
    this.phone,
    this.tin,
    this.customerName,
    this.customerPhone,
    this.soldAt,
    this.subtotal = 0,
    this.discountTotal = 0,
    this.taxTotal = 0,
    this.balanceDue = 0,
  });

  final String businessName;
  final String? branchName;
  final String? address;
  final String? phone;
  final String? tin;
  final String? customerName;
  final String? customerPhone;
  final String number;
  final DateTime? soldAt;
  final String currency;
  final double subtotal;
  final double discountTotal;
  final double taxTotal;
  final double total;
  final double balanceDue;
  final List<SaleLine> lines;
  final List<SalePayment> payments;

  factory Receipt.fromJson(Map<String, dynamic> json) {
    final business = Map<String, dynamic>.from((json['business'] as Map?) ?? const {});
    final branch = Map<String, dynamic>.from((json['branch'] as Map?) ?? const {});
    final sale = Map<String, dynamic>.from((json['sale'] as Map?) ?? const {});
    final customer = json['customer'] == null
        ? null
        : Map<String, dynamic>.from(json['customer'] as Map);
    return Receipt(
      businessName: business['name'] as String? ?? '',
      branchName: branch['name'] as String?,
      address: business['address'] as String?,
      phone: business['phone'] as String?,
      tin: business['tin'] as String?,
      customerName: customer?['name'] as String?,
      customerPhone: customer?['phone'] as String?,
      number: sale['number'] as String? ?? '',
      soldAt: DateTime.tryParse('${sale['sold_at']}'),
      currency: sale['currency'] as String? ?? 'ETB',
      subtotal: double.tryParse('${sale['subtotal']}') ?? 0,
      discountTotal: double.tryParse('${sale['discount_total']}') ?? 0,
      taxTotal: double.tryParse('${sale['tax_total']}') ?? 0,
      total: double.tryParse('${sale['total_amount']}') ?? 0,
      balanceDue: double.tryParse('${sale['balance_due']}') ?? 0,
      lines: ((json['lines'] as List<dynamic>?) ?? const [])
          .map((item) => SaleLine.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList(),
      payments: ((json['payments'] as List<dynamic>?) ?? const [])
          .map((item) => SalePayment.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList(),
    );
  }
}

/// One line of a sale with how much of it can still come back.
class ReturnableLine {
  const ReturnableLine({
    required this.saleLineId,
    required this.description,
    required this.sold,
    required this.returned,
    required this.returnable,
    required this.unitPrice,
  });

  final String saleLineId;
  final String description;
  final double sold;
  final double returned;
  final double returnable;
  final double unitPrice;

  factory ReturnableLine.fromJson(Map<String, dynamic> json) => ReturnableLine(
        saleLineId: json['sale_line_id'] as String,
        description: json['description'] as String? ?? '',
        sold: double.tryParse('${json['quantity_sold']}') ?? 0,
        returned: double.tryParse('${json['quantity_returned']}') ?? 0,
        returnable: double.tryParse('${json['quantity_returnable']}') ?? 0,
        unitPrice: double.tryParse('${json['unit_price']}') ?? 0,
      );
}
