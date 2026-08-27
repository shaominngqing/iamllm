<p align="center">
  <img src="brand/logo.svg" width="560" alt="iamllm — I am the language model">
</p>

# iamllm

把自己封装成一个标准 LLM API：别人照常使用 OpenAI、Claude Code、OpenCode 或 Gemini 客户端，请求进入你的管理台，由你真人回复；你发出的每一段都会成为真实的流式 chunk。

> **I am the language model.** 我就是这个语言模型。

后端是单个 Go 二进制，网页管理台由 React 构建后嵌入其中，手机管理端使用 Flutter。默认只需要 SQLite，不依赖外部数据库、消息队列或常驻的解释器进程。

## 功能

- OpenAI Chat Completions：`/v1/chat/completions`
- OpenAI Responses：`/v1/responses`，支持流式、后台任务和前序响应
- Anthropic Messages：`/v1/messages`，可直接用于 Claude Code
- Gemini GenerateContent：`/v1beta/models/{model}:generateContent`
- 文本、图片、文件提示和 function/tool calling
- 人工逐段流式回答：Enter 发送一段，已有分段后空白 Enter 才结束
- 5 分钟默认等待、随机俏皮超时兜底、2–3 字自动回复流
- 关键词和时间段自动回复；命中后不进入人工待回答队列
- 托管 `sk-` API Key、分钟/每日/并发额度和一键撤销
- 会话摘要列表、懒加载原始上下文、受保护附件预览、工具调用表单
- SSE 实时事件、幂等 chunk、跨设备回答租约和游标分页
- 8 位一次性手机配对码、短期 access token、可轮换 refresh token
- 内置测试页 `/playground` 与 OpenAPI 契约 `/openapi.json`

## 用 Docker 自建

获取源码后，机器上只需 Docker 和 Docker Compose：

```bash
cd iamllm
cp .env.production.example .env.production
```

编辑 `.env.production`，至少替换这四项：

```bash
echo "sk-$(openssl rand -hex 32)"  # IAMLLM_API_KEY
openssl rand -hex 32  # IAMLLM_ADMIN_API_TOKEN
openssl rand -hex 32  # IAMLLM_SESSION_SECRET
openssl rand -base64 24  # IAMLLM_ADMIN_PASSWORD
```

然后启动：

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

访问 `http://服务器地址:8000/admin`。生产环境建议让 Caddy 或 Nginx 负责 HTTPS；[`deploy/Caddyfile.example`](deploy/Caddyfile.example) 是最小 Caddy 示例。

数据写入 Docker 卷 `iamllm-data` 的 `/data/iamllm.db`，容器重启或重新构建不会丢配置。不要运行 `docker compose down -v`，它会明确删除数据卷。

### 备份

```bash
docker compose exec iamllm sh -c 'sqlite3 /data/iamllm.db ".backup /data/backup.db"'
docker compose cp iamllm:/data/backup.db ./iamllm-backup.db
```

若镜像内没有 `sqlite3`，停止服务后直接备份 Docker 卷中的 `iamllm.db`、`-wal` 和 `-shm` 三个文件。单机 SQLite 只运行一个服务副本；不要让多个容器同时挂载同一数据库文件。

## 接入客户端

先在“API 密钥”页面生成一把 `sk-` 钥匙。模型名可以使用你配置的 `IAMLLM_MODEL_NAME`；服务也接受客户端传来的兼容模型名。

以下 `human.example.com` 是占位域名，请替换为自己的 HTTPS 服务地址。

### OpenAI / OpenCode

```text
Base URL: https://human.example.com/v1
API Key:  sk-...
Model:    iam-human
```

```bash
curl -N https://human.example.com/v1/chat/completions \
  -H 'Authorization: Bearer sk-...' \
  -H 'Content-Type: application/json' \
  -d '{"model":"iam-human","stream":true,"messages":[{"role":"user","content":"你好"}]}'
```

### Claude Code

```bash
export ANTHROPIC_BASE_URL=https://human.example.com
export ANTHROPIC_AUTH_TOKEN=sk-...
export ANTHROPIC_MODEL=iam-human
claude
```

不要给 `ANTHROPIC_BASE_URL` 额外追加 `/v1`；Claude Code 自己会请求 `/v1/messages`。

### Gemini

```bash
curl 'https://human.example.com/v1beta/models/iam-human:generateContent' \
  -H 'x-goog-api-key: sk-...' \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"role":"user","parts":[{"text":"你好"}]}]}'
```

完整端点与兼容行为见 [`docs/api-compatibility.md`](docs/api-compatibility.md)。

项目边界与后续计划见 [`docs/architecture.md`](docs/architecture.md) 和 [`docs/roadmap.md`](docs/roadmap.md)。

## Flutter 手机管理端

```bash
cd mobile
flutter pub get
flutter run
```

在网页“服务设置”中生成一次性配对码，然后在手机输入服务器 HTTPS 地址和 8 位配对码。凭据保存在 iOS Keychain / Android Keystore；手机不保存总管理员密钥。

移动端已包含队列、聊天/运行记录/原始上下文、受鉴权图片预览、快捷回复、工具调用、草稿保存、人工 chunk 和 SSE 断线续传。发布前仍需按自己的 Bundle ID、签名、图标和推送服务配置 iOS/Android 工程。

## 本地开发

需要 Go 1.25、Node.js 22 和 Flutter stable：

```bash
cp .env.example .env
set -a; source .env; set +a
make dev
```

常用检查：

```bash
make test
docker build -t iamllm:test .
```

目录边界：

```text
cmd/iamllm                 Go 进程入口
internal/domain            协议无关领域模型
internal/application       队列、超时、自动回复、鉴权
internal/protocol          OpenAI / Anthropic / Gemini 适配器
internal/repository        数据仓储接口
internal/repository/sqlite SQLite 实现与版本化迁移
internal/transport/httpapi HTTP、SSE、Admin API
web/                       React + TypeScript 管理台和 Playground
mobile/                    Flutter iOS / Android 管理端
```

详见 [`docs/architecture.md`](docs/architecture.md)。

## 安全说明

- 公网管理台必须使用 HTTPS。
- 环境总钥匙能力无限，只留给自己；分享时创建可限额、可撤销的托管钥匙。
- API Key 和 refresh token 只保存 HMAC 哈希，完整托管钥匙只在创建时显示一次。
- 原始上下文可能包含代码、路径和系统提示，默认不会进入队列卡片或普通聊天视图。
- `/playground` 不保存 API Key 到服务器，但会保存在当前浏览器的 `localStorage` 以便测试。

## License

MIT
