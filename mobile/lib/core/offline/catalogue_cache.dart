import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../models/product.dart';

/// Local copy of the catalogue, so a sale can be recorded with no connection.
///
/// The cache is a convenience for the device, never an authority. Quantities
/// shown from it are what the server last reported and are labelled as such;
/// the server decides whether a sale actually fits the stock on hand.
class CatalogueCache {
  CatalogueCache({SharedPreferences? preferences}) : _preferences = preferences;

  static const _productsKey = 'estock.catalogue.products.v1';
  static const _fetchedAtKey = 'estock.catalogue.fetched_at.v1';

  SharedPreferences? _preferences;

  Future<SharedPreferences> get _prefs async =>
      _preferences ??= await SharedPreferences.getInstance();

  Future<void> save(List<Product> products) async {
    final prefs = await _prefs;
    await prefs.setString(
      _productsKey,
      jsonEncode(products.map((product) => product.toJson()).toList()),
    );
    await prefs.setString(_fetchedAtKey, DateTime.now().toIso8601String());
  }

  Future<List<Product>> load() async {
    final prefs = await _prefs;
    final raw = prefs.getString(_productsKey);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = jsonDecode(raw) as List<dynamic>;
      return decoded
          .map((item) => Product.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList();
    } catch (_) {
      return const [];
    }
  }

  /// When the cache was last refreshed, so the interface can say how stale it is.
  Future<DateTime?> fetchedAt() async {
    final prefs = await _prefs;
    final raw = prefs.getString(_fetchedAtKey);
    return raw == null ? null : DateTime.tryParse(raw);
  }

  Future<void> clear() async {
    final prefs = await _prefs;
    await prefs.remove(_productsKey);
    await prefs.remove(_fetchedAtKey);
  }
}
