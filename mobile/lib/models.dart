import 'dart:convert';

int _int(dynamic value) => (value as num?)?.toInt() ?? 0;

class HumanRequest {
  HumanRequest({
    required this.id,
    required this.preview,
    required this.status,
    required this.source,
    required this.model,
    required this.createdAt,
    required this.contextChars,
    required this.toolCount,
    required this.attachmentCount,
    required this.streamChunkCount,
    this.answer = '',
    this.messages = const [],
    this.rawMessages = const [],
    this.tools = const [],
    this.chunks = const [],
    this.clientOnline = false,
    this.readAt = 0,
    this.draft = '',
    this.draftUpdatedAt = 0,
    this.draftDeviceId = '',
  });

  final String id, preview, status, source, model, answer, draft, draftDeviceId;
  final int createdAt,
      contextChars,
      toolCount,
      attachmentCount,
      streamChunkCount,
      readAt,
      draftUpdatedAt;
  final List<ChatMessage> messages, rawMessages;
  final List<dynamic> tools;
  final List<StreamChunk> chunks;
  final bool clientOnline;

  String get streamedAnswer {
    final ordered = [...chunks]
      ..sort((a, b) => a.position.compareTo(b.position));
    return ordered.map((chunk) => chunk.content).join();
  }

  String get visibleAnswer => answer.isNotEmpty ? answer : streamedAnswer;

  factory HumanRequest.fromJson(Map<String, dynamic> json) => HumanRequest(
    id: '${json['id']}',
    preview: '${json['preview'] ?? '新请求'}',
    status: '${json['status']}',
    source: '${json['source'] ?? 'api'}',
    model: '${json['model'] ?? ''}',
    answer: '${json['answer'] ?? ''}',
    createdAt: _int(json['created_at']),
    contextChars: _int(json['context_chars']),
    toolCount: _int(json['tool_count']),
    attachmentCount: _int(json['attachment_count']),
    streamChunkCount: _int(json['stream_chunk_count']),
    messages: (json['messages'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList(),
    rawMessages: (json['raw_messages'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList(),
    tools: json['tools'] as List? ?? [],
    chunks: (json['stream_chunks'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(StreamChunk.fromJson)
        .toList(),
    clientOnline: json['client_online'] == true,
    readAt: _int(json['read_at']),
    draft: '${json['draft'] ?? ''}',
    draftUpdatedAt: _int(json['draft_updated_at']),
    draftDeviceId: '${json['draft_device_id'] ?? ''}',
  );
}

class ChatMessage {
  ChatMessage(this.role, this.content);
  final String role;
  final dynamic content;
  factory ChatMessage.fromJson(Map<String, dynamic> json) =>
      ChatMessage('${json['role']}', json['content']);
}

class StreamChunk {
  StreamChunk(this.position, this.content);
  final int position;
  final String content;
  factory StreamChunk.fromJson(Map<String, dynamic> json) =>
      StreamChunk(_int(json['position']), '${json['content'] ?? ''}');
}

class QuickReply {
  QuickReply({
    this.id = '',
    required this.title,
    required this.content,
    this.category = '常用',
    this.active = true,
  });
  final String id, title, content, category;
  final bool active;
  factory QuickReply.fromJson(Map<String, dynamic> json) => QuickReply(
    id: '${json['id'] ?? ''}',
    title: '${json['title'] ?? ''}',
    content: '${json['content'] ?? ''}',
    category: '${json['category'] ?? '常用'}',
    active: json['active'] != false,
  );
  Map<String, dynamic> toJson() => {
    'title': title,
    'content': content,
    'category': category,
    'active': active,
  };
}

class AutoReplyRule {
  AutoReplyRule({
    this.id = '',
    required this.name,
    this.ruleType = 'keyword',
    this.matchType = 'contains',
    this.pattern = '',
    required this.responseText,
    this.startTime = '',
    this.endTime = '',
    this.days = const [0, 1, 2, 3, 4, 5, 6],
    this.delaySeconds = 0,
    this.priority = 0,
    this.active = true,
  });
  final String id,
      name,
      ruleType,
      matchType,
      pattern,
      responseText,
      startTime,
      endTime;
  final List<int> days;
  final int delaySeconds, priority;
  final bool active;
  factory AutoReplyRule.fromJson(Map<String, dynamic> json) => AutoReplyRule(
    id: '${json['id'] ?? ''}',
    name: '${json['name'] ?? ''}',
    ruleType: '${json['rule_type'] ?? 'keyword'}',
    matchType: '${json['match_type'] ?? 'contains'}',
    pattern: '${json['pattern'] ?? ''}',
    responseText: '${json['response_text'] ?? ''}',
    startTime: '${json['start_time'] ?? ''}',
    endTime: '${json['end_time'] ?? ''}',
    days: (json['days'] as List? ?? const [0, 1, 2, 3, 4, 5, 6])
        .map(_int)
        .toList(),
    delaySeconds: _int(json['delay_seconds']),
    priority: _int(json['priority']),
    active: json['active'] != false,
  );
  AutoReplyRule copyWith({bool? active}) => AutoReplyRule(
    id: id,
    name: name,
    ruleType: ruleType,
    matchType: matchType,
    pattern: pattern,
    responseText: responseText,
    startTime: startTime,
    endTime: endTime,
    days: days,
    delaySeconds: delaySeconds,
    priority: priority,
    active: active ?? this.active,
  );
  Map<String, dynamic> toJson() => {
    'name': name,
    'rule_type': ruleType,
    'match_type': matchType,
    'pattern': pattern,
    'response_text': responseText,
    'start_time': startTime,
    'end_time': endTime,
    'days': days,
    'delay_seconds': delaySeconds,
    'priority': priority,
    'active': active,
  };
}

class APIKeyItem {
  APIKeyItem({
    required this.id,
    required this.name,
    required this.keyHint,
    required this.active,
    required this.isMaster,
    required this.rateLimit,
    required this.dailyLimit,
    required this.concurrentLimit,
    required this.usageMinute,
    required this.usageToday,
    required this.pending,
  });
  final String id, name, keyHint;
  final bool active, isMaster;
  final int rateLimit,
      dailyLimit,
      concurrentLimit,
      usageMinute,
      usageToday,
      pending;
  factory APIKeyItem.fromJson(Map<String, dynamic> json) => APIKeyItem(
    id: '${json['id']}',
    name: '${json['name'] ?? ''}',
    keyHint: '${json['key_hint'] ?? ''}',
    active: json['active'] == true,
    isMaster: json['is_master'] == true,
    rateLimit: _int(json['rate_limit_per_minute']),
    dailyLimit: _int(json['daily_limit']),
    concurrentLimit: _int(json['max_concurrent']),
    usageMinute: _int(json['usage_minute']),
    usageToday: _int(json['usage_today']),
    pending: _int(json['pending_requests']),
  );
}

class CreatedAPIKey {
  CreatedAPIKey({
    required this.key,
    required this.baseUrl,
    required this.model,
  });
  final String key, baseUrl, model;
  factory CreatedAPIKey.fromJson(Map<String, dynamic> json) => CreatedAPIKey(
    key: '${json['key']}',
    baseUrl: '${json['base_url']}',
    model: '${json['model']}',
  );
}

class ServiceOverview {
  ServiceOverview({
    required this.model,
    required this.runtime,
    required this.database,
    required this.environment,
    required this.publicBaseUrl,
    required this.pending,
    required this.devices,
    required this.managedKeys,
    required this.timeoutSeconds,
    required this.chunkDelayMs,
    required this.chunkChars,
  });
  final String model, runtime, database, environment, publicBaseUrl;
  final int pending,
      devices,
      managedKeys,
      timeoutSeconds,
      chunkDelayMs,
      chunkChars;
  factory ServiceOverview.fromJson(Map<String, dynamic> json) =>
      ServiceOverview(
        model: '${json['model'] ?? ''}',
        runtime: '${json['runtime'] ?? ''}',
        database: '${json['database'] ?? ''}',
        environment: '${json['environment'] ?? ''}',
        publicBaseUrl: '${json['public_base_url'] ?? ''}',
        pending: _int(json['pending']),
        devices: _int(json['devices']),
        managedKeys: _int(json['managed_keys']),
        timeoutSeconds: _int(json['response_timeout_seconds']),
        chunkDelayMs: _int(json['stream_chunk_delay_ms']),
        chunkChars: _int(json['stream_chunk_chars']),
      );
}

class ModelProfile {
  ModelProfile({
    required this.displayName,
    required this.bio,
    required this.skills,
  });
  final String displayName, bio;
  final List<String> skills;
  factory ModelProfile.fromJson(Map<String, dynamic> json) => ModelProfile(
    displayName: '${json['display_name'] ?? ''}',
    bio: '${json['bio'] ?? ''}',
    skills: (json['skills'] as List? ?? []).map((item) => '$item').toList(),
  );
  Map<String, dynamic> toJson() => {
    'display_name': displayName,
    'bio': bio,
    'skills': skills,
  };
}

class Device {
  Device({
    required this.id,
    required this.name,
    required this.platform,
    this.model = '',
    this.osVersion = '',
    this.appVersion = '',
    this.ipAddress = '',
    this.locale = '',
    this.timezone = '',
    this.createdAt = 0,
    this.lastSeenAt = 0,
    this.revokedAt = 0,
  });
  final String id,
      name,
      platform,
      model,
      osVersion,
      appVersion,
      ipAddress,
      locale,
      timezone;
  final int createdAt, lastSeenAt, revokedAt;
  bool get active => revokedAt == 0;
  factory Device.fromJson(Map<String, dynamic> json) => Device(
    id: '${json['id']}',
    name: '${json['name']}',
    platform: '${json['platform']}',
    model: '${json['device_model'] ?? ''}',
    osVersion: '${json['os_version'] ?? ''}',
    appVersion: '${json['app_version'] ?? ''}',
    ipAddress: '${json['ip_address'] ?? ''}',
    locale: '${json['locale'] ?? ''}',
    timezone: '${json['timezone'] ?? ''}',
    createdAt: _int(json['created_at']),
    lastSeenAt: _int(json['last_seen_at']),
    revokedAt: _int(json['revoked_at']),
  );
}

class TokenPair {
  TokenPair(this.access, this.refresh, this.device);
  final String access, refresh;
  final Device device;
  factory TokenPair.fromJson(Map<String, dynamic> json) => TokenPair(
    '${json['access_token']}',
    '${json['refresh_token']}',
    Device.fromJson(json['device'] as Map<String, dynamic>),
  );
}

class AdminEvent {
  AdminEvent(this.id, this.type, this.resourceId, this.payload);
  final int id;
  final String type, resourceId;
  final Map<String, dynamic> payload;
  factory AdminEvent.fromBlock(String block) {
    final lines = const LineSplitter().convert(block);
    var id = 0, type = '', data = '{}';
    for (final line in lines) {
      if (line.startsWith('id:'))
        id = int.tryParse(line.substring(3).trim()) ?? 0;
      if (line.startsWith('event:')) type = line.substring(6).trim();
      if (line.startsWith('data:')) data = line.substring(5).trim();
    }
    final json = jsonDecode(data) as Map<String, dynamic>;
    return AdminEvent(
      id,
      type,
      '${json['resource_id'] ?? ''}',
      (json['payload'] as Map?)?.cast<String, dynamic>() ?? const {},
    );
  }
}
