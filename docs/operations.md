# 运维手册

iamllm 默认是单实例 Go 服务加 SQLite。运维目标不是搭建复杂集群，而是把四件事做好：HTTPS、持久化、备份和秘密值管理。

![iamllm 单机部署结构](images/deployment.svg)

## 健康检查与日志

```bash
curl https://llm.example.com/health
docker compose ps
docker compose logs --tail=200 iamllm
```

容器自身也配置了健康检查。短时间没有模型调用不会停止服务；只要服务器和容器仍在运行，后台配置和 SQLite 数据都在。

## 数据放在哪里

Compose 使用命名卷 `iamllm-data`：

```text
/data/iamllm.db
/data/iamllm.db-wal
/data/iamllm.db-shm
```

容器重启、镜像重建和 `docker compose down` 不会删除命名卷。以下命令会删除数据，除非确定不再需要，否则不要运行：

```bash
docker compose down -v
docker volume rm iamllm_iamllm-data
```

具体卷名可能因 Compose 项目名而不同，可以用 `docker volume ls` 确认。

## 在线备份

镜像内包含 SQLite CLI 时，使用 SQLite 的在线备份命令：

```bash
docker compose exec iamllm \
  sqlite3 /data/iamllm.db '.backup /data/iamllm-backup.db'

docker compose cp \
  iamllm:/data/iamllm-backup.db \
  ./iamllm-backup-$(date +%Y%m%d-%H%M%S).db
```

备份文件包含会话、API Key 哈希、自动回复和设备记录，应加密存放并限制访问。

### 冷备份

如果运行镜像没有 SQLite CLI，先停止服务，再复制数据库文件：

```bash
docker compose stop iamllm
```

停止后复制 `iamllm.db`。如果不停服务而直接复制，必须同时保存 `iamllm.db`、`iamllm.db-wal` 和 `iamllm.db-shm`，否则备份可能不一致。

## 恢复

1. 停止服务；
2. 先保留当前数据库副本；
3. 把备份恢复为卷内 `/data/iamllm.db`；
4. 确认文件归容器用户 UID `10001` 所有；
5. 启动服务并检查 `/health`、管理员登录和历史会话。

恢复属于覆盖性操作，不要在没有当前备份的情况下直接执行。

## 升级

升级前先备份，然后获取新源码并重建：

```bash
docker compose build --pull iamllm
docker compose up -d iamllm
docker compose logs -f --tail=100 iamllm
```

数据库 schema 会在进程启动时初始化。正式发布后的结构变更应只增加向前迁移，不要求用户手工执行 SQL。

若健康检查失败，保留日志和备份，先回到上一版本镜像；不要反复删除数据卷尝试修复。

## SSE 与反向代理

人工回答可能等待数分钟，并且每个 chunk 应立即到达调用方。代理至少需要：

- 禁用响应缓冲；
- 读取超时大于 `IAMLLM_RESPONSE_TIMEOUT_SECONDS`；
- 不缓存模型 API 和 Admin SSE；
- 保持 HTTP/1.1 长连接；
- 允许请求正文容纳图片或文件。

Caddy：

```caddyfile
reverse_proxy 127.0.0.1:8000 {
    flush_interval -1
}
```

Nginx：

```nginx
proxy_http_version 1.1;
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 600s;
proxy_send_timeout 600s;
```

Cloudflare 或其他 CDN 也可能施加请求时长和正文大小限制。出现固定秒数断开时，应先对比直连反向代理与经过 CDN 的结果。

## 超时配置

```dotenv
IAMLLM_RESPONSE_TIMEOUT_SECONDS=300
IAMLLM_STREAM_IDLE_TIMEOUT_SECONDS=120
IAMLLM_STREAM_CHUNK_DELAY_MS=10
IAMLLM_STREAM_CHUNK_CHARS=3
```

- `RESPONSE_TIMEOUT`：等待首个完整回答流程的总时长；
- `STREAM_IDLE_TIMEOUT`：已经开始流式回答后，两个 chunk 之间允许的最长空闲；
- `STREAM_CHUNK_DELAY_MS` / `CHARS`：自动回复模拟流式输出的节奏。

客户端、代理和 iamllm 都可能有超时，最终生效的是最短的一层。

## 密钥轮换

### 托管 API Key

在“API 密钥”创建新 Key，让调用方完成切换后再撤销旧 Key。不要先撤销唯一可用的 Key。

### 环境总钥匙与管理员秘密

1. 生成新值并更新 `.env.production`；
2. 重建或重启服务；
3. 验证管理员登录和模型调用；
4. 删除终端历史、临时文件和聊天中泄露的旧值。

修改 session secret 会使现有网页 session 失效；修改设备鉴权相关秘密可能要求手机重新配对，这是正常现象。

## 设备管理

后台会记录设备名称、平台、设备型号、连接时间、最近活跃时间、最近使用和 token 状态。丢失手机后应立即在“服务与设备”撤销对应设备。

撤销后台设备不会撤销模型 API Key；两类凭据应分别管理。

## 通知

设置 `IAMLLM_NOTIFICATION_WEBHOOK_URL` 后，新待回答请求可以触发自建通知网关：

```dotenv
IAMLLM_NOTIFICATION_WEBHOOK_URL=https://notify.example.com/iamllm
IAMLLM_NOTIFICATION_WEBHOOK_TIMEOUT_SECONDS=5
```

Webhook 只应用于提醒，不应携带环境总钥匙。公网通知服务也不应收到完整私密上下文，除非部署者明确接受这种数据边界。

## 单实例限制

当前 SQLite 架构只支持一个 iamllm 服务实例写入数据库。以下做法不受支持：

- 多个容器同时挂载同一个 SQLite 文件；
- 把 SQLite 文件放在不保证 POSIX 锁语义的网络盘；
- 只复制数据库驱动，就宣称服务可以水平扩容。

真正的多实例需要 PostgreSQL 仓储、跨进程事件总线和一致的回答租约。在这些能力完成前，使用单实例加可靠备份最稳妥。

## 故障排查顺序

1. `curl /health` 检查服务是否存活；
2. `docker compose logs` 检查配置和数据库错误；
3. 用托管 Key 调用 `/v1/models` 检查鉴权；
4. 绕过 CDN，只经过反向代理测试 SSE；
5. 查看后台“运行记录”，确认请求是否是客户端内部任务；
6. 检查客户端、代理和服务三层超时；
7. 在任何修复性写操作前先备份数据库。
