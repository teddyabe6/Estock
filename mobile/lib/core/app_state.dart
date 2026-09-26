import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/customer.dart';
import '../models/product.dart';
import '../models/session.dart';
import 'api_client.dart';
import 'offline/catalogue_cache.dart';
import 'offline/outbox.dart';
import 'offline/sync_service.dart';

/// Application state: who is signed in, the cached catalogue, and the outbox.
///
/// The session is cached on the device so the app opens straight into work
/// after a restart, even with no connection.
class AppState extends ChangeNotifier {
  AppState({required this.api, Outbox? outbox, CatalogueCache? catalogue})
      : outbox = outbox ?? Outbox(),
        catalogue = catalogue ?? CatalogueCache() {
    sync = SyncService(api: api, outbox: this.outbox);
    sync.addListener(notifyListeners);
  }

  static const _tokenKey = 'estock.token.v1';
  static const _sessionKey = 'estock.session.v1';

  final ApiClient api;
  final Outbox outbox;
  final CatalogueCache catalogue;
  late final SyncService sync;

  UserSession? session;
  List<Product> products = const [];
  List<Customer> customers = const [];
  DateTime? catalogueFetchedAt;
  bool loading = true;
  String? error;

  bool get isSignedIn => session != null;

  /// True when the catalogue on screen came from the device, not the server.
  bool get showingCachedCatalogue => !sync.isOnline && products.isNotEmpty;

  Future<void> start() async {
    final prefs = await SharedPreferences.getInstance();
    api.token = prefs.getString(_tokenKey);

    final cachedSession = prefs.getString(_sessionKey);
    if (cachedSession != null && api.token != null) {
      try {
        session = UserSession.fromJson(
          Map<String, dynamic>.from(jsonDecode(cachedSession) as Map),
        );
      } catch (_) {
        session = null;
      }
    }

    products = await catalogue.load();
    customers = await catalogue.loadCustomers();
    catalogueFetchedAt = await catalogue.fetchedAt();
    loading = false;
    notifyListeners();

    await sync.start();
    if (api.token != null) unawaited(refresh());
  }

  Future<void> signIn(String email, String password) async {
    final dynamic response = await api.post(
      '/auth/login',
      body: {'email': email, 'password': password},
      anonymous: true,
    );
    final token = (response as Map<String, dynamic>)['access_token'] as String;
    api.token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);

    await refresh();
    // Work captured before signing in replays now that there is a session.
    unawaited(sync.sync());
  }

  Future<void> signOut() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_sessionKey);
    api.token = null;
    session = null;
    products = const [];
    customers = const [];
    await catalogue.clear();
    // The outbox is deliberately kept: unsynced work is not thrown away
    // because someone signed out.
    notifyListeners();
  }

  /// Refresh the session and catalogue from the server, falling back to the
  /// cached copies when there is no connection.
  Future<void> refresh() async {
    try {
      final dynamic sessionJson = await api.get('/auth/session');
      session = UserSession.fromJson(Map<String, dynamic>.from(sessionJson as Map));
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_sessionKey, jsonEncode(session!.toJson()));

      if (session!.can('product:view')) {
        final dynamic page = await api.get('/products', query: {'limit': '200'});
        final items = (page as Map<String, dynamic>)['items'] as List<dynamic>;
        products = items
            .map((item) => Product.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
        await catalogue.save(products);
        catalogueFetchedAt = DateTime.now();
      }
      if (session!.can('customer:view')) {
        // Names and phones only, so a credit sale can name its customer with
        // no connection. Balances are deliberately not relied on offline.
        final dynamic page = await api.get('/customers', query: {'limit': '200'});
        final items = (page as Map<String, dynamic>)['items'] as List<dynamic>;
        customers = items
            .map((item) => Customer.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList();
        await catalogue.saveCustomers(customers);
      }
      error = null;
    } on ApiException catch (exception) {
      if (exception.isAuthError) {
        await signOut();
        error = 'Your session expired. Please sign in again.';
      } else if (!exception.isNetworkError) {
        error = exception.message;
      }
      // A network failure is not an error to show: the cached data still works.
    } finally {
      notifyListeners();
    }
  }

  /// Search the catalogue held on the device, so it works with no connection.
  List<Product> search(String query) {
    final text = query.trim().toLowerCase();
    if (text.isEmpty) return products;
    return products.where((product) {
      if (product.name.toLowerCase().contains(text)) return true;
      if ((product.sku ?? '').toLowerCase().contains(text)) return true;
      return product.variants.any((variant) =>
          (variant.barcode ?? '').toLowerCase().contains(text) ||
          (variant.sku ?? '').toLowerCase().contains(text));
    }).toList();
  }

  /// Search the customers held on the device.
  List<Customer> searchCustomers(String query) {
    final text = query.trim().toLowerCase();
    if (text.isEmpty) return customers;
    return customers.where((customer) {
      if (customer.name.toLowerCase().contains(text)) return true;
      if ((customer.phone ?? '').contains(text)) return true;
      return (customer.company ?? '').toLowerCase().contains(text);
    }).toList();
  }

  /// Add a customer on the server. Needs a connection: a customer created
  /// only on the device would have no id for the sale to reference.
  Future<Customer> createCustomer({required String name, String? phone}) async {
    final dynamic created = await api.post(
      '/customers',
      body: {
        'name': name.trim(),
        if (phone != null && phone.trim().isNotEmpty) 'phone': phone.trim(),
      },
    );
    final customer = Customer.fromJson(Map<String, dynamic>.from(created as Map));
    customers = [...customers, customer]..sort((a, b) => a.name.compareTo(b.name));
    await catalogue.saveCustomers(customers);
    notifyListeners();
    return customer;
  }

  Product? findByBarcode(String barcode) {
    final code = barcode.trim().toLowerCase();
    for (final product in products) {
      for (final variant in product.variants) {
        if ((variant.barcode ?? '').toLowerCase() == code) return product;
      }
    }
    return null;
  }

  @override
  void dispose() {
    sync.removeListener(notifyListeners);
    sync.dispose();
    super.dispose();
  }
}

/// Makes [AppState] available to the widget tree without another dependency.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
      : super(notifier: state);

  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope is missing from the widget tree');
    return scope!.notifier!;
  }
}
