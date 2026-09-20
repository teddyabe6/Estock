/// A sellable unit. Every product has at least one variant; simple products
/// have exactly one, created for them by the server.
class Variant {
  const Variant({
    required this.id,
    this.name,
    this.sku,
    this.barcode,
    this.sellingPrice,
    this.quantityOnHand,
  });

  final String id;
  final String? name;
  final String? sku;
  final String? barcode;
  final String? sellingPrice;
  final String? quantityOnHand;

  factory Variant.fromJson(Map<String, dynamic> json) => Variant(
        id: json['id'] as String,
        name: json['name'] as String?,
        sku: json['sku'] as String?,
        barcode: json['barcode'] as String?,
        sellingPrice: json['selling_price']?.toString(),
        quantityOnHand: json['quantity_on_hand']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'sku': sku,
        'barcode': barcode,
        'selling_price': sellingPrice,
        'quantity_on_hand': quantityOnHand,
      };
}

class Product {
  const Product({
    required this.id,
    required this.name,
    required this.variants,
    this.sku,
    this.categoryName,
    this.unitOfMeasure = 'pcs',
    this.trackStock = true,
    this.isPublished = false,
    this.quantityOnHand,
    this.stockStatus,
  });

  final String id;
  final String name;
  final String? sku;
  final String? categoryName;
  final String unitOfMeasure;
  final bool trackStock;
  final bool isPublished;
  final String? quantityOnHand;
  final String? stockStatus;
  final List<Variant> variants;

  Variant? get defaultVariant => variants.isEmpty ? null : variants.first;

  factory Product.fromJson(Map<String, dynamic> json) => Product(
        id: json['id'] as String,
        name: json['name'] as String,
        sku: json['sku'] as String?,
        categoryName: json['category_name'] as String?,
        unitOfMeasure: json['unit_of_measure'] as String? ?? 'pcs',
        trackStock: json['track_stock'] as bool? ?? true,
        isPublished: json['is_published'] as bool? ?? false,
        quantityOnHand: json['quantity_on_hand']?.toString(),
        stockStatus: json['stock_status'] as String?,
        variants: ((json['variants'] as List<dynamic>?) ?? const [])
            .map((item) => Variant.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'sku': sku,
        'category_name': categoryName,
        'unit_of_measure': unitOfMeasure,
        'track_stock': trackStock,
        'is_published': isPublished,
        'quantity_on_hand': quantityOnHand,
        'stock_status': stockStatus,
        'variants': variants.map((variant) => variant.toJson()).toList(),
      };
}
