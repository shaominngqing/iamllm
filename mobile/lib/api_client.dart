import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'app_info.dart';
import 'models.dart';
import 'session_store.dart';

class APIException implements Exception {
  APIException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

class APIClient {
  APIClient(this.session);
  final SessionStore session;
  final http.Client _http = http.Client();
  int _lastEventId = 0;
  Uri uri(String path) =>
      Uri.parse('${session.baseUrl}${path.startsWith('/') ? '' : '/'}$path');

  String get _deviceName {
    if (kIsWeb) return 'Flutter Web 预览';
    final hostname = Platform.localHostname.trim();
    return hostname.isEmpty || hostname == 'localhost'
        ? 'Flutter 手机'
        : hostname;
  }

  Map<String, dynamic> get _deviceMetadata => kIsWeb
      ? {
          'device_name': _deviceName,
          'platform': 'web',
          'device_model': 'browser',
          'os_version': 'Flutter Web',
          'app_version': appVersionMetadata,
          'locale': 'zh-CN',
          'timezone': DateTime.now().timeZoneName,
        }
      : {
          'device_name': _deviceName,
          'platform': Platform.operatingSystem,
          'device_model': Platform.localHostname,
          'os_version': Platform.operatingSystemVersion,
          'app_version': appVersionMetadata,
          'locale': Platform.localeName,
          'timezone': DateTime.now().timeZoneName,
        };

  Future<TokenPair> login(
    String server,
    String username,
    String password,
  ) async {
    session.baseUrl = server.replaceAll(RegExp(r'/+$'), '');
    final json = await _send(
      '/admin/api/v1/auth/login',
      method: 'POST',
      body: {'username': username, 'password': password, ..._deviceMetadata},
      auth: false,
    );
    final pair = TokenPair.fromJson(json);
    await session.save(
      server: session.baseUrl,
      access: pair.access,
      refresh: pair.refresh,
      device: pair.device.id,
    );
    return pair;
  }

  Future<TokenPair> pair(String server, String code) async {
    session.baseUrl = server.replaceAll(RegExp(r'/+$'), '');
    final json = await _send(
      '/admin/api/v1/auth/pair',
      method: 'POST',
      body: {'code': code, ..._deviceMetadata},
      auth: false,
    );
    final pair = TokenPair.fromJson(json);
    await session.save(
      server: session.baseUrl,
      access: pair.access,
      refresh: pair.refresh,
      device: pair.device.id,
    );
    return pair;
  }

  Future<void> refresh() async {
    final json = await _send(
      '/admin/api/v1/auth/refresh',
      method: 'POST',
      body: {'refresh_token': session.refreshToken, ..._deviceMetadata},
      auth: false,
    );
    final pair = TokenPair.fromJson(json);
    await session.save(
      server: session.baseUrl,
      access: pair.access,
      refresh: pair.refresh,
      device: pair.device.id,
    );
  }

  Future<List<HumanRequest>> requests({String status = 'pending'}) async {
    final json = await _send('/admin/api/v1/requests?status=$status&limit=200');
    return (json['items'] as List)
        .whereType<Map<String, dynamic>>()
        .map(HumanRequest.fromJson)
        .toList();
  }

  Future<HumanRequest> request(String id) async =>
      HumanRequest.fromJson(await _send('/admin/api/v1/requests/$id'));

  Future<HumanRequest> markRead(String id) async => HumanRequest.fromJson(
    await _send('/admin/api/v1/requests/$id/read', method: 'PUT', body: {}),
  );

  Future<HumanRequest> saveDraft(String id, String content) async =>
      HumanRequest.fromJson(
        await _send(
          '/admin/api/v1/requests/$id/draft',
          method: 'PUT',
          body: {'content': content, 'device_id': session.deviceId},
        ),
      );
  Future<List<ChatMessage>> rawMessages(String id) async {
    final value = await _send('/admin/api/v1/requests/$id/raw');
    return (value['messages'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<List<QuickReply>> quickReplies({bool all = false}) async {
    final value = await _send(
      '/admin/api/v1/quick-replies${all ? '?all=1' : ''}',
    );
    return (value['items'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(QuickReply.fromJson)
        .toList();
  }

  Future<QuickReply> saveQuickReply(QuickReply item) async {
    final value = await _send(
      item.id.isEmpty
          ? '/admin/api/v1/quick-replies'
          : '/admin/api/v1/quick-replies/${item.id}',
      method: item.id.isEmpty ? 'POST' : 'PATCH',
      body: item.toJson(),
    );
    return QuickReply.fromJson(value);
  }

  Future<void> deleteQuickReply(String id) async {
    await _send('/admin/api/v1/quick-replies/$id', method: 'DELETE');
  }

  Future<List<AutoReplyRule>> autoRules() async {
    final value = await _send('/admin/api/v1/auto-rules');
    return (value['items'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(AutoReplyRule.fromJson)
        .toList();
  }

  Future<AutoReplyRule> saveAutoRule(AutoReplyRule item) async {
    final value = await _send(
      item.id.isEmpty
          ? '/admin/api/v1/auto-rules'
          : '/admin/api/v1/auto-rules/${item.id}',
      method: item.id.isEmpty ? 'POST' : 'PATCH',
      body: item.toJson(),
    );
    return AutoReplyRule.fromJson(value);
  }

  Future<void> deleteAutoRule(String id) async {
    await _send('/admin/api/v1/auto-rules/$id', method: 'DELETE');
  }

  Future<List<APIKeyItem>> apiKeys() async {
    final value = await _send('/admin/api/v1/api-keys');
    return (value['items'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(APIKeyItem.fromJson)
        .toList();
  }

  Future<CreatedAPIKey> createAPIKey({
    required String name,
    required int rate,
    required int daily,
    required int concurrent,
  }) async => CreatedAPIKey.fromJson(
    await _send(
      '/admin/api/v1/api-keys',
      method: 'POST',
      body: {
        'name': name,
        'rate_limit_per_minute': rate,
        'daily_limit': daily,
        'max_concurrent': concurrent,
      },
    ),
  );

  Future<void> revokeAPIKey(String id) async {
    await _send('/admin/api/v1/api-keys/$id/revoke', method: 'POST', body: {});
  }

  Future<ServiceOverview> overview() async =>
      ServiceOverview.fromJson(await _send('/admin/api/v1/overview'));

  Future<ModelProfile> profile() async =>
      ModelProfile.fromJson(await _send('/admin/api/v1/profile'));

  Future<ModelProfile> saveProfile(ModelProfile profile) async =>
      ModelProfile.fromJson(
        await _send(
          '/admin/api/v1/profile',
          method: 'PUT',
          body: profile.toJson(),
        ),
      );

  Future<({List<Device> items, String currentDeviceId})> devices() async {
    final value = await _send('/admin/api/v1/devices');
    return (
      items: (value['items'] as List? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(Device.fromJson)
          .toList(),
      currentDeviceId: '${value['current_device_id'] ?? ''}',
    );
  }

  Future<void> revokeDevice(String id) async {
    await _send('/admin/api/v1/devices/$id', method: 'DELETE');
  }

  Future<void> sendChunk(String id, String chunkId, String content) async {
    await _send(
      '/admin/api/v1/requests/$id/chunks',
      method: 'POST',
      body: {
        'chunk_id': chunkId,
        'content': content,
        'operator_id': session.deviceId,
      },
    );
  }

  Future<void> complete(String id) async {
    await _send(
      '/admin/api/v1/requests/$id/complete',
      method: 'POST',
      body: {},
    );
  }

  Future<void> answer(String id, String content) async {
    await _send(
      '/admin/api/v1/requests/$id/answer',
      method: 'POST',
      body: {'content': content, 'operator_id': session.deviceId},
    );
  }

  Future<void> answerTool(
    String id,
    String toolName,
    Map<String, dynamic> arguments,
  ) async {
    await _send(
      '/admin/api/v1/requests/$id/answer',
      method: 'POST',
      body: {
        'response_type': 'tool_call',
        'tool_name': toolName,
        'tool_arguments': arguments,
        'operator_id': session.deviceId,
      },
    );
  }

  Stream<AdminEvent> events() async* {
    while (session.signedIn) {
      try {
        final request = http.Request('GET', uri('/admin/api/v1/events'));
        request.headers['Authorization'] = 'Bearer ${session.accessToken}';
        if (_lastEventId > 0) {
          request.headers['Last-Event-ID'] = '$_lastEventId';
        }
        final response = await _http.send(request);
        if (response.statusCode == 401) {
          await refresh();
          continue;
        }
        if (response.statusCode != 200) {
          throw APIException(response.statusCode, '事件连接失败');
        }
        var buffer = '';
        await for (final chunk in response.stream.transform(utf8.decoder)) {
          buffer += chunk;
          final blocks = buffer.split('\n\n');
          buffer = blocks.removeLast();
          for (final block in blocks) {
            if (block.contains('data:')) {
              final event = AdminEvent.fromBlock(block);
              if (event.id > _lastEventId) _lastEventId = event.id;
              yield event;
            }
          }
        }
      } catch (_) {
        await Future<void>.delayed(const Duration(seconds: 2));
      }
    }
  }

  Future<Map<String, dynamic>> _send(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
    bool auth = true,
    bool retried = false,
  }) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (body != null) headers['Content-Type'] = 'application/json';
    if (auth && session.accessToken.isNotEmpty)
      headers['Authorization'] = 'Bearer ${session.accessToken}';
    final request = http.Request(method, uri(path))..headers.addAll(headers);
    if (body != null) request.body = jsonEncode(body);
    final response = await _http.send(request);
    final text = await response.stream.bytesToString();
    if (response.statusCode == 401 &&
        auth &&
        !retried &&
        session.refreshToken.isNotEmpty) {
      await refresh();
      return _send(path, method: method, body: body, auth: auth, retried: true);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      var message = '请求失败 (${response.statusCode})';
      try {
        final json = jsonDecode(text);
        message = '${json['error']?['message'] ?? json['detail'] ?? message}';
      } catch (_) {}
      throw APIException(response.statusCode, message);
    }
    if (text.isEmpty) return {};
    return jsonDecode(text) as Map<String, dynamic>;
  }

  void close() => _http.close();
}
