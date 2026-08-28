# API 兼容性

iamllm 实现的是客户端接入所需的协议子集，不声称复制各厂商云端模型的全部行为。机器可读契约以当前实例的 `/openapi.json` 为准；面向具体客户端的可复制配置见 [客户端接入教程](client-integration.md)。

## OpenAI

| 端点 | 支持 |
| --- | --- |
| `GET /v1/models` | 模型和能力元数据 |
| `POST /v1/chat/completions` | 普通/流式、图片、文件、tool calls、自定义 `conversation_id` |
| `POST /v1/responses` | 普通/流式、`background`、`previous_response_id`、`conversation`、function calls |
| `GET /v1/responses/{id}` | 查询后台 Response |

`previous_response_id` 与 `conversation` 不能同时使用。系统消息和工具定义会保存给管理端，但不会污染用户可见聊天标题。

OpenAI 风格接口接受 `Authorization: Bearer sk-...`。`GET /v1/models/{model}` 可用于客户端启动时的模型探测。

## Anthropic

| 端点 | 支持 |
| --- | --- |
| `POST /v1/messages` | 普通/流式、system blocks、图片、document、tool_use/tool_result |
| `POST /v1/messages/count_tokens` | 轻量本地估算 |

鉴权接受 `x-api-key` 或 `Authorization: Bearer`。`count_tokens` 不计入调用额度。

Claude Code 的 `ANTHROPIC_BASE_URL` 应填写实例根地址，不要追加 `/v1`。

## Gemini

| 端点 | 支持 |
| --- | --- |
| `:generateContent` | 普通响应 |
| `:streamGenerateContent` | SSE 流式响应 |
| `:countTokens` | 轻量本地估算 |

同时接受 `/v1beta/models/...` 与 `/v1/models/...`，鉴权接受 `x-goog-api-key`、查询参数 `key` 或 Bearer。

## 人工异步任务

- `POST /v1/human/jobs`
- `GET /v1/human/jobs/{id}`

用于不希望保持 HTTP 长连接的调用方。

## 管理契约

Admin API 位于 `/admin/api/v1`，由 React 和 Flutter 共用。接口包含登录/配对、游标队列、请求详情、原始上下文、附件、回复 chunk、工具调用、配置、设备和可恢复 SSE。完整机器可读路径见运行实例的 `/openapi.json`。

## 通用行为

- 文本回答可以由多个人工或自动 chunk 组成；厂商适配器会把它们拼成同一条助手消息语义。
- 非流式请求也会等待人工完成，再返回单个 JSON 响应。
- 默认总等待时间是 300 秒；超时会返回配置的兜底文本，而不是永久占用连接。
- 客户端重试可能产生新的模型请求。回答 chunk 自身使用 `chunk_id` 幂等，网络重试不会重复写入同一段。
- Agent 客户端可能为标题、记忆、压缩和工具调用发送独立请求；这不属于同一个 SSE 响应的重复 chunk。
