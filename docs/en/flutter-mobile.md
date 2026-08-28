# Flutter mobile administration

[English](flutter-mobile.md) · [简体中文](../zh-CN/flutter-mobile.md)

`mobile/` is a runnable Flutter iOS/Android application designed to let the human model take over from anywhere. It intentionally keeps low-frequency server administration out of the primary mobile flow.

Implemented capabilities include:

- QR pairing, an eight-character one-time code, and administrator fallback login;
- Keychain/Keystore storage and automatic refresh-token rotation;
- pending, answered, and expired queues;
- iOS-oriented four-tab navigation and narrow-screen layouts;
- SSE reconnect with `Last-Event-ID` recovery;
- user-visible chat, compact run details, and lazy raw context;
- one assistant bubble for multiple stream chunks;
- authenticated image previews and file cards;
- quick replies, server-side drafts, chunk sending, and empty-message completion;
- tool selection and JSON argument submission;
- full automation-rule and quick-reply management;
- API-key requests, limits, one-time display, and revocation;
- service status, public profile, and administrator device details;
- idempotent `chunk_id` values and cross-device answer-conflict feedback.

<p align="center">
  <img src="../images/mobile-inbox.png" width="23%" alt="Real Flutter inbox">
  <img src="../images/mobile-conversation.png" width="23%" alt="Real Flutter conversation">
  <img src="../images/mobile-automation.png" width="23%" alt="Real Flutter automation">
  <img src="../images/mobile-keys.png" width="23%" alt="Real Flutter API keys">
</p>

## Run

```bash
cd mobile
flutter pub get
flutter run
```

The app contains no server address. A web-generated QR code uses:

```text
iamllm://pair?server=<instance-url>&code=<one-time-code>
```

After scanning, the app validates the scheme, address, and code before calling the pairing API.

HTTP is available for local development; the Android manifest and iOS Info.plist allow local debug connections. Production builds must connect to HTTPS and use the deployer's own application identity and signing.

## Release preparation

The deployer still owns:

- Bundle ID / applicationId, display name, icons, and launch assets;
- Apple Developer and Android keystore signing;
- an optional APNs/FCM gateway referenced by `IAMLLM_NOTIFICATION_WEBHOOK_URL`;
- privacy policy, crash-reporting choices, and store materials.

Push notifications should wake and alert the app without embedding complete conversation content. The application fetches authoritative state through the Admin API after opening.
