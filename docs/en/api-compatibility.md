# API compatibility

[English](api-compatibility.md) · [简体中文](../zh-CN/api-compatibility.md)

iamllm implements the protocol surface required by common clients; it does not claim to reproduce every cloud-model behavior. The current instance's `/openapi.json` is the machine-readable contract. Copyable client configuration lives in [Client integration](client-integration.md).

## OpenAI

| Endpoint | Support |
| --- | --- |
| `GET /v1/models` | Model and capability metadata |
| `POST /v1/chat/completions` | Streaming/non-streaming, images, files, tool calls, custom `conversation_id` |
| `POST /v1/responses` | Streaming/non-streaming, `background`, `previous_response_id`, `conversation`, function calls |
| `GET /v1/responses/{id}` | Retrieve a background response |

`previous_response_id` and `conversation` are mutually exclusive. System messages and tool definitions remain available to administrators but do not pollute user-visible chat titles.

OpenAI-style endpoints accept `Authorization: Bearer sk-...`. Clients may probe `GET /v1/models/{model}` during startup.

## Anthropic

| Endpoint | Support |
| --- | --- |
| `POST /v1/messages` | Streaming/non-streaming, system blocks, images, documents, `tool_use`/`tool_result` |
| `POST /v1/messages/count_tokens` | Lightweight local estimate |

Authentication accepts `x-api-key` or `Authorization: Bearer`. Token counting does not consume call quota.

Set Claude Code's `ANTHROPIC_BASE_URL` to the instance root without `/v1`.

## Gemini

| Endpoint | Support |
| --- | --- |
| `:generateContent` | Non-streaming response |
| `:streamGenerateContent` | SSE stream |
| `:countTokens` | Lightweight local estimate |

Both `/v1beta/models/...` and `/v1/models/...` are accepted. Authentication may use `x-goog-api-key`, the `key` query parameter, or Bearer.

## Human asynchronous jobs

- `POST /v1/human/jobs`
- `GET /v1/human/jobs/{id}`

Use these endpoints when a caller cannot hold an HTTP connection open. The first request returns a job identifier; the caller polls until the state is `answered` or `expired`.

## Streaming semantics

- A human can send multiple chunks; clients must render them as one assistant message.
- After at least one chunk, an empty reply ends the response.
- Automation replies use native protocol events and can be split into small delayed chunks.
- Timeout errors use the vendor-compatible error envelope whenever the protocol defines one.

Reverse proxies must disable response buffering, or chunks may arrive together at the end.

## Tools

The console normalizes vendor tool definitions for review. A human tool answer is encoded back as OpenAI `tool_calls`, Responses function calls, Anthropic `tool_use`, or Gemini function calls. iamllm returns the request; the caller remains responsible for executing the tool and sending its result in a follow-up model request.

## Attachments

HTTP(S) image URLs and supported inline/base64 forms are normalized into protected attachment metadata. Administrative attachment endpoints require an administrator session or device token. Local paths that exist only on the caller's computer cannot be fetched by the server.

## Deliberate boundaries

- Token counts are local estimates, not vendor tokenizer parity.
- iamllm does not execute client-side tools.
- Vendor-specific hosted features outside the documented endpoints are not emulated.
- One user action in an agent client can create several independent API requests for titles, memory, planning, or tool continuation.

For concrete setup and troubleshooting examples, continue with [Client integration](client-integration.md).
