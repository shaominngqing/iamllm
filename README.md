# iamllm

一个由真人驱动的完整聊天服务：既可以通过网页连续对话，也可以作为 OpenAI 兼容 API 被程序调用。问题进入实时队列后，由真人阅读完整上下文、图片和工具定义，再亲自返回文字或函数调用。

## 已支持

- 无需刷新：回答后台会自动同步新问题，并在页面休眠时降低刷新频率
- 统一控制台：驾驶舱、实时收件箱、自动化和模型人设都在一个单页后台中完成
- 连续对话：网页聊天和服务端会话都会持久化上下文
- 图片输入：网页上传 JPEG/PNG/WebP；API 支持 OpenAI 风格的 `image_url`
- 真人技能：可在管理端维护展示名称、简介、在线状态和技能列表
- 工具调用：接收 Chat Completions 的 `tools`，真人可以返回标准 `tool_calls`
- 快捷话术：在回答框中一键插入常用回复，不会未经确认自动发送
- 自动回复：可按关键词或每周时间段触发，支持延迟发送、启停、优先级和跨午夜时段
- 防重复回答：每个后台标签页自动接管并续租问题，其他页面暂时只读；访客断线后会提示
- 同步、异步与流式：兼容 `/v1/chat/completions`，另有适合真人延迟的任务接口
- 安全基础：API Key、管理员登录、访客会话隔离、图片类型与大小检查

## 本地启动

需要 Python 3.11 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload
```

入口：

- 访客聊天页：<http://127.0.0.1:8000/chat>
- 真人回答后台：<http://127.0.0.1:8000/admin>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

当前本地开发凭据位于 `.env`：

- 后台用户名：`admin`
- 后台密码：`iamllm-local`
- API Key：`human-local-demo-key`
- 模型名称：`iam-shaomingqing`

这些凭据只适合本机测试。部署前必须全部更换，`.env` 已被 Git 忽略。

## 最直观的体验方式

1. 同时打开访客聊天页和回答后台。
2. 在聊天页发送文字或图片。
3. 后台会自动出现新问题，不需要刷新。
4. 在同一个后台页面查看完整上下文、图片和工具，并直接回复。
5. 真人提交回答后，聊天页会自动显示回复。
6. 继续追问，后台将显示此前所有轮次。

## 回答后台的连续处理方式

- 待回答队列按先来后到排列，发送答案后会自动打开下一条，不需要反复点列表。
- 队列原本为空时，新的问题会自动接进来并聚焦回答框；也可以关闭“空闲自动接单”。
- 正在打字时，新问题只更新左侧队列并显示提醒，不会抢走当前问题或输入焦点。
- 每个问题的未发送答案都会保存在本地草稿中，切换问题或意外刷新后仍可恢复。
- 使用 `J` / `K` 可以在下一条和上一条之间移动；输入框内的快捷键仍保持正常。
- 队列清空后会显示完成状态，下一条问题到达时再继续，而不是停留在已经回答的旧问题上。
- 回答框使用聊天软件习惯：`Enter` 发送，`Shift + Enter` 换行，并兼容中文输入法的选词状态。
- 两张后台同时打开时，先进入问题的页面会获得 30 秒可续租的回答权；另一页只读，离开后可重新接管，避免两个人同时回答。
- 后台会显示访客是否仍在线；断线不影响已经送达的问题和答案保存。

## 超时兜底

同步 Chat Completions 和访客聊天默认等待真人 5 分钟。超时后会返回一条正常的助手消息，而不是让调用方一直等待或直接收到 `504`；响应中的 `human_metadata.answer_source` 会标记为 `timeout_fallback`，方便接入方识别。

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

## OpenAI 兼容调用

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

- SQLite 数据库：`data/iamllm.db`
- 访客上传图片：`data/uploads/`
- 模型和后台配置：`.env`

这些目录已从 Git 中忽略，但正式部署仍需单独备份数据库和上传文件。

## 测试

```bash
.venv/bin/pytest
```

测试覆盖鉴权、异步回答、图片输入、图片上传、工具调用、连续上下文、流式返回、后台接管互斥、在线状态、通知 Webhook、生产密钥检查、关键词自动回复和跨午夜时间规则。

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
3. 创建时填写两个不会写入 Git 的秘密变量：
   - `IAMLLM_API_KEY`：至少 24 个字符，建议用 `sk-` 加随机字符串。
   - `IAMLLM_ADMIN_PASSWORD`：至少 16 个字符。
4. 等待构建完成后访问 `/chat` 和 `/admin`；程序接入地址为 `/v1`。

免费版适合先试玩，不适合保存重要数据：实例闲置后会休眠，重新唤醒通常需要等待；免费服务不能挂载持久磁盘，因此 SQLite 会在重启、休眠恢复或重新部署时丢失，上传的图片也一样。要长期使用当前架构，应升级到可挂载磁盘的付费实例；或者后续把 SQLite 和上传目录分别迁移到托管数据库与对象存储。

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

单机内测继续使用 SQLite 即可。只有需要多实例部署时，再迁移到 PostgreSQL 和对象存储。
