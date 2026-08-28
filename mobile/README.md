# iamllm Mobile

[English](README.md) · [简体中文](README.zh-CN.md)

The Flutter administration app runs on iOS and Android from one codebase. It communicates only through iamllm's `/admin/api/v1` REST and SSE contract and never connects directly to the server database.

The app has four workspaces:

- **Conversations:** search and filter requests, view user-visible chat, merge stream chunks, reply, or call a tool.
- **Automation:** create, edit, enable, and delete keyword/schedule rules and quick replies.
- **API keys:** request a managed key, set limits, view it once, and revoke it later.
- **Service:** inspect health, edit public identity, and review or revoke administrator devices.

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

QR pairing is the default first connection. The web console generates a QR code containing the current instance URL and an eight-character one-time code. The app does not ship with any server address.

Manual URL/code entry remains available when the camera cannot be used. Administrator credentials are a deployment-owner fallback only. Use HTTPS for every production distribution.

See [Flutter mobile administration](../docs/en/flutter-mobile.md) for features, pairing, and release preparation.
