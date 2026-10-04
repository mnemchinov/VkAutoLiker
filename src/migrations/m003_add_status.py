"""Миграция 003: переход с liked_at на status в processed_posts.

Старые БД имеют колонку liked_at без status. SQLite не поддерживает
DROP COLUMN до 3.35.0, поэтому используется pattern:
create new → copy → drop old → rename.
Существующие записи получают status=0 (UNKNOWN).
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Мигрирует processed_posts со старой схемой (liked_at) на новую (status)."""
    cursor = conn.execute("PRAGMA table_info(processed_posts)")
    columns = [row[1] for row in cursor.fetchall()]
    if "status" in columns:
        return
    conn.execute("""
        CREATE TABLE processed_posts_new (
            owner_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (owner_id, item_id)
        )
    """)
    conn.execute("""
        INSERT INTO processed_posts_new (owner_id, item_id, status)
        SELECT owner_id, item_id, 0 FROM processed_posts
    """)
    conn.execute("DROP TABLE processed_posts")
    conn.execute("ALTER TABLE processed_posts_new RENAME TO processed_posts")
