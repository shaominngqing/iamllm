class PairingPayload {
  const PairingPayload({required this.server, required this.code});

  final String server;
  final String code;

  static PairingPayload? parse(String raw) {
    final uri = Uri.tryParse(raw.trim());
    if (uri == null || uri.scheme != 'iamllm' || uri.host != 'pair') {
      return null;
    }
    final server = Uri.tryParse(uri.queryParameters['server']?.trim() ?? '');
    final code = uri.queryParameters['code']?.trim() ?? '';
    if (server == null ||
        !{'http', 'https'}.contains(server.scheme) ||
        server.host.isEmpty ||
        !RegExp(r'^\d{8}$').hasMatch(code)) {
      return null;
    }
    final normalized = server.replace(
      path: server.path.replaceAll(RegExp(r'/+$'), ''),
    );
    return PairingPayload(server: normalized.toString(), code: code);
  }
}
