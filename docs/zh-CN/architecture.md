# 架构

[English](../en/architecture.md) · [简体中文](architecture.md)

iamllm 是单服务、客户端分离的自托管应用。Go 服务拥有全部业务状态；React 和 Flutter 只通过版本化 HTTP 契约访问它。

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

## 为什么使用 Go + SQLite

- Go 可以编译成单二进制，协议流和长连接不依赖解释器进程，适合别人拿 Docker 直接部署。
- SQLite WAL 对“一位真人模型、一个服务实例”的写入规模足够，并让备份和迁移保持简单。
- React 管理台编译成静态资源后嵌入 Go，不需要单独部署前端。
- Flutter 共用一套 iOS/Android 代码，通过 Admin API 工作，不直连数据库。

仓储层用接口隔离，未来若需要真正的多实例水平扩容，可以增加 PostgreSQL 实现；在那之前不为单人项目引入外部数据库服务、消息队列和分布式锁。

## 领域与状态

所有厂商请求先归一化为 `domain.RequestInput`，再创建 `HumanRequest`。协议适配层不能自己实现等待、超时或自动回复。

请求状态只有：

- `pending`：客户端仍在等待或后台任务尚未回答。
- `answered`：文字或工具调用已完成。
- `expired`：异步任务过期且没有可返回内容。

人工 chunk 带调用端生成的 `chunk_id`。数据库对 `(request_id, chunk_id)` 建唯一索引，因此网络重试不会重复写入。首个 chunk 会获取 30 秒回答租约，后续 chunk 自动续租，降低网页和手机同时回答的风险。

## 大上下文性能

队列列表只查询摘要列，不读取 `messages_json` 或 `tools_json`。请求详情也只返回：

- 清理掉系统块后的用户可见聊天；
- 工具名称、简短说明和参数数量；
- 附件的受保护读取地址。

完整 system prompt、工具 schema 和原始消息只有打开“原始上下文”时才读取，并支持 gzip。这避免 Codex/Claude Code 数十万字符的内部提示阻塞列表渲染。

## 实时与恢复

- 模型输出使用各厂商原生 SSE 事件。
- 管理端事件使用 `/admin/api/v1/events`，事件 ID 单调递增。
- Web 与 Flutter 在断线后使用 `Last-Event-ID` 续传，同时保留低频轮询兜底。
- 队列使用稳定游标分页，不使用会在并发插入时漂移的 offset。
- 管理回复 chunk 幂等；草稿和已读状态由服务器统一保存，Web 与 Flutter 可无缝接力。

## 身份与密钥

- 模型 API：环境总钥匙或托管 `sk-` API Key。
- 网页首次登录：管理员用户名和密码。
- 手机首次登录：网页生成包含实例地址与 8 位一次性码的二维码；配对码 10 分钟有效且仅可使用一次。
- 设备 access token 15 分钟过期；refresh token 每次刷新都会轮换，可按设备撤销。
- 托管 Key 与 refresh token 只存 HMAC-SHA256，不存可还原明文。

## 数据演进

SQLite schema 嵌入二进制并在启动时串行初始化。当前项目只包含一份最新基线 schema；版本正式发布后再从该基线追加向前迁移。

当前部署模型明确为单实例。要增加 PostgreSQL 时，应为 SQLite 和 PostgreSQL 运行同一组仓储契约测试，并在提供多实例前加入跨进程事件总线和租约一致性，不能只替换 SQL 驱动就宣称支持水平扩容。
