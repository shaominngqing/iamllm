import 'package:flutter_test/flutter_test.dart';
import 'package:iamllm_mobile/models.dart';
import 'package:iamllm_mobile/pairing_payload.dart';

void main() {
  test('request summary decodes safely', () {
    final item = HumanRequest.fromJson({
      'id': 'req_1',
      'preview': '你好',
      'status': 'pending',
      'source': 'openai_chat',
      'model': 'human',
      'created_at': 1,
      'context_chars': 2,
      'tool_count': 0,
      'attachment_count': 0,
      'stream_chunk_count': 0,
    });
    expect(item.preview, '你好');
    expect(item.messages, isEmpty);
  });

  test('stream chunks are sorted and merged into one assistant answer', () {
    final item = HumanRequest.fromJson({
      'id': 'req_stream',
      'preview': '在吗',
      'status': 'answered',
      'source': 'openai_chat',
      'created_at': 1,
      'stream_chunks': [
        {'position': 3, 'content': '。'},
        {'position': 1, 'content': '在，'},
        {'position': 2, 'content': '灵魂在线'},
      ],
    });

    expect(item.visibleAnswer, '在，灵魂在线。');
  });

  test('completed answer takes precedence over its delivery chunks', () {
    final item = HumanRequest.fromJson({
      'id': 'req_done',
      'preview': '你好',
      'status': 'answered',
      'source': 'anthropic_messages',
      'answer': '你好呀',
      'stream_chunks': [
        {'position': 1, 'content': '你'},
        {'position': 2, 'content': '好呀'},
      ],
    });

    expect(item.visibleAnswer, '你好呀');
  });

  test('pairing QR carries the instance URL and one-time code', () {
    final payload = PairingPayload.parse(
      'iamllm://pair?server=https%3A%2F%2Fhuman.example.com%2F&code=12345678',
    );

    expect(payload?.server, 'https://human.example.com');
    expect(payload?.code, '12345678');
  });

  test('pairing QR rejects unrelated or unsafe payloads', () {
    expect(PairingPayload.parse('https://example.com'), isNull);
    expect(
      PairingPayload.parse(
        'iamllm://pair?server=file%3A%2F%2Ftmp&code=12345678',
      ),
      isNull,
    );
    expect(
      PairingPayload.parse(
        'iamllm://pair?server=https%3A%2F%2Fexample.com&code=1234',
      ),
      isNull,
    );
  });
}
