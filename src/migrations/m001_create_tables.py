"""Миграция 001: создание таблиц processed_posts, sessions, closed_walls.

Выполняется только на пустой БД (user_version=0). Создаёт все три таблицы
с финальной схемой (включая is_auto и status).
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Создаёт таблицы processed_posts, sessions, closed_walls."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_posts (
            owner_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (owner_id, item_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            likes_count INTEGER DEFAULT 0,
            session_date TEXT NOT NULL,
            is_auto INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS closed_walls (
            owner_id INTEGER PRIMARY KEY,
            last_checked INTEGER NOT NULL
        )
    """)
