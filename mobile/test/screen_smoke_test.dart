import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:iamllm_mobile/api_client.dart';
import 'package:iamllm_mobile/design.dart';
import 'package:iamllm_mobile/models.dart';
import 'package:iamllm_mobile/screens/home_shell.dart';
import 'package:iamllm_mobile/screens/login_screen.dart';
import 'package:iamllm_mobile/session_store.dart';

void main() {
  testWidgets('login never inherits text decoration', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: iamllmTheme(),
        builder: (context, child) => DefaultTextStyle.merge(
          style: const TextStyle(
            decoration: TextDecoration.none,
            decorationColor: Colors.transparent,
            decorationThickness: 0,
          ),
          child: child ?? const SizedBox.shrink(),
        ),
        home: LoginScreen(api: _FakeAPI(), onDone: () {}),
      ),
    );

    final style = DefaultTextStyle.of(
      tester.element(find.text('连接你的 LLM')),
    ).style;
    expect(style.decoration, TextDecoration.none);
    expect(style.decorationColor, Colors.transparent);
  });

  testWidgets('mobile console works at a phone viewport', (tester) async {
    tester.view.physicalSize = const Size(430, 932);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        theme: iamllmTheme(),
        home: HomeShell(api: _FakeAPI(), onLogout: () async {}),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('会话'), findsWidgets);
    expect(find.text('在吗'), findsWidgets);
    final inheritedText = DefaultTextStyle.of(
      tester.element(find.text('在吗').first),
    ).style;
    expect(inheritedText.decoration, anyOf(isNull, TextDecoration.none));
    expect(inheritedText.color, isNot(const Color(0xd0ff0000)));

    await tester.tap(find.text('自动回复').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('自动规则'), findsWidgets);
    expect(find.text('在吗就先应一声'), findsOneWidget);

    await tester.tap(find.text('密钥').last);
    await tester.pumpAndSettle();
    expect(find.text('体验用户'), findsOneWidget);
    expect(find.text('sk-ab••••••••cdef'), findsOneWidget);

    await tester.tap(find.text('设置').last);
    await tester.pumpAndSettle();
    expect(find.text('iam-alice'), findsWidgets);
    expect(find.text('这台测试手机'), findsOneWidget);
  });

  testWidgets('stream chunks render as one assistant message', (tester) async {
    tester.view.physicalSize = const Size(430, 932);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeAPI();

    await tester.pumpWidget(
      MaterialApp(
        theme: iamllmTheme(),
        home: HomeShell(api: api, onLogout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('在吗').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.text('在，灵魂在线。'), findsOneWidget);
    expect(find.text('灵魂在线'), findsNothing);
  });

  testWidgets('completing an answer closes without a transient error', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(430, 932);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        theme: iamllmTheme(),
        home: HomeShell(api: _FakeAPI(), onLogout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('在吗').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();

    expect(find.text('等待你的回复 · 1'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class _FakeAPI extends APIClient {
  _FakeAPI() : super(SessionStore());

  HumanRequest get sample => HumanRequest(
    id: 'req_mobile',
    preview: '在吗',
    status: 'pending',
    source: 'openai_chat',
    model: 'iam-alice',
    createdAt: DateTime.now().millisecondsSinceEpoch,
    contextChars: 12,
    toolCount: 0,
    attachmentCount: 0,
    streamChunkCount: 3,
    messages: [ChatMessage('user', '在吗')],
    chunks: [StreamChunk(3, '。'), StreamChunk(1, '在，'), StreamChunk(2, '灵魂在线')],
    clientOnline: true,
  );

  @override
  Stream<AdminEvent> events() => const Stream.empty();

  @override
  Future<List<HumanRequest>> requests({String status = 'pending'}) async =>
      status == 'pending' ? [sample] : [];

  @override
  Future<HumanRequest> request(String id) async => sample;

  @override
  Future<HumanRequest> markRead(String id) async => sample;

  @override
  Future<HumanRequest> saveDraft(String id, String content) async => sample;

  @override
  Future<List<ChatMessage>> rawMessages(String id) async => sample.messages;

  @override
  Future<List<QuickReply>> quickReplies({bool all = false}) async => [
    QuickReply(id: 'quick_1', title: '收到', content: '收到，我先看一下。'),
  ];

  @override
  Future<void> complete(String id) async {}

  @override
  Future<void> answer(String id, String content) async {}

  @override
  Future<List<AutoReplyRule>> autoRules() async => [
    AutoReplyRule(
      id: 'rule_1',
      name: '在吗就先应一声',
      pattern: '在吗',
      responseText: '在的，脑子正在开机。',
    ),
  ];

  @override
  Future<List<APIKeyItem>> apiKeys() async => [
    APIKeyItem(
      id: 'key_1',
      name: '体验用户',
      keyHint: 'sk-ab••••••••cdef',
      active: true,
      isMaster: false,
      rateLimit: 10,
      dailyLimit: 100,
      concurrentLimit: 3,
      usageMinute: 1,
      usageToday: 8,
      pending: 0,
    ),
  ];

  @override
  Future<ServiceOverview> overview() async => ServiceOverview(
    model: 'iam-alice',
    runtime: 'go',
    database: 'sqlite',
    environment: 'local',
    publicBaseUrl: 'http://192.0.2.10:8000',
    pending: 1,
    devices: 1,
    managedKeys: 1,
    timeoutSeconds: 300,
    chunkDelayMs: 10,
    chunkChars: 3,
  );

  @override
  Future<ModelProfile> profile() async => ModelProfile(
    displayName: 'iam-alice',
    bio: '一个真人驱动的多模态模型。',
    skills: const ['看图', '写代码', '偶尔走神'],
  );

  @override
  Future<({String currentDeviceId, List<Device> items})> devices() async => (
    currentDeviceId: 'device_1',
    items: [
      Device(
        id: 'device_1',
        name: '这台测试手机',
        platform: 'android',
        model: '23127PN0CC',
        appVersion: '0.1.0+1',
        lastSeenAt: DateTime.now().millisecondsSinceEpoch,
      ),
    ],
  );
}
