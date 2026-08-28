# Product roadmap

[English](roadmap.md) · [简体中文](../zh-CN/roadmap.md)

iamllm is not a hosted instance for one particular author. It lets anyone publish themselves from their own server as a standard model API. Each instance represents one human model, and its operator owns the data and credentials.

## Current baseline: self-hosted single instance

- one Go backend, embedded React console, and SQLite WAL persistence;
- OpenAI Chat Completions / Responses, Anthropic Messages, and Gemini GenerateContent;
- text, images, files, tools, and human stream chunks;
- shared Admin API, device sessions, drafts, read state, and answer leases for Web and Flutter;
- revocable `sk-` keys, limits, automation, webhook notifications, and Playground;
- one-command Docker Compose deployment without an external database, queue, or interpreter.

## Next: easier first deployment

1. First-run wizard for administrator creation, owner key, model name, and public URL.
2. Diagnostics for HTTPS, reverse proxy, SSE, database writes, and notification webhooks.
3. Configuration export/import plus guided online backup and restore.
4. Versioned container images, checksums, release notes, and upgrade documentation.
5. End-to-end compatibility tests using real OpenAI SDKs, Claude Code, OpenCode, and Gemini SDKs.

## Mobile refinement

1. iOS-first notifications, badges, and deep links without private conversation text by default.
2. Offline drafts, idempotent resume after network recovery, and cross-device conflict handling.
3. Better search, quick actions, attachment viewers, and device-security alerts.
4. Deployer-owned app identifiers, signing, APNs/FCM, and store metadata; no official client hard-codes an instance.

## Only after real scale requires it

- a PostgreSQL repository implementation and shared contract tests;
- a multi-instance event bus and cross-process answer leases;
- multiple administrator roles and audit history;
- optional object storage and large-attachment lifecycle management.

The project will not add placeholder adapters, compatibility layers, or speculative database columns before a real deployment requires them.

## Explicitly out of scope

- pretending the server performs autonomous inference;
- making any SaaS provider mandatory;
- hard-coding an author's server, model, or key into the mobile client;
- preserving unpublished historical schemas or one-off transition code;
- leaking OpenAI, Anthropic, or Gemini differences into the core domain.
