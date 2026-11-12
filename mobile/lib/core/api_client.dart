import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

/// Errors the API returns, in the shape the backend uses.
class ApiException implements Exception {
  ApiException(this.statusCode, this.code, this.message, [this.details]);

  final int statusCode;
  final String code;
  final String message;
  final Object? details;

  /// The caller needs to sign in again.
  bool get isAuthError => statusCode == 401;

  /// The request never reached the server, so it is safe to retry later.
  bool get isNetworkError => statusCode == 0;

  /// The server refused the request on its merits; retrying will not help.
  bool get isPermanent => statusCode >= 400 && statusCode < 500 && !isAuthError;

  @override
  String toString() => message;
}

/// Thin HTTP client for the Estock API.
///
/// It carries the session token and turns failures into [ApiException];
/// every business rule stays on the server.
class ApiClient {
  ApiClient({required this.baseUrl, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _http;

  /// Session token, set after sign-in and cleared on sign-out.
  String? token;

  static const _timeout = Duration(seconds: 20);

  /// A query value may be a string or a list of them; a list becomes one
  /// parameter per entry, which is what the API reads as a list.
  Future<dynamic> get(String path, {Map<String, dynamic>? query, bool anonymous = false}) =>
      _send('GET', path, query: query, anonymous: anonymous);

  Future<dynamic> post(String path, {Object? body, bool anonymous = false}) =>
      _send('POST', path, body: body, anonymous: anonymous);

  Future<dynamic> patch(String path, {Object? body}) => _send('PATCH', path, body: body);

  /// A file the server will only hand to somebody signed in — a payment
  /// slip, say, which is a stranger's banking document and has no public
  /// link on purpose.  Returns its bytes and what kind of thing they are.
  Future<(Uint8List, String)> getBytes(String path) async {
    final headers = <String, String>{};
    if (token != null) headers['Authorization'] = 'Bearer $token';
    late http.Response response;
    try {
      response = await _http
          .get(Uri.parse('$baseUrl$path'), headers: headers)
          .timeout(_timeout);
    } on TimeoutException {
      throw ApiException(0, 'timeout', 'The server took too long to answer.');
    } catch (_) {
      throw ApiException(0, 'network_error', 'No connection.');
    }
    if (response.statusCode >= 400) {
      final dynamic payload = _tryDecode(utf8.decode(response.bodyBytes));
      final map =
          payload is Map<String, dynamic> ? payload : const <String, dynamic>{};
      throw ApiException(
        response.statusCode,
        map['code'] as String? ?? 'error',
        map['message'] as String? ?? 'Request failed (${response.statusCode})',
        map['details'],
      );
    }
    return (
      response.bodyBytes,
      response.headers['content-type'] ?? 'application/octet-stream',
    );
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool anonymous = false,
  }) async {
    final uri = Uri.parse('$baseUrl$path').replace(
      queryParameters: query?.isEmpty ?? true ? null : query,
    );

    final headers = <String, String>{'Accept': 'application/json'};
    if (body != null) headers['Content-Type'] = 'application/json';
    if (!anonymous && token != null) headers['Authorization'] = 'Bearer $token';

    late http.Response response;
    try {
      final request = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) request.body = jsonEncode(body);
      final streamed = await _http.send(request).timeout(_timeout);
      response = await http.Response.fromStream(streamed);
    } on TimeoutException {
      throw ApiException(0, 'timeout', 'The server took too long to answer.');
    } catch (_) {
      // Anything that stops the request reaching the server is a network
      // problem: the operation can be queued and retried (see Outbox).
      throw ApiException(
        0,
        'network_error',
        'No connection. Your work is saved and will sync when you are back online.',
      );
    }

    if (response.statusCode == 204) return null;

    final text = utf8.decode(response.bodyBytes);
    final dynamic payload = text.isEmpty ? null : _tryDecode(text);

    if (response.statusCode >= 400) {
      final map = payload is Map<String, dynamic> ? payload : const <String, dynamic>{};
      throw ApiException(
        response.statusCode,
        map['code'] as String? ?? 'error',
        map['message'] as String? ?? 'Request failed (${response.statusCode})',
        map['details'],
      );
    }
    return payload;
  }

  dynamic _tryDecode(String text) {
    try {
      return jsonDecode(text);
    } catch (_) {
      return null;
    }
  }

  void close() => _http.close();
}
