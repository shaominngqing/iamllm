# Client integration

[English](client-integration.md) · [简体中文](../zh-CN/client-integration.md)

Callers should be able to treat iamllm like an ordinary model service. Most integrations need three values:

```text
Server:  https://llm.example.com
API key: sk-...
Model:   iam-human
```

Every value below is an example. Create shareable keys in the web console under **API keys** and never distribute the environment owner key.

## Verify the instance first

```bash
export IAMLLM_URL=https://llm.example.com
export IAMLLM_KEY=sk-your-managed-key
export IAMLLM_MODEL=iam-human

curl "$IAMLLM_URL/health"
curl "$IAMLLM_URL/v1/models" \
  -H "Authorization: Bearer $IAMLLM_KEY"
```

Protocol base URLs differ slightly:

| Use | Base URL |
| --- | --- |
| OpenAI SDKs and OpenCode | `https://llm.example.com/v1` |
| Claude Code / Anthropic SDK | `https://llm.example.com` |
| Gemini REST | `https://llm.example.com` |

![Real iamllm integration guide](../images/web-connect.jpg)

The deployed **Integration guide** shows URLs and copyable commands based on the instance's actual public address.

## OpenAI Chat Completions

### curl

```bash
curl -N "$IAMLLM_URL/v1/chat/completions" \
  -H "Authorization: Bearer $IAMLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d "{
    \"model\": \"$IAMLLM_MODEL\",
    \"stream\": true,
    \"messages\": [
      {\"role\": \"system\", \"content\": \"Keep the answer concise.\"},
      {\"role\": \"user\", \"content\": \"Hello, who are you?\"}
    ]
  }"
```

### Python SDK

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["IAMLLM_KEY"],
    base_url="https://llm.example.com/v1",
)

stream = client.chat.completions.create(
    model="iam-human",
    stream=True,
    messages=[{"role": "user", "content": "Tell me a very short joke."}],
)

for event in stream:
    text = event.choices[0].delta.content
    if text:
        print(text, end="", flush=True)
```

### JavaScript SDK

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.IAMLLM_KEY,
  baseURL: "https://llm.example.com/v1",
});

const stream = await client.chat.completions.create({
  model: "iam-human",
  stream: true,
  messages: [{ role: "user", content: "Hello" }],
});

for await (const event of stream) {
  process.stdout.write(event.choices[0]?.delta?.content ?? "");
}
```

![Human streaming reply](../images/streaming-reply.en.svg)

The human may send several chunks, but protocol and chat semantics still treat them as one assistant message. An empty Enter ends the response only after at least one chunk was sent.

## OpenAI Responses API

Use Responses for `input`, previous responses, background jobs, or Responses-style function calls:

```bash
curl -N "$IAMLLM_URL/v1/responses" \
  -H "Authorization: Bearer $IAMLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d "{
    \"model\": \"$IAMLLM_MODEL\",
    \"stream\": true,
    \"input\": \"Introduce yourself in one sentence.\"
  }"
```

Create and later retrieve a background response:

```bash
curl "$IAMLLM_URL/v1/responses" \
  -H "Authorization: Bearer $IAMLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d "{
    \"model\": \"$IAMLLM_MODEL\",
    \"background\": true,
    \"input\": \"Think about this and answer when ready.\"
  }"

curl "$IAMLLM_URL/v1/responses/resp_xxx" \
  -H "Authorization: Bearer $IAMLLM_KEY"
```

## Claude Code

Claude Code uses Anthropic Messages:

```bash
export ANTHROPIC_BASE_URL=https://llm.example.com
export ANTHROPIC_AUTH_TOKEN=sk-your-managed-key
export ANTHROPIC_MODEL=iam-human

claude
```

Important details:

- `ANTHROPIC_BASE_URL` has no `/v1`; Claude Code appends `/v1/messages`.
- Use `ANTHROPIC_AUTH_TOKEN`; iamllm accepts the Bearer authorization it produces.
- The selected model must match your configured identifier. For “model identifier is invalid,” compare `ANTHROPIC_MODEL`, the console model name, and Claude Code's `/model`.
- Claude Code sends system prompts, skills, tool schemas, and environment context. iamllm keeps these in the run log while the chat focuses on user-visible messages.

Direct Messages API call:

```bash
curl -N "$IAMLLM_URL/v1/messages" \
  -H "x-api-key: $IAMLLM_KEY" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'Content-Type: application/json' \
  -d "{
    \"model\": \"$IAMLLM_MODEL\",
    \"max_tokens\": 1024,
    \"stream\": true,
    \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]
  }"
```

## OpenCode

Add an OpenAI-compatible provider:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "iamllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "iamllm",
      "options": {
        "baseURL": "https://llm.example.com/v1"
      },
      "models": {
        "iam-human": {
          "name": "iam-human"
        }
      }
    }
  }
}
```

Save this as a project or user `opencode.json`, then run:

```text
/connect
Other
iamllm
sk-your-managed-key
```

Use `/models` to select `iamllm/iam-human`. To read the key from an environment variable, add:

```json
"apiKey": "{env:IAMLLM_KEY}"
```

OpenCode configuration can change between releases. If your version rejects `provider`, consult its current provider documentation. OpenCode may send a separate “generate a conversation title” request near the first user message; that is a distinct client request, not a duplicated iamllm chunk. A stable internal prompt can be handled with automation.

## Gemini

Non-streaming:

```bash
curl "$IAMLLM_URL/v1beta/models/$IAMLLM_MODEL:generateContent" \
  -H "x-goog-api-key: $IAMLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "contents": [{
      "role": "user",
      "parts": [{"text": "Hello"}]
    }]
  }'
```

Streaming:

```bash
curl -N "$IAMLLM_URL/v1beta/models/$IAMLLM_MODEL:streamGenerateContent?alt=sse" \
  -H "x-goog-api-key: $IAMLLM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"role":"user","parts":[{"text":"Answer in chunks"}]}]}'
```

Gemini authentication accepts `x-goog-api-key`, Bearer, or a `key` query parameter.

## Images and files

OpenAI Chat Completions image example:

```json
{
  "model": "iam-human",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "What is in this image?"},
      {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}}
    ]
  }]
}
```

Supported clients may also send base64 data URLs. The iamllm server must be able to reach remote URLs; a local absolute path that exists only on the caller's computer is not a public attachment. Administrative attachment routes require an authenticated session or device token.

## Tool calls

When a request contains `tools`, the conversation desk shows names, descriptions, and schemas. Choose **Call client tool** and enter the tool plus JSON arguments. iamllm emits the appropriate `tool_calls`, function call, `tool_use`, or Gemini function-call form.

The caller executes tools. The iamllm server does not run shell commands, edit client files, or access the caller's environment. Tool results normally arrive in a follow-up model request.

## Why one chat can produce several requests

Agent clients such as Codex, Claude Code, and OpenCode can issue independent model requests to:

- generate a title;
- summarize memory or compact context;
- plan the next step;
- select or continue a tool;
- retry after an error.

One click is therefore not always one API request. iamllm folds system prompts and tool schemas into the run log but cannot infer every client's custom internal intent. Configure recognizable internal jobs as automation rules.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `401 Unauthorized` | Wrong, revoked, exhausted, or missing key. Test `/v1/models` with Bearer authentication. |
| `400 model identifier is invalid` | Client model differs from `IAMLLM_MODEL_NAME`. Check the client and Claude Code `/model`. |
| `404 /v1/responses` | Wrong base URL or outdated service. OpenAI base URL should end in `/v1`. |
| Request waits for a long time | A human has not answered. Check the queue, notifications, and response timeout. |
| All text appears at once | The proxy buffers SSE. Use Caddy `flush_interval -1` or Nginx `proxy_buffering off`. |
| Title or memory task appears beside the first prompt | It is a separate agent-client request. Inspect the run log and automate stable prompts. |
| Another request follows a tool call | Expected: the client executed the tool and returned its result. |
| Image cannot be displayed | The URL is local-only, the server cannot fetch it, or the attachment requires admin authentication. |
| Timeout feels shorter than five minutes | Compare client, proxy, and server timeouts; the shortest one wins. |

The running instance's `/openapi.json` is always the authoritative machine-readable contract.
