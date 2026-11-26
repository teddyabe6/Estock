import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_state.dart';
import '../core/server_address.dart';

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();

  /// Where the server is, in a copy of the app built without one; null in a
  /// build for a shop, which knows its server already.
  TextEditingController? _server;
  final _formKey = GlobalKey<FormState>();
  bool _busy = false;

  /// Whether the password is shown as typed.  Hidden by default, but a
  /// password typed blind on a phone keyboard is a password typed twice.
  bool _showPassword = false;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final state = AppScope.of(context);
    if (state.asksForServer && _server == null) {
      // The address used last time, so the next sign-in is two fields again.
      _server = TextEditingController(
        text: state.server.isEmpty ? '' : serverLabel(state.server),
      );
    }
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _server?.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final state = AppScope.of(context);
    try {
      final server = _server;
      if (server != null) await state.useServer(server.text);
      await state.signIn(_email.text.trim(), _password.text);
    } on ApiException catch (exception) {
      setState(() => _error = exception.isNetworkError && _server != null
          ? _unreachable(serverLabel(state.server))
          : exception.message);
    } catch (_) {
      setState(() => _error = 'Could not sign in. Please try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Said when the server the person typed did not answer — most often a
  /// computer on another Wi-Fi, or an address missing its port.
  static String _unreachable(String label) {
    final port = label.contains(':') ? '' : ' (it usually ends in :8000)';
    return 'Could not reach $label. Check the address$port, that Estock is '
        'running on that computer, and that this phone is on the same Wi-Fi.';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Icon(Icons.storefront,
                        size: 48, color: theme.colorScheme.primary),
                    const SizedBox(height: 16),
                    Text('Estock', style: theme.textTheme.headlineSmall),
                    const SizedBox(height: 4),
                    Text(
                      'Your shop, in your pocket.',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 28),
                    if (_error != null) ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.errorContainer,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _error!,
                          style: TextStyle(color: theme.colorScheme.onErrorContainer),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],
                    if (_server != null) ...[
                      TextFormField(
                        key: const Key('server'),
                        controller: _server,
                        decoration: const InputDecoration(
                          labelText: 'Server',
                          hintText: '192.168.1.20:8000',
                          helperText:
                              'Where Estock runs: the address its computer shows',
                        ),
                        keyboardType: TextInputType.url,
                        autocorrect: false,
                        enableSuggestions: false,
                        textInputAction: TextInputAction.next,
                        validator: (value) => apiBaseFor(value ?? '') == null
                            ? 'Enter the server address, like 192.168.1.20:8000'
                            : null,
                      ),
                      const SizedBox(height: 12),
                    ],
                    TextFormField(
                      key: const Key('email'),
                      controller: _email,
                      decoration: const InputDecoration(labelText: 'Email'),
                      keyboardType: TextInputType.emailAddress,
                      autocorrect: false,
                      validator: (value) =>
                          (value ?? '').contains('@') ? null : 'Enter your email',
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      key: const Key('password'),
                      controller: _password,
                      decoration: InputDecoration(
                        labelText: 'Password',
                        suffixIcon: IconButton(
                          key: const Key('showPassword'),
                          tooltip: _showPassword
                              ? 'Hide the password'
                              : 'Show the password',
                          icon: Icon(_showPassword
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined),
                          onPressed: () =>
                              setState(() => _showPassword = !_showPassword),
                        ),
                      ),
                      obscureText: !_showPassword,
                      autocorrect: false,
                      enableSuggestions: false,
                      onFieldSubmitted: (_) => _submit(),
                      validator: (value) =>
                          (value ?? '').isEmpty ? 'Enter your password' : null,
                    ),
                    const SizedBox(height: 20),
                    FilledButton(
                      key: const Key('signIn'),
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Sign in'),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'Signing in needs a connection. After that you can keep '
                      'working offline.',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
