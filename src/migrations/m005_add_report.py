"""Миграция 005: добавление колонки report в sessions (отчёт о сессии).

Сессия хранит JSON-отчёт: счётчики постов по этапам конвейера
(собрано/отсеяно/дубликаты/LLM/лайки/провалы) и причину остановки.
Пишется один раз в end_session(). «статус» в боте показывает его
второй строкой; старые сессии (report NULL) показываются одной строкой.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Добавляет колонку report в sessions, если её нет."""
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "report" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN report TEXT")
