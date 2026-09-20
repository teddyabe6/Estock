import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/app_state.dart';
import 'core/theme.dart';
import 'screens/credit_screen.dart';
import 'screens/pending_screen.dart';
import 'screens/shell_screen.dart';
import 'screens/sign_in_screen.dart';

/// Where the API lives. Set at build time:
///
///   flutter run --dart-define=API_BASE_URL=https://api.example.et/api/v1
const apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://localhost:8000/api/v1',
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState(api: ApiClient(baseUrl: apiBaseUrl));
  await state.start();
  runApp(EstockApp(state: state));
}

class EstockApp extends StatelessWidget {
  const EstockApp({super.key, required this.state});

  final AppState state;

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: MaterialApp(
        title: 'Estock',
        debugShowCheckedModeBanner: false,
        theme: EstockTheme.light(),
        darkTheme: EstockTheme.dark(),
        routes: {
          '/credit': (_) => const CreditScreen(),
          '/pending': (_) => const PendingScreen(),
        },
        home: const _Root(),
      ),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    if (state.loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    // A cached session means the app opens straight into work, even offline.
    return state.isSignedIn ? const ShellScreen() : const SignInScreen();
  }
}
