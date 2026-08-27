import 'dart:ui';
import 'package:flutter/cupertino.dart';
import '../api_client.dart';
import '../design.dart';
import 'api_keys_screen.dart';
import 'automation_screen.dart';
import 'inbox_screen.dart';
import 'service_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.api, required this.onLogout});

  final APIClient api;
  final Future<void> Function() onLogout;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final navigators = List.generate(4, (_) => GlobalKey<NavigatorState>());
  int selected = 0;

  void select(int index) {
    if (selected == index) {
      navigators[index].currentState?.popUntil((route) => route.isFirst);
      return;
    }
    setState(() => selected = index);
  }

  Widget root(int index) => switch (index) {
    0 => InboxScreen(api: widget.api),
    1 => AutomationScreen(api: widget.api),
    2 => APIKeysScreen(api: widget.api),
    _ => ServiceScreen(api: widget.api, onLogout: widget.onLogout),
  };

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    final bottomGap = bottomInset > AppSpacing.xs ? bottomInset : AppSpacing.xs;
    final reserved = keyboardOpen ? 0.0 : bottomGap + 68;

    return DefaultTextStyle(
      style: const TextStyle(
        color: AppColors.ink,
        fontSize: 17,
        decoration: TextDecoration.none,
      ),
      child: CupertinoPageScaffold(
        backgroundColor: AppColors.canvas,
        child: Stack(
          children: [
            Positioned.fill(
              bottom: reserved,
              child: IndexedStack(
                index: selected,
                children: List.generate(
                  4,
                  (index) => Navigator(
                    key: navigators[index],
                    onGenerateRoute: (_) =>
                        CupertinoPageRoute<void>(builder: (_) => root(index)),
                  ),
                ),
              ),
            ),
            AnimatedPositioned(
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOutCubic,
              left: AppSpacing.screen,
              right: AppSpacing.screen,
              bottom: keyboardOpen ? -76 : bottomGap,
              height: 60,
              child: _GlassTabBar(selected: selected, onSelect: select),
            ),
          ],
        ),
      ),
    );
  }
}

class _GlassTabBar extends StatelessWidget {
  const _GlassTabBar({required this.selected, required this.onSelect});

  final int selected;
  final ValueChanged<int> onSelect;

  static const items = [
    (CupertinoIcons.bubble_left, '会话'),
    (CupertinoIcons.bolt, '自动回复'),
    (CupertinoIcons.lock, '密钥'),
    (CupertinoIcons.gear, '设置'),
  ];

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(AppRadius.floating),
      boxShadow: const [
        BoxShadow(
          color: Color(0x18000000),
          blurRadius: 32,
          offset: Offset(0, 12),
        ),
        BoxShadow(
          color: Color(0x10000000),
          blurRadius: 3,
          offset: Offset(0, 1),
        ),
      ],
    ),
    child: ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.floating),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 24, sigmaY: 24),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Color(0xf7ffffff), Color(0xebffffff)],
            ),
            borderRadius: BorderRadius.circular(AppRadius.floating),
            border: Border.all(color: const Color(0x26000000), width: .5),
          ),
          child: Row(
            children: List.generate(
              items.length,
              (index) => Expanded(
                child: _TabItem(
                  icon: items[index].$1,
                  label: items[index].$2,
                  selected: selected == index,
                  onPressed: () => onSelect(index),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class _TabItem extends StatelessWidget {
  const _TabItem({
    required this.icon,
    required this.label,
    required this.selected,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => CupertinoButton(
    padding: const EdgeInsets.symmetric(horizontal: 3),
    minimumSize: Size.zero,
    pressedOpacity: .58,
    onPressed: onPressed,
    child: SizedBox(
      height: 52,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            width: 24,
            height: 24,
            child: Icon(
              icon,
              size: 21,
              color: selected
                  ? CupertinoColors.activeBlue
                  : CupertinoColors.secondaryLabel,
            ),
          ),
          const SizedBox(height: 1),
          Text(
            label,
            maxLines: 1,
            style: TextStyle(
              color: selected
                  ? CupertinoColors.activeBlue
                  : CupertinoColors.secondaryLabel,
              fontSize: 10.5,
              fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
              letterSpacing: -.1,
            ),
          ),
        ],
      ),
    ),
  );
}
