# API 兼容性

## OpenAI

| 端点 | 支持 |
| --- | --- |
| `GET /v1/models` | 模型和能力元数据 |
| `POST /v1/chat/completions` | 普通/流式、图片、文件、tool calls、自定义 `conversation_id` |
| `POST /v1/responses` | 普通/流式、`background`、`previous_response_id`、`conversation`、function calls |
| `GET /v1/responses/{id}` | 查询后台 Response |

`previous_response_id` 与 `conversation` 不能同时使用。系统消息和工具定义会保存给管理端，但不会污染用户可见聊天标题。

## Anthropic

| 端点 | 支持 |
| --- | --- |
| `POST /v1/messages` | 普通/流式、system blocks、图片、document、tool_use/tool_result |
| `POST /v1/messages/count_tokens` | 轻量本地估算 |

鉴权接受 `x-api-key` 或 `Authorization: Bearer`。`count_tokens` 不计入调用额度。

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
