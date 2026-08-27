import 'dart:async';
import 'package:flutter/cupertino.dart';
import '../api_client.dart';
import '../design.dart';
import '../models.dart';
import 'conversation_screen.dart';

class InboxScreen extends StatefulWidget {
  const InboxScreen({super.key, required this.api});
  final APIClient api;

  @override
  State<InboxScreen> createState() => _InboxState();
}

class _InboxState extends State<InboxScreen> {
  final search = TextEditingController();
  List<HumanRequest> items = [];
  String filter = 'pending', error = '';
  bool loading = true;
  StreamSubscription? events;
  Timer? incomingTimer;
  AdminEvent? incoming;

  @override
  void initState() {
    super.initState();
    load();
    search.addListener(_refreshSearch);
    events = widget.api.events().listen((event) {
      if (event.type == 'request.created' &&
          event.payload['automated'] != true) {
        incomingTimer?.cancel();
        if (mounted) setState(() => incoming = event);
        incomingTimer = Timer(const Duration(seconds: 4), () {
          if (mounted) setState(() => incoming = null);
        });
      }
      if (event.type.startsWith('request.')) load(quiet: true);
    });
  }

  void _refreshSearch() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    events?.cancel();
    incomingTimer?.cancel();
    search.removeListener(_refreshSearch);
    search.dispose();
    super.dispose();
  }

  Future<void> load({bool quiet = false}) async {
    if (!quiet && mounted) setState(() => loading = true);
    try {
      final value = await widget.api.requests(status: filter);
      if (!mounted) return;
      setState(() {
        items = value;
        error = '';
      });
    } catch (e) {
      if (!mounted || quiet) return;
      setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  List<HumanRequest> get visible {
    final term = search.text.trim().toLowerCase();
    if (term.isEmpty) return items;
    return items
        .where(
          (item) =>
              '${item.preview} ${item.visibleAnswer} ${sourceName(item.source)}'
                  .toLowerCase()
                  .contains(term),
        )
        .toList();
  }

  Future<void> open(HumanRequest request) async {
    unawaited(
      widget.api.markRead(request.id).then<void>((_) {}).catchError((_) {}),
    );
    final handled = await Navigator.of(context).push<bool>(
      CupertinoPageRoute(
        builder: (_) => ConversationScreen(api: widget.api, id: request.id),
      ),
    );
    if (!mounted) return;
    if (handled == true && filter == 'pending') {
      setState(() => items.removeWhere((item) => item.id == request.id));
    }
    await load(quiet: true);
  }

  @override
  Widget build(BuildContext context) {
    final shown = visible;
    return CupertinoPageScaffold(
      backgroundColor: CupertinoColors.systemGroupedBackground,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          CupertinoSliverNavigationBar(
            border: null,
            backgroundColor: CupertinoColors.systemGroupedBackground.withValues(
              alpha: .9,
            ),
            largeTitle: const Text('会话'),
            trailing: CupertinoButton(
              padding: EdgeInsets.zero,
              minimumSize: const Size(32, 32),
              onPressed: loading ? null : load,
              child: const Icon(CupertinoIcons.refresh, size: 20),
            ),
          ),
          CupertinoSliverRefreshControl(onRefresh: load),
          if (incoming != null) SliverToBoxAdapter(child: _incomingBanner()),
          SliverToBoxAdapter(child: _controls()),
          if (error.isNotEmpty)
            SliverToBoxAdapter(child: _errorBanner())
          else if (loading && items.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: Center(child: CupertinoActivityIndicator(radius: 12)),
            )
          else if (shown.isEmpty)
            SliverFillRemaining(
              hasScrollBody: false,
              child: EmptyState(
                icon: search.text.isEmpty
                    ? CupertinoIcons.check_mark_circled
                    : CupertinoIcons.search,
                title: search.text.isEmpty ? '暂时没有新消息' : '没有找到会话',
                subtitle: search.text.isEmpty
                    ? '有新的请求时，它会自动出现在这里。'
                    : '换一个关键词试试。',
              ),
            )
          else ...[
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(32, 17, 20, 8),
                child: Text(
                  _sectionTitle(shown.length),
                  style: const TextStyle(
                    color: CupertinoColors.secondaryLabel,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 28),
              sliver: SliverList.builder(
                itemCount: shown.length,
                itemBuilder: (context, index) => _ConversationTile(
                  item: shown[index],
                  first: index == 0,
                  last: index == shown.length - 1,
                  onTap: () => open(shown[index]),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _controls() => Padding(
    padding: const EdgeInsets.fromLTRB(16, 2, 16, 0),
    child: Column(
      children: [
        CupertinoSearchTextField(
          controller: search,
          placeholder: '搜索会话',
          backgroundColor: CupertinoColors.systemBackground,
          borderRadius: BorderRadius.circular(AppRadius.control),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
          style: const TextStyle(color: CupertinoColors.label, fontSize: 17),
          placeholderStyle: const TextStyle(
            color: CupertinoColors.placeholderText,
            fontSize: 17,
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: CupertinoSlidingSegmentedControl<String>(
            groupValue: filter,
            thumbColor: CupertinoColors.systemBackground,
            backgroundColor: CupertinoColors.systemGrey5,
            padding: const EdgeInsets.all(2),
            children: {
              'pending': _segment('待回答', 'pending'),
              'answered': _segment('已回答', 'answered'),
              'expired': _segment('已过期', 'expired'),
            },
            onValueChanged: (value) {
              if (value == null || value == filter) return;
              setState(() {
                filter = value;
                items = [];
              });
              load();
            },
          ),
        ),
      ],
    ),
  );

  Widget _incomingBanner() {
    final event = incoming!;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 10),
      child: CupertinoButton(
        padding: EdgeInsets.zero,
        onPressed: () async {
          incomingTimer?.cancel();
          setState(() => incoming = null);
          try {
            final request = await widget.api.request(event.resourceId);
            if (mounted) await open(request);
          } catch (_) {}
        },
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
          decoration: BoxDecoration(
            color: CupertinoColors.systemBackground,
            borderRadius: BorderRadius.circular(AppRadius.group),
            boxShadow: const [
              BoxShadow(
                color: Color(0x16000000),
                blurRadius: 18,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            children: [
              const BrandAvatar(size: 34),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '新消息',
                      style: TextStyle(
                        color: CupertinoColors.label,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${event.payload['preview'] ?? '有人正在等你的回答'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
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
                size: 14,
                color: CupertinoColors.tertiaryLabel,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _segment(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
        ),
        if (filter == value && items.isNotEmpty) ...[
          const SizedBox(width: 5),
          Container(
            constraints: const BoxConstraints(minWidth: 18),
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(
              color: filter == 'pending'
                  ? CupertinoColors.activeBlue
                  : CupertinoColors.systemGrey4,
              borderRadius: BorderRadius.circular(9),
            ),
            child: Text(
              '${items.length}',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: filter == 'pending'
                    ? CupertinoColors.white
                    : CupertinoColors.label,
                fontSize: 10,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ],
    ),
  );

  Widget _errorBanner() => Container(
    margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
    padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
    decoration: BoxDecoration(
      color: CupertinoColors.systemRed.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(AppRadius.group),
    ),
    child: Row(
      children: [
        const Icon(
          CupertinoIcons.exclamationmark_circle,
          color: CupertinoColors.systemRed,
          size: 18,
        ),
        const SizedBox(width: 9),
        Expanded(child: Text(error, style: const TextStyle(fontSize: 12))),
        CupertinoButton(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          onPressed: load,
          child: const Text('重试', style: TextStyle(fontSize: 13)),
        ),
      ],
    ),
  );

  String _sectionTitle(int count) => switch (filter) {
    'answered' => '已回答 · $count',
    'expired' => '已过期 · $count',
    _ => '等待你的回复 · $count',
  };
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile({
    required this.item,
    required this.first,
    required this.last,
    required this.onTap,
  });

  final HumanRequest item;
  final bool first, last;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final summary = item.status == 'pending' && item.draft.isNotEmpty
        ? '草稿：${item.draft.replaceAll('\n', ' ')}'
        : item.status == 'answered' && item.visibleAnswer.isNotEmpty
        ? item.visibleAnswer.replaceAll('\n', ' ')
        : [
            sourceName(item.source),
            if (item.toolCount > 0) '${item.toolCount} 个工具',
            if (item.attachmentCount > 0) '${item.attachmentCount} 个附件',
          ].join(' · ');
    return Container(
      decoration: BoxDecoration(
        color: CupertinoColors.systemBackground,
        borderRadius: BorderRadius.vertical(
          top: first ? const Radius.circular(AppRadius.group) : Radius.zero,
          bottom: last ? const Radius.circular(AppRadius.group) : Radius.zero,
        ),
      ),
      child: CupertinoButton(
        padding: EdgeInsets.zero,
        onPressed: onTap,
        pressedOpacity: .62,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
              child: Row(
                children: [
                  Stack(
                    clipBehavior: Clip.none,
                    children: [
                      Container(
                        width: 42,
                        height: 42,
                        decoration: BoxDecoration(
                          color: _sourceColor(item.source),
                          shape: BoxShape.circle,
                        ),
                        alignment: Alignment.center,
                        child: Icon(
                          _sourceIcon(item.source),
                          color: CupertinoColors.white,
                          size: 20,
                        ),
                      ),
                      if (item.readAt == 0)
                        Positioned(
                          right: -1,
                          top: -1,
                          child: Container(
                            width: 11,
                            height: 11,
                            decoration: BoxDecoration(
                              color: CupertinoColors.activeBlue,
                              shape: BoxShape.circle,
                              border: Border.all(
                                color: CupertinoColors.systemBackground,
                                width: 2,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                item.preview,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: CupertinoColors.label,
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: -.15,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              relativeTime(item.createdAt),
                              style: const TextStyle(
                                color: CupertinoColors.secondaryLabel,
                                fontSize: 12,
                              ),
                            ),
                            const SizedBox(width: 4),
                            const Icon(
                              CupertinoIcons.chevron_forward,
                              color: CupertinoColors.tertiaryLabel,
                              size: 13,
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          summary,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color:
                                item.status == 'pending' &&
                                    item.draft.isNotEmpty
                                ? CupertinoColors.systemRed
                                : CupertinoColors.secondaryLabel,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (!last)
              const Padding(
                padding: EdgeInsets.only(left: 68),
                child: SizedBox(
                  height: .5,
                  child: ColoredBox(color: CupertinoColors.separator),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

Color _sourceColor(String source) => switch (source) {
  'anthropic_messages' => const Color(0xffd97745),
  'gemini_generate' => const Color(0xff4f7ad9),
  'openai_responses' => const Color(0xff7d5bd4),
  'web_chat' => const Color(0xff34a853),
  _ => const Color(0xff303238),
};

IconData _sourceIcon(String source) => switch (source) {
  'anthropic_messages' => CupertinoIcons.sparkles,
  'gemini_generate' => CupertinoIcons.wand_stars,
  'web_chat' => CupertinoIcons.globe,
  _ => CupertinoIcons.chevron_left_slash_chevron_right,
};
