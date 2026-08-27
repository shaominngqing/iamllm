import 'package:flutter/cupertino.dart';
import '../api_client.dart';
import '../design.dart';
import '../pairing_payload.dart';
import 'scan_pairing_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.api, required this.onDone});

  final APIClient api;
  final VoidCallback onDone;

  @override
  State<LoginScreen> createState() => _LoginState();
}

class _LoginState extends State<LoginScreen> {
  bool busy = false;
  String error = '';

  Future<void> scan() async {
    final payload = await Navigator.push<PairingPayload>(
      context,
      CupertinoPageRoute(builder: (_) => const ScanPairingScreen()),
    );
    if (payload == null || !mounted) return;
    setState(() {
      busy = true;
      error = '';
    });
    try {
      await widget.api.pair(payload.server, payload.code);
      widget.onDone();
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> manual(_ManualMode mode) async {
    final connected = await Navigator.push<bool>(
      context,
      CupertinoPageRoute(
        builder: (_) => _ManualConnectScreen(api: widget.api, mode: mode),
      ),
    );
    if (connected == true) widget.onDone();
  }

  @override
  Widget build(BuildContext context) => CupertinoPageScaffold(
    backgroundColor: CupertinoColors.systemGroupedBackground,
    child: SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.xxl,
          AppSpacing.lg,
          AppSpacing.xxl,
        ),
        children: [
          const _ConnectHero(),
          const SizedBox(height: 36),
          CupertinoButton.filled(
            onPressed: busy ? null : scan,
            minimumSize: const Size.fromHeight(56),
            borderRadius: BorderRadius.circular(AppRadius.group),
            child: busy
                ? const CupertinoActivityIndicator(color: CupertinoColors.white)
                : const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(CupertinoIcons.qrcode_viewfinder, size: 22),
                      SizedBox(width: 9),
                      Text(
                        '扫描二维码连接',
                        style: TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
          ),
          const SizedBox(height: 12),
          const Text(
            '在网页控制台打开「服务与设备 → 连接新设备」',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: CupertinoColors.secondaryLabel,
              fontSize: 12,
              height: 1.45,
            ),
          ),
          if (error.isNotEmpty) ...[
            const SizedBox(height: 18),
            _ErrorBanner(text: error),
          ],
          const SizedBox(height: 34),
          const Padding(
            padding: EdgeInsets.only(left: 14, bottom: 8),
            child: Text(
              '其他登录方式',
              style: TextStyle(
                color: CupertinoColors.secondaryLabel,
                fontSize: 13,
              ),
            ),
          ),
          Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: CupertinoColors.systemBackground,
              borderRadius: BorderRadius.circular(AppRadius.group),
            ),
            child: Column(
              children: [
                _AlternativeTile(
                  icon: CupertinoIcons.number,
                  title: '输入配对码',
                  subtitle: '适合相机不可用时',
                  onTap: () => manual(_ManualMode.pairingCode),
                ),
                const Padding(
                  padding: EdgeInsets.only(left: 58),
                  child: SizedBox(
                    height: .5,
                    child: ColoredBox(color: CupertinoColors.separator),
                  ),
                ),
                _AlternativeTile(
                  icon: CupertinoIcons.person_crop_circle,
                  title: '管理员账号登录',
                  subtitle: '仅作为部署者备用入口',
                  onTap: () => manual(_ManualMode.account),
                ),
              ],
            ),
          ),
          const SizedBox(height: 26),
          const Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                CupertinoIcons.lock_shield,
                size: 14,
                color: CupertinoColors.secondaryLabel,
              ),
              SizedBox(width: 6),
              Text(
                '登录凭据加密保存在这台设备上',
                style: TextStyle(
                  color: CupertinoColors.secondaryLabel,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

class _ConnectHero extends StatelessWidget {
  const _ConnectHero();
  @override
  Widget build(BuildContext context) => Column(
    children: [
      Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(AppRadius.prominent),
          boxShadow: [
            BoxShadow(
              color: const Color(0xff111a16).withValues(alpha: .2),
              blurRadius: 28,
              offset: const Offset(0, 12),
            ),
          ],
        ),
        child: const BrandAvatar(size: 82),
      ),
      const SizedBox(height: 26),
      const Text(
        '连接你的 LLM',
        style: TextStyle(
          color: CupertinoColors.label,
          fontSize: 32,
          fontWeight: FontWeight.w700,
          letterSpacing: -1.1,
        ),
      ),
      const SizedBox(height: 10),
      const Padding(
        padding: EdgeInsets.symmetric(horizontal: 18),
        child: Text(
          '扫描部署实例生成的二维码，服务器地址和一次性凭据会自动完成配置。',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: CupertinoColors.secondaryLabel,
            fontSize: 15,
            height: 1.5,
          ),
        ),
      ),
    ],
  );
}

class _AlternativeTile extends StatelessWidget {
  const _AlternativeTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });
  final IconData icon;
  final String title, subtitle;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => CupertinoButton(
    padding: EdgeInsets.zero,
    onPressed: onTap,
    child: SizedBox(
      height: 68,
      child: Row(
        children: [
          const SizedBox(width: 16),
          Icon(icon, size: 24, color: AppColors.accent),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: CupertinoColors.label,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: const TextStyle(
                    color: CupertinoColors.secondaryLabel,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          const Icon(
            CupertinoIcons.chevron_forward,
            size: 16,
            color: CupertinoColors.tertiaryLabel,
          ),
          const SizedBox(width: 14),
        ],
      ),
    ),
  );
}

enum _ManualMode { pairingCode, account }

class _ManualConnectScreen extends StatefulWidget {
  const _ManualConnectScreen({required this.api, required this.mode});
  final APIClient api;
  final _ManualMode mode;
  @override
  State<_ManualConnectScreen> createState() => _ManualConnectScreenState();
}

class _ManualConnectScreenState extends State<_ManualConnectScreen> {
  late final server = TextEditingController(text: widget.api.session.baseUrl);
  final code = TextEditingController();
  final user = TextEditingController(text: 'admin');
  final password = TextEditingController();
  bool busy = false, obscure = true;
  String error = '';

  @override
  void dispose() {
    server.dispose();
    code.dispose();
    user.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    FocusScope.of(context).unfocus();
    if (server.text.trim().isEmpty) {
      setState(() => error = '请填写服务器地址');
      return;
    }
    setState(() {
      busy = true;
      error = '';
    });
    try {
      if (widget.mode == _ManualMode.pairingCode) {
        await widget.api.pair(server.text.trim(), code.text.trim());
      } else {
        await widget.api.login(
          server.text.trim(),
          user.text.trim(),
          password.text,
        );
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => CupertinoPageScaffold(
    navigationBar: CupertinoNavigationBar(
      middle: Text(widget.mode == _ManualMode.pairingCode ? '输入配对码' : '管理员登录'),
      previousPageTitle: '返回',
    ),
    backgroundColor: CupertinoColors.systemGroupedBackground,
    child: SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 28, 20, 30),
        children: [
          Text(
            widget.mode == _ManualMode.pairingCode
                ? '扫码不可用时，可以手动输入网页显示的信息。'
                : '账号密码登录仅建议部署者本人使用。',
            style: const TextStyle(
              color: CupertinoColors.secondaryLabel,
              fontSize: 14,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 22),
          _FieldLabel('服务器地址'),
          CupertinoTextField(
            controller: server,
            placeholder: 'https://your-domain.com',
            keyboardType: TextInputType.url,
            textInputAction: TextInputAction.next,
            autocorrect: false,
            padding: const EdgeInsets.all(15),
            prefix: const Padding(
              padding: EdgeInsets.only(left: 13),
              child: Icon(
                CupertinoIcons.globe,
                size: 19,
                color: CupertinoColors.secondaryLabel,
              ),
            ),
          ),
          const SizedBox(height: 18),
          if (widget.mode == _ManualMode.pairingCode) ...[
            _FieldLabel('8 位配对码'),
            CupertinoTextField(
              controller: code,
              placeholder: '00000000',
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.done,
              maxLength: 8,
              textAlign: TextAlign.center,
              onSubmitted: (_) => submit(),
              padding: const EdgeInsets.all(15),
              style: const TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w600,
                letterSpacing: 5,
              ),
            ),
          ] else ...[
            _FieldLabel('用户名'),
            CupertinoTextField(
              controller: user,
              autofillHints: const [AutofillHints.username],
              textInputAction: TextInputAction.next,
              padding: const EdgeInsets.all(15),
            ),
            const SizedBox(height: 18),
            _FieldLabel('密码'),
            CupertinoTextField(
              controller: password,
              autofillHints: const [AutofillHints.password],
              obscureText: obscure,
              onSubmitted: (_) => submit(),
              padding: const EdgeInsets.all(15),
              suffix: CupertinoButton(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                onPressed: () => setState(() => obscure = !obscure),
                child: Icon(
                  obscure ? CupertinoIcons.eye : CupertinoIcons.eye_slash,
                  size: 19,
                ),
              ),
            ),
          ],
          if (error.isNotEmpty) ...[
            const SizedBox(height: 16),
            _ErrorBanner(text: error),
          ],
          const SizedBox(height: 24),
          CupertinoButton.filled(
            onPressed: busy ? null : submit,
            minimumSize: const Size.fromHeight(52),
            borderRadius: BorderRadius.circular(AppRadius.control),
            child: busy
                ? const CupertinoActivityIndicator(color: CupertinoColors.white)
                : const Text(
                    '连接',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
          ),
        ],
      ),
    ),
  );
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 12, bottom: 7),
    child: Text(
      text,
      style: const TextStyle(
        color: CupertinoColors.secondaryLabel,
        fontSize: 13,
      ),
    ),
  );
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.text});
  final String text;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(13),
    decoration: BoxDecoration(
      color: CupertinoColors.systemRed.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(AppRadius.control),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(
          CupertinoIcons.exclamationmark_circle,
          color: CupertinoColors.systemRed,
          size: 19,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: CupertinoColors.systemRed,
              fontSize: 13,
              height: 1.4,
            ),
          ),
        ),
      ],
    ),
  );
}
