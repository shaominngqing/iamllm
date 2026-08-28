# Operations

[English](operations.md) · [简体中文](../zh-CN/operations.md)

iamllm defaults to one Go service and SQLite. Operations should keep four things reliable: HTTPS, persistence, backups, and secret management.

![Single-server iamllm deployment](../images/deployment.en.svg)

## Health and logs

```bash
curl https://llm.example.com/health
docker compose ps
docker compose logs --tail=200 iamllm
```

The container has its own health check. Inactivity does not suspend a self-hosted server; configuration and SQLite remain available while the host and container run.

## Data location

Compose uses the `iamllm-data` named volume:

```text
/data/iamllm.db
/data/iamllm.db-wal
/data/iamllm.db-shm
```

Container restart, image rebuild, and `docker compose down` preserve the volume. These commands delete data and should not be used unless deletion is intended:

```bash
docker compose down -v
docker volume rm iamllm_iamllm-data
```

The actual volume name can vary with the Compose project name; inspect it with `docker volume ls`.

## Online backup

If the image contains the SQLite CLI:

```bash
docker compose exec iamllm \
  sqlite3 /data/iamllm.db '.backup /data/iamllm-backup.db'

docker compose cp \
  iamllm:/data/iamllm-backup.db \
  ./iamllm-backup-$(date +%Y%m%d-%H%M%S).db
```

Backups contain conversations, key hashes, automation, and device records. Encrypt them and restrict access.

### Cold backup

If SQLite CLI is unavailable, stop the service before copying the database:

```bash
docker compose stop iamllm
```

Copying while the service runs requires `iamllm.db`, `iamllm.db-wal`, and `iamllm.db-shm` together; otherwise the backup may be inconsistent.

## Restore

1. Stop the service.
2. Preserve a copy of the current database.
3. Restore the backup to `/data/iamllm.db` inside the volume.
4. Ensure container user UID `10001` owns the file.
5. Start the service and test `/health`, administrator login, and conversation history.

Restore overwrites state. Never perform it without preserving the current database first.

## Upgrade

Back up, then rebuild from the new source:

```bash
docker compose build --pull iamllm
docker compose up -d iamllm
docker compose logs -f --tail=100 iamllm
```

The process initializes the database schema at startup. Released schema changes must use forward migrations and must not require manual SQL.

If health fails, preserve logs and backup, then return to the previous image. Do not repeatedly delete the data volume as a repair strategy.

## SSE and reverse proxies

Human answers may wait for minutes and every chunk should reach callers immediately. A proxy must:

- disable response buffering and caching;
- use a read timeout longer than `IAMLLM_RESPONSE_TIMEOUT_SECONDS`;
- preserve HTTP/1.1 long-lived connections;
- accept request bodies large enough for images and files.

Caddy:

```caddyfile
reverse_proxy 127.0.0.1:8000 {
    flush_interval -1
}
```

Nginx:

```nginx
proxy_http_version 1.1;
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 600s;
proxy_send_timeout 600s;
```

CDNs can impose their own duration and body limits. If a connection always closes at the same time, compare a direct reverse-proxy request with the CDN path.

## Timeouts and automatic streaming

```dotenv
IAMLLM_RESPONSE_TIMEOUT_SECONDS=300
IAMLLM_STREAM_IDLE_TIMEOUT_SECONDS=120
IAMLLM_STREAM_CHUNK_DELAY_MS=10
IAMLLM_STREAM_CHUNK_CHARS=3
```

- `RESPONSE_TIMEOUT`: total time available for an answer flow.
- `STREAM_IDLE_TIMEOUT`: maximum gap between chunks after streaming begins.
- `STREAM_CHUNK_DELAY_MS` / `CHARS`: cadence for automatic replies.

Client, proxy, and server timeouts all apply; the shortest layer wins.

## Key rotation

For a managed key, create a replacement, let callers switch, then revoke the old key.

For environment secrets:

1. generate new values and update `.env.production`;
2. recreate or restart the service;
3. verify administrator login and model calls;
4. remove old values from shell history, temporary files, and chats.

Changing the session secret signs web users out. Changing device-authentication secrets may require phone pairing again.

## Device management

The console records device name, platform, model, connection time, last activity, last operation, and token status. Revoke a lost device immediately. Device revocation and model API-key revocation are separate controls.

## Notifications

An optional self-hosted notification gateway can receive new-pending-request alerts:

```dotenv
IAMLLM_NOTIFICATION_WEBHOOK_URL=https://notify.example.com/iamllm
IAMLLM_NOTIFICATION_WEBHOOK_TIMEOUT_SECONDS=5
```

The webhook is an alert path, not an authentication channel. Do not include owner secrets or complete private context unless you explicitly trust that data boundary.

## Single-instance limit

Unsupported configurations include:

- several containers writing one SQLite file;
- SQLite on a network filesystem without reliable POSIX locking;
- replacing only the database driver and claiming horizontal scaling.

True multi-instance operation requires a PostgreSQL repository, cross-process events, and consistent answer leases. Until then, one instance with reliable backup is the supported design.

## Troubleshooting order

1. Check `/health`.
2. Inspect `docker compose logs` for configuration or database errors.
3. Call `/v1/models` with a managed key to test authentication.
4. Bypass the CDN and test SSE through the reverse proxy only.
5. Inspect the conversation run log for client-internal requests.
6. Compare client, proxy, and server timeouts.
7. Back up before any repair that writes data.
