from __future__ import annotations

import re
from contextlib import AbstractContextManager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


_INSERT_OR_IGNORE = re.compile(
    r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", flags=re.IGNORECASE
)


def translate_sqlite_sql(sql: str) -> str:
    """Translate the small SQLite SQL subset used by the application."""

    statement = sql.strip()
    if statement.upper() == "BEGIN IMMEDIATE":
        return "BEGIN"
    if statement.upper().startswith("PRAGMA "):
        return "SELECT 1"

    translated = _INSERT_OR_IGNORE.sub("INSERT INTO", sql)
    if translated != sql:
        translated = f"{translated.rstrip()} ON CONFLICT DO NOTHING"
    translated = translated.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
    )
    return translated.replace("?", "%s")


class PostgresConnection:
    """Expose the sqlite3 connection methods used by Database over psycopg."""

    dialect = "postgresql"

    def __init__(self, connection: Any) -> None:
        self.raw = connection

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None):
        translated = translate_sqlite_sql(sql)
        if params is None:
            return self.raw.execute(translated)
        return self.raw.execute(translated, params)

    def executemany(self, sql: str, params_seq: list[tuple[Any, ...]]):
        # psycopg exposes batch execution on cursors rather than connections.
        with self.raw.cursor() as cursor:
            cursor.executemany(translate_sqlite_sql(sql), params_seq)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)


class PostgresLease(AbstractContextManager[PostgresConnection]):
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool
        self._lease: Any = None

    def __enter__(self) -> PostgresConnection:
        self._lease = self.pool.connection()
        raw = self._lease.__enter__()
        return PostgresConnection(raw)

    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:
        assert self._lease is not None
        return self._lease.__exit__(exc_type, exc_value, traceback)


class PostgresBackend:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: ConnectionPool | None = None

    def open(self) -> None:
        if self.pool is not None:
            return
        self.pool = ConnectionPool(
            conninfo=self.database_url,
            min_size=1,
            max_size=5,
            kwargs={
                "row_factory": dict_row,
                # Supabase's transaction pooler does not support prepared statements.
                "prepare_threshold": None,
            },
            open=True,
        )
        self.pool.wait(timeout=15)

    def connect(self) -> PostgresLease:
        self.open()
        assert self.pool is not None
        return PostgresLease(self.pool)

    def close(self) -> None:
        if self.pool is None:
            return
        self.pool.close()
        self.pool = None
