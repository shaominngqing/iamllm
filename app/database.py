from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _now_ms() -> int:
    return int(time.time() * 1000)


class Database:
    def __init__(self, path: Path, *, timezone_name: str = "Asia/Shanghai"):
        self.path = path
        self.timezone_name = timezone_name
        self.timezone = ZoneInfo(timezone_name)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS human_requests (
                    id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    preview TEXT NOT NULL DEFAULT '',
                    context_chars INTEGER NOT NULL DEFAULT 0,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    system_count INTEGER NOT NULL DEFAULT 0,
                    tool_count INTEGER NOT NULL DEFAULT 0,
                    attachment_count INTEGER NOT NULL DEFAULT 0,
                    request_kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'answered', 'expired')
                    ),
                    answer TEXT,
                    mode TEXT NOT NULL CHECK (mode IN ('sync', 'async')),
                    created_at INTEGER NOT NULL,
                    answered_at INTEGER,
                    expires_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_human_requests_status_created
                ON human_requests(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS human_stream_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(request_id, position),
                    FOREIGN KEY (request_id) REFERENCES human_requests(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_human_stream_chunks_request
                ON human_stream_chunks(request_id, position);

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    owner_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT,
                    tool_call_id TEXT,
                    tool_calls_json TEXT,
                    request_id TEXT UNIQUE,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
                ON conversation_messages(conversation_id, created_at, id);

                CREATE TABLE IF NOT EXISTS model_profile (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    display_name TEXT NOT NULL,
                    bio TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quick_replies (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auto_reply_rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    rule_type TEXT NOT NULL CHECK (rule_type IN ('keyword', 'schedule')),
                    match_type TEXT CHECK (match_type IN ('contains', 'exact') OR match_type IS NULL),
                    pattern TEXT,
                    response_text TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    days_json TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
                    delay_seconds INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_hint TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1,
                    rate_limit_per_minute INTEGER NOT NULL DEFAULT 10,
                    daily_limit INTEGER NOT NULL DEFAULT 100,
                    max_concurrent INTEGER NOT NULL DEFAULT 3,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_used_at INTEGER,
                    revoked_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_api_keys_active
                ON api_keys(active, created_at DESC);

                CREATE TABLE IF NOT EXISTS api_key_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_key_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_api_key_calls_window
                ON api_key_calls(api_key_id, created_at);

                INSERT OR IGNORE INTO app_meta(key, value)
                VALUES ('queue_version', 1);
                """
            )
            self._ensure_column(
                connection, "human_requests", "conversation_id", "TEXT"
            )
            self._ensure_column(
                connection,
                "human_requests",
                "tools_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection, "human_requests", "response_json", "TEXT"
            )
            self._ensure_column(
                connection,
                "human_requests",
                "source",
                "TEXT NOT NULL DEFAULT 'api'",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "updated_at",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection, "human_requests", "auto_reply_rule_id", "TEXT"
            )
            self._ensure_column(
                connection, "human_requests", "auto_reply_due_at", "INTEGER"
            )
            self._ensure_column(
                connection, "human_requests", "auto_reply_label", "TEXT"
            )
            self._ensure_column(
                connection, "human_requests", "auto_reply_text", "TEXT"
            )
            self._ensure_column(
                connection, "human_requests", "answer_source", "TEXT"
            )
            self._ensure_column(
                connection,
                "human_requests",
                "stream_requested",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "stream_chunk_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection, "human_requests", "claim_owner", "TEXT"
            )
            self._ensure_column(
                connection, "human_requests", "claim_expires_at", "INTEGER"
            )
            self._ensure_column(
                connection, "human_requests", "client_last_seen_at", "INTEGER"
            )
            self._ensure_column(
                connection, "human_requests", "api_key_id", "TEXT"
            )
            self._ensure_column(
                connection,
                "human_requests",
                "preview",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "context_chars",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "message_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "system_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "tool_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "attachment_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "human_requests",
                "request_kind",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._backfill_request_summaries(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_human_requests_api_key_status
                ON human_requests(api_key_id, status)
                """
            )
            self._seed_control_center(connection)
            connection.execute("PRAGMA optimize")

    @staticmethod
    def _seed_control_center(connection: sqlite3.Connection) -> None:
        now = _now_ms()
        quick_replies = [
            (
                "quick_brain_boot",
                "脑子开机中",
                "收到，脑子正在开机。这次不是延迟，是人类特性。",
                "缓一缓",
            ),
            (
                "quick_think_seriously",
                "容我认真想想",
                "这个问题值得我认真想一下，先别催，人脑没有进度条。",
                "缓一缓",
            ),
            (
                "quick_need_context",
                "再给点上下文",
                "我大概懂了，但还差一点上下文。你再多说两句，我争取不像算命。",
                "追问",
            ),
            (
                "quick_honest_no",
                "诚实地不会",
                "这个我真不会。作为真人模型，我决定保留诚实这个稀缺功能。",
                "诚实模式",
            ),
        ]
        connection.executemany(
            """
            INSERT OR IGNORE INTO quick_replies (
                id, title, content, category, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            [(*reply, now, now) for reply in quick_replies],
        )
        auto_rules = [
            (
                "rule_are_you_ai",
                "身份核验专线",
                "keyword",
                "exact",
                "你是AI吗",
                "不是。我回复慢，是因为我真的要打字。",
                None,
                None,
                "[0,1,2,3,4,5,6]",
                3,
                100,
            ),
            (
                "rule_are_you_there",
                "在吗探测器",
                "keyword",
                "contains",
                "在吗",
                "在，但灵魂可能还要几分钟才能上线。",
                None,
                None,
                "[0,1,2,3,4,5,6]",
                5,
                80,
            ),
            (
                "rule_sleeping",
                "睡眠模式",
                "schedule",
                None,
                None,
                "本模型正在充电（睡觉）。消息已收到，醒来后由本人继续处理。",
                "00:00",
                "08:30",
                "[0,1,2,3,4,5,6]",
                8,
                20,
            ),
        ]
        connection.executemany(
            """
            INSERT OR IGNORE INTO auto_reply_rules (
                id, name, rule_type, match_type, pattern, response_text,
                start_time, end_time, days_json, delay_seconds, priority,
                active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            [(*rule, now, now) for rule in auto_rules],
        )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @classmethod
    def _backfill_request_summaries(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT id, messages_json, tools_json
            FROM human_requests
            WHERE preview = '' OR context_chars = 0 OR request_kind = ''
            """
        ).fetchall()
        for row in rows:
            messages = json.loads(row["messages_json"] or "[]")
            tools = json.loads(row["tools_json"] or "[]")
            summary = cls._request_summary(messages, tools)
            connection.execute(
                """
                UPDATE human_requests
                SET preview = ?, context_chars = ?, message_count = ?,
                    system_count = ?, tool_count = ?, attachment_count = ?,
                    request_kind = ?
                WHERE id = ?
                """,
                (
                    summary["preview"],
                    summary["context_chars"],
                    summary["message_count"],
                    summary["system_count"],
                    summary["tool_count"],
                    summary["attachment_count"],
                    summary["request_kind"],
                    row["id"],
                ),
            )

    @staticmethod
    def _bump_queue_version(connection: sqlite3.Connection) -> None:
        connection.execute(
            "UPDATE app_meta SET value = value + 1 WHERE key = 'queue_version'"
        )

    def queue_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_meta WHERE key = 'queue_version'"
            ).fetchone()
        return int(row["value"])

    def _api_key_usage_windows(self, now_ms: int) -> tuple[int, int]:
        local_now = datetime.fromtimestamp(now_ms / 1000, self.timezone)
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return now_ms - 60_000, int(midnight.timestamp() * 1000)

    def create_api_key(
        self,
        *,
        key_id: str,
        name: str,
        key_hint: str,
        key_hash: str,
        rate_limit_per_minute: int,
        daily_limit: int,
        max_concurrent: int,
    ) -> dict[str, Any]:
        now = _now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO api_keys (
                    id, name, key_hint, key_hash, active,
                    rate_limit_per_minute, daily_limit, max_concurrent,
                    request_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, 0, ?, ?)
                """,
                (
                    key_id,
                    name,
                    key_hint,
                    key_hash,
                    rate_limit_per_minute,
                    daily_limit,
                    max_concurrent,
                    now,
                    now,
                ),
            )
        result = self.get_api_key(key_id)
        assert result is not None
        return result

    def get_api_key(self, key_id: str) -> dict[str, Any] | None:
        now = _now_ms()
        minute_start, day_start = self._api_key_usage_windows(now)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT key_row.*,
                    (SELECT COUNT(*) FROM api_key_calls calls
                     WHERE calls.api_key_id = key_row.id
                       AND calls.created_at >= ?) AS usage_minute,
                    (SELECT COUNT(*) FROM api_key_calls calls
                     WHERE calls.api_key_id = key_row.id
                       AND calls.created_at >= ?) AS usage_today,
                    (SELECT COUNT(*) FROM human_requests requests
                     WHERE requests.api_key_id = key_row.id
                       AND requests.status = 'pending') AS pending_requests
                FROM api_keys key_row WHERE key_row.id = ?
                """,
                (minute_start, day_start, key_id),
            ).fetchone()
        return self._deserialize_api_key(row) if row else None

    def list_api_keys(self) -> list[dict[str, Any]]:
        now = _now_ms()
        minute_start, day_start = self._api_key_usage_windows(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key_row.*,
                    (SELECT COUNT(*) FROM api_key_calls calls
                     WHERE calls.api_key_id = key_row.id
                       AND calls.created_at >= ?) AS usage_minute,
                    (SELECT COUNT(*) FROM api_key_calls calls
                     WHERE calls.api_key_id = key_row.id
                       AND calls.created_at >= ?) AS usage_today,
                    (SELECT COUNT(*) FROM human_requests requests
                     WHERE requests.api_key_id = key_row.id
                       AND requests.status = 'pending') AS pending_requests
                FROM api_keys key_row
                ORDER BY key_row.revoked_at IS NOT NULL,
                    key_row.active DESC, key_row.created_at DESC
                """,
                (minute_start, day_start),
            ).fetchall()
        return [self._deserialize_api_key(row) for row in rows]

    def update_api_key(
        self, key_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "active",
            "rate_limit_per_minute",
            "daily_limit",
            "max_concurrent",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        existing = self.get_api_key(key_id)
        if not existing:
            return None
        if existing["revoked"]:
            return existing
        if not updates:
            return existing
        if "active" in updates:
            updates["active"] = int(bool(updates["active"]))
        updates["updated_at"] = _now_ms()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE api_keys SET {assignment} WHERE id = ?",
                (*updates.values(), key_id),
            )
        return self.get_api_key(key_id)

    def revoke_api_key(self, key_id: str) -> dict[str, Any] | None:
        now = _now_ms()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE api_keys
                SET active = 0, revoked_at = ?, updated_at = ?
                WHERE id = ? AND revoked_at IS NULL
                """,
                (now, now, key_id),
            )
        if not cursor.rowcount and not self.get_api_key(key_id):
            return None
        return self.get_api_key(key_id)

    def authorize_api_key_hash(
        self, key_hash: str, *, count_usage: bool
    ) -> dict[str, Any]:
        now = _now_ms()
        minute_start, day_start = self._api_key_usage_windows(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if not row or not row["active"] or row["revoked_at"] is not None:
                return {"status": "invalid"}

            connection.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            if not count_usage:
                return {"status": "allowed", "api_key_id": str(row["id"])}

            usage_minute = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM api_key_calls
                    WHERE api_key_id = ? AND created_at >= ?
                    """,
                    (row["id"], minute_start),
                ).fetchone()["count"]
            )
            usage_today = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM api_key_calls
                    WHERE api_key_id = ? AND created_at >= ?
                    """,
                    (row["id"], day_start),
                ).fetchone()["count"]
            )
            pending = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM human_requests
                    WHERE api_key_id = ? AND status = 'pending'
                    """,
                    (row["id"],),
                ).fetchone()["count"]
            )
            if usage_minute >= int(row["rate_limit_per_minute"]):
                oldest = connection.execute(
                    """
                    SELECT MIN(created_at) AS created_at FROM api_key_calls
                    WHERE api_key_id = ? AND created_at >= ?
                    """,
                    (row["id"], minute_start),
                ).fetchone()["created_at"]
                retry_after = max(1, int((int(oldest or now) + 60_000 - now + 999) / 1000))
                return {
                    "status": "limited",
                    "reason": "minute",
                    "retry_after": retry_after,
                    "limit": int(row["rate_limit_per_minute"]),
                }
            if usage_today >= int(row["daily_limit"]):
                local_now = datetime.fromtimestamp(now / 1000, self.timezone)
                next_midnight = (local_now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                retry_after = max(
                    1,
                    int((next_midnight.timestamp() * 1000 - now + 999) / 1000),
                )
                return {
                    "status": "limited",
                    "reason": "daily",
                    "retry_after": retry_after,
                    "limit": int(row["daily_limit"]),
                }
            if pending >= int(row["max_concurrent"]):
                return {
                    "status": "limited",
                    "reason": "concurrent",
                    "retry_after": 5,
                    "limit": int(row["max_concurrent"]),
                }

            connection.execute(
                "INSERT INTO api_key_calls(api_key_id, created_at) VALUES (?, ?)",
                (row["id"], now),
            )
            connection.execute(
                """
                UPDATE api_keys
                SET request_count = request_count + 1, last_used_at = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
            connection.execute(
                "DELETE FROM api_key_calls WHERE created_at < ?",
                (day_start - 86_400_000,),
            )
            return {"status": "allowed", "api_key_id": str(row["id"])}

    def ensure_profile(self, *, display_name: str) -> None:
        now = _now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO model_profile (
                    singleton_id, display_name, bio, availability,
                    skills_json, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?)
                """,
                (
                    display_name,
                    "每一个回答都由真人阅读上下文后亲自完成。",
                    "本地体验中 · 回复速度取决于本人是否在线",
                    json.dumps(
                        ["个人经验与判断", "创意讨论", "认真倾听", "图片理解"],
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )

    def get_profile(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_profile WHERE singleton_id = 1"
            ).fetchone()
        if not row:
            raise RuntimeError("Model profile has not been initialized")
        result = dict(row)
        result["skills"] = json.loads(result.pop("skills_json"))
        return result

    def update_profile(
        self,
        *,
        display_name: str,
        bio: str,
        availability: str,
        skills: list[str],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE model_profile
                SET display_name = ?, bio = ?, availability = ?,
                    skills_json = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (
                    display_name,
                    bio,
                    availability,
                    json.dumps(skills, ensure_ascii=False),
                    _now_ms(),
                ),
            )
            self._bump_queue_version(connection)

    def list_quick_replies(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM quick_replies"
        if not include_inactive:
            query += " WHERE active = 1"
        query += " ORDER BY active DESC, category, created_at"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._deserialize_quick_reply(row) for row in rows]

    def create_quick_reply(
        self, *, title: str, content: str, category: str, active: bool = True
    ) -> dict[str, Any]:
        reply_id = f"quick_{uuid.uuid4().hex[:16]}"
        now = _now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quick_replies (
                    id, title, content, category, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (reply_id, title, content, category, int(active), now, now),
            )
            self._bump_queue_version(connection)
        return self.get_quick_reply(reply_id)

    def get_quick_reply(self, reply_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM quick_replies WHERE id = ?", (reply_id,)
            ).fetchone()
        if not row:
            raise KeyError(reply_id)
        return self._deserialize_quick_reply(row)

    def update_quick_reply(self, reply_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "content", "category", "active"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            try:
                return self.get_quick_reply(reply_id)
            except KeyError:
                return None
        if "active" in updates:
            updates["active"] = int(bool(updates["active"]))
        updates["updated_at"] = _now_ms()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE quick_replies SET {assignment} WHERE id = ?",
                (*updates.values(), reply_id),
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        if not cursor.rowcount:
            return None
        return self.get_quick_reply(reply_id)

    def delete_quick_reply(self, reply_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM quick_replies WHERE id = ?", (reply_id,)
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        return bool(cursor.rowcount)

    def list_auto_reply_rules(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM auto_reply_rules
                ORDER BY active DESC,
                    CASE rule_type WHEN 'keyword' THEN 0 ELSE 1 END,
                    priority DESC, created_at
                """
            ).fetchall()
        return [self._deserialize_auto_rule(row) for row in rows]

    def get_auto_reply_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auto_reply_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return self._deserialize_auto_rule(row) if row else None

    def create_auto_reply_rule(self, values: dict[str, Any]) -> dict[str, Any]:
        rule_id = f"rule_{uuid.uuid4().hex[:16]}"
        now = _now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auto_reply_rules (
                    id, name, rule_type, match_type, pattern, response_text,
                    start_time, end_time, days_json, delay_seconds, priority,
                    active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    values["name"],
                    values["rule_type"],
                    values.get("match_type"),
                    values.get("pattern"),
                    values["response_text"],
                    values.get("start_time"),
                    values.get("end_time"),
                    json.dumps(values.get("days", list(range(7)))),
                    int(values.get("delay_seconds", 0)),
                    int(values.get("priority", 0)),
                    int(bool(values.get("active", False))),
                    now,
                    now,
                ),
            )
            self._bump_queue_version(connection)
        result = self.get_auto_reply_rule(rule_id)
        assert result is not None
        return result

    def update_auto_reply_rule(
        self, rule_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name", "rule_type", "match_type", "pattern", "response_text",
            "start_time", "end_time", "delay_seconds", "priority", "active",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if "days" in values:
            updates["days_json"] = json.dumps(values["days"])
        if "active" in updates:
            updates["active"] = int(bool(updates["active"]))
        updates["updated_at"] = _now_ms()
        assignment = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE auto_reply_rules SET {assignment} WHERE id = ?",
                (*updates.values(), rule_id),
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        if not cursor.rowcount:
            return None
        return self.get_auto_reply_rule(rule_id)

    def delete_auto_reply_rule(self, rule_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM auto_reply_rules WHERE id = ?", (rule_id,)
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        return bool(cursor.rowcount)

    def resolve_auto_reply(
        self, messages: list[dict[str, Any]], *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        moment = now or datetime.now(self.timezone)
        latest_text = self._latest_user_text(messages)
        for rule in self.list_auto_reply_rules():
            if not rule["active"]:
                continue
            if rule["rule_type"] == "keyword":
                pattern = (rule.get("pattern") or "").strip()
                if not pattern or not latest_text:
                    continue
                if rule["match_type"] == "exact":
                    matched = latest_text.casefold().strip() == pattern.casefold()
                else:
                    matched = pattern.casefold() in latest_text.casefold()
                if matched:
                    return rule
                continue
            if moment.weekday() not in rule["days"]:
                continue
            current = moment.strftime("%H:%M")
            start = rule.get("start_time") or "00:00"
            end = rule.get("end_time") or "23:59"
            in_window = start <= current < end if start <= end else current >= start or current < end
            if in_window:
                return rule
        return None

    def process_due_auto_replies(self) -> int:
        now = _now_ms()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, auto_reply_text FROM human_requests
                WHERE status = 'pending' AND auto_reply_due_at IS NOT NULL
                    AND auto_reply_due_at <= ?
                ORDER BY auto_reply_due_at LIMIT 50
                """,
                (now,),
            ).fetchall()
        answered = 0
        for row in rows:
            if self.answer_request(
                str(row["id"]),
                {"role": "assistant", "content": str(row["auto_reply_text"])},
                f"msg_auto_{uuid.uuid4().hex[:16]}",
                answer_source="automation",
            ):
                answered += 1
        return answered

    def overview(self) -> dict[str, Any]:
        local_now = datetime.now(self.timezone)
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = int(midnight.timestamp())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'answered' AND answered_at >= ? THEN 1 ELSE 0 END) AS answered_today,
                    SUM(CASE WHEN answer_source = 'automation' AND answered_at >= ? THEN 1 ELSE 0 END) AS automated_today,
                    AVG(CASE WHEN status = 'answered' AND answered_at >= ? THEN answered_at - created_at END) AS avg_seconds
                FROM human_requests
                """,
                (today_start, today_start, today_start),
            ).fetchone()
            conversations = connection.execute(
                "SELECT COUNT(*) AS count FROM conversations"
            ).fetchone()
            active_rules = connection.execute(
                "SELECT COUNT(*) AS count FROM auto_reply_rules WHERE active = 1"
            ).fetchone()
        return {
            "pending": int(row["pending"] or 0),
            "answered_today": int(row["answered_today"] or 0),
            "automated_today": int(row["automated_today"] or 0),
            "avg_response_seconds": round(float(row["avg_seconds"] or 0)),
            "conversations": int(conversations["count"]),
            "active_rules": int(active_rules["count"]),
            "queue_version": self.queue_version(),
        }

    def create_conversation(
        self, *, conversation_id: str, owner_token: str, title: str = "新对话"
    ) -> dict[str, Any]:
        now = _now_ms()
        owner_hash = hashlib.sha256(owner_token.encode()).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (
                    id, owner_hash, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, owner_hash, title, now, now),
            )
        result = self.get_conversation(conversation_id, owner_token=owner_token)
        assert result is not None
        return result

    def get_conversation(
        self, conversation_id: str, *, owner_token: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not row:
                return None
            if owner_token is not None:
                owner_hash = hashlib.sha256(owner_token.encode()).hexdigest()
                if not hmac_compare(str(row["owner_hash"]), owner_hash):
                    return None
            message_rows = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at, rowid
                """,
                (conversation_id,),
            ).fetchall()
            latest_request = connection.execute(
                """
                SELECT * FROM human_requests
                WHERE conversation_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        result = dict(row)
        result["messages"] = [
            self._deserialize_conversation_message(message) for message in message_rows
        ]
        result["latest_request"] = (
            self._deserialize_request(latest_request) if latest_request else None
        )
        return result

    def add_conversation_message(
        self,
        *,
        message_id: str,
        conversation_id: str,
        role: str,
        content: Any,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        request_id: str | None = None,
    ) -> None:
        now = _now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages (
                    id, conversation_id, role, content_json, tool_call_id,
                    tool_calls_json, request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    json.dumps(content, ensure_ascii=False),
                    tool_call_id,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    request_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

    def rename_conversation_if_new(self, conversation_id: str, title: str) -> None:
        clean_title = " ".join(title.split()).strip()[:42] or "图片对话"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE conversations SET title = ?
                WHERE id = ? AND title = '新对话'
                """,
                (clean_title, conversation_id),
            )

    def conversation_messages_for_api(
        self, conversation_id: str
    ) -> list[dict[str, Any]]:
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return []
        messages: list[dict[str, Any]] = []
        for stored in conversation["messages"]:
            message: dict[str, Any] = {
                "role": stored["role"],
                "content": stored["content"],
            }
            if stored.get("tool_call_id"):
                message["tool_call_id"] = stored["tool_call_id"]
            if stored.get("tool_calls"):
                message["tool_calls"] = stored["tool_calls"]
            messages.append(message)
        return messages

    def conversation_has_pending(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM human_requests
                WHERE conversation_id = ? AND status = 'pending'
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return row is not None

    def create_request(
        self,
        *,
        request_id: str,
        model: str,
        messages: list[dict[str, Any]],
        mode: str,
        expires_at: int,
        conversation_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        source: str = "api",
        stream_requested: bool = False,
        api_key_id: str | None = None,
    ) -> dict[str, Any]:
        now_seconds = int(time.time())
        now = _now_ms()
        tools = tools or []
        messages_json = json.dumps(messages, ensure_ascii=False)
        tools_json = json.dumps(tools, ensure_ascii=False)
        summary = self._request_summary(messages, tools)
        auto_rule = self.resolve_auto_reply(messages)
        auto_due_at = (
            now + int(auto_rule["delay_seconds"]) * 1000 if auto_rule else None
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO human_requests (
                    id, model, messages_json, preview, context_chars,
                    message_count, system_count, tool_count, attachment_count,
                    request_kind,
                    status, answer, mode,
                    created_at, answered_at, expires_at, conversation_id,
                    tools_json, response_json, source, updated_at,
                    auto_reply_rule_id, auto_reply_due_at, auto_reply_label,
                    auto_reply_text, answer_source, stream_requested,
                    stream_chunk_count, api_key_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    model,
                    messages_json,
                    summary["preview"],
                    summary["context_chars"],
                    summary["message_count"],
                    summary["system_count"],
                    summary["tool_count"],
                    summary["attachment_count"],
                    summary["request_kind"],
                    "pending",
                    None,
                    mode,
                    now_seconds,
                    None,
                    expires_at,
                    conversation_id,
                    tools_json,
                    None,
                    source,
                    now,
                    auto_rule["id"] if auto_rule else None,
                    auto_due_at,
                    auto_rule["name"] if auto_rule else None,
                    auto_rule["response_text"] if auto_rule else None,
                    None,
                    int(stream_requested),
                    0,
                    api_key_id,
                ),
            )
            self._bump_queue_version(connection)
        result = self.get_request(request_id)
        assert result is not None
        return result

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM human_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._deserialize_request(row) if row else None

    def get_request_state(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, status, stream_requested, stream_chunk_count,
                       answered_at, answer_source,
                       claim_owner, claim_expires_at, client_last_seen_at
                FROM human_requests WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["stream_requested"] = bool(result.get("stream_requested", 0))
        now = _now_ms()
        result["claim_active"] = bool(
            result.get("claim_owner")
            and int(result.get("claim_expires_at") or 0) > now
        )
        result["client_connected"] = bool(
            result.get("client_last_seen_at")
            and int(result["client_last_seen_at"]) >= now - 6_000
        )
        return result

    def claim_request(
        self, request_id: str, owner_id: str, *, lease_seconds: int = 30
    ) -> dict[str, Any] | None:
        now = _now_ms()
        claim_expires_at = now + lease_seconds * 1000
        changed_owner = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, claim_owner, claim_expires_at
                FROM human_requests WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if not row or row["status"] != "pending":
                return None
            current_owner = row["claim_owner"]
            current_expiry = int(row["claim_expires_at"] or 0)
            if current_owner and current_owner != owner_id and current_expiry > now:
                return None
            changed_owner = current_owner != owner_id
            connection.execute(
                """
                UPDATE human_requests
                SET claim_owner = ?, claim_expires_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (owner_id, claim_expires_at, request_id),
            )
            if changed_owner:
                self._bump_queue_version(connection)
        return {
            "id": request_id,
            "status": "pending",
            "claim_owner": owner_id,
            "claim_expires_at": claim_expires_at,
            "claim_active": True,
        }

    def release_request_claim(self, request_id: str, owner_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE human_requests
                SET claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ? AND status = 'pending' AND claim_owner = ?
                """,
                (request_id, owner_id),
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        return bool(cursor.rowcount)

    def touch_client_connection(self, request_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE human_requests SET client_last_seen_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_now_ms(), request_id),
            )

    @staticmethod
    def operator_can_write(
        row: dict[str, Any], owner_id: str | None
    ) -> bool:
        claim_owner = row.get("claim_owner")
        claim_expires_at = int(row.get("claim_expires_at") or 0)
        if not claim_owner or claim_expires_at <= _now_ms():
            return True
        return bool(owner_id and owner_id == claim_owner)

    def list_stream_chunks(
        self, request_id: str, *, after_position: int = 0
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT position, content, created_at
                FROM human_stream_chunks
                WHERE request_id = ? AND position > ?
                ORDER BY position
                """,
                (request_id, after_position),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_stream_chunk(
        self,
        request_id: str,
        content: str,
        *,
        idle_timeout_seconds: int = 120,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not content.strip():
            return None
        now = _now_ms()
        idle_expires_at = int(time.time()) + idle_timeout_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, stream_requested, stream_chunk_count,
                       claim_owner, claim_expires_at
                FROM human_requests WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if (
                not row
                or row["status"] != "pending"
                or (
                    owner_id is not None
                    and not self.operator_can_write(dict(row), owner_id)
                )
            ):
                return None
            position = int(row["stream_chunk_count"]) + 1
            connection.execute(
                """
                INSERT INTO human_stream_chunks (
                    request_id, position, content, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (request_id, position, content, now),
            )
            connection.execute(
                """
                UPDATE human_requests
                SET stream_chunk_count = ?, updated_at = ?,
                    auto_reply_due_at = NULL, expires_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (position, now, idle_expires_at, request_id),
            )
            self._bump_queue_version(connection)
        return {
            "position": position,
            "content": content,
            "created_at": now,
            "expires_at": idle_expires_at,
        }

    def finalize_stream_request(
        self,
        request_id: str,
        message_id: str,
        *,
        answer_source: str = "human_stream",
        owner_id: str | None = None,
    ) -> bool:
        now_seconds = int(time.time())
        now = _now_ms()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM human_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if (
                not row
                or row["status"] != "pending"
                or int(row["stream_chunk_count"]) < 1
                or (
                    owner_id is not None
                    and not self.operator_can_write(dict(row), owner_id)
                )
            ):
                return False
            chunks = connection.execute(
                """
                SELECT content FROM human_stream_chunks
                WHERE request_id = ? ORDER BY position
                """,
                (request_id,),
            ).fetchall()
            answer = "".join(chunk["content"] for chunk in chunks)
            response_message = {"role": "assistant", "content": answer}
            cursor = connection.execute(
                """
                UPDATE human_requests
                SET status = 'answered', answer = ?, response_json = ?,
                    answered_at = ?, updated_at = ?, answer_source = ?,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (
                    answer,
                    json.dumps(response_message, ensure_ascii=False),
                    now_seconds,
                    now,
                    answer_source,
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
            conversation_id = row["conversation_id"]
            if conversation_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO conversation_messages (
                        id, conversation_id, role, content_json, tool_call_id,
                        tool_calls_json, request_id, created_at
                    ) VALUES (?, ?, 'assistant', ?, NULL, NULL, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        json.dumps(answer, ensure_ascii=False),
                        request_id,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
            self._bump_queue_version(connection)
        return True

    def list_requests(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT * FROM human_requests
                    WHERE status = ?
                    ORDER BY created_at DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM human_requests
                    ORDER BY created_at DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._deserialize_request(row) for row in rows]

    def list_request_summaries(
        self, *, status: str | None = None, limit: int = 300
    ) -> list[dict[str, Any]]:
        columns = """
            id, model, preview, context_chars, message_count, system_count,
            tool_count, attachment_count, request_kind, status, mode,
            created_at, answered_at, expires_at,
            conversation_id, source, updated_at, auto_reply_rule_id,
            auto_reply_due_at, auto_reply_label, answer_source,
            stream_requested, stream_chunk_count, claim_owner,
            claim_expires_at, client_last_seen_at, api_key_id
        """
        with self._connect() as connection:
            if status:
                rows = connection.execute(
                    f"""
                    SELECT {columns} FROM human_requests
                    WHERE status = ?
                    ORDER BY created_at DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT {columns} FROM human_requests
                    ORDER BY
                        CASE status
                            WHEN 'pending' THEN 0
                            WHEN 'answered' THEN 1
                            ELSE 2
                        END,
                        created_at DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._deserialize_request_summary(row) for row in rows]

    def answer_request(
        self,
        request_id: str,
        response_message: dict[str, Any],
        message_id: str,
        *,
        answer_source: str = "human",
        owner_id: str | None = None,
    ) -> bool:
        now_seconds = int(time.time())
        now = _now_ms()
        answer = response_message.get("content")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM human_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if (
                not row
                or row["status"] != "pending"
                or (
                    owner_id is not None
                    and not self.operator_can_write(dict(row), owner_id)
                )
            ):
                return False
            cursor = connection.execute(
                """
                UPDATE human_requests
                SET status = 'answered', answer = ?, response_json = ?,
                    answered_at = ?, updated_at = ?, answer_source = ?,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (
                    answer,
                    json.dumps(response_message, ensure_ascii=False),
                    now_seconds,
                    now,
                    answer_source,
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
            conversation_id = row["conversation_id"]
            if conversation_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO conversation_messages (
                        id, conversation_id, role, content_json, tool_call_id,
                        tool_calls_json, request_id, created_at
                    ) VALUES (?, ?, 'assistant', ?, NULL, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        json.dumps(response_message.get("content"), ensure_ascii=False),
                        json.dumps(
                            response_message.get("tool_calls"), ensure_ascii=False
                        )
                        if response_message.get("tool_calls")
                        else None,
                        request_id,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
            self._bump_queue_version(connection)
        return True

    def expire_request(self, request_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE human_requests
                SET status = 'expired', updated_at = ?,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (_now_ms(), request_id),
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)

    def expire_due_requests(self) -> int:
        now_seconds = int(time.time())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE human_requests
                SET status = 'expired', updated_at = ?,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (_now_ms(), now_seconds),
            )
            if cursor.rowcount:
                self._bump_queue_version(connection)
        return cursor.rowcount

    def settle_due_requests(self, timeout_fallback_text: str) -> int:
        """Settle due asynchronous requests without racing synchronous callers.

        Public chat gets a visible assistant response, API async jobs expire, and
        synchronous requests are left to their waiting HTTP handler so it can
        return either the human answer or the configured fallback atomically.
        """
        now_seconds = int(time.time())
        now = _now_ms()
        settled = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, conversation_id, source, mode, stream_chunk_count
                FROM human_requests
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (now_seconds,),
            ).fetchall()
            for row in rows:
                if int(row["stream_chunk_count"]):
                    chunks = connection.execute(
                        """
                        SELECT content FROM human_stream_chunks
                        WHERE request_id = ? ORDER BY position
                        """,
                        (row["id"],),
                    ).fetchall()
                    answer = "".join(chunk["content"] for chunk in chunks)
                    response = {"role": "assistant", "content": answer}
                    cursor = connection.execute(
                        """
                        UPDATE human_requests
                        SET status = 'answered', answer = ?, response_json = ?,
                            answered_at = ?, updated_at = ?,
                            answer_source = 'human_timeout_partial',
                            claim_owner = NULL, claim_expires_at = NULL
                        WHERE id = ? AND status = 'pending'
                        """,
                        (
                            answer,
                            json.dumps(response, ensure_ascii=False),
                            now_seconds,
                            now,
                            row["id"],
                        ),
                    )
                    if cursor.rowcount and row["conversation_id"]:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO conversation_messages (
                                id, conversation_id, role, content_json,
                                tool_call_id, tool_calls_json, request_id,
                                created_at
                            ) VALUES (?, ?, 'assistant', ?, NULL, NULL, ?, ?)
                            """,
                            (
                                f"msg_timeout_partial_{row['id']}",
                                row["conversation_id"],
                                json.dumps(answer, ensure_ascii=False),
                                row["id"],
                                now,
                            ),
                        )
                        connection.execute(
                            "UPDATE conversations SET updated_at = ? WHERE id = ?",
                            (now, row["conversation_id"]),
                        )
                    settled += cursor.rowcount
                    continue
                if row["mode"] == "sync":
                    continue
                if (
                    row["source"] == "web_chat"
                    and row["conversation_id"]
                    and timeout_fallback_text
                ):
                    response = {
                        "role": "assistant",
                        "content": timeout_fallback_text,
                    }
                    cursor = connection.execute(
                        """
                        UPDATE human_requests
                        SET status = 'answered', answer = ?, response_json = ?,
                            answered_at = ?, updated_at = ?,
                            answer_source = 'timeout_fallback',
                            claim_owner = NULL, claim_expires_at = NULL
                        WHERE id = ? AND status = 'pending'
                        """,
                        (
                            timeout_fallback_text,
                            json.dumps(response, ensure_ascii=False),
                            now_seconds,
                            now,
                            row["id"],
                        ),
                    )
                    if cursor.rowcount:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO conversation_messages (
                                id, conversation_id, role, content_json,
                                tool_call_id, tool_calls_json, request_id,
                                created_at
                            ) VALUES (?, ?, 'assistant', ?, NULL, NULL, ?, ?)
                            """,
                            (
                                f"msg_timeout_{row['id']}",
                                row["conversation_id"],
                                json.dumps(timeout_fallback_text, ensure_ascii=False),
                                row["id"],
                                now,
                            ),
                        )
                        connection.execute(
                            "UPDATE conversations SET updated_at = ? WHERE id = ?",
                            (now, row["conversation_id"]),
                        )
                        settled += 1
                else:
                    cursor = connection.execute(
                        """
                        UPDATE human_requests
                        SET status = 'expired', updated_at = ?,
                            claim_owner = NULL, claim_expires_at = NULL
                        WHERE id = ? AND status = 'pending'
                        """,
                        (now, row["id"]),
                    )
                    settled += cursor.rowcount
            if settled:
                self._bump_queue_version(connection)
        return settled

    def pending_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM human_requests WHERE status = 'pending'"
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _deserialize_api_key(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result.pop("key_hash", None)
        result["active"] = bool(result["active"])
        result["revoked"] = result.get("revoked_at") is not None
        result["status"] = (
            "revoked"
            if result["revoked"]
            else "active"
            if result["active"]
            else "paused"
        )
        result["usage_minute"] = int(result.get("usage_minute") or 0)
        result["usage_today"] = int(result.get("usage_today") or 0)
        result["pending_requests"] = int(result.get("pending_requests") or 0)
        result["managed"] = True
        return result

    @staticmethod
    def _deserialize_request(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["messages"] = json.loads(result.pop("messages_json"))
        result["tools"] = json.loads(result.pop("tools_json") or "[]")
        result["response"] = (
            json.loads(result.pop("response_json"))
            if result.get("response_json")
            else (
                {"role": "assistant", "content": result.get("answer")}
                if result.get("answer") is not None
                else None
            )
        )
        result.pop("response_json", None)
        result["stream_requested"] = bool(result.get("stream_requested", 0))
        now = _now_ms()
        result["claim_active"] = bool(
            result.get("claim_owner")
            and int(result.get("claim_expires_at") or 0) > now
        )
        result["client_connected"] = bool(
            result.get("client_last_seen_at")
            and int(result["client_last_seen_at"]) >= now - 6_000
        )
        if not result.get("preview"):
            result["preview"] = Database._request_preview(result["messages"])
        result["context_chars"] = int(result.get("context_chars") or 0)
        result["message_count"] = int(
            result.get("message_count") or len(result["messages"])
        )
        result["system_count"] = int(result.get("system_count") or 0)
        result["tool_count"] = int(result.get("tool_count") or 0)
        result["attachment_count"] = int(result.get("attachment_count") or 0)
        result["request_kind"] = result.get("request_kind") or "conversation"
        return result

    @staticmethod
    def _deserialize_request_summary(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["stream_requested"] = bool(result.get("stream_requested", 0))
        result["context_chars"] = int(result.get("context_chars") or 0)
        result["message_count"] = int(result.get("message_count") or 0)
        result["system_count"] = int(result.get("system_count") or 0)
        result["tool_count"] = int(result.get("tool_count") or 0)
        result["attachment_count"] = int(result.get("attachment_count") or 0)
        result["request_kind"] = result.get("request_kind") or "conversation"
        now = _now_ms()
        result["claim_active"] = bool(
            result.get("claim_owner")
            and int(result.get("claim_expires_at") or 0) > now
        )
        result["client_connected"] = bool(
            result.get("client_last_seen_at")
            and int(result["client_last_seen_at"]) >= now - 6_000
        )
        return result

    @staticmethod
    def _deserialize_quick_reply(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["active"] = bool(result["active"])
        return result

    @staticmethod
    def _deserialize_auto_rule(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["active"] = bool(result["active"])
        result["days"] = json.loads(result.pop("days_json") or "[]")
        return result

    @staticmethod
    def _deserialize_conversation_message(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["content"] = json.loads(result.pop("content_json"))
        result["tool_calls"] = (
            json.loads(result.pop("tool_calls_json"))
            if result.get("tool_calls_json")
            else None
        )
        result.pop("tool_calls_json", None)
        return result

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = [
                str(part.get("text", ""))
                for part in content
                if part.get("type") == "text"
            ]
            image_count = sum(
                1 for part in content if part.get("type") == "image_url"
            )
            file_count = sum(1 for part in content if part.get("type") == "file")
            label = " ".join(texts).strip()
            if image_count:
                label = f"{label} · {image_count} 张图片".strip(" ·")
            if file_count:
                label = f"{label} · {file_count} 个文件".strip(" ·")
            return label or ("附件消息" if file_count else "图片消息")
        if message.get("role") == "tool":
            return "工具返回结果"
        return ""

    @staticmethod
    def _short_title(value: str, *, limit: int = 88) -> str:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        cleaned = " ".join((lines[0] if lines else value).split())
        cleaned = cleaned.lstrip("#>*- ")
        if not cleaned:
            return "新请求"
        if cleaned[0] in "[{" and len(cleaned) > 48:
            return "结构化数据处理请求"
        if len(cleaned) <= limit:
            return cleaned
        candidate = cleaned[:limit].rstrip()
        if " " in candidate[limit // 2 :]:
            candidate = candidate.rsplit(" ", 1)[0]
        return f"{candidate.rstrip('，。,:;；')}…"

    @classmethod
    def _request_preview(cls, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            text = cls._message_text(message)
            if text:
                return cls._short_title(cls._clean_user_text(text))
        for message in reversed(messages):
            text = cls._message_text(message)
            if text:
                return cls._short_title(text)
        return "新请求"

    @staticmethod
    def _clean_user_text(value: str) -> str:
        text = value.strip()
        request_marker = re.search(
            r"^#{1,3}\s*(?:My request|我的请求|用户请求)\s*:\s*$",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if request_marker:
            text = text[request_marker.end() :].strip()
        text = re.sub(r"</?image\b[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(
            r"^#{1,3}\s*Files mentioned by the user\s*:\s*$.*?(?=^#{1,3}\s|\Z)",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
        ).strip()
        return text or value.strip()

    @classmethod
    def _request_kind(cls, messages: list[dict[str, Any]]) -> str:
        latest = cls._latest_user_text(messages).casefold()
        if "analyze this rollout and produce json" in latest and "raw_memory" in latest:
            return "memory"
        if "generate 0 to 3 hyperpersonalized suggestions" in latest:
            return "suggestions"
        if any(
            marker in latest
            for marker in (
                "generate a concise title",
                "generate a short title",
                "your job is to generate a title",
            )
        ):
            return "title"
        if latest.startswith(
            "you are a helpful assistant. you will be presented with a user prompt"
        ):
            return "utility"
        return "conversation"

    @staticmethod
    def _attachment_count(messages: list[dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                structured = sum(
                    1
                    for part in content
                    if isinstance(part, dict)
                    and part.get("type") in {"image_url", "file"}
                )
                text = "\n".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                structured = 0
                text = str(content or "")
            paths: set[str] = set()
            for match in re.finditer(
                r"^##[ \t]+[^\n:]+:[ \t]*(\S.+)$", text, flags=re.MULTILINE
            ):
                paths.add(match.group(1).strip())
            total += max(structured, len(paths))
        return total

    @classmethod
    def _request_summary(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, int | str]:
        tool_activity = len(tools)
        for message in messages:
            if message.get("role") == "tool":
                tool_activity += 1
            tool_activity += len(message.get("tool_calls") or [])
        return {
            "preview": cls._request_preview(messages),
            "context_chars": len(json.dumps(messages, ensure_ascii=False))
            + len(json.dumps(tools, ensure_ascii=False)),
            "message_count": len(messages),
            "system_count": sum(
                1
                for message in messages
                if message.get("role") in {"system", "developer"}
            ),
            "tool_count": tool_activity,
            "attachment_count": cls._attachment_count(messages),
            "request_kind": cls._request_kind(messages),
        }

    @staticmethod
    def _latest_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return Database._clean_user_text(content)
            if isinstance(content, list):
                return Database._clean_user_text(" ".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip())
        return ""


def hmac_compare(first: str, second: str) -> bool:
    import hmac

    return hmac.compare_digest(first, second)
