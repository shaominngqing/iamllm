# iamllm

一个 API 优先的多协议模型网关：OpenAI、Claude Code、Gemini 及其生态客户端可以直接接入同一服务。请求进入实时队列后，由服务端统一处理上下文、图片、工具定义、流式输出和访问控制；网页 Playground 仅用于连通性与效果调试。

## 已支持

- 无需刷新：会话工作台会自动同步新问题，并在页面休眠时降低刷新频率
- 会话式接管：同一次客户端任务产生的聊天、记忆、标题和建议调用会聚合显示，不再平铺成重复问题
- 大上下文治理：默认还原用户看到的聊天；系统指令、运行记录、工具定义和原始内容按需展开
- 统一控制台：概览、会话工作台、API 密钥、接入指南、自动回复和服务设置都在一个单页后台中完成
- 接入分享卡：创建密钥后可导出包含 API Key、Base URL、模型 ID 和额度信息的 PNG 卡片
- API Playground：保留一套接近 Codex / Claude 的轻量聊天界面，只用于接入调试，不作为产品主入口
- 连续对话：Playground 和服务端会话都会持久化上下文
- 图片与文件：网页支持图片上传；API 会保留 OpenAI、Claude、Gemini 的图片和文件块，后台提供缩略图、PDF/网页预览及本地路径说明
- 模型能力：可在管理端维护展示名称、简介、服务状态和技能列表
- 工具调用：统一展示各协议的执行时间线，并根据 JSON Schema 生成参数表单；工具仍由调用方客户端实际执行
- 快捷话术：在回答框中一键插入常用回复，不会未经确认自动发送
- 自动回复：可按关键词或每周时间段触发，支持延迟发送、启停、优先级和跨午夜时段
- 防重复回答：每个后台标签页自动接管并续租问题，其他页面暂时只读；访客断线后会提示
- 多协议同步、异步与流式：兼容 OpenAI、Claude 和 Gemini 的主流生成入口，另有适合真人延迟的任务接口
- 访问控制：随机 `sk-` 密钥、单钥匙暂停/撤销、分钟/每日/同时等待额度、管理员登录和访客会话隔离

## 项目结构

后端仍然使用 FastAPI，但按职责拆分，入口不再承载具体业务：

- `app/main.py`：应用工厂、生命周期、静态资源和路由装配
- `app/routers/`：兼容 API、访客聊天、管理后台三组 HTTP 路由
- `app/services/human_requests.py`：真人请求创建、会话衔接和通知入队
- `app/services/streaming.py`：协议无关的人类回复事件及各协议流式输出
- `app/services/api_keys.py`：总钥匙兼容、托管密钥签发与多协议统一限流
- `app/schemas.py`：OpenAI 兼容入口、网页聊天和后台操作的输入模型
- `app/security.py`：API Key、管理员和访客会话鉴权
- `app/errors.py`：OpenAI、Claude、Gemini 各自的错误响应格式
- `app/protocols.py`：三家协议的输入归一化和最终响应转换
- `app/repositories/`：真人任务所需的持久化接口，便于后续替换 PostgreSQL
- `app/database.py`：统一数据访问层；本地默认 SQLite，设置 `IAMLLM_DATABASE_URL` 后使用 PostgreSQL
- `app/db_compat.py`：PostgreSQL 连接池与当前 SQL 子集的兼容适配

新的协议入口应只负责“解析请求 → 创建统一真人任务 → 格式化响应”，不要把队列、超时或会话逻辑重新写进路由。

## 本地启动

需要 Python 3.11 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload
```

入口：

- API Playground（仅调试）：<http://127.0.0.1:8000/chat>
- API 控制台：<http://127.0.0.1:8000/admin>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

当前本地开发凭据位于 `.env`：

- 后台用户名：`admin`
- 后台密码：`iamllm-local`
- API Key：`human-local-demo-key`
- 模型名称：`iam-shaomingqing`

这些凭据只适合本机测试。部署前必须全部更换，`.env` 已被 Git 忽略。

## 推荐工作方式

1. 在控制台的“API 密钥”中为调用者生成独立的 `sk-...` 密钥。
2. 打开“接入指南”，复制 OpenAI、Claude Code、Gemini 或 cURL 示例。
3. 让调用者从自己熟悉的客户端发起请求；新任务会自动出现在会话工作台，无需刷新。
4. 在会话工作台中阅读聊天、预览附件、检查工具过程，并连续发送回复 chunk。
5. 使用 `/chat` Playground 做本地连通性、上下文、图片和流式回复测试。

## 会话工作台的连续处理方式

- 待回答会话按先来后到排列；同一客户端在两分钟内产生的后台步骤会并入当前任务，新的真实用户对话会另起一项。
- 文件清单式提示会提取真正的“用户请求”作为短标题，不再把 `Files mentioned by the user` 或长 system prompt 当标题。
- “聊天”视图显示用户和助手的完整历史；“运行记录”展示工具调用及结果；“原始上下文”用于排查协议细节。
- 记忆整理、建议生成和标题生成会明确标成后台任务，并为常见安全结果提供一键填入。
- 工具调用不会让操作者猜 JSON：简单参数会自动生成输入框，复杂对象仍可使用 JSON；页面会说明工具由客户端执行、结果如何返回。
- 图片和文件显示为附件卡片；可读取内容支持预览，仅有调用方本地路径时会解释为何服务端无法直接打开。
- 原始折叠内容只在点开时创建页面内容，单条超长文本也会先显示摘要，可继续展开或复制。该机制对 OpenAI、Claude、Gemini 和其他兼容客户端统一生效。
- 队列原本为空时，新的问题会自动接进来并聚焦回答框；也可以关闭“空闲自动接单”。
- 正在打字时，新问题只更新左侧队列并显示提醒，不会抢走当前问题或输入焦点。
- 每个问题的未发送答案都会保存在本地草稿中，切换问题或意外刷新后仍可恢复。
- 使用 `J` / `K` 可以在下一条和上一条之间移动；输入框内的快捷键仍保持正常。
- 队列清空后会显示完成状态，下一条问题到达时再继续，而不是停留在已经回答的旧问题上。
- 回答框使用聊天软件习惯：`Enter` 发送，`Shift + Enter` 换行，并兼容中文输入法的选词状态。
- 两张后台同时打开时，先进入问题的页面会获得 30 秒可续租的回答权；另一页只读，离开后可重新接管，避免两个人同时回答。
- 后台会显示访客是否仍在线；断线不影响已经送达的问题和答案保存。

## 超时兜底

同步 Chat Completions、Responses、Claude Messages、Gemini GenerateContent 和访客聊天默认等待真人 5 分钟。超时后会返回一条正常的助手消息，而不是让调用方一直等待或直接收到 `504`；响应中的人类元数据会标记回答来源，方便接入方识别。

- `IAMLLM_RESPONSE_TIMEOUT_SECONDS`：真人首段回复等待上限，默认 `300` 秒。
- `IAMLLM_STREAM_IDLE_TIMEOUT_SECONDS`：发出任意 chunk 后的空闲收尾时间，默认 `120` 秒；每发一段都会重新计时，超时后自动用已发送片段收尾。
- `IAMLLM_TIMEOUT_FALLBACK_TEXT`：超时回复文案；设为空字符串可恢复为同步接口返回 `504`。
- `IAMLLM_JOB_TTL_SECONDS`：异步任务的最长保留时间，默认 24 小时。异步接口本来就是为长等待设计的，因此不会在 5 分钟时提前兜底。

## 忙不过来时

后台的“自动挡”有两层能力：

- 快捷话术只是把预设文字填入回复框，仍然需要你点击发送。
- 自动回复规则会在新问题匹配关键词或时间段时开始倒计时，到点后自动发送。倒计时结束前由真人抢答，自动回复就不会再发送。
- “规则试运行”可以输入一条模拟问题，查看会命中哪条规则、原因和回复内容；试运行永远不会真的发送。

时间段默认按 `Asia/Shanghai` 执行，可通过 `.env` 中的 `IAMLLM_TIMEZONE` 修改。

项目内置了几条带点人味的示例。自动规则默认关闭，需要在控制台检查并手动启用；快捷话术默认可用。

## 访问密钥管理

后台的“访问密钥”页可以给每位体验者生成一把独立的随机 `sk-...` 钥匙。完整密钥只在创建成功时展示一次，数据库只保存基于服务端会话密钥计算的 HMAC 指纹和一小段提示，因此之后无法从后台找回明文；遗失时应撤销旧钥匙并重新生成。

创建成功后的单次展示窗口可以复制完整接入信息，或下载一张接入分享卡。分享卡包含完整 API Key、OpenAI Base URL、Claude/Gemini 根地址、模型 ID 和调用额度；它等同于明文密钥，应私下发送，泄露后立即撤销。

每把托管钥匙可以分别设置：

- 每分钟最多发起多少个生成请求
- 每天最多发起多少个生成请求（按 `IAMLLM_TIMEZONE` 的自然日重置）
- 最多允许多少个问题同时处于“等真人回答”状态
- 临时暂停/恢复，以及不可逆的永久撤销

模型列表、token 计数和异步任务状态查询不会消耗生成额度；Chat Completions、Responses、Claude Messages、Gemini GenerateContent 和 `/v1/human/jobs` 会计入。触发限制时，各协议会返回自己的标准 `429` 错误结构和 `Retry-After` 响应头。

`.env` 中的 `IAMLLM_API_KEY` 继续作为不受额度限制的环境变量总钥匙，以兼容已经接入的客户端。它不会被数据库管理，建议只由服务所有者持有；对外体验统一使用后台生成的托管钥匙。

## API 兼容调用

三套入口共用同一个真人队列、上下文、图片、工具和 chunk，不会创建三套互相看不见的对话系统：

| 客户端协议 | 入口 | 鉴权 | 已支持 |
| --- | --- | --- | --- |
| OpenAI Chat Completions | `POST /v1/chat/completions` | `Authorization: Bearer` | `messages`、图片、函数工具、普通/流式返回 |
| OpenAI Responses | `POST /v1/responses` | `Authorization: Bearer` | `input`、`instructions`、Items、图片、函数工具、`previous_response_id`、background、完整 SSE 生命周期 |
| Claude Messages | `POST /v1/messages` | `x-api-key` 或 `Authorization: Bearer` | system/content blocks、base64/URL 图片、tool use/result、普通/流式返回 |
| Gemini GenerateContent | `POST /v1beta/models/{model}:generateContent` | `x-goog-api-key`、`?key=` 或 Bearer | contents/parts、system instruction、inlineData 图片、function call/response、普通/流式返回 |

此外支持 `GET /v1/responses/{id}` 查询 background Response、Claude 与 Gemini 的 count-tokens 入口，以及使用两种鉴权方式访问 `/v1/models`。标准兼容入口会接受并原样返回调用方传入的模型名，因此使用固定 `gpt-*`、`claude-*` 或 `gemini-*` 模型名的客户端不必额外改造；实际回答者始终是同一个真人模型。

### Chat Completions

同步请求会等待真人回答，调用方超时时间应略大于服务端的 5 分钟兜底时间：

```bash
curl --max-time 310 http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer human-local-demo-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "iam-shaomingqing",
    "messages": [{"role": "user", "content": "如果是你，会怎么选择？"}],
    "stream": false
  }'
```

`stream: true` 会进入真人直播回答模式：后台每次在非空输入框按 `Enter`，当前这一段都会立即作为一个 `chat.completion.chunk` 推给调用方，然后清空输入框等待下一段。至少发过一段后，在空输入框再次按 `Enter` 才会发送结束事件和 `[DONE]`；第一次空回车只会提醒，不会误结束。`Shift + Enter` 用于段内换行。调用方按标准流式方式依次拼接 `choices[0].delta.content` 即可得到完整回答。

网页聊天同样实时展示每个 chunk。后台每次非空 `Enter` 都会创建一个真正的回复 chunk，网页端立即追加显示；空 `Enter` 才结束回答。对于明确使用 `stream: false` 的 Chat Completions 请求或异步任务，传输协议本身没有中间事件通道，因此服务端仍按 chunk 生成内容，但调用方只能在结束后一次取回拼接全文。

### OpenAI Responses

OpenAI SDK 的 `base_url` 设为本服务的 `/v1` 地址后，可以直接调用 Responses：

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://你的服务.onrender.com/v1",
    api_key="sk-你的随机密钥",
)

response = client.responses.create(
    model="iam-shaomingqing",
    input="如果你是真人，现在最想吐槽什么？",
)
print(response.output_text)
```

使用 `stream=True` 时，服务会依次发送 `response.created`、输出 Item/内容块事件、每段真人文字对应的 `response.output_text.delta`，最后发送 `response.completed`。它不是 Chat Completions 的 `choices[].delta` 包装。

连续追问可把上一轮的 `response.id` 作为 `previous_response_id`；服务端会把之前的输入、真人回答和本轮输入组合成完整上下文。传入 `background=True` 会立即返回 `in_progress`，随后使用 `GET /v1/responses/{id}` 查询，适合不愿保持五分钟 HTTP 连接的调用方。

### Claude Messages / Claude Code

Claude 原生客户端使用服务根地址（不要额外补 `/v1`），并可继续使用它熟悉的 `x-api-key`：

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://你的服务.onrender.com",
    api_key="sk-你的随机密钥",
)

message = client.messages.create(
    model="claude-sonnet-compatible",
    max_tokens=1024,
    messages=[{"role": "user", "content": "你真的是本人在回吗？"}],
)
print(message.content[0].text)
```

Claude 流式调用会收到标准 `message_start`、`content_block_start/delta/stop`、`message_delta` 和 `message_stop` 事件。Claude Code 提交的 system blocks、tool definitions、`tool_use` / `tool_result` 历史也会转换为后台可读的上下文。

### Gemini GenerateContent

Google GenAI SDK 可把 `base_url` 指向服务根地址，继续使用原生 `generate_content`、`generate_content_stream` 和 `count_tokens`。REST 客户端可以直接调用：

```bash
curl 'https://你的服务.onrender.com/v1beta/models/gemini-compatible:generateContent?key=sk-你的随机密钥' \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"parts":[{"text":"用 Gemini 的格式问真人一个问题"}]}]}'
```

流式路径为 `/v1beta/models/{model}:streamGenerateContent?alt=sse`；后台发出的每个真人 chunk 都会成为一个 Gemini `GenerateContentResponse` SSE 数据块，最后一个数据块带 `finishReason: "STOP"`。`v1` 同名路径也可以使用。

### 图片输入

API 接受公开图片 URL、图片 Data URL，或者本服务上传后产生的 `/uploads/...` 地址：

```json
{
  "model": "iam-shaomingqing",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "你从这张图里看到了什么？"},
        {
          "type": "image_url",
          "image_url": {"url": "https://example.com/photo.jpg"}
        }
      ]
    }
  ]
}
```

### 异步任务

真人可能无法立即回复，业务接入更推荐异步接口：

```bash
curl http://127.0.0.1:8000/v1/human/jobs \
  -H 'Authorization: Bearer human-local-demo-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "iam-shaomingqing",
    "messages": [{"role": "user", "content": "你今天最想分享什么？"}]
  }'
```

使用返回的 `id` 查询状态：

```bash
curl http://127.0.0.1:8000/v1/human/jobs/你的请求ID \
  -H 'Authorization: Bearer human-local-demo-key'
```

### 服务端保存上下文

先创建一个会话：

```bash
curl -X POST http://127.0.0.1:8000/v1/human/conversations \
  -H 'Authorization: Bearer human-local-demo-key'
```

之后每次调用 `/v1/human/jobs` 或 `/v1/chat/completions` 时传入返回的 `conversation_id`，`messages` 只放本轮新增消息。服务端会把本轮消息、之前的提问、真人回答和工具结果组合成完整上下文。

### 函数工具

请求中的工具定义与 Chat Completions 格式一致：

```json
{
  "model": "iam-shaomingqing",
  "messages": [{"role": "user", "content": "帮我保存这句话"}],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "save_note",
        "description": "保存笔记",
        "parameters": {
          "type": "object",
          "properties": {"text": {"type": "string"}},
          "required": ["text"]
        }
      }
    }
  ]
}
```

后台会展示工具说明与参数结构。真人可以直接回答，也可以选择工具并填写 JSON 参数，接口将返回 `finish_reason: "tool_calls"`。

## 数据位置

- 本地默认 SQLite 数据库：`data/iamllm.db`
- 设置 `IAMLLM_DATABASE_URL` 后：API 密钥、设置、会话和请求历史写入 PostgreSQL，SQLite 路径不再使用
- 访客上传图片：`data/uploads/`
- 模型和后台配置：`.env`

这些目录已从 Git 中忽略。PostgreSQL 只解决结构化数据持久化；上传文件仍在本地目录，正式部署还需单独备份或迁移到对象存储。

## 测试

```bash
.venv/bin/pytest
```

测试覆盖多协议鉴权、托管密钥不落明文、暂停/恢复/撤销与三类额度、异步回答、图片输入、图片上传、工具调用、连续上下文、流式返回、后台接管互斥、在线状态、通知 Webhook、生产密钥检查、关键词自动回复和跨午夜时间规则。

## Docker 部署

本项目固定使用一个应用进程，SQLite、上传图片和运行数据统一保存在 Docker 命名卷 `iamllm-data` 中。不要擅自增加 Uvicorn worker 数量；多进程会破坏当前的接管租约和后台任务一致性。

本机先验证：

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

正式服务器先生成生产配置：

```bash
cp .env.production.example .env.production
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

把三个随机值分别填入 `.env.production` 的 API Key、后台密码和会话密钥，设置真实域名，然后启动：

```bash
docker compose --env-file .env.production up -d --build
docker compose logs -f app
```

生产模式会主动拒绝示例凭据、过短密钥、非 HTTPS 公网地址，以及没有 Secure 标记的登录 Cookie。容器默认只把端口绑定到 `127.0.0.1:8000`，应由 Caddy、Nginx 或云平台入口提供公网 HTTPS，再反向代理到这个地址。

## Render 免费公网体验

仓库根目录的 `render.yaml` 可以直接创建一个新加坡区的免费 Web Service。Render 会提供公开的 `https://你的服务名.onrender.com` 地址，并自动处理 HTTPS。

1. 把代码推送到 GitHub 仓库。
2. 在 Render 选择 **New → Blueprint**，连接这个仓库。
3. 创建时填写三个不会写入 Git 的秘密变量：
   - `IAMLLM_API_KEY`：至少 24 个字符，建议用 `sk-` 加随机字符串。
   - `IAMLLM_ADMIN_PASSWORD`：至少 16 个字符。
   - `IAMLLM_DATABASE_URL`：Supabase/PostgreSQL 连接串。Render 建议使用 Supabase 的 Session pooler URI。
4. 等待构建完成后访问 `/chat` 和 `/admin`；程序接入地址为 `/v1`。

免费实例闲置后仍会休眠，下一次请求可能需要等待冷启动；但使用 `IAMLLM_DATABASE_URL` 后，API 密钥、设置、会话和请求历史保存在托管 PostgreSQL 中，不会再跟着 Render 实例消失。上传图片目前仍写入 Render 临时磁盘，休眠恢复、重启或重新部署后可能丢失，长期使用应迁移到 Supabase Storage 等对象存储。

Render 会通过 `PORT` 环境变量指定监听端口，项目的容器启动器已经自动读取它；本地没有该变量时仍使用 `8000`。

### 新问题通知 Webhook

设置 `IAMLLM_NOTIFICATION_WEBHOOK_URL` 后，每条新问题都会异步 POST 一份 JSON。发送失败会重试 3 次，但不会阻塞访客请求。`IAMLLM_PUBLIC_BASE_URL` 用于在通知里生成直达回答页的链接。

```json
{
  "event": "human_request.created",
  "text": "🧠 新问题到达 · 访客聊天\n你在吗？\nhttps://human.example.com/admin#inbox/chatcmpl_xxx",
  "request": {
    "id": "chatcmpl_xxx",
    "source": "web_chat",
    "preview": "你在吗？",
    "admin_url": "https://human.example.com/admin#inbox/chatcmpl_xxx"
  }
}
```

这是通用 Webhook 格式，可先接自动化平台，再转发到飞书、Telegram、Slack 或邮件。

### 备份持久卷

升级或迁移前先短暂停机并复制整个数据目录，这样数据库和上传图片会一起保存：

```bash
mkdir -p backups
docker compose stop app
docker compose cp app:/data ./backups/data-backup
docker compose start app
```

## 正式公网前检查

- 已更换所有默认密码、API Key 和会话密钥
- 域名已启用 HTTPS，`IAMLLM_COOKIE_SECURE=true`
- 已测试 Webhook、数据卷备份和恢复
- 已在反向代理或云平台配置请求限流和日志轮转
- 已说明隐私政策、内容保留期限和删除方式

本地单机内测继续使用 SQLite 即可；Render 免费部署应使用 PostgreSQL。要让图片和附件也跨重启保存，还需迁移到对象存储。
