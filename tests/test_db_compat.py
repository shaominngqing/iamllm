from __future__ import annotations

from app.db_compat import translate_sqlite_sql


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
