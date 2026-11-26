/// Where the app finds its server, from what somebody typed.
///
/// A copy of the app built without a server asks for one at sign-in, and
/// people type an address every way there is: "192.168.1.20:8000",
/// "http://192.168.1.20:8000", "192.168.1.20:8000/api/v1/".  They are all
/// the same server.
library;

final _hostName = RegExp(r'^[A-Za-z0-9.\-]+$');

/// The API's base URL for what was typed, or null when it is not an address.
String? apiBaseFor(String typed) {
  var text = typed.trim();
  if (text.isEmpty) return null;
  if (!text.contains('://')) text = 'http://$text';
  final uri = Uri.tryParse(text);
  if (uri == null ||
      (uri.scheme != 'http' && uri.scheme != 'https') ||
      // A name or an IPv4 address; an IPv6 one keeps its colons.
      !(_hostName.hasMatch(uri.host) || uri.host.contains(':'))) {
    return null;
  }
  var path = uri.path;
  while (path.endsWith('/')) {
    path = path.substring(0, path.length - 1);
  }
  if (!path.endsWith('/api/v1')) path = '$path/api/v1';
  return Uri(
    scheme: uri.scheme,
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    path: path,
  ).toString();
}

/// The server the way a person would say it: no "http://", no "/api/v1".
String serverLabel(String apiBase) {
  var label = apiBase;
  if (label.startsWith('http://')) label = label.substring('http://'.length);
  if (label.endsWith('/api/v1')) {
    label = label.substring(0, label.length - '/api/v1'.length);
  }
  return label;
}
