import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../api_client.dart';
import '../design.dart';
import '../models.dart';

part 'conversation_widgets.dart';

class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key, required this.api, required this.id});
  final APIClient api;
  final String id;
  @override
  State<ConversationScreen> createState() => _ConversationState();
}

class _ConversationState extends State<ConversationScreen> {
  HumanRequest? item;
  List<ChatMessage> rawMessages = [];
  List<QuickReply> quickReplies = [];
  final text = TextEditingController(), scroll = ScrollController();
  bool busy = false,
      closing = false,
      draftReady = false,
      nearBottom = true,
      newBelow = false,
      markedRead = false;
  String tab = 'chat',
      error = '',
      sendState = 'idle',
      failedAction = '',
      failedContent = '',
      optimisticChunk = '',
      lastSavedDraft = '';
  Timer? timer, draftTimer;
  String get draftKey => 'draft.${widget.id}';

  @override
  void initState() {
    super.initState();
    text.addListener(scheduleDraft);
    scroll.addListener(onScroll);
    load();
    widget.api.quickReplies().then((value) {
      if (mounted) setState(() => quickReplies = value);
    });
    timer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (!closing && !busy) load(quiet: true);
    });
  }

  @override
  void dispose() {
    closing = true;
    timer?.cancel();
    draftTimer?.cancel();
    text.removeListener(scheduleDraft);
    scroll.removeListener(onScroll);
    text.dispose();
    scroll.dispose();
    super.dispose();
  }

  void onScroll() {
    if (!scroll.hasClients) return;
    final close = scroll.position.maxScrollExtent - scroll.position.pixels < 96;
    if (close != nearBottom || (close && newBelow)) {
      setState(() {
        nearBottom = close;
        if (close) newBelow = false;
      });
    }
  }

  void scrollToLatest({bool animate = true}) {
    if (!scroll.hasClients) return;
    if (animate) {
      scroll.animateTo(
        scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
      );
    } else {
      scroll.jumpTo(scroll.position.maxScrollExtent);
    }
    if (mounted) setState(() => newBelow = false);
  }

  void scheduleDraft() {
    if (!draftReady || closing) return;
    if (sendState == 'failed') {
      setState(() {
        sendState = 'idle';
        failedAction = '';
      });
    }
    draftTimer?.cancel();
    final value = text.text;
    SharedPreferences.getInstance().then(
      (prefs) => prefs.setString(draftKey, value),
    );
    if (value == lastSavedDraft) return;
    draftTimer = Timer(const Duration(milliseconds: 650), () async {
      lastSavedDraft = value;
      try {
        await widget.api.saveDraft(widget.id, value);
      } catch (_) {
        if (lastSavedDraft == value) lastSavedDraft = '\u0000';
      }
    });
  }

  Future<void> load({bool quiet = false}) async {
    if (closing) return;
    try {
      final value = await widget.api.request(widget.id);
      if (!mounted || closing) return;
      final previous = item;
      final firstLoad = previous == null;
      final hasNewFlow =
          previous != null &&
          (previous.streamChunkCount != value.streamChunkCount ||
              previous.messages.length != value.messages.length);
      if (!draftReady && value.status == 'pending') {
        draftReady = true;
        lastSavedDraft = value.draft;
        text.text = value.draft;
        if (value.draft.isEmpty) {
          SharedPreferences.getInstance().then((prefs) {
            if (!mounted || closing || text.text.isNotEmpty) return;
            final local = prefs.getString(draftKey) ?? '';
            if (local.isNotEmpty) text.text = local;
          });
        }
      } else if (draftReady &&
          value.draftDeviceId.isNotEmpty &&
          value.draftDeviceId != widget.api.session.deviceId &&
          value.draftUpdatedAt > (previous?.draftUpdatedAt ?? 0) &&
          text.text == lastSavedDraft) {
        lastSavedDraft = value.draft;
        text.text = value.draft;
      }
      setState(() {
        item = value;
        error = '';
      });
      if (!markedRead) {
        markedRead = true;
        widget.api.markRead(widget.id).catchError((_) => value);
      }
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !closing && scroll.hasClients) {
          if (firstLoad || nearBottom)
            scrollToLatest(animate: !firstLoad);
          else if (hasNewFlow)
            setState(() => newBelow = true);
        }
      });
    } catch (e) {
      if (!quiet && mounted && !closing) setState(() => error = '$e');
    }
  }

  Future<void> sendChunk([String? retryValue]) async {
    final current = item;
    if (busy || current == null) return;
    final value = (retryValue ?? text.text).trim();
    if (value.isEmpty) {
      if (current.streamChunkCount == 0) {
        snack('第一下空白不会结束——模型只是眨了眨眼。');
      } else {
        await finish();
      }
      return;
    }
    setState(() {
      busy = true;
      sendState = 'sending';
      failedAction = '';
      optimisticChunk = value;
    });
    try {
      await widget.api.sendChunk(
        widget.id,
        'mobile-${DateTime.now().microsecondsSinceEpoch}',
        value,
      );
      lastSavedDraft = '';
      text.clear();
      if (mounted)
        setState(() {
          optimisticChunk = '';
          sendState = 'sent';
        });
      await load();
    } catch (_) {
      if (mounted)
        setState(() {
          optimisticChunk = '';
          sendState = 'failed';
          failedAction = 'chunk';
          failedContent = value;
        });
    } finally {
      if (mounted && !closing) setState(() => busy = false);
    }
  }

  Future<void> finish() async {
    if (busy) return;
    setState(() {
      busy = true;
      sendState = 'sending';
      failedAction = '';
    });
    try {
      await widget.api.complete(widget.id);
      closeHandled();
    } catch (_) {
      if (mounted)
        setState(() {
          sendState = 'failed';
          failedAction = 'complete';
        });
    } finally {
      if (mounted && !closing) setState(() => busy = false);
    }
  }

  Future<void> direct() async {
    if (text.text.trim().isEmpty || busy) return;
    setState(() {
      busy = true;
      sendState = 'sending';
      failedAction = '';
    });
    try {
      await widget.api.answer(widget.id, text.text.trim());
      text.clear();
      closeHandled();
    } catch (_) {
      if (mounted)
        setState(() {
          sendState = 'failed';
          failedAction = 'direct';
        });
    } finally {
      if (mounted && !closing) setState(() => busy = false);
    }
  }

  Future<void> retryFailed() async {
    if (failedAction == 'chunk')
      await sendChunk(failedContent);
    else if (failedAction == 'complete')
      await finish();
    else if (failedAction == 'direct')
      await direct();
  }

  Future<void> answerTool() async {
    final current = item;
    if (current == null || current.tools.isEmpty) return;
    final names = current.tools
        .whereType<Map>()
        .map((tool) => tool['function'])
        .whereType<Map>()
        .map((function) => '${function['name'] ?? ''}')
        .where((name) => name.isNotEmpty)
        .toList();
    if (names.isEmpty) return;
    var selected = names.first;
    final arguments = TextEditingController(text: '{}');
    final result = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => Padding(
          padding: EdgeInsets.fromLTRB(
            20,
            4,
            20,
            MediaQuery.viewInsetsOf(context).bottom + 24,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '调用客户端工具',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 7),
              const Text(
                '工具会在 Codex、Claude Code 或 OpenCode 那一端执行。',
                style: TextStyle(color: AppColors.muted),
              ),
              const SizedBox(height: 18),
              DropdownButtonFormField<String>(
                initialValue: selected,
                items: names
                    .map(
                      (name) =>
                          DropdownMenuItem(value: name, child: Text(name)),
                    )
                    .toList(),
                onChanged: (value) =>
                    setSheetState(() => selected = value ?? selected),
                decoration: const InputDecoration(labelText: '工具'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: arguments,
                minLines: 4,
                maxLines: 10,
                decoration: const InputDecoration(
                  labelText: '参数 JSON',
                  hintText: '{"path":"README.md"}',
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () {
                  try {
                    final decoded = jsonDecode(arguments.text);
                    if (decoded is! Map) throw const FormatException();
                    Navigator.pop(context, decoded.cast<String, dynamic>());
                  } catch (_) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('参数需要是合法 JSON 对象')),
                    );
                  }
                },
                child: const Text('返回工具调用'),
              ),
            ],
          ),
        ),
      ),
    );
    arguments.dispose();
    if (result == null || !mounted) return;
    setState(() => busy = true);
    try {
      await widget.api.answerTool(widget.id, selected, result);
      closeHandled();
    } catch (e) {
      snack('$e');
    } finally {
      if (mounted && !closing) setState(() => busy = false);
    }
  }

  Future<void> selectTab(String value) async {
    setState(() => tab = value);
    if (value == 'raw' && rawMessages.isEmpty) {
      try {
        final value = await widget.api.rawMessages(widget.id);
        if (mounted) setState(() => rawMessages = value);
      } catch (e) {
        snack('$e');
      }
    }
  }

  void snack(String value) {
    if (mounted && !closing)
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(value)));
  }

  void closeHandled() {
    if (!mounted || closing) return;
    closing = true;
    timer?.cancel();
    draftTimer?.cancel();
    FocusManager.instance.primaryFocus?.unfocus();
    Navigator.of(context).pop(true);
  }

  void showViewOptions() {
    showCupertinoModalPopup<void>(
      context: context,
      builder: (context) => CupertinoActionSheet(
        title: const Text('查看内容'),
        actions: [
          CupertinoActionSheetAction(
            onPressed: () {
              Navigator.pop(context);
              selectTab('chat');
            },
            child: const Text('聊天'),
          ),
          CupertinoActionSheetAction(
            onPressed: () {
              Navigator.pop(context);
              selectTab('run');
            },
            child: const Text('运行记录'),
          ),
          CupertinoActionSheetAction(
            onPressed: () {
              Navigator.pop(context);
              selectTab('raw');
            },
            child: const Text('原始上下文'),
          ),
        ],
        cancelButton: CupertinoActionSheetAction(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final current = item;
    final visibleAnswer = current == null
        ? ''
        : current.status == 'pending'
        ? current.visibleAnswer + optimisticChunk
        : current.visibleAnswer;
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        titleSpacing: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              current?.preview ?? '加载会话',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
            if (current != null)
              Text(
                '${sourceName(current.source)} · ${relativeTime(current.createdAt)}',
                style: const TextStyle(
                  fontSize: 10,
                  color: AppColors.muted,
                  fontWeight: FontWeight.w400,
                ),
              ),
          ],
        ),
        actions: [
          CupertinoButton(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            onPressed: showViewOptions,
            child: const Icon(CupertinoIcons.ellipsis_circle, size: 23),
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: current == null
          ? Center(
              child: error.isEmpty
                  ? const CircularProgressIndicator(strokeWidth: 2)
                  : Text(error),
            )
          : Column(
              children: [
                if (tab != 'chat')
                  _ViewBanner(
                    tab: tab,
                    onClose: () => setState(() => tab = 'chat'),
                  ),
                Expanded(
                  child: tab == 'run'
                      ? _Run(item: current)
                      : Stack(
                          children: [
                            ListView(
                              controller: scroll,
                              padding: const EdgeInsets.fromLTRB(
                                16,
                                18,
                                16,
                                64,
                              ),
                              children: [
                                ...(tab == 'raw'
                                        ? rawMessages
                                        : current.messages)
                                    .map(
                                      (message) => _Bubble(
                                        message: message,
                                        api: widget.api,
                                      ),
                                    ),
                                if (tab == 'chat' && visibleAnswer.isNotEmpty)
                                  _Bubble(
                                    message: ChatMessage(
                                      'assistant',
                                      visibleAnswer,
                                    ),
                                    api: widget.api,
                                    streamState: current.status == 'pending'
                                        ? sendState == 'idle'
                                              ? 'sent'
                                              : sendState
                                        : '',
                                  ),
                              ],
                            ),
                            if (newBelow)
                              Positioned(
                                right: 16,
                                bottom: 12,
                                child: CupertinoButton(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 13,
                                    vertical: 8,
                                  ),
                                  color: CupertinoColors.systemBackground,
                                  borderRadius: BorderRadius.circular(20),
                                  onPressed: scrollToLatest,
                                  child: const Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(CupertinoIcons.arrow_down, size: 15),
                                      SizedBox(width: 5),
                                      Text(
                                        '新消息',
                                        style: TextStyle(
                                          fontSize: 12,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                          ],
                        ),
                ),
                if (current.status == 'pending' && tab == 'chat')
                  _Composer(
                    current: current,
                    controller: text,
                    busy: busy,
                    sendState: sendState,
                    quickReplies: quickReplies,
                    onSend: sendChunk,
                    onFinish: finish,
                    onDirect: direct,
                    onTool: answerTool,
                    onRetry: retryFailed,
                  ),
              ],
            ),
    );
  }
}
