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
    this.stockedAt = const {},
    this.minStock,
    this.reorderLevel,
  });

  final String productId;

  /// Branch id to quantity, zeroes included: a branch that holds none of this
  /// is the answer somebody is looking for, not a row to leave out.
  final Map<String, double> quantities;

  /// The branches that have ever had any of it through their door.
  ///
  /// Zero at a branch that stocks it means somebody must go and buy some.
  /// Zero at a branch that has never carried it means nothing at all — the
  /// shop simply does not sell it.  Drawn as the same "0", the second kind
  /// buries the first: four satellite branches that each carry two lines
  /// turn every other product into four empty shelves.
  final Set<String> stockedAt;

  final double total;
  final double? minStock;
  final double? reorderLevel;

  double at(String? branchId) =>
      branchId == null ? total : (quantities[branchId] ?? 0);

  /// Whether this branch sells it at all.
  ///
  /// Everywhere, until the server says otherwise: an older server, or a
  /// copy cached before this was recorded, should not quietly empty the
  /// restocking list.
  bool carriedAt(String branchId) =>
      stockedAt.isEmpty || stockedAt.contains(branchId);
}

/// A branch that needs restocking, and how little is left there.
class ShortBranch {
  const ShortBranch({
    required this.name,
    required this.quantity,
    required this.status,
  });

  final String name;
  final double quantity;
  final String status;

  bool get isEmpty => status == 'out_of_stock';
}

/// The whole picture: the branches, and every product against them.
class StockByBranch {
  const StockByBranch({required this.branches, required this.spreads});

  const StockByBranch.empty() : branches = const [], spreads = const {};

  final List<StockBranch> branches;
  final Map<String, StockSpread> spreads;

  bool get isEmpty => spreads.isEmpty;

  StockSpread? forProduct(String productId) => spreads[productId];

  /// How urgent each status is, worst first.
  static const _rank = {
    'out_of_stock': 0,
    'critical': 1,
    'warning': 2,
    'ok': 3,
  };

  /// Judge one quantity against this product's own levels.
  String _judge(StockSpread spread, double quantity) {
    if (quantity <= 0) return 'out_of_stock';
    final min = spread.minStock;
    if (min != null && quantity <= min) return 'critical';
    final reorder = spread.reorderLevel;
    if (reorder != null && quantity <= reorder) return 'warning';
    return 'ok';
  }

  /// Out of stock, critical, warning or ok at one branch — or, with no
  /// branch named, at the worst branch of them all.
  ///
  /// Worked out here rather than read off the server, because the server
  /// judges an item against everything the business holds.  That is the
  /// wrong question twice over.  Standing in one shop with an empty shelf,
  /// what the other branches have is no comfort.  And looking at the whole
  /// business, a total that clears the reorder level says nothing about the
  /// branch that has run out: five branches holding 91 between them reads
  /// as healthy while the main shop has seven left of a minimum of ten.
  /// Somewhere short is the thing worth knowing either way.
  String statusFor(String productId, String? branchId) {
    final spread = spreads[productId];
    if (spread == null) return 'ok';
    if (branchId != null) return _judge(spread, spread.at(branchId));
    return branches
        .where((branch) => spread.carriedAt(branch.id))
        .map((branch) => _judge(spread, spread.at(branch.id)))
        .fold('ok', (worst, here) =>
            (_rank[here] ?? 3) < (_rank[worst] ?? 3) ? here : worst);
  }

  /// The branches where this product needs restocking, worst first.
  ///
  /// What makes "short somewhere" useful rather than alarming: it is only
  /// worth telling somebody that a product is low if they are also told
  /// which shop to go and look at, and how little is left there.
  List<ShortBranch> shortBranches(String productId) {
    final spread = spreads[productId];
    if (spread == null) return const [];
    final short = branches
        .where((branch) =>
            spread.carriedAt(branch.id) &&
            _judge(spread, spread.at(branch.id)) != 'ok')
        .toList()
      ..sort((a, b) {
        final byUrgency = (_rank[_judge(spread, spread.at(a.id))] ?? 3)
            .compareTo(_rank[_judge(spread, spread.at(b.id))] ?? 3);
        return byUrgency != 0 ? byUrgency : a.name.compareTo(b.name);
      });
    return [
      for (final branch in short)
        ShortBranch(
          name: branch.name,
          quantity: spread.at(branch.id),
          status: _judge(spread, spread.at(branch.id)),
        ),
    ];
  }

  /// Build from ``GET /stock/overview``.  Rows arrive per variant; a product
  /// with several of them is one line on a phone, so they are added up.
  factory StockByBranch.fromJson(Map<String, dynamic> json) {
    final branches = ((json['branches'] as List<dynamic>?) ?? const [])
        .map((item) => StockBranch.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();

    final totals = <String, double>{};
    final byBranch = <String, Map<String, double>>{};
    final carried = <String, Set<String>>{};
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
      carried
          .putIfAbsent(productId, () => <String>{})
          .addAll(((row['stocked_at'] as List<dynamic>?) ?? const [])
              .map((id) => '$id'));
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
            stockedAt: carried[productId] ?? const {},
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
              'stocked_at': spread.stockedAt.toList(),
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

  /// Sent by the other branch and not yet said to have arrived.  The stock
  /// has already left one shelf and is on nobody's until this is answered.
  bool get awaitsReceipt => status == 'dispatched';

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
    if (awaitsAcceptance || awaitsReceipt) {
      return user.can('stock:transfer') &&
          toBranchId != null &&
          myBranchIds.contains(toBranchId);
    }
    return false;
  }

  /// The status as somebody would say it.  "Dispatched" is the ledger's
  /// word; what the branch waiting for it wants to hear is that it is on
  /// its way.
  String get statusLabel => switch (status) {
        'dispatched' => 'on its way',
        'draft' => 'not sent yet',
        _ => status.replaceAll('_', ' '),
      };

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
