# Architecture

[English](architecture.md) · [简体中文](../zh-CN/architecture.md)

iamllm is a self-hosted single service with separate clients. The Go process owns business state; React and Flutter use only versioned HTTP contracts.

```text
OpenAI / Claude / OpenCode / Gemini clients
                    |
            protocol adapters
                    |
          application services
       queue · timeout · automation
       auth · limits · device sessions
                    |
          repository interfaces
                    |
               SQLite WAL

React console ── REST + SSE ──┐
Flutter iOS/Android ──────────┘
```

## Why Go and SQLite

- Go produces one binary and handles protocol streams and long-lived connections without an interpreter runtime.
- SQLite WAL is sufficient for one human model and one service instance while keeping deployment and backup simple.
- The compiled React console is embedded in the Go binary, so the web frontend is not deployed separately.
- Flutter shares one iOS/Android codebase and uses the Admin API instead of the database.

Repository interfaces leave room for a future PostgreSQL implementation. Until real horizontal scaling is required, iamllm does not add an external database, queue, or distributed lock to a single-person deployment.

## Domain and state

Every vendor request is normalized to `domain.RequestInput` before the application creates a `HumanRequest`. Protocol adapters never implement waiting, timeout, or automation themselves.

A request is one of:

- `pending`: a client is waiting or an asynchronous job has no answer yet;
- `answered`: text or a tool call completed;
- `expired`: an asynchronous job expired without returnable content.

Human chunks carry caller-generated `chunk_id` values. A unique `(request_id, chunk_id)` database index makes retries idempotent. The first chunk obtains a short answer lease and later chunks renew it, reducing collisions between web and mobile responders.

## Large-context performance

Queue queries read summary columns only, not `messages_json` or `tools_json`. Request details return a cleaned user-visible conversation, compact tool metadata, and protected attachment URLs. Full system prompts, tool schemas, and original messages load only when an administrator opens **Raw context**, with gzip support.

This keeps large Codex, Claude Code, and other agent prompts out of the main rendering path.

## Realtime and recovery

- Model output uses each vendor's native SSE event shape.
- Administrative events use `/admin/api/v1/events` with monotonically increasing IDs.
- Web and Flutter reconnect with `Last-Event-ID` and keep low-frequency polling as a fallback.
- Queue pagination uses stable cursors rather than offsets that drift under concurrent inserts.
- Reply chunks are idempotent; drafts and read state live on the server for cross-device handoff.

## Identity and credentials

- Model API: the environment owner key or a managed `sk-` key.
- Initial web login: administrator username and password.
- Initial mobile login: a QR code containing the instance URL and an eight-character one-time pairing code.
- Device access tokens expire after 15 minutes; refresh tokens rotate on use and can be revoked per device.
- Managed keys and refresh tokens are stored as HMAC-SHA256 hashes, never recoverable plaintext.

## Data evolution

The SQLite schema is embedded and initialized serially at startup. The pre-release repository contains one current baseline schema. Once a stable version is published, later changes must add forward migrations.

The current deployment model is explicitly single-instance. A real PostgreSQL option must run the same repository contract tests and ship with a cross-process event bus and consistent answer leases before claiming horizontal scaling.
