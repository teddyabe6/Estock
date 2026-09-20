class Branch {
  const Branch({required this.id, required this.name, this.isDefault = false});

  final String id;
  final String name;
  final bool isDefault;

  factory Branch.fromJson(Map<String, dynamic> json) => Branch(
        id: json['id'] as String,
        name: json['name'] as String,
        isDefault: json['is_default'] as bool? ?? false,
      );

  Map<String, dynamic> toJson() =>
      {'id': id, 'name': name, 'is_default': isDefault};
}

/// Who is signed in, for which business, and what they are allowed to see.
///
/// The permission list mirrors what the server enforces; it decides what to
/// show, never what is allowed.
class UserSession {
  const UserSession({
    required this.userId,
    required this.fullName,
    required this.email,
    required this.tenantId,
    required this.tenantName,
    required this.currency,
    required this.role,
    required this.permissions,
    required this.branches,
    this.readOnly = false,
    this.subscriptionMessage,
  });

  final String userId;
  final String fullName;
  final String email;
  final String tenantId;
  final String tenantName;
  final String currency;
  final String role;
  final List<String> permissions;
  final List<Branch> branches;
  final bool readOnly;
  final String? subscriptionMessage;

  bool can(String permission) => permissions.contains(permission);

  factory UserSession.fromJson(Map<String, dynamic> json) {
    final user = Map<String, dynamic>.from(json['user'] as Map);
    final subscription =
        Map<String, dynamic>.from((json['subscription'] as Map?) ?? const {});
    return UserSession(
      userId: user['id'] as String,
      fullName: user['full_name'] as String,
      email: user['email'] as String,
      tenantId: json['tenant_id'] as String,
      tenantName: json['tenant_name'] as String,
      currency: json['currency'] as String? ?? 'ETB',
      role: json['role'] as String? ?? '',
      permissions: ((json['permissions'] as List<dynamic>?) ?? const [])
          .map((item) => item.toString())
          .toList(),
      branches: ((json['branches'] as List<dynamic>?) ?? const [])
          .map((item) => Branch.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList(),
      readOnly: subscription['read_only'] as bool? ?? false,
      subscriptionMessage: subscription['message'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'user': {'id': userId, 'full_name': fullName, 'email': email},
        'tenant_id': tenantId,
        'tenant_name': tenantName,
        'currency': currency,
        'role': role,
        'permissions': permissions,
        'branches': branches.map((branch) => branch.toJson()).toList(),
        'subscription': {
          'read_only': readOnly,
          'message': subscriptionMessage,
        },
      };
}
