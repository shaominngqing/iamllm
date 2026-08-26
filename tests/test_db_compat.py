from __future__ import annotations

from app.db_compat import PostgresConnection, translate_sqlite_sql


def test_translate_sqlite_placeholders_and_identity() -> None:
    sql = """
        CREATE TABLE calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value TEXT NOT NULL
        )
    """
    translated = translate_sqlite_sql(sql)
    assert "BIGSERIAL PRIMARY KEY" in translated
    assert "AUTOINCREMENT" not in translated
    assert "value TEXT" in translated

    query = translate_sqlite_sql("SELECT * FROM calls WHERE value = ? LIMIT ?")
    assert query == "SELECT * FROM calls WHERE value = %s LIMIT %s"


def test_translate_insert_or_ignore() -> None:
    translated = translate_sqlite_sql(
        "INSERT OR IGNORE INTO app_meta(key, value) VALUES (?, ?)"
    )
    assert translated == (
        "INSERT INTO app_meta(key, value) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING"
    )


def test_translate_transaction_and_pragma() -> None:
    assert translate_sqlite_sql("BEGIN IMMEDIATE") == "BEGIN"
    assert translate_sqlite_sql("PRAGMA optimize") == "SELECT 1"


def test_translate_sqlite_integer_to_postgres_bigint() -> None:
    translated = translate_sqlite_sql(
        "CREATE TABLE events (created_at INTEGER NOT NULL, active INTEGER DEFAULT 1)"
    )
    assert translated == (
        "CREATE TABLE events (created_at BIGINT NOT NULL, active BIGINT DEFAULT 1)"
    )


def test_postgres_executemany_uses_cursor() -> None:
    calls: list[tuple[str, list[tuple[str, int]]]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def executemany(self, sql, params):
            calls.append((sql, params))

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    connection = PostgresConnection(FakeConnection())
    params = [("queue_version", 1)]
    connection.executemany(
        "INSERT OR IGNORE INTO app_meta(key, value) VALUES (?, ?)", params
    )

    assert calls == [
        (
            "INSERT INTO app_meta(key, value) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            params,
        )
    ]
