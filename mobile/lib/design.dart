import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

abstract final class AppColors {
  static const canvas = Color(0xfff2f2f7);
  static const surface = Color(0xffffffff);
  static const ink = Color(0xff000000);
  static const muted = Color(0xff8e8e93);
  static const line = Color(0xffe5e5ea);
  static const soft = Color(0xfff2f2f7);
  static const accent = Color(0xff007aff);
  static const accentSoft = Color(0xffeaf3ff);
  static const warning = Color(0xffff9500);
  static const danger = Color(0xffff3b30);
}

/// Shared iOS layout rhythm. Screen content stays on a 4pt grid, while
/// interactive surfaces use a small set of concentric corner radii.
abstract final class AppSpacing {
  static const xxs = 4.0;
  static const xs = 8.0;
  static const sm = 12.0;
  static const md = 16.0;
  static const lg = 20.0;
  static const xl = 24.0;
  static const xxl = 32.0;
  static const screen = md;
}

abstract final class AppRadius {
  static const control = 12.0;
  static const group = 16.0;
  static const bubble = 18.0;
  static const prominent = 22.0;
  static const floating = 28.0;
}

abstract final class AppMetrics {
  static const minimumTapTarget = 44.0;
}

ThemeData iamllmTheme() {
  const scheme = ColorScheme.light(
    primary: AppColors.ink,
    onPrimary: Colors.white,
    secondary: AppColors.accent,
    onSecondary: Colors.white,
    surface: AppColors.surface,
    onSurface: AppColors.ink,
    error: AppColors.danger,
  );
  return ThemeData(
    useMaterial3: true,
    platform: TargetPlatform.iOS,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.canvas,
    dividerColor: AppColors.line,
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
    cupertinoOverrideTheme: const CupertinoThemeData(
      primaryColor: AppColors.accent,
      scaffoldBackgroundColor: AppColors.canvas,
      barBackgroundColor: Color(0xf7ffffff),
      textTheme: CupertinoTextThemeData(
        primaryColor: AppColors.accent,
        textStyle: TextStyle(fontSize: 17, color: AppColors.ink),
        actionTextStyle: TextStyle(fontSize: 17, color: AppColors.accent),
        tabLabelTextStyle: TextStyle(fontSize: 10, color: AppColors.muted),
        navTitleTextStyle: TextStyle(
          fontSize: 17,
          fontWeight: FontWeight.w600,
          color: AppColors.ink,
        ),
        navLargeTitleTextStyle: TextStyle(
          fontSize: 34,
          fontWeight: FontWeight.w700,
          color: AppColors.ink,
        ),
      ),
    ),
    appBarTheme: const AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: true,
      backgroundColor: AppColors.canvas,
      foregroundColor: AppColors.ink,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: TextStyle(
        color: AppColors.ink,
        fontSize: 17,
        fontWeight: FontWeight.w600,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 68,
      backgroundColor: Colors.white,
      indicatorColor: Colors.transparent,
      elevation: 0,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 11,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w700
              : FontWeight.w500,
          color: states.contains(WidgetState.selected)
              ? AppColors.ink
              : AppColors.muted,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 23,
          color: states.contains(WidgetState.selected)
              ? AppColors.accent
              : AppColors.muted,
        ),
      ),
    ),
    cardTheme: const CardThemeData(
      elevation: 0,
      color: AppColors.surface,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(AppRadius.group)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.soft,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      hintStyle: const TextStyle(color: Color(0xffa0a0a4), fontSize: 14),
      labelStyle: const TextStyle(color: AppColors.muted),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.control),
        borderSide: BorderSide.none,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.control),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.control),
        borderSide: const BorderSide(color: AppColors.accent, width: 1.2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 48),
        backgroundColor: AppColors.accent,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.control),
        ),
        textStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 44),
        foregroundColor: AppColors.accent,
        side: const BorderSide(color: AppColors.line),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.control),
        ),
      ),
    ),
    chipTheme: const ChipThemeData(
      side: BorderSide(color: AppColors.line),
      backgroundColor: AppColors.surface,
      selectedColor: AppColors.accent,
      labelStyle: TextStyle(fontSize: 12, color: AppColors.muted),
      secondaryLabelStyle: TextStyle(fontSize: 12, color: Colors.white),
      shape: StadiumBorder(),
    ),
  );
}

class BrandAvatar extends StatelessWidget {
  const BrandAvatar({super.key, this.size = 36, this.inverted = false});
  final double size;
  final bool inverted;
  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(size),
    painter: _IamllmMarkPainter(inverted: inverted),
  );
}

class _IamllmMarkPainter extends CustomPainter {
  const _IamllmMarkPainter({required this.inverted});

  final bool inverted;

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.width / 512;
    canvas.save();
    canvas.scale(scale);

    final outerColor = inverted
        ? const Color(0xfff7f8f3)
        : const Color(0xff111a16);
    final bubbleColor = inverted
        ? const Color(0xff111a16)
        : const Color(0xfff7f8f3);
    final glyphColor = inverted
        ? const Color(0xfff7f8f3)
        : const Color(0xff111a16);

    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(0, 0, 512, 512),
        const Radius.circular(112),
      ),
      Paint()..color = outerColor,
    );

    final bubble = Path()
      ..moveTo(112, 76)
      ..lineTo(400, 76)
      ..cubicTo(442, 76, 476, 110, 476, 152)
      ..lineTo(476, 328)
      ..cubicTo(476, 370, 442, 404, 400, 404)
      ..lineTo(258, 404)
      ..lineTo(152, 476)
      ..lineTo(152, 404)
      ..lineTo(112, 404)
      ..cubicTo(70, 404, 36, 370, 36, 328)
      ..lineTo(36, 152)
      ..cubicTo(36, 110, 70, 76, 112, 76)
      ..close();
    canvas.drawPath(bubble, Paint()..color = bubbleColor);

    canvas.drawCircle(const Offset(256, 174), 30, Paint()..color = glyphColor);
    canvas.drawLine(
      const Offset(256, 234),
      const Offset(256, 304),
      Paint()
        ..color = glyphColor
        ..strokeWidth = 38
        ..strokeCap = StrokeCap.round,
    );

    final pulse = Path()
      ..moveTo(120, 334)
      ..lineTo(202, 334)
      ..lineTo(229, 293)
      ..lineTo(271, 368)
      ..lineTo(302, 312)
      ..lineTo(330, 334)
      ..lineTo(392, 334);
    canvas.drawPath(
      pulse,
      Paint()
        ..color = const Color(0xffb9e83f)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 20
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _IamllmMarkPainter oldDelegate) =>
      oldDelegate.inverted != inverted;
}

class PageIntro extends StatelessWidget {
  const PageIntro({
    super.key,
    required this.title,
    required this.subtitle,
    this.action,
  });
  final String title, subtitle;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(20, 12, 20, 18),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 34,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -.8,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                subtitle,
                style: const TextStyle(
                  color: AppColors.muted,
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
        ?action,
      ],
    ),
  );
}

class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(20, 22, 20, 10),
    child: Row(
      children: [
        Text(
          text,
          style: const TextStyle(
            fontSize: 13,
            color: AppColors.muted,
            fontWeight: FontWeight.w500,
          ),
        ),
        const Spacer(),
        ?trailing,
      ],
    ),
  );
}

class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.active, this.size = 8});
  final bool active;
  final double size;
  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      color: active ? AppColors.accent : const Color(0xffa9aaad),
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
  });
  final IconData icon;
  final String title, subtitle;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 54,
            height: 54,
            decoration: BoxDecoration(
              color: AppColors.accentSoft,
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: AppColors.accent),
          ),
          const SizedBox(height: 18),
          Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 7),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: AppColors.muted,
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ],
      ),
    ),
  );
}

String relativeTime(int value) {
  if (value == 0) return '暂无记录';
  final ms = value > 100000000000 ? value : value * 1000;
  final diff = DateTime.now().millisecondsSinceEpoch - ms;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return '${diff ~/ 60000} 分钟前';
  if (diff < 86400000) return '${diff ~/ 3600000} 小时前';
  final time = DateTime.fromMillisecondsSinceEpoch(ms).toLocal();
  return '${time.month}月${time.day}日';
}

String sourceName(String value) =>
    {
      'openai_chat': 'OpenAI Chat',
      'openai_responses': 'OpenAI Responses',
      'anthropic_messages': 'Claude',
      'gemini_generate': 'Gemini',
      'web_chat': 'Playground',
      'api': 'API',
    }[value] ??
    value;
