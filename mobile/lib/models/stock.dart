// Where the stock actually is, who asked for what, and what is left to count.
//
// The phone's own view of the cross-branch picture (PRD 9, 15). It is kept on
// the device beside the catalogue, because "how many have *we* got" is a
// question asked on the shop floor, where the signal is worst.

import 'session.dart';

/// One branch, with everything it holds of the products in the overview.
class StockBranch {
  const StockBranch({
    required this.id,
    required this.name,
    this.isDefault = false,
    this.total = 0,
  });

  final String id;
  final String name;
  final bool isDefault;
  final double total;

  factory StockBranch.fromJson(Map<String, dynamic> json) => StockBranch(
        id: json['branch_id'] as String,
        name: json['name'] as String,
        isDefault: json['is_default'] as bool? ?? false,
        total: double.tryParse('${json['total']}') ?? 0,
      );

  Map<String, dynamic> toJson() => {
        'branch_id': id,
        'name': name,
        'is_default': isDefault,
        'total': total.toString(),
      };
}

/// What one product's stock looks like spread across the branches.
class StockSpread {
  const StockSpread({
    required this.productId,
    required this.quantities,
    required this.total,
    this.minStock,
    this.reorderLevel,
  });

  final String productId;

  /// Branch id to quantity, zeroes included: a branch that holds none of this
  /// is the answer somebody is looking for, not a row to leave out.
  final Map<String, double> quantities;
  final double total;
  final double? minStock;
  final double? reorderLevel;

  double at(String? branchId) =>
      branchId == null ? total : (quantities[branchId] ?? 0);
}

/// The whole picture: the branches, and every product against them.
class StockByBranch {
  const StockByBranch({required this.branches, required this.spreads});

  const StockByBranch.empty() : branches = const [], spreads = const {};

  final List<StockBranch> branches;
  final Map<String, StockSpread> spreads;

  bool get isEmpty => spreads.isEmpty;

  StockSpread? forProduct(String productId) => spreads[productId];

  /// Out of stock, critical, warning or ok at one branch — or across the
  /// business when no branch is named.
  ///
  /// Worked out here rather than read off the server, because the server
  /// judges an item against everything the business holds: nothing is really
  /// short while another branch has plenty to send.  Standing in one shop
  /// with an empty shelf, that is not the question being asked.
  String statusFor(String productId, String? branchId) {
    final spread = spreads[productId];
    if (spread == null) return 'ok';
    final quantity = spread.at(branchId);
    if (quantity <= 0) return 'out_of_stock';
    final min = spread.minStock;
    if (min != null && quantity <= min) return 'critical';
    final reorder = spread.reorderLevel;
    if (reorder != null && quantity <= reorder) return 'warning';
    return 'ok';
  }

  /// Build from ``GET /stock/overview``.  Rows arrive per variant; a product
  /// with several of them is one line on a phone, so they are added up.
  factory StockByBranch.fromJson(Map<String, dynamic> json) {
    final branches = ((json['branches'] as List<dynamic>?) ?? const [])
        .map((item) => StockBranch.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();

    final totals = <String, double>{};
    final byBranch = <String, Map<String, double>>{};
    final minimums = <String, double?>{};
    final reorders = <String, double?>{};

    for (final item in (json['rows'] as List<dynamic>?) ?? const []) {
      final row = Map<String, dynamic>.from(item as Map);
      final productId = row['product_id'] as String;
      final quantities = Map<String, dynamic>.from(
        (row['quantities'] as Map?) ?? const {},
      );
      final into = byBranch.putIfAbsent(productId, () => <String, double>{});
      for (final branch in branches) {
        into[branch.id] = (into[branch.id] ?? 0) +
            (double.tryParse('${quantities[branch.id]}') ?? 0);
      }
      totals[productId] =
          (totals[productId] ?? 0) + (double.tryParse('${row['total']}') ?? 0);
      // Several variants of one product can carry different thresholds; the
      // highest is the one that raises the warning soonest, which is the one
      // worth acting on.
      minimums[productId] =
          _higher(minimums[productId], double.tryParse('${row['min_stock']}'));
      reorders[productId] = _higher(
        reorders[productId],
        double.tryParse('${row['reorder_level']}'),
      );
    }

    return StockByBranch(
      branches: branches,
      spreads: {
        for (final productId in totals.keys)
          productId: StockSpread(
            productId: productId,
            quantities: byBranch[productId] ?? const {},
            total: totals[productId] ?? 0,
            minStock: minimums[productId],
            reorderLevel: reorders[productId],
          ),
      },
    );
  }

  static double? _higher(double? a, double? b) {
    if (a == null) return b;
    if (b == null) return a;
    return a > b ? a : b;
  }

  Map<String, dynamic> toJson() => {
        'branches': branches.map((branch) => branch.toJson()).toList(),
        'rows': [
          for (final spread in spreads.values)
            {
              'product_id': spread.productId,
              'quantities': spread.quantities
                  .map((key, value) => MapEntry(key, value.toString())),
              'total': spread.total.toString(),
              'min_stock': spread.minStock?.toString(),
              'reorder_level': spread.reorderLevel?.toString(),
            }
        ],
      };
}

/// A branch with no stock recorded against it yet.
class BranchToCount {
  const BranchToCount({
    required this.branchId,
    required this.branchName,
    required this.productCount,
  });

  final String branchId;
  final String branchName;
  final int productCount;

  factory BranchToCount.fromJson(Map<String, dynamic> json) => BranchToCount(
        branchId: json['branch_id'] as String,
        branchName: json['branch_name'] as String,
        productCount: (json['product_count'] as num?)?.toInt() ?? 0,
      );
}

/// A branch a transfer or request could involve.  Names only.
class TransferBranch {
  const TransferBranch({
    required this.branchId,
    required this.branchName,
    required this.isMine,
    this.locationId,
  });

  final String branchId;
  final String branchName;
  final bool isMine;
  final String? locationId;

  factory TransferBranch.fromJson(Map<String, dynamic> json) => TransferBranch(
        branchId: json['branch_id'] as String,
        branchName: json['branch_name'] as String,
        isMine: json['is_mine'] as bool? ?? false,
        locationId: json['location_id'] as String?,
      );
}

class TransferLine {
  const TransferLine({required this.name, required this.quantity});

  final String name;
  final double quantity;

  factory TransferLine.fromJson(Map<String, dynamic> json) => TransferLine(
        name: json['name'] as String? ?? 'Product',
        quantity: double.tryParse('${json['quantity_sent']}') ?? 0,
      );
}

/// A transfer or a request — the same record at different stages.
class StockTransfer {
  const StockTransfer({
    required this.id,
    required this.reference,
    required this.status,
    required this.lines,
    this.fromBranchId,
    this.fromBranchName,
    this.toBranchId,
    this.toBranchName,
    this.note,
    this.decisionNote,
    this.requestedByName,
    this.decidedByName,
    this.requestedAt,
    this.decidedAt,
  });

  final String id;
  final String reference;
  final String status;
  final List<TransferLine> lines;
  final String? fromBranchId;
  final String? fromBranchName;
  final String? toBranchId;
  final String? toBranchName;
  final String? note;
  final String? decisionNote;
  final String? requestedByName;
  final String? decidedByName;
  final DateTime? requestedAt;
  final DateTime? decidedAt;

  bool get isRequest => requestedAt != null;
  bool get awaitsDecision => status == 'requested';
  bool get awaitsAcceptance => status == 'approved';

  /// Whether this is the signed-in user's move to make.
  ///
  /// Deciding is for whoever runs the branch being asked; accepting is for
  /// whoever runs the branch that asked.  Anything else is somebody else's
  /// to answer, and a badge that counts it is a badge nobody can clear.
  bool needsAnswerFrom(UserSession user, Set<String> myBranchIds) {
    if (awaitsDecision) {
      return user.can('stock:transfer_approve') &&
          fromBranchId != null &&
          myBranchIds.contains(fromBranchId);
    }
    if (awaitsAcceptance) {
      return user.can('stock:transfer') &&
          toBranchId != null &&
          myBranchIds.contains(toBranchId);
    }
    return false;
  }

  String get route =>
      '${fromBranchName ?? '…'} → ${toBranchName ?? '…'}';

  factory StockTransfer.fromJson(Map<String, dynamic> json) => StockTransfer(
        id: json['id'] as String,
        reference: json['reference'] as String,
        status: json['status'] as String,
        fromBranchId: json['from_branch_id'] as String?,
        fromBranchName: json['from_branch_name'] as String?,
        toBranchId: json['to_branch_id'] as String?,
        toBranchName: json['to_branch_name'] as String?,
        note: json['note'] as String?,
        decisionNote: json['decision_note'] as String?,
        requestedByName: json['requested_by_name'] as String?,
        decidedByName: json['decided_by_name'] as String?,
        requestedAt: DateTime.tryParse('${json['requested_at']}'),
        decidedAt: DateTime.tryParse('${json['decided_at']}'),
        lines: ((json['lines'] as List<dynamic>?) ?? const [])
            .map((item) => TransferLine.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
      );
}
