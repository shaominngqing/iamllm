import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'api_client.dart';
import 'design.dart';
import 'session_store.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  debugPaintSizeEnabled = false;
  debugPaintBaselinesEnabled = false;
  debugPaintTextLayoutBoxes = false;
  debugPaintLayerBordersEnabled = false;
  debugPaintPointersEnabled = false;
  debugRepaintRainbowEnabled = false;
  debugRepaintTextRainbowEnabled = false;
  runApp(const IamllmApp());
}

class IamllmApp extends StatefulWidget {
  const IamllmApp({super.key});
  @override
  State<IamllmApp> createState() => _IamllmAppState();
}

class _IamllmAppState extends State<IamllmApp> {
  final session = SessionStore();
  APIClient? api;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    session.load().then((_) {
      api = APIClient(session);
      if (mounted) setState(() => loading = false);
    });
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'iamllm',
    theme: iamllmTheme(),
    builder: (context, child) => DefaultTextStyle.merge(
      style: const TextStyle(
        decoration: TextDecoration.none,
        decorationColor: Colors.transparent,
        decorationThickness: 0,
      ),
      child: child ?? const SizedBox.shrink(),
    ),
    home: loading
        ? const Scaffold(body: Center(child: CircularProgressIndicator()))
        : session.signedIn
        ? HomeShell(api: api!, onLogout: logout)
        : LoginScreen(api: api!, onDone: () => setState(() {})),
  );

  Future<void> logout() async {
    await session.clear();
    if (mounted) setState(() {});
  }
}
