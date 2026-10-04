"""Миграция 002: добавление колонки is_auto в sessions (для --no-limit).

Старые БД (до --no-limit) не имеют колонки is_auto. ALTER TABLE добавляет
с DEFAULT 1 — все прошлые сессии помечаются как авто (корректно: они были
запущены launchd).
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Добавляет колонку is_auto в sessions, если её нет."""
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "is_auto" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN is_auto INTEGER DEFAULT 1")
